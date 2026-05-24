"""DNS 解析器资源池 —— 可扩展核心"""

import logging
import threading
import time
import random
from enum import Enum

import dns.resolver
import dns.exception

from dns_resolver_pool.exceptions import PoolExhaustedException, ResourceUnhealthyException
from dns_resolver_pool.servers import (
    ServerEntry,
    _DOMESTIC,
    _OVERSEAS,
    HEALTH_CHECK_DOMAINS,
)

logger = logging.getLogger(__name__)


class SelectStrategy(Enum):
    """服务端选择策略"""
    LATENCY_WEIGHTED = "latency_weighted"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


class ServerState:
    """运行时状态"""

    __slots__ = (
        "ip", "name", "region", "enabled", "weight",
        "latency_ms", "fail_count", "success_count",
        "consecutive_fails", "last_used", "last_health",
        "_resolver",
    )

    def __init__(self, entry: ServerEntry) -> None:
        self.ip: str = entry["ip"]
        self.name: str = entry.get("name", entry["ip"])
        self.region: str = entry.get("region", "unknown")
        self.enabled: bool = entry.get("enabled", True)
        self.weight: int = entry.get("weight", 5)
        self.latency_ms: float = 0.0
        self.fail_count: int = 0
        self.success_count: int = 0
        self.consecutive_fails: int = 0
        self.last_used: float = 0.0
        self.last_health: float = 0.0
        self._resolver: dns.resolver.Resolver | None = None


class DNSResolverPool:
    """线程安全的 DNS 解析器资源池

    使用示例::

        pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
        pool.health_check(timeout=3.0)
        ip = pool.resolve("www.example.com")
        print(pool.stats())
    """

    def __init__(
        self,
        regions: tuple[str, ...] = ("domestic", "overseas"),
        strategy: SelectStrategy = SelectStrategy.LATENCY_WEIGHTED,
        cache_ttl: int = 300,
        max_consecutive_fails: int = 3,
        revive_after: int = 120,
    ) -> None:
        self._servers: list[ServerState] = []
        self._cache: dict[str, tuple[list[str], float]] = {}
        self._cache_ttl = cache_ttl
        self._max_fails = max_consecutive_fails
        self._revive_after = revive_after
        self._strategy = strategy
        self._lock = threading.Lock()
        self._rr_index = 0
        self._load_defaults(regions)

    # ── 公开 API ─────────────────────────────────────────────────────

    def resolve(self, domain: str, record_type: str = "A", timeout: float = 5.0) -> str:
        """解析域名，返回单个最优 IP"""
        cache_key = f"{domain}:{record_type}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("缓存命中: %s → %s", domain, cached[0])
            return cached[0]

        last_err: Exception | None = None
        for state in self._select_sequence():
            try:
                ips = self._do_resolve(state, domain, record_type, timeout)
                self._on_success(state, len(ips))
                result = ips[0]
                self._cache_set(cache_key, ips)
                return result
            except Exception as exc:
                logger.warning("DNS %s 解析 %s 失败: %s", state.ip, domain, exc)
                self._on_fail(state)
                last_err = exc
                continue

        raise PoolExhaustedException(
            "DNS 服务器",
            str(last_err) if last_err else "全部健康检查失败"
        )

    def resolve_all(self, domain: str, record_type: str = "A", timeout: float = 5.0) -> list[str]:
        """解析域名，返回全部 IP 列表"""
        cache_key = f"{domain}:{record_type}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.debug("缓存命中(resolve_all): %s → %d 条记录", domain, len(cached))
            return cached

        last_err: Exception | None = None
        for state in self._select_sequence():
            try:
                ips = self._do_resolve(state, domain, record_type, timeout)
                self._on_success(state, len(ips))
                self._cache_set(cache_key, ips)
                return ips
            except Exception as exc:
                logger.warning("DNS %s resolve_all %s 失败: %s", state.ip, domain, exc)
                self._on_fail(state)
                last_err = exc
                continue

        raise PoolExhaustedException(
            "DNS 服务器",
            str(last_err) if last_err else "全部健康检查失败"
        )

    def add_server(self, entry: ServerEntry) -> None:
        """动态添加 DNS 服务器"""
        state = ServerState(entry)
        with self._lock:
            existing = [s for s in self._servers if s.ip == state.ip]
            if existing:
                existing[0].enabled = True
                existing[0].weight = state.weight
                return
            self._servers.append(state)

    def remove_server(self, ip: str) -> bool:
        """移除（禁用）DNS 服务器"""
        with self._lock:
            for s in self._servers:
                if s.ip == ip:
                    s.enabled = False
                    return True
        return False

    def enable_server(self, ip: str) -> bool:
        """重新启用 DNS 服务器"""
        with self._lock:
            for s in self._servers:
                if s.ip == ip:
                    s.enabled = True
                    s.consecutive_fails = 0
                    return True
        return False

    def health_check(self, timeout: float = 3.0) -> dict[str, str]:
        """全量健康检查，返回 {ip: 'OK'|'FAIL'}"""
        results: dict[str, str] = {}
        for state in self._get_alive():
            ok = self._probe_server(state, timeout)
            with self._lock:
                if ok:
                    state.consecutive_fails = 0
                    state.last_health = time.time()
                    results[state.ip] = "OK"
                else:
                    state.consecutive_fails += 1
                    state.last_health = time.time()
                    if state.consecutive_fails >= self._max_fails:
                        state.enabled = False
                        logger.warning("DNS %s (%s) 连续失败 %d 次，已隔离", state.ip, state.name, state.consecutive_fails)
                    results[state.ip] = "FAIL"
        ok_count = sum(1 for v in results.values() if v == "OK")
        logger.info("健康检查完成: %d/%d 可用", ok_count, len(results))
        return results

    def stats(self) -> list[dict]:
        """返回所有服务器运行时状态"""
        with self._lock:
            return [
                {
                    "ip": s.ip,
                    "name": s.name,
                    "region": s.region,
                    "enabled": s.enabled,
                    "latency_ms": round(s.latency_ms, 1),
                    "success": s.success_count,
                    "fail": s.fail_count,
                    "last_used": s.last_used,
                }
                for s in self._servers
            ]

    def clear_cache(self) -> None:
        """清空 DNS 解析缓存"""
        with self._lock:
            self._cache.clear()

    @property
    def strategy(self) -> SelectStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, value: SelectStrategy) -> None:
        self._strategy = value

    # ── 内部 ─────────────────────────────────────────────────────────

    def _load_defaults(self, regions: tuple[str, ...]) -> None:
        region_map = {"domestic": _DOMESTIC, "overseas": _OVERSEAS}
        for r in regions:
            for entry in region_map.get(r, []):
                if entry.get("enabled", True):
                    self._servers.append(ServerState(entry))
        logger.info("已加载 %d 台 DNS 服务器（地域: %s）", len(self._servers), ", ".join(regions))

    def _select_sequence(self):
        """按策略生成服务器迭代器（fallback 用）"""
        alive = self._get_alive()
        self._try_revive()
        if not alive:
            return iter(())

        if self._strategy == SelectStrategy.LATENCY_WEIGHTED:
            return self._latency_weighted_order(alive)
        elif self._strategy == SelectStrategy.ROUND_ROBIN:
            return self._round_robin_order(alive)
        else:
            return self._random_order(alive)

    @staticmethod
    def _do_resolve(state: ServerState, domain: str, record_type: str, timeout: float) -> list[str]:
        # 复用 Resolver 实例，减少重复创建开销
        if state._resolver is None:
            state._resolver = dns.resolver.Resolver()
            state._resolver.nameservers = [state.ip]
        resolver = state._resolver
        resolver.timeout = timeout
        resolver.lifetime = timeout
        start = time.monotonic()
        try:
            answer = resolver.resolve(domain, record_type)
            elapsed = (time.monotonic() - start) * 1000
            state.latency_ms = state.latency_ms * 0.7 + elapsed * 0.3 if state.latency_ms else elapsed
            return [str(r) for r in answer]
        except dns.exception.DNSException as exc:
            raise ResourceUnhealthyException(state.ip, str(exc)) from exc

    def _probe_server(self, state: ServerState, timeout: float) -> bool:
        domain = random.choice(HEALTH_CHECK_DOMAINS)
        try:
            self._do_resolve(state, domain, "A", timeout)
            return True
        except ResourceUnhealthyException:
            return False

    def _get_alive(self) -> list[ServerState]:
        with self._lock:
            return [s for s in self._servers if s.enabled]

    def _try_revive(self) -> None:
        now = time.time()
        with self._lock:
            for s in self._servers:
                if not s.enabled and (now - s.last_health) > self._revive_after:
                    s.enabled = True
                    s.consecutive_fails = 0
                    logger.info("DNS %s (%s) 超过复活时间，已重新启用", s.ip, s.name)

    def _on_success(self, state: ServerState, ip_count: int) -> None:
        with self._lock:
            state.success_count += 1
            state.consecutive_fails = 0
            state.last_used = time.time()

    def _on_fail(self, state: ServerState) -> None:
        with self._lock:
            state.fail_count += 1
            state.consecutive_fails += 1
            state.last_used = time.time()
            if state.consecutive_fails >= self._max_fails:
                state.enabled = False

    # ── 选择策略 ─────────────────────────────────────────────────────

    def _latency_weighted_order(self, alive: list[ServerState]):
        scored = sorted(
            alive,
            key=lambda s: (1.0 if s.latency_ms == 0 else s.latency_ms) / max(s.weight, 1)
        )
        return iter(scored)

    def _round_robin_order(self, alive: list[ServerState]):
        with self._lock:
            self._rr_index = (self._rr_index + 1) % len(alive)
            ordered = alive[self._rr_index:] + alive[:self._rr_index]
        return iter(ordered)

    @staticmethod
    def _random_order(alive: list[ServerState]):
        shuffled = list(alive)
        random.shuffle(shuffled)
        return iter(shuffled)

    # ── 缓存 ─────────────────────────────────────────────────────────

    def _cache_get(self, key: str) -> list[str] | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ips, expires = entry
            if time.time() > expires:
                del self._cache[key]
                return None
            return ips

    def _cache_set(self, key: str, ips: list[str]) -> None:
        with self._lock:
            self._cache[key] = (ips, time.time() + self._cache_ttl)

    # ── 魔术方法 ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        alive = len(self._get_alive())
        total = len(self._servers)
        return f"DNSResolverPool(alive={alive}/{total}, strategy={self._strategy.value})"

    def __len__(self) -> int:
        return len(self._get_alive())

"""DNS 解析器资源池 —— 可扩展核心"""

import json
import logging
import os
import threading
import time
import random
import socket
from collections import deque
from enum import Enum

import dns.resolver
import dns.exception

from dns_resolver_pool.exceptions import PoolExhaustedException, ResourceUnhealthyException
from dns_resolver_pool.servers import (
    ServerEntry,
    _DOMESTIC,
    _OVERSEAS,
    _load_from_data_dir,
    HEALTH_CHECK_DOMAINS,
)
from resource_pool.base import DummyLock, ResourcePool, StrategyProtocol

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
        "_resolvers",
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
        # 每线程独立 Resolver 实例，确保多线程安全
        self._resolvers: threading.local = threading.local()

    def get_resolver(self) -> dns.resolver.Resolver:
        """获取当前线程的 Resolver 实例（惰性初始化）"""
        resolver = getattr(self._resolvers, "instance", None)
        if resolver is None:
            resolver = dns.resolver.Resolver()
            resolver.nameservers = [self.ip]
            self._resolvers.instance = resolver
        return resolver

    def reset_resolvers(self) -> None:
        """释放所有线程的 Resolver 引用"""
        self._resolvers = threading.local()


class DNSResolverPool(ResourcePool):
    """线程安全的 DNS 解析器资源池

    使用示例::

        pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
        pool.health_check(timeout=3.0)
        ip = pool.resolve("www.example.com")
        print(pool.stats())
    """

    _CACHE_SHARDS: int = 16  # 缓存分段数，按域名首字符哈希分片

    def __init__(
        self,
        regions: tuple[str, ...] = ("domestic", "overseas"),
        strategy: SelectStrategy | StrategyProtocol = SelectStrategy.LATENCY_WEIGHTED,
        cache_ttl: int = 300,
        max_cache_size: int = 4096,
        max_consecutive_fails: int = 3,
        revive_after: int = 120,
        thread_safe: bool = True,
        fallback_to_system: bool = True,
        data_dir: str | None = None,
        load_builtin: bool = True,
        load_fed: bool = True,
    ) -> None:
        self._servers: list[ServerState] = []
        self._cache: dict[str, tuple[list[str], float]] = {}
        self._cache_ttl = cache_ttl
        self._max_cache_size = max_cache_size
        self._cache_order: deque[str] = deque()
        self._max_fails = max_consecutive_fails
        self._revive_after = revive_after
        self._fallback_to_system = fallback_to_system
        self._strategy_enum: SelectStrategy | None = None
        self._strategy_fn: StrategyProtocol | None = None
        self._set_strategy(strategy)
        self._thread_safe = thread_safe
        self._lock = threading.Lock() if thread_safe else DummyLock()
        # 缓存分片锁：按域名首字符哈希到 16 个独立锁，减少缓存读写争用
        self._cache_locks: list[threading.Lock | DummyLock] = [
            threading.Lock() if thread_safe else DummyLock()
            for _ in range(self._CACHE_SHARDS)
        ]
        self._rr_index = 0
        self._last_revive_check: float = 0.0
        self._socket_patched: bool = False
        self._original_getaddrinfo = None
        self._data_dir = data_dir
        self._load_builtin = load_builtin
        self._load_fed = load_fed
        self._load_defaults(regions)

    # ── 公开 API ─────────────────────────────────────────────────────

    def resolve(self, domain: str, record_type: str = "A", timeout: float = 5.0) -> str:
        """解析域名，返回单个最优 IP

        优先使用池内 DNS 服务器，全部失败则回退到系统 DNS。
        """
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

        # ── 全部 DNS 服务器失败 → 回退到系统 DNS ──
        if self._fallback_to_system:
            try:
                logger.warning(
                    "全部 %d 台 DNS 服务器解析 %s 失败，回退到系统 DNS",
                    len(self._servers), domain,
                )
                ips = self._system_resolve(domain, record_type, timeout)
                self._cache_set(cache_key, ips)
                return ips[0]
            except Exception as exc:
                raise PoolExhaustedException(
                    "DNS 服务器",
                    f"全部池内+系统 DNS 失败: {exc}"
                ) from exc

        raise PoolExhaustedException(
            "DNS 服务器",
            str(last_err) if last_err else "全部 DNS 服务器失败"
        )

    def resolve_all(self, domain: str, record_type: str = "A", timeout: float = 5.0) -> list[str]:
        """解析域名，返回全部 IP 列表

        优先使用池内 DNS 服务器，全部失败则回退到系统 DNS。
        """
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

        # ── 全部 DNS 服务器失败 → 回退到系统 DNS ──
        if self._fallback_to_system:
            try:
                logger.warning(
                    "全部 %d 台 DNS 服务器 resolve_all %s 失败，回退到系统 DNS",
                    len(self._servers), domain,
                )
                ips = self._system_resolve(domain, record_type, timeout)
                self._cache_set(cache_key, ips)
                return ips
            except Exception as exc:
                raise PoolExhaustedException(
                    "DNS 服务器",
                    f"全部池内+系统 DNS 失败: {exc}"
                ) from exc

        raise PoolExhaustedException(
            "DNS 服务器",
            str(last_err) if last_err else "全部 DNS 服务器失败"
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
        with self._lock:
            snapshot = list(self._servers)
        for state in snapshot:
            ok, elapsed_ms = self._probe_server(state, timeout)
            with self._lock:
                # 重新校验 state 仍在池中且未被其他线程修改
                if state not in self._servers:
                    continue
                if ok:
                    # 仅在仍启用时才更新（避免覆盖并发隔离操作）
                    if state.enabled:
                        state.consecutive_fails = 0
                        # 健康检查成功：用 EMA 更新延迟，使延迟加权策略生效
                        state.latency_ms = (
                            state.latency_ms * 0.7 + elapsed_ms * 0.3
                            if state.latency_ms else elapsed_ms
                        )
                        results[state.ip] = "OK"
                    else:
                        # 已被隔离但探测通过，保留隔离状态等待 _try_revive
                        results[state.ip] = "OK(隔离中)"
                else:
                    state.consecutive_fails += 1
                    # 健康检查失败：立即用实际耗时（超时值）更新延迟，
                    # 避免延迟为 0 的不可用服务器在延迟加权策略中排到首位
                    if state.latency_ms == 0 or elapsed_ms > state.latency_ms:
                        state.latency_ms = elapsed_ms
                    if state.consecutive_fails >= self._max_fails:
                        state.enabled = False
                        logger.warning("DNS %s (%s) 连续失败 %d 次，已隔离", state.ip, state.name, state.consecutive_fails)
                    results[state.ip] = "FAIL"
                state.last_health = time.time()
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

    def get_server(self) -> str:
        """返回当前最优 DNS 服务器的 IP（供编排器调用）"""
        alive = self._get_alive()
        self._try_revive()
        if not alive:
            raise PoolExhaustedException("DNS 服务器", "无可用 DNS 服务器")
        it = self._select_sequence()
        try:
            return next(it).ip
        except StopIteration:
            raise PoolExhaustedException("DNS 服务器", "策略迭代器异常终止")

    def clear_cache(self) -> None:
        """清空 DNS 解析缓存（线程安全，获取所有分片锁）"""
        acquired: list = []
        try:
            for lock in self._cache_locks:
                lock.acquire()
                acquired.append(lock)
            self._cache.clear()
            self._cache_order.clear()
        finally:
            for lock in reversed(acquired):
                lock.release()

    def close(self) -> None:
        """释放线程本地 Resolver 引用

        在长期运行的服务中，若使用了短生命周期线程池（线程频繁创建/销毁），
        可定期调用此方法释放已退出线程持有的 Resolver 对象。

        常规 ThreadPoolExecutor（线程复用）场景无需调用。
        """
        with self._lock:
            for s in self._servers:
                # 替换为新的 threading.local，旧引用由 GC 回收
                s.reset_resolvers()
        logger.info("已释放所有线程本地 Resolver 引用")

    # ── Socket 补丁：透明接入 requests / urllib3 ──────────────────────

    @property
    def is_patched(self) -> bool:
        """socket.getaddrinfo 是否已被 patch"""
        return self._socket_patched

    def patch_socket(self) -> None:
        """Patch socket.getaddrinfo，全局 DNS 走池内 14 台服务器。

        调用后，当前进程内所有通过 socket.getaddrinfo 发起的 DNS
        解析（requests、urllib3、标准库 socket 等）将经由 DNS 池按
        策略轮询 14 台 DNS 服务器解析，全部失败时回退到系统 DNS。

        线程安全：patched 函数内部不持锁，直接委托给 resolve_all()
        （内部自带缓存+分片锁），多线程安全。

        使用示例::

            dns = DNSResolverPool()
            dns.patch_socket()
            requests.get("https://www.baidu.com")  # DNS 走池
            dns.unpatch_socket()
        """
        if self._socket_patched:
            return
        self._original_getaddrinfo = socket.getaddrinfo
        pool_ref = self

        def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            # 非域名或不合法 → 直通原版
            if not isinstance(host, str) or not host:
                return pool_ref._original_getaddrinfo(
                    host, port, family, type, proto, flags,
                )
            # AI_NUMERICHOST：调用方声明 host 已是数字地址
            if flags & socket.AI_NUMERICHOST:
                return pool_ref._original_getaddrinfo(
                    host, port, family, type, proto, flags,
                )
            try:
                ips = pool_ref.resolve_all(host)
                if not ips:
                    raise PoolExhaustedException(
                        "DNS 服务器", f"resolve_all 返回空: {host}",
                    )
            except PoolExhaustedException:
                # 池内 + 系统 DNS 全部失败
                raise socket.gaierror(
                    f"[DNS-Pool] all servers exhausted for {host}",
                )
            except Exception:
                # 意外异常 → 降级到原始 getaddrinfo
                return pool_ref._original_getaddrinfo(
                    host, port, family, type, proto, flags,
                )
            # 将 IP 列表转成 getaddrinfo 元组格式
            result = []
            for ip in ips:
                try:
                    result.extend(
                        pool_ref._original_getaddrinfo(
                            ip, port, family, type, proto, flags,
                        ),
                    )
                except socket.gaierror:
                    continue
            if result:
                return result
            raise socket.gaierror(
                f"[DNS-Pool] no usable address for {host}",
            )

        socket.getaddrinfo = _patched_getaddrinfo
        self._socket_patched = True
        logger.info("socket.getaddrinfo 已接入 DNS 池 (%d 台)", len(self._servers))

    def unpatch_socket(self) -> None:
        """恢复 socket.getaddrinfo 为系统默认"""
        if self._original_getaddrinfo is not None:
            socket.getaddrinfo = self._original_getaddrinfo
            self._original_getaddrinfo = None
            self._socket_patched = False
            logger.info("socket.getaddrinfo 已恢复为系统默认")

    def __enter__(self):
        """上下文管理器入口：自动 patch socket"""
        self.patch_socket()
        return self

    def __exit__(self, *args: object) -> None:
        """上下文管理器出口：自动 unpatch socket"""
        self.unpatch_socket()
        return None

    @property
    def strategy(self) -> SelectStrategy | StrategyProtocol:
        if self._strategy_enum is not None:
            return self._strategy_enum
        assert self._strategy_fn is not None, "策略未初始化"
        return self._strategy_fn

    @strategy.setter
    def strategy(self, value: SelectStrategy | StrategyProtocol) -> None:
        self._set_strategy(value)

    def __contains__(self, ip: str) -> bool:
        """检查 IP 是否在池中"""
        with self._lock:
            return any(s.ip == ip for s in self._servers)

    # ── 内部 ─────────────────────────────────────────────────────────

    def _set_strategy(self, value: SelectStrategy | StrategyProtocol) -> None:
        if isinstance(value, SelectStrategy):
            self._strategy_enum = value
            self._strategy_fn = None
        else:
            self._strategy_enum = None
            self._strategy_fn = value

    def _load_defaults(self, regions: tuple[str, ...]) -> None:
        # ── 优先从 data_dir 加载（如果指定）──
        if self._data_dir:
            path = os.path.join(self._data_dir, "dns_servers.json")
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    items = data.get("items", [])
                    for item in items:
                        if item.get("enabled", True):
                            self._servers.append(ServerState({
                                "ip": str(item["ip"]),
                                "name": str(item.get("name", item["ip"])),
                                "region": str(item.get("region", "unknown")),
                                "enabled": bool(item.get("enabled", True)),
                                "weight": int(item.get("weight", 5)),
                            }))
                    logger.info("已从 %s 加载 %d 台 DNS 服务器", path, len(self._servers))
                    return
                except Exception as e:
                    logger.warning("加载 %s 失败: %s", path, e)

        # ── 从 JSON 数据文件加载（含 fed 养成数据）──
        loaded_from_json = False
        if self._load_builtin or self._load_fed:
            json_servers = _load_from_data_dir()
            if json_servers:
                for entry in json_servers:
                    # 检查地域过滤
                    if entry.get("region") not in regions:
                        continue
                    # 检查 source 过滤
                    source = entry.get("source", "builtin")
                    if source == "builtin" and not self._load_builtin:
                        continue
                    if source == "fed" and not self._load_fed:
                        continue
                    if entry.get("enabled", True):
                        self._servers.append(ServerState(entry))
                loaded_from_json = True

        # ── 回退到硬编码（仅当 JSON 加载失败且 load_builtin=True）──
        if not loaded_from_json and self._load_builtin:
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

        # 枚举策略与 callable 策略分别存储在不同字段，类型检查器不会混淆
        if self._strategy_enum is not None:
            if self._strategy_enum is SelectStrategy.LATENCY_WEIGHTED:
                return self._latency_weighted_order(alive)
            if self._strategy_enum is SelectStrategy.ROUND_ROBIN:
                return self._round_robin_order(alive)
            if self._strategy_enum is SelectStrategy.RANDOM:
                return self._random_order(alive)
            return iter(())
        if self._strategy_fn is not None:
            return self._strategy_fn(alive)
        return iter(())

    def _do_resolve(self, state: ServerState, domain: str, record_type: str, timeout: float) -> list[str]:
        # 通过 ServerState 公开方法获取每线程独立 Resolver 实例
        # 多线程场景：每线程复用独立 Resolver，无锁无争用
        # 单线程场景：等价于复用同一 Resolver
        resolver = state.get_resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout
        start = time.monotonic()
        try:
            answer = resolver.resolve(domain, record_type)
            elapsed = (time.monotonic() - start) * 1000
            with self._lock:
                state.latency_ms = state.latency_ms * 0.7 + elapsed * 0.3 if state.latency_ms else elapsed
            return [str(r) for r in answer]
        except dns.exception.DNSException as exc:
            raise ResourceUnhealthyException(state.ip, str(exc)) from exc

    @staticmethod
    def _system_resolve(domain: str, record_type: str, timeout: float) -> list[str]:
        """使用系统 DNS 解析（不指定 nameservers，走 OS 配置）"""
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout
        answer = resolver.resolve(domain, record_type)
        return [str(r) for r in answer]

    @staticmethod
    def _probe_server(state: ServerState, timeout: float) -> tuple[bool, float]:
        """探测单台 DNS 是否可用，返回 (可用, 延迟ms)"""
        domain = random.choice(HEALTH_CHECK_DOMAINS)
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [state.ip]
        resolver.timeout = timeout
        resolver.lifetime = timeout
        start = time.monotonic()
        try:
            resolver.resolve(domain, "A")
            elapsed = (time.monotonic() - start) * 1000
            return True, elapsed
        except dns.exception.DNSException:
            elapsed = (time.monotonic() - start) * 1000
            return False, elapsed

    def _get_alive(self) -> list[ServerState]:
        with self._lock:
            return [s for s in self._servers if s.enabled]

    def _try_revive(self) -> None:
        now = time.time()
        with self._lock:
            # 时间戳检查纳入锁范围，避免多线程重复复活
            if now - self._last_revive_check < 30:
                return
            self._last_revive_check = now
            for s in self._servers:
                if not s.enabled and (now - s.last_health) > self._revive_after:
                    s.enabled = True
                    # 只给一次机会：再失败立即重新隔离
                    s.consecutive_fails = max(0, self._max_fails - 1)
                    logger.info("DNS %s (%s) 超过复活时间，已重新启用（试用中）", s.ip, s.name)

    def _on_success(self, state: ServerState, _ip_count: int) -> None:
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
                logger.warning(
                    "DNS %s (%s) 连续失败 %d 次，已隔离（resolve 触发）",
                    state.ip, state.name, state.consecutive_fails,
                )

    # ── 选择策略 ─────────────────────────────────────────────────────

    @staticmethod
    def _latency_weighted_order(alive: list[ServerState]):
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

    # ── 缓存（分片锁）────────────────────────────────────────────────

    @staticmethod
    def _cache_shard(key: str) -> int:
        """按域名首字符哈希到分片索引（0.._CACHE_SHARDS-1）"""
        return ord(key[0]) % DNSResolverPool._CACHE_SHARDS if key else 0

    def _cache_get(self, key: str) -> list[str] | None:
        lock = self._cache_locks[self._cache_shard(key)]
        with lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ips, expires = entry
            if time.time() > expires:
                del self._cache[key]
                # 惰性清理 order（不遍历，仅在访问时移除）
                try:
                    self._cache_order.remove(key)
                except ValueError:
                    pass
                return None
            return ips

    def _cache_set(self, key: str, ips: list[str]) -> None:
        lock = self._cache_locks[self._cache_shard(key)]
        with lock:
            # 防御：如果另一线程已缓存此 key，不覆盖（保留先写入的结果）
            if key in self._cache:
                return
            self._cache[key] = (ips, time.time() + self._cache_ttl)
            self._cache_order.append(key)
            # LRU 淘汰：超过上限则逐出最早条目（O(1)）
            while len(self._cache_order) > self._max_cache_size:
                oldest = self._cache_order.popleft()
                self._cache.pop(oldest, None)
                logger.debug("缓存淘汰: %s", oldest)

    # ── 魔术方法 ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        with self._lock:
            alive = len([s for s in self._servers if s.enabled])
            total = len(self._servers)
        if self._strategy_enum is not None:
            strategy_name = self._strategy_enum.value
        elif self._strategy_fn is not None:
            strategy_name = type(self._strategy_fn).__name__
        else:
            strategy_name = "unknown"
        return f"DNSResolverPool(alive={alive}/{total}, strategy={strategy_name})"

    def __len__(self) -> int:
        """返回当前可用（alive）服务器数量，被隔离的不计入"""
        return len(self._get_alive())

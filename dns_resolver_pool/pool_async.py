"""异步 DNS 解析器资源池 —— asyncio 版本

与同步版 DNSResolverPool 功能一致，但：
- 使用 dns.asyncresolver 替代 dns.resolver 实现真正的异步 DNS 查询
- 使用 contextvars.ContextVar 替代 threading.local() 实现 per-task 隔离
- 健康检查使用异步解析器
"""

import asyncio
import contextvars
import logging
import random
import time
from collections import deque
from enum import Enum

import dns.asyncresolver
import dns.exception

from dns_resolver_pool.exceptions import PoolExhaustedException, ResourceUnhealthyException
from dns_resolver_pool.servers import (
    ServerEntry,
    _DOMESTIC,
    _OVERSEAS,
    HEALTH_CHECK_DOMAINS,
)
from resource_pool.base import StrategyProtocol
from resource_pool.base_async import AsyncDummyLock, AsyncResourcePool
from resource_pool.orchestrator_async import AsyncPoolOrchestrator

logger = logging.getLogger(__name__)


class SelectStrategy(Enum):
    """服务端选择策略（与同步版共用）"""
    LATENCY_WEIGHTED = "latency_weighted"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


class AsyncServerState:
    """异步 DNS 服务器运行时状态 —— 使用 ContextVar 实现 per-task 隔离"""

    __slots__ = (
        "ip", "name", "region", "enabled", "weight",
        "latency_ms", "fail_count", "success_count",
        "consecutive_fails", "last_used", "last_health",
        "_resolver_ctx",
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
        # ContextVar 自动 per-task 隔离，子任务继承父任务值
        self._resolver_ctx: contextvars.ContextVar = contextvars.ContextVar(
            f"resolver_{self.ip}", default=None
        )

    def get_resolver(self) -> dns.asyncresolver.Resolver:
        """获取当前 asyncio Task 的异步 Resolver 实例（惰性初始化）"""
        resolver = self._resolver_ctx.get()
        if resolver is None:
            resolver = dns.asyncresolver.Resolver()
            resolver.nameservers = [self.ip]
            self._resolver_ctx.set(resolver)
        return resolver

    def reset_resolvers(self) -> None:
        """释放当前 Task 的 Resolver 引用（ContextVar 会自动随 Task 消亡而清理）"""
        self._resolver_ctx.set(None)


class AsyncDNSResolverPool(AsyncResourcePool):
    """协程安全的 DNS 解析器资源池（asyncio 版本）

    使用示例::

        pool = AsyncDNSResolverPool()
        await pool.health_check(timeout=3.0)
        ip = await pool.resolve("www.example.com")
        ips = await pool.resolve_all("www.example.com")
    """

    _CACHE_SHARDS: int = 16

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
    ) -> None:
        self._servers: list[AsyncServerState] = []
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
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()
        # 缓存分片锁：按域名首字符哈希到 16 个独立锁，减少缓存读写争用
        self._cache_locks: list[asyncio.Lock | AsyncDummyLock] = [
            asyncio.Lock() if thread_safe else AsyncDummyLock()
            for _ in range(self._CACHE_SHARDS)
        ]
        self._rr_index = 0
        self._last_revive_check: float = 0.0
        self._load_defaults(regions)

    # ── 公开 API ─────────────────────────────────────────────────────

    async def resolve(self, domain: str, record_type: str = "A",
                      timeout: float = 5.0) -> str:
        """解析域名，返回单个最优 IP

        优先使用池内 DNS 服务器，全部失败则回退到系统 DNS。
        """
        cache_key = f"{domain}:{record_type}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.debug("缓存命中: %s → %s", domain, cached[0])
            return cached[0]

        last_err: Exception | None = None
        for state in await self._select_sequence():
            try:
                ips = await self._do_resolve(state, domain, record_type, timeout)
                await self._on_success(state, len(ips))
                result = ips[0]
                await self._cache_set(cache_key, ips)
                return result
            except Exception as exc:
                logger.warning("DNS %s 解析 %s 失败: %s", state.ip, domain, exc)
                await self._on_fail(state)
                last_err = exc
                continue

        # ── 全部 DNS 服务器失败 → 回退到系统 DNS ──
        if self._fallback_to_system:
            try:
                logger.warning(
                    "全部 %d 台 DNS 服务器解析 %s 失败，回退到系统 DNS",
                    len(self._servers), domain,
                )
                ips = await self._system_resolve(domain, record_type, timeout)
                await self._cache_set(cache_key, ips)
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

    async def resolve_all(self, domain: str, record_type: str = "A",
                          timeout: float = 5.0) -> list[str]:
        """解析域名，返回全部 IP 列表

        优先使用池内 DNS 服务器，全部失败则回退到系统 DNS。
        """
        cache_key = f"{domain}:{record_type}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            logger.debug("缓存命中(resolve_all): %s → %d 条记录", domain, len(cached))
            return cached

        last_err: Exception | None = None
        for state in await self._select_sequence():
            try:
                ips = await self._do_resolve(state, domain, record_type, timeout)
                await self._on_success(state, len(ips))
                await self._cache_set(cache_key, ips)
                return ips
            except Exception as exc:
                logger.warning("DNS %s resolve_all %s 失败: %s", state.ip, domain, exc)
                await self._on_fail(state)
                last_err = exc
                continue

        # ── 全部 DNS 服务器失败 → 回退到系统 DNS ──
        if self._fallback_to_system:
            try:
                logger.warning(
                    "全部 %d 台 DNS 服务器 resolve_all %s 失败，回退到系统 DNS",
                    len(self._servers), domain,
                )
                ips = await self._system_resolve(domain, record_type, timeout)
                await self._cache_set(cache_key, ips)
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

    async def add_server(self, entry: ServerEntry) -> None:
        """动态添加 DNS 服务器"""
        state = AsyncServerState(entry)
        async with self._lock:
            existing = [s for s in self._servers if s.ip == state.ip]
            if existing:
                existing[0].enabled = True
                existing[0].weight = state.weight
                return
            self._servers.append(state)

    async def remove_server(self, ip: str) -> bool:
        """移除（禁用）DNS 服务器"""
        async with self._lock:
            for s in self._servers:
                if s.ip == ip:
                    s.enabled = False
                    return True
        return False

    async def enable_server(self, ip: str) -> bool:
        """重新启用 DNS 服务器"""
        async with self._lock:
            for s in self._servers:
                if s.ip == ip:
                    s.enabled = True
                    s.consecutive_fails = 0
                    return True
        return False

    async def health_check(self, timeout: float = 3.0) -> dict[str, str]:
        """全量异步健康检查"""
        results: dict[str, str] = {}
        async with self._lock:
            snapshot = list(self._servers)
        for state in snapshot:
            ok = await self._probe_server(state, timeout)
            async with self._lock:
                if state not in self._servers:
                    continue
                if ok:
                    if state.enabled:
                        state.consecutive_fails = 0
                        results[state.ip] = "OK"
                    else:
                        results[state.ip] = "OK(隔离中)"
                else:
                    state.consecutive_fails += 1
                    if state.consecutive_fails >= self._max_fails:
                        state.enabled = False
                        logger.warning(
                            "DNS %s (%s) 连续失败 %d 次，已隔离",
                            state.ip, state.name, state.consecutive_fails,
                        )
                    results[state.ip] = "FAIL"
                state.last_health = time.time()
        ok_count = sum(1 for v in results.values() if v == "OK")
        logger.info("健康检查完成: %d/%d 可用", ok_count, len(results))
        return results

    async def stats(self) -> list[dict]:
        """返回所有服务器运行时状态"""
        async with self._lock:
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

    async def get_server(self) -> str:
        """返回当前最优 DNS 服务器的 IP（供编排器调用）"""
        alive = self._get_alive()
        await self._try_revive()
        if not alive:
            raise PoolExhaustedException("DNS 服务器", "无可用 DNS 服务器")
        it = await self._select_sequence()
        try:
            return next(it).ip
        except StopIteration:
            raise PoolExhaustedException("DNS 服务器", "策略迭代器异常终止")

    async def clear_cache(self) -> None:
        """清空 DNS 解析缓存（协程安全，获取所有分片锁）"""
        acquired: list = []
        try:
            for lock in self._cache_locks:
                await lock.acquire()
                acquired.append(lock)
            self._cache.clear()
            self._cache_order.clear()
        finally:
            for lock in reversed(acquired):
                lock.release()

    async def close(self) -> None:
        """释放 per-task Resolver 引用"""
        async with self._lock:
            for s in self._servers:
                s.reset_resolvers()
        logger.info("已释放所有 per-task Resolver 引用")

    # ── 魔术方法 ─────────────────────────────────────────────────────

    @property
    def strategy(self) -> SelectStrategy | StrategyProtocol:
        """当前选择策略"""
        if self._strategy_enum is not None:
            return self._strategy_enum
        assert self._strategy_fn is not None, "策略未初始化"
        return self._strategy_fn

    @strategy.setter
    def strategy(self, value: SelectStrategy | StrategyProtocol) -> None:
        """运行时切换策略"""
        self._set_strategy(value)

    def __repr__(self) -> str:
        alive = len(self._get_alive())
        total = len(self._servers)
        if self._strategy_enum is not None:
            strategy_name = self._strategy_enum.value
        else:
            strategy_name = type(self._strategy_fn).__name__
        return f"AsyncDNSResolverPool(alive={alive}/{total}, strategy={strategy_name})"

    def __len__(self) -> int:
        return len(self._get_alive())

    def __contains__(self, ip: str) -> bool:
        return any(s.ip == ip for s in self._servers)

    # ── 内部 ─────────────────────────────────────────────────────────

    def _load_defaults(self, regions: tuple[str, ...]) -> None:
        region_map = {"domestic": _DOMESTIC, "overseas": _OVERSEAS}
        for r in regions:
            for entry in region_map.get(r, []):
                if entry.get("enabled", True):
                    self._servers.append(AsyncServerState(entry))
        logger.info("已加载 %d 台 DNS 服务器（地域: %s）", len(self._servers), ", ".join(regions))

    def _set_strategy(self, value: SelectStrategy | StrategyProtocol) -> None:
        """设置策略（内部）"""
        if isinstance(value, SelectStrategy):
            self._strategy_enum = value
            self._strategy_fn = None
        else:
            self._strategy_enum = None
            self._strategy_fn = value

    async def _select_sequence(self):
        alive = self._get_alive()
        await self._try_revive()
        if not alive:
            return iter(())

        # 枚举策略与 callable 策略分别存储在不同字段，避免类型混淆
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

    async def _do_resolve(self, state: AsyncServerState, domain: str,
                          record_type: str, timeout: float) -> list[str]:
        resolver = state.get_resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout
        start = time.monotonic()
        try:
            answer = await resolver.resolve(domain, record_type)
            elapsed = (time.monotonic() - start) * 1000
            # asyncio 单线程下写入原子安全；暂不加锁避免 async-lock 嵌套复杂性
            state.latency_ms = state.latency_ms * 0.7 + elapsed * 0.3 if state.latency_ms else elapsed
            return [str(r) for r in answer]
        except dns.exception.DNSException as exc:
            raise ResourceUnhealthyException(state.ip, str(exc)) from exc

    @staticmethod
    async def _system_resolve(domain: str, record_type: str, timeout: float) -> list[str]:
        """使用系统 DNS 异步解析（不指定 nameservers，走 OS 配置）"""
        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout
        answer = await resolver.resolve(domain, record_type)
        return [str(r) for r in answer]

    @staticmethod
    async def _probe_server(state: AsyncServerState, timeout: float) -> bool:
        """异步探测单台 DNS 是否可用"""
        domain = random.choice(HEALTH_CHECK_DOMAINS)
        resolver = dns.asyncresolver.Resolver()
        resolver.nameservers = [state.ip]
        resolver.timeout = timeout
        resolver.lifetime = timeout
        try:
            await resolver.resolve(domain, "A")
            return True
        except dns.exception.DNSException:
            return False

    def _get_alive(self) -> list[AsyncServerState]:
        return [s for s in self._servers if s.enabled]

    async def _try_revive(self) -> None:
        """检查并复活超时隔离的 DNS 服务器（锁内操作，与同步版一致）"""
        now = time.time()
        async with self._lock:
            # 时间戳检查纳入锁范围，避免多协程重复复活（与同步版对齐）
            if now - self._last_revive_check < 30:
                return
            self._last_revive_check = now
            for s in self._servers:
                if not s.enabled and (now - s.last_health) > self._revive_after:
                    s.enabled = True
                    # 只给一次机会：再失败立即重新隔离
                    s.consecutive_fails = max(0, self._max_fails - 1)
                    logger.info("DNS %s (%s) 超过复活时间，已重新启用（试用中）", s.ip, s.name)

    async def _on_success(self, state: AsyncServerState, _ip_count: int) -> None:
        async with self._lock:
            state.success_count += 1
            state.consecutive_fails = 0
            state.last_used = time.time()

    async def _on_fail(self, state: AsyncServerState) -> None:
        async with self._lock:
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
    def _latency_weighted_order(alive: list[AsyncServerState]):
        scored = sorted(
            alive,
            key=lambda s: (1.0 if s.latency_ms == 0 else s.latency_ms) / max(s.weight, 1)
        )
        return iter(scored)

    def _round_robin_order(self, alive: list[AsyncServerState]):
        self._rr_index = (self._rr_index + 1) % len(alive)
        ordered = alive[self._rr_index:] + alive[:self._rr_index]
        return iter(ordered)

    @staticmethod
    def _random_order(alive: list[AsyncServerState]):
        shuffled = list(alive)
        random.shuffle(shuffled)
        return iter(shuffled)

    # ── 缓存（分片锁）────────────────────────────────────────────────

    @staticmethod
    def _cache_shard(key: str) -> int:
        return ord(key[0]) % AsyncDNSResolverPool._CACHE_SHARDS if key else 0

    async def _cache_get(self, key: str) -> list[str] | None:
        lock = self._cache_locks[self._cache_shard(key)]
        async with lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ips, expires = entry
            if time.time() > expires:
                del self._cache[key]
                try:
                    self._cache_order.remove(key)
                except ValueError:
                    pass
                return None
            return ips

    async def _cache_set(self, key: str, ips: list[str]) -> None:
        lock = self._cache_locks[self._cache_shard(key)]
        async with lock:
            if key in self._cache:
                return
            self._cache[key] = (ips, time.time() + self._cache_ttl)
            self._cache_order.append(key)
            while len(self._cache_order) > self._max_cache_size:
                oldest = self._cache_order.popleft()
                self._cache.pop(oldest, None)
                logger.debug("缓存淘汰: %s", oldest)


# ── 自动注册到异步编排器 ──
AsyncPoolOrchestrator.register_dispatch(AsyncDNSResolverPool, "get_server")

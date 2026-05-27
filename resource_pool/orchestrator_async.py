"""异步资源池编排器 —— 跨池协同调度（asyncio 版本）

与同步版 PoolOrchestrator 功能一致，但所有操作均为异步。
"""

import asyncio
import inspect
import logging
from typing import Any, AsyncIterator

from resource_pool.base_async import AsyncDummyLock, AsyncResourcePool
from resource_pool.exceptions import PoolExhaustedError
from resource_pool.orchestrator import PoolCombo

logger = logging.getLogger(__name__)


class AsyncPoolOrchestrator:
    """异步跨资源池编排器 —— 一次调用获取多池组合资源

    使用示例::

        from resource_pool.orchestrator_async import AsyncPoolOrchestrator
        from user_agent_pool.pool_async import AsyncUserAgentPool
        from dns_resolver_pool.pool_async import AsyncDNSResolverPool

        ua = AsyncUserAgentPool()
        dns = AsyncDNSResolverPool()
        orch = AsyncPoolOrchestrator(ua=ua, dns=dns)

        combo = await orch.next()
        # {"ua": {...}, "dns_ip": "8.8.8.8"}

        async for combo in orch.combos(limit=5):
            ...
    """

    # ── 分派注册表：池类型 → 资源获取方法名 ─────────────────────────
    _DISPATCH: dict[type, str] = {}

    @classmethod
    def register_dispatch(cls, pool_type: type, method_name: str) -> None:
        """注册异步资源池类型的分派方法。

        Args:
            pool_type: 异步资源池类型（如 AsyncProxyPool）
            method_name: 异步资源获取方法名（如 "get_dict"）
        """
        if not isinstance(pool_type, type):
            raise TypeError(f"pool_type 必须是类型，收到: {type(pool_type).__name__}")
        if not isinstance(method_name, str) or not method_name:
            raise TypeError(f"method_name 必须是非空字符串，收到: {method_name!r}")
        cls._DISPATCH[pool_type] = method_name
        logger.debug("异步编排器已注册分派: %s → %s()", pool_type.__name__, method_name)

    def __init__(self, thread_safe: bool = True, **pools: AsyncResourcePool) -> None:
        """注册异步资源池

        Args:
            thread_safe: 是否启用协程安全锁（单协程场景可关闭）
            **pools: 命名资源池，如 ua=AsyncUserAgentPool()
        """
        if not pools:
            raise ValueError("至少需要注册一个资源池")
        self._pools: dict[str, AsyncResourcePool] = pools
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()

    # ── 池管理 ───────────────────────────────────────────────────────

    async def register(self, name: str, pool: AsyncResourcePool) -> None:
        """动态注册资源池"""
        if not isinstance(pool, AsyncResourcePool):
            raise TypeError(f"'{name}' 必须实现 AsyncResourcePool 协议")
        async with self._lock:
            self._pools[name] = pool
        logger.info("异步编排器已注册资源池: %s (%s)", name, type(pool).__name__)

    async def unregister(self, name: str) -> AsyncResourcePool | None:
        """移除资源池，返回被移除的池（或 None）"""
        async with self._lock:
            return self._pools.pop(name, None)

    @property
    def pool_names(self) -> tuple[str, ...]:
        """已注册的池名称（同步属性）"""
        # 名称快照不严格需要锁：asyncio 单线程下 dict keys 是安全的
        return tuple(self._pools.keys())

    # ── 组合获取 ─────────────────────────────────────────────────────

    async def next(self) -> PoolCombo:
        """异步获取一组组合资源（每池各取一个最优）

        Returns:
            ``PoolCombo`` 对象，支持属性访问（``combo.ua``）和字典访问（``combo["ua"]``）
        """
        combo: dict[str, Any] = {}
        async with self._lock:
            pools_snapshot = dict(self._pools)
        for name, pool in pools_snapshot.items():
            try:
                combo[name] = await self._fetch_from_pool_async(name, pool)
            except Exception as exc:  # noqa: BLE001
                logger.error("异步编排器从 '%s' 获取资源失败: %s", name, exc)
                raise
        logger.debug("异步编排器返回组合: %s", {k: str(v)[:60] for k, v in combo.items()})
        return PoolCombo(combo)

    async def combos(self, limit: int | None = None) -> AsyncIterator[PoolCombo]:
        """异步生成组合资源迭代器

        Args:
            limit: 最多返回几组，None=无限（需外部停止）

        Yields:
            PoolCombo 对象（每次迭代每池各取一个资源）
        """
        count = 0
        while limit is None or count < limit:
            try:
                yield await self.next()
                count += 1
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                raise
            except PoolExhaustedError:
                logger.warning("异步编排器迭代终止：资源池已耗尽")
                break
            except Exception:  # noqa: BLE001
                logger.error("异步编排器迭代发生未预期异常，终止迭代", exc_info=True)
                break

    # ── 健康检查 ─────────────────────────────────────────────────────

    async def health_check_all(self, timeout: float = 5.0) -> dict[str, Any]:
        """对所有池执行异步健康检查（如果池支持）"""
        results: dict[str, Any] = {}
        async with self._lock:
            pools_snapshot = dict(self._pools)
        for name, pool in pools_snapshot.items():
            if hasattr(pool, "health_check"):
                results[name] = await pool.health_check(timeout)
            else:
                results[name] = "N/A (池不支持健康检查)"
        return results

    # ── 内部 ─────────────────────────────────────────────────────────

    @staticmethod
    async def _fetch_from_pool_async(name: str, pool: AsyncResourcePool) -> Any:
        """从单个异步池取资源 —— 优先 isinstance 精确分派，hasattr 兜底

        分派优先级：
        1. isinstance 匹配注册表（_DISPATCH）
        2. hasattr 探测（向后兼容）
        """
        # ── 1. isinstance 精确分派 ──
        for pool_type, method_name in AsyncPoolOrchestrator._DISPATCH.items():
            if isinstance(pool, pool_type):
                method = getattr(pool, method_name)
                if asyncio.iscoroutinefunction(method):
                    return await method()
                result = method()
                # isawaitable 兜底：某些方法虽非 async def 但返回 coroutine 对象
                if inspect.isawaitable(result):
                    return await result
                return result

        # ── 2. hasattr 兜底（已弃用，将在未来版本移除） ──
        # 请使用 AsyncPoolOrchestrator.register_dispatch() 注册自定义池。
        logger.warning(
            "池 '%s' (%s) 未注册分派，使用 hasattr 回退（已弃用）。"
            "请调用 AsyncPoolOrchestrator.register_dispatch() 显式注册。",
            name, type(pool).__name__,
        )
        if hasattr(pool, "get_dict"):
            result = pool.get_dict()
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(pool, "get_headers"):
            result = pool.get_headers()
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(pool, "get"):
            result = pool.get()
            if inspect.isawaitable(result):
                return await result
            return result
        if hasattr(pool, "get_server"):
            result = pool.get_server()
            if inspect.isawaitable(result):
                return await result
            return result
        raise RuntimeError(f"'{name}' ({type(pool).__name__}) 无可用的资源获取方法")

    def __repr__(self) -> str:
        names = ", ".join(self._pools.keys())
        return f"AsyncPoolOrchestrator({names})"




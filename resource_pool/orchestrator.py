"""资源池编排器 —— 跨池协同调度"""

import threading
import logging
from typing import Any, Iterator

from resource_pool.base import DummyLock, ResourcePool
from resource_pool.exceptions import PoolExhaustedError

logger = logging.getLogger(__name__)


class PoolOrchestrator:
    """跨资源池编排器 —— 一次调用获取多池组合资源

    使用示例::

        from resource_pool import PoolOrchestrator, UserAgentPool, DNSResolverPool

        ua = UserAgentPool()
        dns = DNSResolverPool()
        orch = PoolOrchestrator(ua=ua, dns=dns)

        combo = orch.next()          # {"ua": "...", "dns_ip": "..."}
        # 或迭代：
        for combo in orch.combos():
            requests.get(url, headers={"User-Agent": combo["ua"]})
    """

    def __init__(self, thread_safe: bool = True, **pools: ResourcePool) -> None:
        """注册资源池

        Args:
            thread_safe: 是否启用线程安全锁（单线程场景可关闭）
            **pools: 命名资源池，如 ua=UserAgentPool(), dns=DNSResolverPool()
        """
        if not pools:
            raise ValueError("至少需要注册一个资源池")
        self._pools: dict[str, ResourcePool] = pools
        self._lock = threading.Lock() if thread_safe else DummyLock()

    # ── 池管理 ───────────────────────────────────────────────────────

    def register(self, name: str, pool: ResourcePool) -> None:
        """动态注册资源池"""
        if not isinstance(pool, ResourcePool):
            raise TypeError(f"'{name}' 必须实现 ResourcePool 协议")
        with self._lock:
            self._pools[name] = pool
        logger.info("编排器已注册资源池: %s (%s)", name, type(pool).__name__)

    def unregister(self, name: str) -> ResourcePool | None:
        """移除资源池，返回被移除的池（或 None）"""
        with self._lock:
            return self._pools.pop(name, None)

    @property
    def pool_names(self) -> tuple[str, ...]:
        """已注册的池名称"""
        with self._lock:
            return tuple(self._pools.keys())

    # ── 组合获取 ─────────────────────────────────────────────────────

    def next(self) -> dict[str, Any]:
        """获取一组组合资源（每池各取一个最优）

        Returns:
            ``{"ua": "Mozilla/5.0...", "dns_ip": "8.8.8.8", "proxy": "http://..."}``

        Raises:
            RuntimeError: 某个池已耗尽且无法 fallback
        """
        combo: dict[str, Any] = {}
        with self._lock:
            pools_snapshot = dict(self._pools)
        for name, pool in pools_snapshot.items():
            try:
                combo[name] = PoolOrchestrator._fetch_from_pool(name, pool)
            except Exception as exc:  # noqa: BLE001
                logger.error("编排器从 '%s' 获取资源失败: %s", name, exc)
                raise
        logger.debug("编排器返回组合: %s", {k: str(v)[:60] for k, v in combo.items()})
        return combo

    def combos(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        """生成组合资源迭代器

        Args:
            limit: 最多返回几组，None=无限（需外部停止）

        Yields:
            每池各取一个资源的组合字典
        """
        count = 0
        while limit is None or count < limit:
            try:
                yield self.next()
                count += 1
            except (KeyboardInterrupt, SystemExit):
                raise
            except PoolExhaustedError:
                logger.warning("编排器迭代终止：资源池已耗尽")
                break
            except Exception:  # noqa: BLE001
                logger.error("编排器迭代发生未预期异常，终止迭代", exc_info=True)
                break

    # ── 健康检查 ─────────────────────────────────────────────────────

    def health_check_all(self, timeout: float = 5.0) -> dict[str, Any]:
        """对所有池执行健康检查（如果池支持）"""
        results: dict[str, Any] = {}
        with self._lock:
            pools_snapshot = dict(self._pools)
        for name, pool in pools_snapshot.items():
            if hasattr(pool, "health_check"):
                results[name] = pool.health_check(timeout)
            else:
                results[name] = "N/A (池不支持健康检查)"
        return results

    # ── 内部 ─────────────────────────────────────────────────────────

    @staticmethod
    def _fetch_from_pool(name: str, pool: ResourcePool) -> Any:
        """从单个池取资源 —— 按池类型分发

        分发优先级（由高到低）：
        1. get_dict()  → ProxyPool（返回 proxies 字典）
        2. get_headers() → UserAgentPool（返回完整 Header Profile）
        3. get()        → 通用兜底（返回 UA 字符串等）
        4. get_server() → DNSResolverPool（返回最优 DNS IP）

        自定义池若同时实现多个方法，上层方法优先。
        """
        # ProxyPool: 返回 proxies 字典
        if hasattr(pool, "get_dict"):
            return pool.get_dict()
        # UserAgentPool: 返回完整 Header Profile
        if hasattr(pool, "get_headers"):
            return pool.get_headers()
        if hasattr(pool, "get"):
            return pool.get()
        # DNSResolverPool: 返回最优 DNS 服务器 IP
        if hasattr(pool, "get_server"):
            return pool.get_server()
        raise RuntimeError(f"'{name}' ({type(pool).__name__}) 无可用的资源获取方法")

    def __repr__(self) -> str:
        with self._lock:
            names = ", ".join(self._pools.keys())
        return f"PoolOrchestrator({names})"

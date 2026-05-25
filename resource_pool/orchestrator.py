"""资源池编排器 —— 跨池协同调度"""

import threading
import logging
from typing import Any, Iterator, Mapping

from resource_pool.base import DummyLock, ResourcePool
from resource_pool.exceptions import PoolExhaustedError

logger = logging.getLogger(__name__)


class PoolCombo(Mapping):
    """多池组合结果的不可变容器

    支持属性访问（``combo.ua``）、字典访问（``combo["ua"]``）、
    解包（``**combo``）和迭代（``for key, val in combo``）。

    使用示例::

        combo = orch.next()
        print(combo.ua)           # 属性访问
        print(combo["dns_ip"])    # 字典访问
        headers = {**combo}       # 解包为普通 dict
        for k, v in combo:        # 迭代
            print(k, v)
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = {k: v for k, v in data.items()}

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(
                f"'PoolCombo' 没有字段 '{name}'，可用字段: {list(self._data.keys())}"
            ) from None

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._data

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        items = ", ".join(
            f"{k}={str(v)[:60]!r}" for k, v in self._data.items()
        )
        return f"PoolCombo({items})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PoolCombo):
            return self._data == other._data
        if isinstance(other, dict):
            return self._data == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(sorted(self._data.items())))

    def keys(self) -> Any:
        return self._data.keys()

    def values(self) -> Any:
        return self._data.values()

    def items(self) -> Any:
        return self._data.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


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

    自定义池分派::

        如果自定义池实现了特殊的资源获取方法，可注册到分派表：

            PoolOrchestrator.register_dispatch(MyCustomPool, "fetch_resource")
    """

    # ── 分派注册表：池类型 → 资源获取方法名 ─────────────────────────
    _DISPATCH: dict[type, str] = {}

    @classmethod
    def register_dispatch(cls, pool_type: type, method_name: str) -> None:
        """注册资源池类型的分派方法。

        编排器的 _fetch_from_pool 优先使用 isinstance 精确匹配注册表，
        未匹配到才回退到 hasattr 探测（向后兼容）。

        Args:
            pool_type: 资源池类型（如 ProxyPool）
            method_name: 资源获取方法名（如 "get_dict"）

        使用示例::

            PoolOrchestrator.register_dispatch(MyCustomPool, "fetch_resource")
        """
        if not isinstance(pool_type, type):
            raise TypeError(f"pool_type 必须是类型，收到: {type(pool_type).__name__}")
        if not isinstance(method_name, str) or not method_name:
            raise TypeError(f"method_name 必须是非空字符串，收到: {method_name!r}")
        cls._DISPATCH[pool_type] = method_name
        logger.debug("已注册分派: %s → %s()", pool_type.__name__, method_name)

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

    def next(self) -> PoolCombo:
        """获取一组组合资源（每池各取一个最优）

        Returns:
            ``PoolCombo`` 对象，支持属性访问（``combo.ua``）和字典访问（``combo["ua"]``）

        Raises:
            RuntimeError: 某个池已耗尽且无法 fallback
        """
        combo: dict[str, Any] = {}
        with self._lock:
            pools_snapshot = dict(self._pools)
        for name, pool in pools_snapshot.items():
            try:
                combo[name] = PoolOrchestrator._fetch_from_pool(name, pool)
            except PoolExhaustedError:
                raise
            except Exception as exc:
                logger.error("编排器从 '%s' 获取资源失败: %s", name, exc)
                raise
        logger.debug("编排器返回组合: %s", {k: str(v)[:60] for k, v in combo.items()})
        return PoolCombo(combo)

    def combos(self, limit: int | None = None) -> Iterator[PoolCombo]:
        """生成组合资源迭代器

        Args:
            limit: 最多返回几组，None=无限（需外部停止）

        Yields:
            PoolCombo 对象（每次迭代每池各取一个资源）
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
        """从单个池取资源 —— 优先 isinstance 精确分派，hasattr 兜底

        分派优先级：
        1. isinstance 匹配注册表（_DISPATCH）—— 确定性、无歧义
        2. hasattr 探测（向后兼容）—— 自定义池未注册时自动探测

        内置池注册关系（由各子包 __init__.py 自动注册）：
        - ProxyPool      → get_dict()
        - UserAgentPool  → get_headers()
        - DNSResolverPool → get_server()
        """
        # ── 1. isinstance 精确分派 ──
        for pool_type, method_name in PoolOrchestrator._DISPATCH.items():
            if isinstance(pool, pool_type):
                return getattr(pool, method_name)()

        # ── 2. hasattr 兜底（向后兼容，未来版本将移除） ──
        if hasattr(pool, "get_dict"):
            return pool.get_dict()
        if hasattr(pool, "get_headers"):
            return pool.get_headers()
        if hasattr(pool, "get"):
            return pool.get()
        if hasattr(pool, "get_server"):
            return pool.get_server()
        raise RuntimeError(f"'{name}' ({type(pool).__name__}) 无可用的资源获取方法")

    def __repr__(self) -> str:
        with self._lock:
            names = ", ".join(self._pools.keys())
        return f"PoolOrchestrator({names})"

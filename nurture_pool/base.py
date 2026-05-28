"""资源池抽象基类 —— 定义统一接口协议"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator
import threading


class DummyLock:
    """空操作锁 —— thread_safe=False 时替代 threading.Lock，零开销"""
    def __enter__(self) -> "DummyLock":
        return self
    def __exit__(self, *args: object) -> None:
        pass


class ReadWriteLock:
    """读写锁 —— 读多写少场景的性能优化

    多个读者可同时持有锁，写者独占。写者优先（避免写饥饿）。

    使用示例::

        rwlock = ReadWriteLock()

        # 读操作（多线程可并发）
        with rwlock.read():
            data = shared_list.copy()

        # 写操作（独占）
        with rwlock.write():
            shared_list.append(item)

    适用场景：
    - UA 池：get/get_headers 高频读，add/remove 低频写
    - DNS 缓存：resolve 读缓存，_cache_set 写缓存
    - 代理池：get/get_alive 高频读，add_proxy/mark_failed 中频写
    """

    class _ReadContext:
        """读锁上下文管理器"""
        __slots__ = ("_owner",)

        def __init__(self, owner: "ReadWriteLock") -> None:
            self._owner = owner

        def __enter__(self) -> "ReadWriteLock._ReadContext":
            self._owner._acquire_read()
            return self

        def __exit__(self, *args: object) -> None:
            self._owner._release_read()

    class _WriteContext:
        """写锁上下文管理器"""
        __slots__ = ("_owner",)

        def __init__(self, owner: "ReadWriteLock") -> None:
            self._owner = owner

        def __enter__(self) -> "ReadWriteLock._WriteContext":
            self._owner._acquire_write()
            return self

        def __exit__(self, *args: object) -> None:
            self._owner._release_write()

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writers_waiting: int = 0
        self._writer_active: bool = False

    def read(self) -> "ReadWriteLock._ReadContext":
        """获取读锁上下文管理器"""
        return ReadWriteLock._ReadContext(self)

    def write(self) -> "ReadWriteLock._WriteContext":
        """获取写锁上下文管理器"""
        return ReadWriteLock._WriteContext(self)

    def _acquire_read(self) -> None:
        with self._cond:
            # 写者优先：有写者等待或写者活跃时，读者等待
            while self._writer_active or self._writers_waiting > 0:
                self._cond.wait()
            self._readers += 1

    def _release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    def _acquire_write(self) -> None:
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._writer_active or self._readers > 0:
                    self._cond.wait()
                self._writer_active = True
            finally:
                self._writers_waiting -= 1

    def _release_write(self) -> None:
        with self._cond:
            self._writer_active = False
            self._cond.notify_all()


class DummyReadWriteLock:
    """空操作读写锁 —— thread_safe=False 时替代 ReadWriteLock，零开销"""

    class _NoopContext:
        def __enter__(self) -> "DummyReadWriteLock._NoopContext":
            return self
        def __exit__(self, *args: object) -> None:
            pass

    def __init__(self) -> None:
        self._ctx = DummyReadWriteLock._NoopContext()

    def read(self) -> "DummyReadWriteLock._NoopContext":
        return self._ctx

    def write(self) -> "DummyReadWriteLock._NoopContext":
        return self._ctx


class ResourcePool(ABC):
    """所有资源池的抽象基类

    子类需实现 __len__ 和 __repr__，可选实现 __contains__。
    框架层可依赖此基类做统一调度（如：遍历所有池做健康检查）。

    子类必须在 __init__ 中初始化 self._lock：
        self._lock = threading.Lock() if thread_safe else DummyLock()
    """

    _lock: threading.Lock | DummyLock

    def __init_subclass__(cls, **kwargs: object) -> None:
        """子类注册钩子 —— 框架可在此校验子类契约"""
        super().__init_subclass__(**kwargs)

    @abstractmethod
    def __len__(self) -> int:
        """返回可用资源数量"""
        ...

    @abstractmethod
    def __repr__(self) -> str:
        """可读的运行时状态"""
        ...

    def __contains__(self, item: Any) -> bool:
        """是否包含指定资源（子类可按需覆盖）"""
        return False


class StrategyProtocol(ABC):
    """资源选择策略协议 —— 实现此协议的 callable 对象可作为自定义策略

    适用于 DNSResolverPool / ProxyPool 等需要按策略选择资源节点的池。

    使用示例::

        class MyStrategy:
            def __call__(self, servers: list) -> Iterator:
                # 自定义排序/过滤逻辑
                return iter(sorted(servers, key=lambda s: s.weight, reverse=True))

        pool.strategy = MyStrategy()
    """

    @abstractmethod
    def __call__(self, servers: list) -> Iterator:
        """接收 alive 服务器列表，返回迭代器"""
        ...

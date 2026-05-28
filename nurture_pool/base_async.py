"""异步资源池抽象基类 —— 与同步 ResourcePool 平行的 asyncio 接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
import asyncio


class AsyncDummyLock:
    """空操作异步上下文管理器 —— thread_safe=False 时替代 asyncio.Lock，零开销"""

    async def __aenter__(self) -> "AsyncDummyLock":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class AsyncReadWriteLock:
    """异步读写锁 —— 读多写少场景的性能优化（asyncio 版本）

    多个协程可同时持有读锁，写锁独占。写者优先（避免写饥饿）。

    使用示例::

        rwlock = AsyncReadWriteLock()

        # 读操作（多协程可并发）
        async with rwlock.read():
            data = shared_list.copy()

        # 写操作（独占）
        async with rwlock.write():
            shared_list.append(item)
    """

    class _ReadContext:
        __slots__ = ("_owner",)

        def __init__(self, owner: "AsyncReadWriteLock") -> None:
            self._owner = owner

        async def __aenter__(self) -> "AsyncReadWriteLock._ReadContext":
            await self._owner._acquire_read()
            return self

        async def __aexit__(self, *args: object) -> None:
            await self._owner._release_read()

    class _WriteContext:
        __slots__ = ("_owner",)

        def __init__(self, owner: "AsyncReadWriteLock") -> None:
            self._owner = owner

        async def __aenter__(self) -> "AsyncReadWriteLock._WriteContext":
            await self._owner._acquire_write()
            return self

        async def __aexit__(self, *args: object) -> None:
            await self._owner._release_write()

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._readers: int = 0
        self._writers_waiting: int = 0
        self._writer_active: bool = False

    def read(self) -> "AsyncReadWriteLock._ReadContext":
        return AsyncReadWriteLock._ReadContext(self)

    def write(self) -> "AsyncReadWriteLock._WriteContext":
        return AsyncReadWriteLock._WriteContext(self)

    async def _acquire_read(self) -> None:
        async with self._cond:
            while self._writer_active or self._writers_waiting > 0:
                await self._cond.wait()
            self._readers += 1

    async def _release_read(self) -> None:
        async with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    async def _acquire_write(self) -> None:
        async with self._cond:
            self._writers_waiting += 1
            try:
                while self._writer_active or self._readers > 0:
                    await self._cond.wait()
                self._writer_active = True
            finally:
                self._writers_waiting -= 1

    async def _release_write(self) -> None:
        async with self._cond:
            self._writer_active = False
            self._cond.notify_all()


class AsyncDummyReadWriteLock:
    """空操作异步读写锁 —— thread_safe=False 时替代 AsyncReadWriteLock，零开销"""

    class _NoopContext:
        async def __aenter__(self) -> "AsyncDummyReadWriteLock._NoopContext":
            return self
        async def __aexit__(self, *args: object) -> None:
            pass

    def __init__(self) -> None:
        self._ctx = AsyncDummyReadWriteLock._NoopContext()

    def read(self) -> "AsyncDummyReadWriteLock._NoopContext":
        return self._ctx

    def write(self) -> "AsyncDummyReadWriteLock._NoopContext":
        return self._ctx


class AsyncResourcePool(ABC):
    """所有异步资源池的抽象基类

    与同步版 ResourcePool 平行的 asyncio 接口。子类需实现 __len__ 和 __repr__，
    可选实现 __contains__。

    子类必须在 __init__ 中初始化 self._lock：
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()

    框架层可依赖此基类做统一异步调度（如 AsyncPoolOrchestrator）。
    """

    _lock: object  # asyncio.Lock | AsyncDummyLock（避免强制导入 asyncio）

    def __init_subclass__(cls, **kwargs: object) -> None:
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

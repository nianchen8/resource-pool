"""异步资源池抽象基类 —— 与同步 ResourcePool 平行的 asyncio 接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AsyncDummyLock:
    """空操作异步上下文管理器 —— thread_safe=False 时替代 asyncio.Lock，零开销"""

    async def __aenter__(self) -> "AsyncDummyLock":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


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

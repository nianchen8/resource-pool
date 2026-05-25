"""资源池公共异常基类"""

__all__ = ["PoolExhaustedError", "ResourceUnhealthyError"]


class PoolExhaustedError(Exception):
    """池中所有资源均已不可用时抛出

    UA / DNS / Proxy 三个子池的 PoolExhaustedException 均继承自此基类，
    便于统一捕获：except PoolExhaustedError
    """


class ResourceUnhealthyError(Exception):
    """单个资源健康检查失败时抛出"""

"""DNS 解析器池异常"""

from resource_pool.exceptions import PoolExhaustedError, ResourceUnhealthyError


class PoolExhaustedException(PoolExhaustedError):
    """池中所有 DNS 资源均已不可用"""

    def __init__(self, resource_type: str = "", detail: str = ""):
        msg = f"所有 {resource_type} 均不可用" if resource_type else "资源池已耗尽"
        if detail:
            msg += f"：{detail}"
        super().__init__(msg)


class ResourceUnhealthyException(ResourceUnhealthyError):
    """单个 DNS 资源健康检查失败"""

    def __init__(self, resource_id: str, detail: str = ""):
        msg = f"资源 {resource_id} 健康检查失败"
        if detail:
            msg += f"：{detail}"
        super().__init__(msg)

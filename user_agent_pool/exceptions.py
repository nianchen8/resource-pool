"""User-Agent 池异常"""

from resource_pool.exceptions import PoolExhaustedError, ResourceUnhealthyError


class PoolExhaustedException(PoolExhaustedError):
    """池中无可用的 User-Agent 时抛出"""

    def __init__(self, resource_type: str = "", detail: str = ""):
        msg = "暂无可用 User-Agent"
        if resource_type:
            msg = f"分类 '{resource_type}' 下{msg}"
        if detail:
            msg += f"：{detail}"
        super().__init__(msg)


class InvalidAgentException(ResourceUnhealthyError):
    """传入无效的 User-Agent 时抛出"""

    def __init__(self, reason: str = "不合法的 User-Agent"):
        super().__init__(reason)

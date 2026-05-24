class PoolExhaustedException(Exception):
    """池中无可用的 User-Agent 时抛出"""

    def __init__(self, category: str | None = None):
        msg = "暂无可用 User-Agent"
        if category:
            msg = f"分类 '{category}' 下{msg}"
        super().__init__(msg)


class InvalidAgentException(Exception):
    """传入无效的 User-Agent 时抛出"""

    def __init__(self, reason: str = "不合法的 User-Agent"):
        super().__init__(reason)

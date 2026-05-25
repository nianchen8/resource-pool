"""User-Agent 资源池

提供线程安全的 User-Agent 管理，支持按设备分类（desktop/mobile/tablet）的加权/均匀随机获取，
以及完整的 Header Profile 组（User-Agent + Accept + Sec-Ch-Ua 等配套请求头）。

基本用法::

    from user_agent_pool import UserAgentPool

    pool = UserAgentPool()
    ua = pool.get("mobile")                     # 加权随机，返回 UA 字符串
    headers = pool.get_headers("desktop")       # 返回完整请求头字典
    print(pool.count())                         # {'desktop': 10, ...}

    with pool.reserve("desktop") as ua:
        # 用完自动回收
        pass
"""

from user_agent_pool.pool import UserAgentPool, UAReserve, UAStrategy
from user_agent_pool.exceptions import PoolExhaustedException, InvalidAgentException
from user_agent_pool.agents import VALID_CATEGORIES, AVAILABLE_PROFILES, get_available_profiles

from resource_pool.orchestrator import PoolOrchestrator
PoolOrchestrator.register_dispatch(UserAgentPool, "get_headers")

__all__ = [
    "UserAgentPool",
    "UAReserve",
    "UAStrategy",
    "PoolExhaustedException",
    "InvalidAgentException",
    "VALID_CATEGORIES",
    "AVAILABLE_PROFILES",
    "get_available_profiles",
]

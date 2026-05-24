"""Resource Pool —— 可扩展的网络资源池框架

开箱即用的爬虫资源调度：User-Agent 池（含 Header Profile 组） + DNS 解析器池。

基本用法::

    from resource_pool import UserAgentPool, DNSResolverPool, SelectStrategy

    # UA 池
    ua_pool = UserAgentPool()
    ua = ua_pool.get("desktop")
    headers = ua_pool.get_headers("mobile")     # 完整 Header Profile

    # DNS 池
    dns_pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
    dns_pool.health_check()
    ip = dns_pool.resolve("www.example.com")
"""

from user_agent_pool import UserAgentPool, UAReserve, VALID_CATEGORIES
from user_agent_pool.exceptions import PoolExhaustedException as UAPoolExhaustedException
from user_agent_pool.exceptions import InvalidAgentException

from dns_resolver_pool import DNSResolverPool, SelectStrategy
from dns_resolver_pool.exceptions import PoolExhaustedException as DNSPoolExhaustedException
from dns_resolver_pool.exceptions import ResourceUnhealthyException

__all__ = [
    # UA 池
    "UserAgentPool",
    "UAReserve",
    "VALID_CATEGORIES",
    "UAPoolExhaustedException",
    "InvalidAgentException",
    # DNS 池
    "DNSResolverPool",
    "SelectStrategy",
    "DNSPoolExhaustedException",
    "ResourceUnhealthyException",
]

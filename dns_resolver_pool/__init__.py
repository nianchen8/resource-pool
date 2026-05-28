"""DNS 解析器资源池

可扩展的 DNS 解析器资源池，支持延迟加权/轮询/随机三种服务端选择策略，
内置国内+海外 14 台 DNS 服务器，提供自动健康检查、故障隔离、
定时复活、TTL 缓存等能力。

基本用法::

    from dns_resolver_pool import DNSResolverPool, SelectStrategy

    pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
    pool.health_check()                          # 首次使用建议先跑一次
    ip = pool.resolve("www.example.com")         # 返回最快 IP
    ips = pool.resolve_all("www.example.com")    # 返回全部 IP
    print(pool.stats())                          # 各服务器运行时状态

    # 动态扩展
    pool.add_server({"ip": "10.0.0.1", "name": "自建 DNS", "region": "private"})
"""

from dns_resolver_pool.pool import DNSResolverPool, SelectStrategy
from dns_resolver_pool.exceptions import PoolExhaustedException, ResourceUnhealthyException

from nurture_pool.orchestrator import PoolOrchestrator
PoolOrchestrator.register_dispatch(DNSResolverPool, "get_server")

__all__ = [
    "DNSResolverPool",
    "SelectStrategy",
    "PoolExhaustedException",
    "ResourceUnhealthyException",
]

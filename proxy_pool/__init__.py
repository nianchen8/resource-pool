"""代理资源池

可扩展的 HTTP/HTTPS/SOCKS5 代理资源池，支持延迟加权/轮询/随机三种选择策略，
提供自动健康检查、故障隔离、定时复活等能力。

基本用法::

    from proxy_pool import ProxyPool, ProxyStrategy

    pool = ProxyPool(strategy=ProxyStrategy.LATENCY_WEIGHTED)
    pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})
    pool.add_proxy({"scheme": "socks5", "host": "127.0.0.1", "port": 1080})
    pool.health_check()
    proxy_url = pool.get()  # "http://127.0.0.1:8080"
    print(pool.stats())
"""

from proxy_pool.pool import ProxyPool, ProxyStrategy
from proxy_pool.exceptions import PoolExhaustedException, ProxyUnhealthyException

from resource_pool.orchestrator import PoolOrchestrator
PoolOrchestrator.register_dispatch(ProxyPool, "get_dict")

__all__ = [
    "ProxyPool",
    "ProxyStrategy",
    "PoolExhaustedException",
    "ProxyUnhealthyException",
]

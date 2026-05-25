"""Resource Pool —— 可扩展的网络资源池框架

开箱即用的爬虫资源调度：User-Agent 池（含 Header Profile 组） + DNS 解析器池 + 代理池。

基本用法::

    from resource_pool import UserAgentPool, DNSResolverPool, ProxyPool, SelectStrategy

    # UA 池
    ua_pool = UserAgentPool()
    ua = ua_pool.get("desktop")
    headers = ua_pool.get_headers("mobile")     # 完整 Header Profile

    # DNS 池
    dns_pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
    dns_pool.health_check()
    ip = dns_pool.resolve("www.example.com")

    # 代理池
    proxy_pool = ProxyPool()
    proxy_pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})
    proxies = proxy_pool.get_dict()

    # 统一捕获异常
    from resource_pool import PoolExhaustedError
    try:
        ip = dns_pool.resolve("blocked.example.com")
    except PoolExhaustedError:
        print("所有 DNS 都失败了")

高并发建议::

    所有池操作均受 threading.Lock 保护。百级以上并发建议：
    1. 为不同业务线创建独立池实例，减少锁争用
    2. DNS 池配合缓存命中率可大幅降低锁持有时间
    3. UA 池 get/get_headers 是读多写少，锁争用低
    4. 编排器内部的 _fetch_from_pool 在锁外执行，并发友好
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from resource_pool.exceptions import PoolExhaustedError, ResourceUnhealthyError

# ── IDE / 类型检查器可见的静态导入（运行时仍走惰性加载）─────────────
if TYPE_CHECKING:
    from resource_pool.base import ResourcePool, StrategyProtocol
    from resource_pool.orchestrator import PoolOrchestrator
    from user_agent_pool.pool import UserAgentPool, UAStrategy, UAReserve
    from user_agent_pool.agents import VALID_CATEGORIES, AVAILABLE_PROFILES, get_available_profiles
    from user_agent_pool.exceptions import PoolExhaustedException as UAPoolExhaustedException, InvalidAgentException
    from dns_resolver_pool.pool import DNSResolverPool, SelectStrategy
    from dns_resolver_pool.exceptions import (
        PoolExhaustedException as DNSPoolExhaustedException,
        ResourceUnhealthyException,
        ResourceUnhealthyException as DNSUnhealthyException,
    )
    from proxy_pool.pool import ProxyPool, ProxyStrategy
    from proxy_pool.exceptions import PoolExhaustedException as ProxyPoolExhaustedException, ProxyUnhealthyException

# ── 惰性导入 —— 避免按需使用时加载不必要的子包 ──────────────────────

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # attr_name → (module, qualname)
    "UserAgentPool":              ("user_agent_pool", "UserAgentPool"),
    "UAStrategy":                 ("user_agent_pool", "UAStrategy"),
    "UAReserve":                  ("user_agent_pool", "UAReserve"),
    "VALID_CATEGORIES":           ("user_agent_pool", "VALID_CATEGORIES"),
    "AVAILABLE_PROFILES":         ("user_agent_pool", "AVAILABLE_PROFILES"),
    "get_available_profiles":     ("user_agent_pool", "get_available_profiles"),
    "UAPoolExhaustedException":   ("user_agent_pool.exceptions", "PoolExhaustedException"),
    "InvalidAgentException":      ("user_agent_pool.exceptions", "InvalidAgentException"),
    "DNSResolverPool":            ("dns_resolver_pool", "DNSResolverPool"),
    "SelectStrategy":             ("dns_resolver_pool", "SelectStrategy"),
    "DNSPoolExhaustedException":  ("dns_resolver_pool.exceptions", "PoolExhaustedException"),
    "ResourceUnhealthyException": ("dns_resolver_pool.exceptions", "ResourceUnhealthyException"),
    # DNSUnhealthyException 是 ResourceUnhealthyException 的别名，指向同一个底层类
    "DNSUnhealthyException":      ("dns_resolver_pool.exceptions", "ResourceUnhealthyException"),
    "PoolExhaustedError":         ("resource_pool.exceptions", "PoolExhaustedError"),
    "ResourceUnhealthyError":     ("resource_pool.exceptions", "ResourceUnhealthyError"),
    "ResourcePool":               ("resource_pool.base", "ResourcePool"),
    "StrategyProtocol":           ("resource_pool.base", "StrategyProtocol"),
    "PoolOrchestrator":           ("resource_pool.orchestrator", "PoolOrchestrator"),
    "ProxyPool":                  ("proxy_pool", "ProxyPool"),
    "ProxyStrategy":              ("proxy_pool", "ProxyStrategy"),
    "ProxyPoolExhaustedException":("proxy_pool.exceptions", "PoolExhaustedException"),
    "ProxyUnhealthyException":    ("proxy_pool.exceptions", "ProxyUnhealthyException"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        import importlib
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr)
        # 缓存到模块全局，避免重复 import
        globals()[name] = value
        return value
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    # 公共异常
    "PoolExhaustedError",
    "ResourceUnhealthyError",
    # 抽象基类
    "ResourcePool",
    "StrategyProtocol",
    # 编排器
    "PoolOrchestrator",
    # UA 池
    "UserAgentPool",
    "UAStrategy",
    "UAReserve",
    "VALID_CATEGORIES",
    "AVAILABLE_PROFILES",
    "get_available_profiles",
    "UAPoolExhaustedException",
    "InvalidAgentException",
    # DNS 池
    "DNSResolverPool",
    "SelectStrategy",
    "DNSPoolExhaustedException",
    "ResourceUnhealthyException",
    "DNSUnhealthyException",
    # Proxy 池
    "ProxyPool",
    "ProxyStrategy",
    "ProxyPoolExhaustedException",
    "ProxyUnhealthyException",
]

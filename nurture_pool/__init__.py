"""Resource Pool —— 爬虫资源池微框架

短路径（日常使用）::

    import nurture_pool

    ua = nurture_pool.UA()
    ua.pick()                        # 轮换 User-Agent
    ua.headers()                      # 完整反爬请求头

    proxy = nurture_pool.Proxy("1.2.3.4:8080")
    proxy.pick()                      # 轮换代理

    dns = nurture_pool.DNS()
    dns.resolve("www.example.com")    # 轮换 DNS 解析

    c = nurture_pool.combo(ua=ua, dns=dns, proxy=proxy)
    # c.ua / c.dns / c.proxy

长路径（深度定制）::

    from nurture_pool import UserAgentPool, DNSResolverPool, ProxyPool, PoolOrchestrator

    ua_pool = UserAgentPool(strategy=UAStrategy.WEIGHTED)
    dns_pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
    dns_pool.health_check()
    proxy_pool = ProxyPool()
    proxy_pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})
    proxy_pool.health_check()

    orch = PoolOrchestrator(ua=ua_pool, dns=dns_pool, proxy=proxy_pool)
    combos = list(orch.combos(limit=100))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nurture_pool.exceptions import PoolExhaustedError, ResourceUnhealthyError

# ── IDE / 类型检查器可见的静态导入（运行时仍走惰性加载）─────────────
if TYPE_CHECKING:
    from nurture_pool.base import ResourcePool, StrategyProtocol
    from nurture_pool.orchestrator import PoolOrchestrator, PoolCombo
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
    "PoolExhaustedError":         ("nurture_pool.exceptions", "PoolExhaustedError"),
    "ResourceUnhealthyError":     ("nurture_pool.exceptions", "ResourceUnhealthyError"),
    "ResourcePool":               ("nurture_pool.base", "ResourcePool"),
    "StrategyProtocol":           ("nurture_pool.base", "StrategyProtocol"),
    "PoolOrchestrator":           ("nurture_pool.orchestrator", "PoolOrchestrator"),
    "PoolCombo":                  ("nurture_pool.orchestrator", "PoolCombo"),
    "ProxyPool":                  ("proxy_pool", "ProxyPool"),
    "ProxyStrategy":              ("proxy_pool", "ProxyStrategy"),
    "ProxyPoolExhaustedException":("proxy_pool.exceptions", "PoolExhaustedException"),
    "ProxyUnhealthyException":    ("proxy_pool.exceptions", "ProxyUnhealthyException"),
    # 短别名（日常使用）
    "UA":                         ("nurture_pool._shortcuts", "UA"),
    "Proxy":                      ("nurture_pool._shortcuts", "Proxy"),
    "DNS":                        ("nurture_pool._shortcuts", "DNS"),
    "combo":                      ("nurture_pool._shortcuts", "combo"),
    # 养成系 API
    "feed_ua":                    ("nurture_pool._feeding", "feed_ua"),
    "feed_proxy":                 ("nurture_pool._feeding", "feed_proxy"),
    "feed_dns":                   ("nurture_pool._feeding", "feed_dns"),
    "import_ua":                  ("nurture_pool._feeding", "import_ua"),
    "import_proxy":               ("nurture_pool._feeding", "import_proxy"),
    "import_dns":                 ("nurture_pool._feeding", "import_dns"),
    "export_fed":                 ("nurture_pool._feeding", "export_fed"),
    "status":                     ("nurture_pool._feeding", "status"),
    "list_fed":                   ("nurture_pool._feeding", "list_fed"),
    "get_stats":                  ("nurture_pool._feeding", "get_stats"),
    "remove_fed":                 ("nurture_pool._feeding", "remove_fed"),
    "reset":                      ("nurture_pool._feeding", "reset"),
    "sync_seeds":                 ("nurture_pool._feeding", "sync_seeds"),
    "probe_proxy":                ("nurture_pool._feeding", "probe_proxy"),
    "validate_fed_proxies":       ("nurture_pool._feeding", "validate_fed_proxies"),
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
    "PoolCombo",
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
    # 短别名
    "UA",
    "Proxy",
    "DNS",
    "combo",
    # 养成系 API
    "feed_ua",
    "feed_proxy",
    "feed_dns",
    "import_ua",
    "import_proxy",
    "import_dns",
    "export_fed",
    "status",
    "list_fed",
    "get_stats",
    "remove_fed",
    "reset",
    "sync_seeds",
    "probe_proxy",
    "validate_fed_proxies",
]

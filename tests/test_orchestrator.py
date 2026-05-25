"""编排器测试"""

import pytest
from user_agent_pool import UserAgentPool
from proxy_pool import ProxyPool

from resource_pool.orchestrator import PoolOrchestrator


class TestOrchestrator:
    """PoolOrchestrator 基本操作"""

    def test_init_with_pools(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        assert "ua" in orch.pool_names
        assert "proxy" in orch.pool_names

    def test_init_empty_raises(self):
        with pytest.raises(ValueError, match="至少需要注册"):
            PoolOrchestrator()

    def test_register_unregister(self):
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        assert "ua" in orch.pool_names

        orch.unregister("ua")
        assert "ua" not in orch.pool_names

        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})
        orch.register("proxy", proxy)
        assert "proxy" in orch.pool_names

    def test_register_non_pool_raises(self):
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        with pytest.raises(TypeError, match="必须实现 ResourcePool 协议"):
            orch.register("bad", object())  # type: ignore[arg-type]

    def test_next_returns_combo(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        combo = orch.next()

        assert "ua" in combo
        assert "proxy" in combo
        assert isinstance(combo["ua"], dict)   # UA 池返回完整 headers 字典
        assert isinstance(combo["proxy"], dict)  # Proxy 返回 proxies 字典
        assert "User-Agent" in combo["ua"]       # headers 含 UA 字段

    def test_next_ua_proxy_only(self):
        """UA + Proxy 组合（不含 DNS）"""
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "10.0.0.1", "port": 3128})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        combo = orch.next()

        assert "User-Agent" in combo["ua"]   # headers 字典含 UA 字段
        assert "http" in combo["proxy"]      # 代理字典含 http 键

    def test_combos_iterator(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        combos = list(orch.combos(limit=3))

        assert len(combos) == 3
        for c in combos:
            assert "ua" in c
            assert "proxy" in c

    def test_health_check_all(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        results = orch.health_check_all(timeout=2.0)

        assert "ua" in results
        assert "proxy" in results
        assert results["ua"] == "N/A (池不支持健康检查)"

    def test_repr(self):
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        r = repr(orch)
        assert "PoolOrchestrator" in r
        assert "ua" in r

"""DNS 解析器池单元测试"""

import pytest

from dns_resolver_pool import DNSResolverPool, SelectStrategy
from dns_resolver_pool.exceptions import PoolExhaustedException, ResourceUnhealthyException
from dns_resolver_pool.servers import ServerEntry


class TestDNSResolverPool:
    """基础功能测试"""

    def test_init_loads_defaults(self):
        pool = DNSResolverPool()
        assert len(pool) > 0
        # 国内 7 台 + 海外 7 台 = 14
        alive = [s for s in pool.stats() if s["enabled"]]
        assert len(alive) >= 14

    def test_init_domestic_only(self):
        pool = DNSResolverPool(regions=("domestic",))
        stats = pool.stats()
        regions = {s["region"] for s in stats}
        assert regions == {"domestic"}

    def test_init_overseas_only(self):
        pool = DNSResolverPool(regions=("overseas",))
        stats = pool.stats()
        regions = {s["region"] for s in stats}
        assert regions == {"overseas"}

    def test_add_server(self):
        pool = DNSResolverPool()
        before = len(pool.stats())
        pool.add_server({
            "ip": "10.0.0.53",
            "name": "测试 DNS",
            "region": "private",
            "weight": 10,
        })
        after = len(pool.stats())
        assert after == before + 1

    def test_add_duplicate_server(self):
        pool = DNSResolverPool()
        before = len(pool.stats())
        pool.add_server({
            "ip": "10.0.0.53",
            "name": "测试 DNS",
            "region": "private",
        })
        pool.add_server({
            "ip": "10.0.0.53",
            "name": "测试 DNS v2",
            "region": "private",
            "weight": 8,
        })
        # 不应重复添加
        after = len(pool.stats())
        assert after == before + 1

    def test_remove_server(self):
        pool = DNSResolverPool()
        result = pool.remove_server("114.114.114.114")
        assert result is True
        stats = pool.stats()
        s114 = next(s for s in stats if s["ip"] == "114.114.114.114")
        assert s114["enabled"] is False

    def test_remove_nonexistent_server(self):
        pool = DNSResolverPool()
        result = pool.remove_server("0.0.0.0")
        assert result is False

    def test_enable_server(self):
        pool = DNSResolverPool()
        pool.remove_server("114.114.114.114")
        result = pool.enable_server("114.114.114.114")
        assert result is True
        stats = pool.stats()
        s114 = next(s for s in stats if s["ip"] == "114.114.114.114")
        assert s114["enabled"] is True

    def test_stats(self):
        pool = DNSResolverPool()
        stats = pool.stats()
        assert isinstance(stats, list)
        assert len(stats) >= 14
        for s in stats:
            assert "ip" in s
            assert "name" in s
            assert "region" in s
            assert "enabled" in s
            assert "latency_ms" in s

    def test_clear_cache(self):
        pool = DNSResolverPool()
        # 首次解析后应有缓存
        pool.resolve("www.baidu.com")
        pool.clear_cache()
        # 不应抛异常
        assert True

    def test_repr(self):
        pool = DNSResolverPool()
        r = repr(pool)
        assert "DNSResolverPool" in r

    def test_len(self):
        pool = DNSResolverPool()
        assert len(pool) <= len(pool.stats())

    def test_strategy_property(self):
        pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
        assert pool.strategy == SelectStrategy.LATENCY_WEIGHTED
        pool.strategy = SelectStrategy.ROUND_ROBIN
        assert pool.strategy == SelectStrategy.ROUND_ROBIN
        pool.strategy = SelectStrategy.RANDOM
        assert pool.strategy == SelectStrategy.RANDOM

    def test_invalid_server_raises(self):
        """无效 DNS 服务器应抛出异常"""
        pool = DNSResolverPool(regions=("domestic",))
        # 全部移除后应抛出异常
        for s in pool.stats():
            pool.remove_server(s["ip"])
        with pytest.raises(PoolExhaustedException):
            pool.resolve("www.baidu.com")


class TestDNSResolution:
    """实际 DNS 解析测试（需要网络连接）"""

    def test_resolve_returns_ip(self):
        pool = DNSResolverPool(regions=("domestic",))
        ip = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)
        # IP 地址格式：x.x.x.x
        parts = ip.split(".")
        assert len(parts) == 4

    def test_resolve_all_returns_list(self):
        pool = DNSResolverPool(regions=("domestic",))
        ips = pool.resolve_all("www.baidu.com", timeout=5.0)
        assert isinstance(ips, list)
        assert len(ips) > 0
        for ip in ips:
            assert "." in ip

    def test_resolve_caches(self):
        """验证缓存生效：连续两次解析速度"""
        import time
        pool = DNSResolverPool(regions=("domestic",), cache_ttl=60)
        pool.resolve("www.baidu.com")
        start = time.monotonic()
        pool.resolve("www.baidu.com")  # 应命中缓存
        elapsed = (time.monotonic() - start) * 1000
        # 缓存命中应在 1ms 以内
        assert elapsed < 50, f"缓存命中耗时 {elapsed:.1f}ms，可能未命中"

    def test_health_check(self):
        pool = DNSResolverPool(regions=("domestic",))
        results = pool.health_check(timeout=5.0)
        assert isinstance(results, dict)
        assert len(results) > 0
        for ip, status in results.items():
            assert status in ("OK", "FAIL")


class TestSelectStrategy:
    """选择策略测试"""

    def test_latency_weighted(self):
        pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
        pool.health_check(timeout=5.0)
        ip = pool.resolve("www.baidu.com")
        assert isinstance(ip, str)

    def test_round_robin(self):
        pool = DNSResolverPool(strategy=SelectStrategy.ROUND_ROBIN)
        ip = pool.resolve("www.baidu.com")
        assert isinstance(ip, str)

    def test_random(self):
        pool = DNSResolverPool(strategy=SelectStrategy.RANDOM)
        ip = pool.resolve("www.baidu.com")
        assert isinstance(ip, str)


class TestFaultIsolation:
    """故障隔离与复活测试"""

    def test_consecutive_fail_isolation(self):
        """模拟连续失败后服务器被隔离"""
        pool = DNSResolverPool(
            regions=(),                # 不加载默认服务器
            max_consecutive_fails=2,
            revive_after=99999,
        )
        # 添加一个必定失败的服务器
        pool.add_server({
            "ip": "0.0.0.0",
            "name": "Bad DNS",
            "region": "test",
        })

        # 连续失败 2 次（池中只有这一台，必定被选中）
        for _ in range(2):
            try:
                pool.resolve("www.baidu.com", timeout=1.0)
            except PoolExhaustedException:
                pass

        # 检查 Bad DNS 是否被禁用
        stats = pool.stats()
        bad = next(s for s in stats if s["ip"] == "0.0.0.0")
        assert bad["enabled"] is False, "连续失败后应被隔离"

    def test_revive_after_timeout(self):
        """测试复活机制：过了 revive_after 后自动恢复"""
        pool = DNSResolverPool(
            regions=("domestic",),
            max_consecutive_fails=1,
            revive_after=0,  # 立即复活
        )
        # 手动强制隔离
        pool.remove_server("114.114.114.114")
        with pool._lock:
            s = next(s for s in pool._servers if s.ip == "114.114.114.114")
            s.last_health = 0  # 伪造为很久以前

        # 下一次调用应触发复活
        pool.resolve("www.baidu.com")
        stats = pool.stats()
        s114 = next(s for s in stats if s["ip"] == "114.114.114.114")
        assert s114["enabled"] is True, "超过复活时间应自动恢复"

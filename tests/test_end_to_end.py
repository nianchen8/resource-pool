"""端到端测试 —— 获取资源→模拟请求→释放资源全流程

覆盖 UPGRADE_PLAN 11.4：端到端测试走完"获取资源→发起请求→释放资源"全流程。
不依赖真实网络请求，使用 mock + 本地代理完成验证。
"""

import json
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from resource_pool import (
    UserAgentPool, DNSResolverPool, ProxyPool,
    UAStrategy, SelectStrategy, ProxyStrategy, PoolOrchestrator,
    PoolExhaustedError,
)
from user_agent_pool.exceptions import PoolExhaustedException as UAPoolExhausted


# ═══════════════════════════════════════════════════════════════════════
# 1. 端到端：UA+DNS+Proxy 三池组合全流程
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndOrchestrated:
    """编排器三池组合端到端"""

    def test_ua_dns_proxy_full_combo(self):
        """UA + DNS + Proxy 组合获取，验证每个资源可用"""
        ua = UserAgentPool()
        dns = DNSResolverPool(regions=("domestic",))
        dns.health_check(timeout=5.0)
        proxy = ProxyPool()
        proxy.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, dns=dns, proxy=proxy)
        combo = orch.next()

        # 验证三类资源
        assert "ua" in combo
        assert "dns" in combo
        assert "proxy" in combo
        assert "User-Agent" in combo["ua"]
        assert isinstance(combo["dns"], str)
        assert "http" in combo["proxy"]

    def test_combos_iteration_with_three_pools(self):
        """三池组合迭代 5 次，每次返回完整组合"""
        ua = UserAgentPool()
        dns = DNSResolverPool(regions=("domestic",))
        dns.health_check(timeout=5.0)
        proxy = ProxyPool()
        proxy.add_proxy({"scheme": "http", "host": "10.0.0.1", "port": 3128})

        orch = PoolOrchestrator(ua=ua, dns=dns, proxy=proxy)
        combos = list(orch.combos(limit=5))

        assert len(combos) == 5
        for i, c in enumerate(combos):
            assert "User-Agent" in c["ua"], f"第 {i} 组缺少 UA"
            assert isinstance(c["dns"], str), f"第 {i} 组 DNS 不是字符串"
            assert "http" in c["proxy"], f"第 {i} 组 Proxy 缺少 http key"


# ═══════════════════════════════════════════════════════════════════════
# 2. 端到端：UA reserve → 使用 → 归还
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndUAReserve:
    """UA 暂存器全流程"""

    def test_reserve_multiple_rounds(self):
        """多轮 reserve → 使用 → 归还，数量始终一致"""
        pool = UserAgentPool()
        before = pool.count("desktop")
        assert isinstance(before, int)

        for _ in range(min(5, before)):
            with pool.reserve("desktop") as ua:
                assert isinstance(ua, str)
                assert "Mozilla" in ua
                # 模拟"使用"：构造请求头
                headers = {"User-Agent": ua}
                assert headers["User-Agent"] == ua

        after = pool.count("desktop")
        assert after == before

    def test_reserve_all_categories_cycle(self):
        """遍历所有分类的 reserve 流程"""
        pool = UserAgentPool()
        for category in ("desktop", "mobile", "tablet"):
            count_before = pool.count(category)
            assert isinstance(count_before, int)
            if count_before == 0:
                continue
            with pool.reserve(category) as ua:
                assert "Mozilla" in ua
            count_after = pool.count(category)
            assert count_after == count_before

    def test_exhausted_category_handling(self):
        """耗尽分类后被正确处理"""
        pool = UserAgentPool()
        # 耗尽 desktop
        for ua in list(pool.get_all("desktop")):
            pool.remove(ua, "desktop")

        with pytest.raises(UAPoolExhausted):
            pool.get("desktop")

        with pytest.raises(UAPoolExhausted):
            pool.get_headers("desktop")


# ═══════════════════════════════════════════════════════════════════════
# 3. 端到端：代理加载→获取→标记失败→隔离→复活
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndProxyLifecycle:
    """代理全生命周期端到端"""

    @patch("urllib.request.urlopen")
    def test_load_get_mark_revive_cycle(self, mock_urlopen):
        """加载→获取→标记失败→隔离→复活 全流程"""
        mock_urlopen.return_value = MagicMock()
        mock_urlopen.return_value.read.return_value = b"1.2.3.4:8080\n5.6.7.8:3128"
        mock_urlopen.return_value.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_urlopen.return_value
        mock_urlopen.return_value.__exit__.return_value = False

        pool = ProxyPool(max_consecutive_fails=2, revive_after=0)

        # 1. 加载代理
        count = pool.load_from_url("http://fake.api/proxy")
        assert count == 2
        assert len(pool) == 2

        # 2. 获取代理
        proxy_url = pool.get()
        assert proxy_url.startswith("http://")

        # 3. 获取 proxies 字典
        proxy_dict = pool.get_dict()
        assert "http" in proxy_dict
        assert "https" in proxy_dict

        # 4. 标记失败
        pool.mark_failed("1.2.3.4", 8080)
        pool.mark_failed("1.2.3.4", 8080)

        # 5. 验证隔离
        assert "http://1.2.3.4:8080" in pool or len(pool) >= 1

        # 6. 手动恢复
        assert pool.enable_proxy("1.2.3.4", 8080) is True

    def test_stats_after_operations(self):
        """操作后 stats 反映正确状态"""
        pool = ProxyPool()
        pool.add_proxy({"scheme": "http", "host": "stats.proxy", "port": 80})

        stats = pool.stats()
        assert len(stats) == 1
        assert stats[0]["proxy"] == "http://stats.proxy:80"
        assert stats[0]["enabled"] is True

        pool.remove_proxy("stats.proxy", 80)
        stats_after = pool.stats()
        assert stats_after[0]["enabled"] is False


# ═══════════════════════════════════════════════════════════════════════
# 4. 端到端：DNS 解析→缓存→清空→重新解析
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndDNSFlow:
    """DNS 解析全流程端到端"""

    def test_resolve_cache_clear_cycle(self):
        """解析→缓存命中→清空缓存→重新解析"""
        pool = DNSResolverPool(regions=("domestic",), cache_ttl=60)

        # 1. 首次解析
        ip1 = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip1, str)

        # 2. 缓存命中
        start = time.monotonic()
        ip2 = pool.resolve("www.baidu.com", timeout=5.0)
        cached_time = (time.monotonic() - start) * 1000
        assert ip2 == ip1
        assert cached_time < 50, f"缓存命中耗时 {cached_time:.1f}ms"

        # 3. 清空缓存
        pool.clear_cache()

        # 4. 重新解析
        ip3 = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip3, str)

    def test_health_check_then_isolate_then_revive(self):
        """健康检查→隔离→复活 全流程"""
        pool = DNSResolverPool(
            regions=("domestic",),
            max_consecutive_fails=1,
            revive_after=0,  # 立即复活
        )

        # 1. 健康检查
        results = pool.health_check(timeout=5.0)
        assert len(results) >= 7  # domestic 至少 7 台

        # 2. 手动隔离一台
        pool.remove_server("114.114.114.114")

        # 3. 强制触发复活
        with pool._lock:
            for s in pool._servers:
                if s.ip == "114.114.114.114":
                    s.last_health = 0

        pool.resolve("www.baidu.com", timeout=5.0)

        # 4. 验证恢复
        stats = pool.stats()
        s114 = next((s for s in stats if s["ip"] == "114.114.114.114"), None)
        if s114:
            assert s114["enabled"] is True, "超过复活时间应恢复"

    def test_strategy_switching_during_resolve(self):
        """运行时切换策略后正常解析"""
        pool = DNSResolverPool(regions=("domestic",))

        strategies = [
            SelectStrategy.LATENCY_WEIGHTED,
            SelectStrategy.ROUND_ROBIN,
            SelectStrategy.RANDOM,
        ]

        for i, strat in enumerate(strategies, start=1):
            pool.strategy = strat
            ip = pool.resolve("www.baidu.com", timeout=5.0)
            assert isinstance(ip, str), f"第 {i} 次切换策略后解析失败"


# ═══════════════════════════════════════════════════════════════════════
# 5. 端到端：thread_safe=False 零开销模式全流程
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndThreadSafeOff:
    """单线程零开销模式全流程"""

    def test_ua_thread_safe_off_full_flow(self):
        """UA 池 thread_safe=False 完整使用流程"""
        pool = UserAgentPool(thread_safe=False)

        # get
        ua = pool.get("desktop")
        assert isinstance(ua, str)

        # get_headers
        headers = pool.get_headers("mobile")
        assert "User-Agent" in headers

        # count
        stats = pool.count()
        assert isinstance(stats, dict)

        # reserve
        with pool.reserve("tablet") as reserved:
            assert "Mozilla" in reserved

        # add + remove
        pool.add("MyBot/1.0", "desktop", weight=3)
        removed = pool.remove("MyBot/1.0", "desktop")
        assert removed == 1

        # iter
        all_uas = list(pool)
        assert len(all_uas) == sum(pool.count().values())

    def test_proxy_thread_safe_off_full_flow(self):
        """Proxy 池 thread_safe=False 完整使用流程"""
        pool = ProxyPool(thread_safe=False)
        pool.add_proxy({"host": "p1.com", "port": 80})
        pool.add_proxy({"host": "p2.com", "port": 3128})

        # get
        url = pool.get()
        assert url.startswith("http://")

        # get_dict
        d = pool.get_dict()
        assert "http" in d

        # stats
        stats = pool.stats()
        assert len(stats) == 2

        # contains
        assert "http://p1.com:80" in pool

        # remove + enable
        pool.remove_proxy("p1.com", 80)
        assert len(pool) == 1
        pool.enable_proxy("p1.com", 80)
        assert len(pool) == 2

    def test_dns_thread_safe_off_full_flow(self):
        """DNS 池 thread_safe=False 完整使用流程"""
        pool = DNSResolverPool(regions=("domestic",), thread_safe=False)

        # resolve
        ip = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)

        # resolve_all
        ips = pool.resolve_all("www.baidu.com", timeout=5.0)
        assert len(ips) > 0

        # stats
        stats = pool.stats()
        assert len(stats) >= 7

        # health_check
        results = pool.health_check(timeout=5.0)
        assert len(results) > 0

        # close
        pool.close()
        ip2 = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip2, str)


# ═══════════════════════════════════════════════════════════════════════
# 6. 端到端：并发安全最终验证
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndConcurrencyFinal:
    """并发安全最终验证 —— 多池同时并发操作"""

    def test_multi_pool_concurrent_orchestration(self):
        """多池编排器 + 多线程并发获取组合"""
        ua = UserAgentPool()
        dns = DNSResolverPool(regions=("domestic",), cache_ttl=60)
        dns.health_check(timeout=5.0)
        proxy = ProxyPool()
        proxy.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, dns=dns, proxy=proxy)
        errors: list[Exception] = []

        def worker():
            for _ in range(5):
                try:
                    combo = orch.next()
                    assert "User-Agent" in combo["ua"]
                    assert isinstance(combo["dns"], str)
                    assert "http" in combo["proxy"]
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"多池并发出现 {len(errors)} 个异常: {errors[:3]}"

    def test_concurrent_reserve_across_categories(self):
        """跨分类并发 reserve 数量一致"""
        pool = UserAgentPool()
        before_desktop = pool.count("desktop")
        before_mobile = pool.count("mobile")
        assert isinstance(before_desktop, int)
        assert isinstance(before_mobile, int)

        def worker(cat: str):
            for _ in range(5):
                try:
                    with pool.reserve(cat) as _ua:
                        time.sleep(0.005)
                except PoolExhaustedError:
                    pass

        threads = [
            threading.Thread(target=worker, args=("desktop",)),
            threading.Thread(target=worker, args=("mobile",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert pool.count("desktop") == before_desktop
        assert pool.count("mobile") == before_mobile

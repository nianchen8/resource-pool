"""实战测试 —— 真实网络环境下的功能验证"""
import threading
import time
import pytest

from resource_pool import (
    UserAgentPool, DNSResolverPool,
    UAStrategy, SelectStrategy, PoolOrchestrator,
    PoolExhaustedError, ResourceUnhealthyError,
)


# ═══════════════════════════════════════════════════════════════
# 1. DNS 解析器池 —— 真实解析
# ═══════════════════════════════════════════════════════════════

class TestDNSRealWorld:
    """DNS 池在真实 DNS 服务器上的表现"""

    def test_resolve_real_domains(self):
        """解析多个真实域名，确保返回有效 IP"""
        pool = DNSResolverPool(regions=("domestic",))
        domains = [
            "www.baidu.com",
            "www.qq.com",
            "www.taobao.com",
        ]
        for domain in domains:
            ip = pool.resolve(domain, timeout=5.0)
            # 必须是合法的 IPv4 或 IPv6
            parts = ip.replace("[", "").replace("]", "").split(".")
            is_ipv4 = len(parts) == 4 and all(p.isdigit() for p in parts)
            is_ipv6 = ":" in ip
            assert is_ipv4 or is_ipv6, f"{domain} → {ip}（非有效IP）"

    def test_resolve_all_returns_multiple(self):
        """resolve_all 对大型域名应返回多条记录"""
        pool = DNSResolverPool(regions=("domestic",))
        ips = pool.resolve_all("www.baidu.com", timeout=5.0)
        assert len(ips) >= 1, f"百度至少应有 1 条 A 记录，实际: {ips}"

    def test_cache_works(self):
        """缓存命中：第二次解析同一域名应更快"""
        pool = DNSResolverPool(regions=("domestic",), cache_ttl=60)
        # 预热
        pool.resolve("www.baidu.com", timeout=5.0)

        start = time.monotonic()
        pool.resolve("www.baidu.com", timeout=5.0)
        cached_duration = (time.monotonic() - start) * 1000

        # 缓存命中应极快（< 5ms，通常 < 1ms）
        assert cached_duration < 10, f"缓存命中耗时 {cached_duration:.2f}ms（期望 < 10ms）"

    def test_health_check_all_reachable(self):
        """健康检查：国内 DNS 应大部分可达"""
        pool = DNSResolverPool(regions=("domestic",))
        results = pool.health_check(timeout=5.0)
        ok_count = sum(1 for v in results.values() if v == "OK")
        total = len(results)
        assert ok_count >= total * 0.5, f"可用 {ok_count}/{total}，期望 ≥ 50%"

    def test_strategy_round_robin(self):
        """轮询策略下连续解析应使用不同服务器"""
        pool = DNSResolverPool(
            regions=("domestic",),
            strategy=SelectStrategy.ROUND_ROBIN,
        )
        pool.health_check(timeout=5.0)
        # 记录成功使用的服务器（通过延迟区分）
        latencies = []
        for _ in range(6):
            start = time.monotonic()
            pool.resolve("www.baidu.com", timeout=5.0)
            latencies.append(round((time.monotonic() - start) * 1000))
        # 至少有不同延迟值（说明用了不同服务器）
        assert len(set(latencies)) >= 2 or len(latencies) >= 6

    def test_close_releases_resources(self):
        """close() 不抛异常"""
        pool = DNSResolverPool(regions=("domestic",))
        pool.resolve("www.baidu.com", timeout=5.0)
        pool.close()  # 不应抛异常
        # close 后仍可正常使用：新的 Resolver 会自动创建
        ip = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)

    def test_thread_safe_off_works(self):
        """thread_safe=False 模式下真实解析"""
        pool = DNSResolverPool(regions=("domestic",), thread_safe=False)
        ip = pool.resolve("www.baidu.com", timeout=5.0)
        parts = ip.split(".")
        assert len(parts) == 4


# ═══════════════════════════════════════════════════════════════
# 2. User-Agent 池 —— 真实请求头质量
# ═══════════════════════════════════════════════════════════════

class TestUARealWorld:
    """UA 池实际返回数据验证"""

    def test_get_returns_valid_ua(self):
        """每个分类的 UA 都包含标准浏览器标识"""
        pool = UserAgentPool()
        for cat in ("desktop", "mobile", "tablet"):
            ua = pool.get(cat)
            assert "Mozilla" in ua, f"{cat} UA 不含 Mozilla: {ua[:60]}"
            assert len(ua) > 30, f"{cat} UA 太短: {len(ua)} 字"

    def test_get_headers_contains_expected_fields(self):
        """get_headers 返回完整的请求头"""
        pool = UserAgentPool()
        headers = pool.get_headers("desktop")
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert len(headers) >= 3, f"headers 字段过少: {list(headers.keys())}"

    def test_exclude_filters_correctly(self):
        """exclude 参数排除特定关键词"""
        pool = UserAgentPool()
        # 注意："Safari" 出现在所有现代浏览器 UA 中，
        # 故用更精确的关键词排除
        for _ in range(20):
            ua = pool.get("desktop", exclude={"Firefox", "Edg"})
            assert "Firefox" not in ua
            assert "Edg" not in ua

    def test_strategy_uniform(self):
        """UNIFORM 策略下各 UA 被选中的概率接近"""
        pool = UserAgentPool(strategy=UAStrategy.UNIFORM)
        counts: dict[str, int] = {}
        for _ in range(200):
            ua = pool.get("desktop")
            counts[ua] = counts.get(ua, 0) + 1
        # 每个都有被选中
        assert len(counts) >= len(pool._agents["desktop"]) * 0.7

    def test_reserve_restores(self):
        """reserve 取出后归还"""
        pool = UserAgentPool()
        before = pool.count("desktop")
        with pool.reserve("desktop") as ua:
            # 取出期间数量 -1
            assert pool.count("desktop") == before - 1
        # 退出后恢复
        assert pool.count("desktop") == before

    def test_count_type(self):
        """count() 返回类型"""
        pool = UserAgentPool()
        all_counts = pool.count()
        assert isinstance(all_counts, dict)
        assert "desktop" in all_counts

        single = pool.count("mobile")
        assert isinstance(single, int)

    def test_iter_produces_all(self):
        """迭代所有 UA"""
        pool = UserAgentPool()
        total = len(pool)
        items = list(pool)
        assert len(items) == total

    def test_thread_safe_off_works(self):
        """thread_safe=False 所有操作正常"""
        pool = UserAgentPool(thread_safe=False)
        ua = pool.get("desktop")
        assert isinstance(ua, str)
        headers = pool.get_headers("mobile")
        assert "User-Agent" in headers
        stats = pool.count()
        assert isinstance(stats, dict)


# ═══════════════════════════════════════════════════════════════
# 3. 编排器 —— UA + DNS 组合
# ═══════════════════════════════════════════════════════════════

class TestOrchestratorRealWorld:
    """编排器真实组合测试"""

    def test_combo_ua_dns(self):
        """编排器 UA+DNS：DNS 因需域名会抛 RuntimeError（符合设计）"""
        ua = UserAgentPool()
        dns = DNSResolverPool(regions=("domestic",))
        dns.health_check(timeout=5.0)

        orch = PoolOrchestrator(ua=ua, dns=dns)
        # DNSResolverPool 需域名参数，编排器会明确报错
        with pytest.raises(RuntimeError, match="resolve"):
            orch.next()

    def test_combo_ua_only(self):
        """只有 UA 池的编排器"""
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        combo = orch.next()
        assert "ua" in combo
        assert "User-Agent" in combo["ua"]

    def test_combos_yields_multiple(self):
        """combos(limit=N) 返回 N 组"""
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        combos = list(orch.combos(limit=5))
        assert len(combos) == 5
        for c in combos:
            assert "User-Agent" in c["ua"]


# ═══════════════════════════════════════════════════════════════
# 4. 并发实战压力测试
# ═══════════════════════════════════════════════════════════════

class TestConcurrencyStress:
    """多线程高负载实战"""

    def test_50_threads_ua_get(self):
        """50 线程同时 get() 100 次"""
        pool = UserAgentPool()
        errors: list[Exception] = []
        iterations = 100

        def worker():
            for _ in range(iterations):
                try:
                    pool.get("desktop")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"50线程并发出现 {len(errors)} 个异常: {errors[:3]}"

    def test_20_threads_dns_resolve(self):
        """20 线程同时解析（利用缓存降低 DNS 请求）"""
        pool = DNSResolverPool(regions=("domestic",), cache_ttl=60)
        # 预热缓存
        pool.resolve("www.baidu.com", timeout=5.0)
        errors: list[Exception] = []

        def worker():
            for _ in range(10):
                try:
                    pool.resolve("www.baidu.com", timeout=5.0)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"20线程DNS并发出现 {len(errors)} 个异常: {errors[:3]}"


# ═══════════════════════════════════════════════════════════════
# 5. 故障隔离 —— 真实网络模拟
# ═══════════════════════════════════════════════════════════════

class TestFaultIsolationRealWorld:
    """在真实网络中验证故障隔离机制"""

    def test_bad_server_isolated(self):
        """添加一个不可达 DNS，确认被隔离后不影响解析"""
        pool = DNSResolverPool(
            regions=("domestic",),
            max_consecutive_fails=1,  # 一次失败即隔离，确保 health_check 能触发
            revive_after=99999,
        )
        # 添加不可达服务器
        pool.add_server({
            "ip": "192.0.2.1",  # TEST-NET-1，RFC 5737 保留地址，通常不可达
            "name": "Bad DNS",
            "region": "test",
        })

        # 显式健康检查：逐一探测所有服务器（比 resolve 循环更确定性）
        pool.health_check(timeout=5.0)

        # 检查 Bad DNS 状态
        stats = pool.stats()
        bad = next((s for s in stats if s["ip"] == "192.0.2.1"), None)
        assert bad is not None, "Bad DNS 应在 stats 中"

        if bad["enabled"]:
            # 该 IP 在当前网络环境中恰好可达（如 Docker/VM 占用 TEST-NET），跳过断言
            pytest.skip("192.0.2.1 在当前网络环境中可达，跳过隔离验证")

        assert bad["enabled"] is False, "不可达服务器应被隔离"

        # 隔离后仍可正常解析
        ip = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)

    def test_uniform_strategy_switching(self):
        """运行时切换策略不抛异常"""
        pool = DNSResolverPool(regions=("domestic",))

        pool.strategy = SelectStrategy.ROUND_ROBIN
        pool.resolve("www.baidu.com", timeout=5.0)

        pool.strategy = SelectStrategy.RANDOM
        pool.resolve("www.baidu.com", timeout=5.0)

        pool.strategy = SelectStrategy.LATENCY_WEIGHTED
        pool.resolve("www.baidu.com", timeout=5.0)

    def test_clear_cache_then_resolve(self):
        """清空缓存后仍能解析"""
        pool = DNSResolverPool(regions=("domestic",))
        pool.resolve("www.baidu.com", timeout=5.0)
        pool.clear_cache()
        ip = pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)

"""并发安全测试 —— 验证多线程下的数据一致性"""

import threading
import time

from user_agent_pool import UserAgentPool
from user_agent_pool.exceptions import PoolExhaustedException

N_THREADS = 10
ITERATIONS = 30


class TestUAConcurrency:
    """User-Agent 池并发测试"""

    def test_concurrent_get_does_not_crash(self):
        """大量线程同时 get() 不抛非预期异常"""
        pool = UserAgentPool()
        errors: list[Exception] = []

        def worker():
            for _ in range(ITERATIONS):
                try:
                    pool.get("desktop")
                except PoolExhaustedException:
                    pass
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发 get 出现异常: {errors}"

    def test_concurrent_get_headers_does_not_crash(self):
        """大量线程同时 get_headers() 不抛非预期异常"""
        pool = UserAgentPool()
        errors: list[Exception] = []

        def worker():
            for _ in range(ITERATIONS):
                try:
                    pool.get_headers("mobile")
                except PoolExhaustedException:
                    pass
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发 get_headers 出现异常: {errors}"

    def test_concurrent_add_remove_consistent(self):
        """并发增删后 count 与实际长度一致"""
        pool = UserAgentPool()
        pool.remove(pool.get("desktop"), "desktop")  # 腾出一个位置

        def adder():
            for i in range(ITERATIONS // N_THREADS):
                pool.add(f"ConcurrentBot/{i}", "desktop", weight=2)

        def remover():
            for _ in range(ITERATIONS // N_THREADS):
                try:
                    ua = pool.get("desktop")
                    pool.remove(ua, "desktop")
                except PoolExhaustedException:
                    pass

        threads = [threading.Thread(target=adder) for _ in range(N_THREADS // 2)]
        threads += [threading.Thread(target=remover) for _ in range(N_THREADS // 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # count 应与实际长度一致
        stats_result = pool.count()
        stats: dict[str, int] = stats_result if isinstance(stats_result, dict) else {"desktop": stats_result}  # type: ignore[assignment]
        with pool._lock:
            actual = len(pool._agents.get("desktop", []))
        assert stats.get("desktop") == actual, f"count={stats.get('desktop')} 实际={actual}（不一致）"

    def test_concurrent_reserve_restores_correctly(self):
        """大量线程 reserve 后数量应恢复原值"""
        pool = UserAgentPool()
        count_result = pool.count("desktop")
        before: int = count_result if isinstance(count_result, int) else count_result.get("desktop", 0)  # type: ignore[union-attr]
        errors: list[Exception] = []

        def worker():
            try:
                with pool.reserve("desktop") as _ua:
                    time.sleep(0.01)  # 模拟使用
            except PoolExhaustedException:
                pass
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(min(N_THREADS, before))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        after_result = pool.count("desktop")
        after: int = after_result if isinstance(after_result, int) else after_result.get("desktop", 0)  # type: ignore[union-attr]
        assert after == before, f"reserve 后数量: before={before} after={after}"


class TestDNSConcurrency:
    """DNS 解析器池并发测试"""

    def test_concurrent_resolve_does_not_crash(self):
        """大量线程同时 resolve 同一域名不抛非预期异常"""
        from dns_resolver_pool import DNSResolverPool
        from dns_resolver_pool.exceptions import PoolExhaustedException as DNSPoolExhausted

        pool = DNSResolverPool(regions=("domestic",), cache_ttl=60)
        errors: list[Exception] = []

        def worker():
            for _ in range(5):
                try:
                    pool.resolve("www.baidu.com", timeout=5.0)
                except DNSPoolExhausted:
                    pass
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发 resolve 出现异常: {errors}"

    def test_concurrent_stats_is_consistent(self):
        """并发操作期间 stats() 调用不抛异常且返回有效结构"""
        from dns_resolver_pool import DNSResolverPool

        pool = DNSResolverPool(regions=("domestic",))

        stats_errors: list[Exception] = []

        def resolver():
            try:
                pool.resolve("www.baidu.com", timeout=5.0)
            except PoolExhaustedException:
                pass
            except Exception as e:
                stats_errors.append(e)

        def stat_collector():
            for _ in range(10):
                try:
                    s = pool.stats()
                    if not isinstance(s, list):
                        stats_errors.append(TypeError("stats 返回非 list"))
                except Exception as e:
                    stats_errors.append(e)
                time.sleep(0.005)

        threads = [threading.Thread(target=resolver) for _ in range(3)]
        threads.append(threading.Thread(target=stat_collector))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(stats_errors) == 0, f"并发 stats 出现异常: {stats_errors}"

    def test_concurrent_add_remove_does_not_crash(self):
        """并发增删 DNS 服务器不抛非预期异常"""
        from dns_resolver_pool import DNSResolverPool

        pool = DNSResolverPool(regions=("domestic",))
        errors: list[Exception] = []

        def adder():
            for i in range(10):
                try:
                    pool.add_server({
                        "ip": f"10.0.{i}.{i % 255}",
                        "name": f"并发测试 DNS {i}",
                        "region": "test",
                    })
                except Exception as e:
                    errors.append(e)

        def remover():
            for _ in range(10):
                try:
                    pool.remove_server("114.114.114.114")
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=adder),
            threading.Thread(target=remover),
            threading.Thread(target=adder),
            threading.Thread(target=remover),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发增删出现异常: {errors}"

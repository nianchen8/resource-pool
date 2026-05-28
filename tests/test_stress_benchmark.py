"""基准压力测试 —— 100/500/1000 并发下的锁性能

衡量 ReadWriteLock + 缓存分片锁的优化效果。
运行方式：
    python -m pytest tests/test_stress_benchmark.py -v -s --tb=short
或仅运行特定级别：
    python -m pytest tests/test_stress_benchmark.py -k "100" -v -s
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from user_agent_pool import UserAgentPool
from proxy_pool import ProxyPool
from dns_resolver_pool import DNSResolverPool


# ── 辅助函数 ─────────────────────────────────────────────────────────

def _measure_concurrent(
    pool,
    worker_fn,
    num_threads: int,
    iterations_per_thread: int,
) -> dict:
    """运行并发基准测试，返回 {total_ops, elapsed_sec, ops_per_sec, latencies}"""
    latencies: list[float] = []
    lat_lock = threading.Lock()

    def worker():
        for _ in range(iterations_per_thread):
            start = time.perf_counter()
            worker_fn(pool)
            elapsed = time.perf_counter() - start
            with lat_lock:
                latencies.append(elapsed)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker) for _ in range(num_threads)]
        for f in as_completed(futures):
            f.result()  # 传播异常
    total_elapsed = time.perf_counter() - start

    total_ops = num_threads * iterations_per_thread
    latencies.sort()
    return {
        "total_ops": total_ops,
        "elapsed_sec": round(total_elapsed, 3),
        "ops_per_sec": round(total_ops / total_elapsed, 1),
        "p50_ms": round(latencies[len(latencies) // 2] * 1000, 3),
        "p99_ms": round(latencies[int(len(latencies) * 0.99)] * 1000, 3),
        "max_ms": round(latencies[-1] * 1000, 3),
    }


# ── UA 池压力测试 ────────────────────────────────────────────────────

class TestUABenchmark:
    """UA 池读写锁基准"""

    @pytest.mark.parametrize("n_threads", [100, 500])
    def test_ua_get_throughput(self, n_threads: int):
        """测试 get() 操作在高并发下的吞吐量"""
        pool = UserAgentPool()
        iters = max(10, 5000 // n_threads)  # 保证总操作数 ≈ 5000

        def do_get(p: UserAgentPool) -> None:
            p.get("all")

        result = _measure_concurrent(pool, do_get, n_threads, iters)
        print(f"\n  UA get() @ {n_threads}线程: "
              f"{result['ops_per_sec']} ops/s, "
              f"P50={result['p50_ms']}ms, P99={result['p99_ms']}ms, "
              f"max={result['max_ms']}ms")

        # 基本性能断言：吞吐量不应过低
        assert result["ops_per_sec"] > 1000, (
            f"UA get 吞吐量过低: {result['ops_per_sec']} ops/s"
        )

    @pytest.mark.parametrize("n_threads", [100, 500])
    def test_ua_get_headers_throughput(self, n_threads: int):
        """测试 get_headers() 操作（含 Profile 查找）"""
        pool = UserAgentPool()
        iters = max(10, 5000 // n_threads)

        def do_get_headers(p: UserAgentPool) -> None:
            p.get_headers("desktop")

        result = _measure_concurrent(pool, do_get_headers, n_threads, iters)
        print(f"\n  UA get_headers() @ {n_threads}线程: "
              f"{result['ops_per_sec']} ops/s, "
              f"P50={result['p50_ms']}ms, P99={result['p99_ms']}ms")


# ── Proxy 池压力测试 ─────────────────────────────────────────────────

class TestProxyBenchmark:
    """代理池锁基准"""

    @pytest.fixture
    def large_proxy_pool(self) -> ProxyPool:
        """含 50 个虚拟代理的池子"""
        pool = ProxyPool(thread_safe=True)
        for i in range(50):
            pool.add_proxy({
                "scheme": "http",
                "host": f"10.0.{i // 256}.{i % 256}",
                "port": 8080 + (i % 100),
            })
        return pool

    @pytest.mark.parametrize("n_threads", [100, 500])
    def test_proxy_get_throughput(self, large_proxy_pool: ProxyPool, n_threads: int):
        """测试代理池 get() 并发吞吐"""
        pool = large_proxy_pool
        iters = max(10, 5000 // n_threads)

        def do_get(p: ProxyPool) -> None:
            p.get()

        result = _measure_concurrent(pool, do_get, n_threads, iters)
        print(f"\n  Proxy get() @ {n_threads}线程: "
              f"{result['ops_per_sec']} ops/s, "
              f"P50={result['p50_ms']}ms, P99={result['p99_ms']}ms, "
              f"max={result['max_ms']}ms")

        assert result["ops_per_sec"] > 500, (
            f"Proxy get 吞吐量过低: {result['ops_per_sec']} ops/s"
        )

    @pytest.mark.parametrize("n_threads", [100, 500])
    def test_proxy_mixed_rw_throughput(self, large_proxy_pool: ProxyPool, n_threads: int):
        """测试读多写少（90% get + 10% mark_failed）"""
        pool = large_proxy_pool
        iters = max(10, 3000 // n_threads)

        def mixed_worker(p: ProxyPool) -> None:
            for i in range(iters):
                if i % 10 == 0:
                    # 10% 写：标记随机代理失败
                    p.mark_failed(f"10.0.{i % 50 // 256}.{i % 50 % 256}", 8080)
                else:
                    p.get()

        result = _measure_concurrent(pool, mixed_worker, n_threads, 1)
        # 每个 worker 内部已做 iters 次操作
        total_ops = n_threads * iters
        print(f"\n  Proxy 读写混合 @ {n_threads}线程: "
              f"{total_ops} ops, "
              f"elapsed={result['elapsed_sec']}s")


# ── DNS 缓存压力测试 ─────────────────────────────────────────────────

class TestDNSCacheBenchmark:
    """DNS 缓存分片锁基准"""

    @pytest.fixture
    def dns_pool_with_warm_cache(self) -> DNSResolverPool:
        """预热缓存的 DNS 池"""
        pool = DNSResolverPool(regions=("domestic",), cache_ttl=300)
        # 预填充缓存：100 个不同域名
        for i in range(100):
            domain = f"test{i}.example.com"
            cache_key = f"{domain}:A"
            pool._cache[cache_key] = (["1.2.3.4"], time.time() + 300)
            pool._cache_order.append(cache_key)
        return pool

    @pytest.mark.parametrize("n_threads", [100, 500])
    def test_dns_cache_hit_throughput(
        self, dns_pool_with_warm_cache: DNSResolverPool, n_threads: int
    ):
        """测试缓存命中路径的并发吞吐（不触发实际 DNS 查询）"""
        pool = dns_pool_with_warm_cache
        iters = max(10, 5000 // n_threads)

        # 直接测缓存命中的内部路径
        def cache_read(p: DNSResolverPool) -> None:
            for i in range(iters):
                key = f"test{i % 100}.example.com:A"
                p._cache_get(key)

        result = _measure_concurrent(pool, cache_read, n_threads, 1)
        total_ops = n_threads * iters
        print(f"\n  DNS cache命中 @ {n_threads}线程: "
              f"{total_ops} reads, "
              f"elapsed={result['elapsed_sec']}s, "
              f"P50={result['p50_ms']}ms, P99={result['p99_ms']}ms")

    @pytest.mark.parametrize("n_threads", [100, 500])
    def test_dns_cache_mixed_rw(
        self, dns_pool_with_warm_cache: DNSResolverPool, n_threads: int
    ):
        """测试缓存读写混合（80% 读 + 20% 写）"""
        pool = dns_pool_with_warm_cache
        iters = max(10, 3000 // n_threads)

        def mixed_worker(p: DNSResolverPool) -> None:
            for i in range(iters):
                if i % 5 == 0:
                    # 20% 写
                    key = f"new_test{i}.example.com:A"
                    p._cache_set(key, [f"10.0.{i % 256}.{i // 256}"])
                else:
                    # 80% 读
                    key = f"test{i % 100}.example.com:A"
                    p._cache_get(key)

        result = _measure_concurrent(pool, mixed_worker, n_threads, 1)
        total_ops = n_threads * iters
        print(f"\n  DNS cache读写混合 @ {n_threads}线程: "
              f"{total_ops} ops, "
              f"elapsed={result['elapsed_sec']}s")


# ── 综合对比报告 ─────────────────────────────────────────────────────

class TestBenchmarkReport:
    """生成综合压力测试报告"""

    def test_summary_report(self):
        """汇总所有三级（100/500/1000）的 UA + Proxy + DNS 基准数据"""
        print("\n" + "=" * 70)
        print("  nurture-pool v1.0.3 基准压力测试报告")
        print("=" * 70)

        results: list[dict] = []

        # ── UA 池 ──
        pool = UserAgentPool()
        for n in [100, 500, 1000]:
            iters = max(10, 5000 // n)
            r = _measure_concurrent(pool, lambda p: p.get("all"), n, iters)
            results.append({"组件": "UA get()", "线程": n, **r})

        # ── Proxy 池 ──
        ppool = ProxyPool(thread_safe=True)
        for i in range(50):
            ppool.add_proxy({
                "scheme": "http",
                "host": f"10.0.{i // 256}.{i % 256}",
                "port": 8080 + (i % 100),
            })
        for n in [100, 500, 1000]:
            iters = max(10, 3000 // n)
            r = _measure_concurrent(ppool, lambda p: p.get(), n, iters)
            results.append({"组件": "Proxy get()", "线程": n, **r})

        # ── DNS 缓存 ──
        dns_pool = DNSResolverPool(regions=("domestic",), cache_ttl=300)
        for i in range(100):
            key = f"test{i}.example.com:A"
            dns_pool._cache[key] = (["1.2.3.4"], time.time() + 300)
            dns_pool._cache_order.append(key)
        for n in [100, 500, 1000]:
            iters = max(10, 5000 // n)

            def dns_read(p: DNSResolverPool, _iters: int = iters) -> None:
                for i in range(_iters):
                    p._cache_get(f"test{i % 100}.example.com:A")

            r = _measure_concurrent(dns_pool, dns_read, n, 1)
            total = n * iters
            r["ops_per_sec"] = round(total / r["elapsed_sec"], 1)
            results.append({"组件": "DNS cache", "线程": n, **r})

        # ── 打印表格 ──
        print(f"\n{'组件':<16} {'线程':>5} {'总操作':>8} {'耗时(s)':>8} "
              f"{'吞吐(ops/s)':>12} {'P50(ms)':>9} {'P99(ms)':>9}")
        print("-" * 70)
        for r in results:
            print(f"{r['组件']:<16} {r['线程']:>5} {r['total_ops']:>8} "
                  f"{r['elapsed_sec']:>8} {r['ops_per_sec']:>12} "
                  f"{r['p50_ms']:>9} {r['p99_ms']:>9}")

        print("-" * 70)
        print("  注：P50/P99 为单次操作延迟。DNS 缓存为纯内存分片锁读写。")
        print("      UA 池使用 ReadWriteLock，Proxy 池使用 threading.Lock。")
        print("=" * 70)

        # 断言各组件在 1000 并发下依然稳健
        for r in results:
            if r["线程"] == 1000:
                assert r["ops_per_sec"] > 0, (
                    f"{r['组件']} 在 1000 并发下吞吐量为零"
                )

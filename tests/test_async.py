"""异步组件测试 —— AsyncUserAgentPool / AsyncDNSResolverPool / AsyncProxyPool / AsyncPoolOrchestrator"""

import asyncio

import pytest

from resource_pool.base_async import AsyncDummyLock, AsyncResourcePool
from resource_pool.exceptions import PoolExhaustedError
from resource_pool.orchestrator_async import AsyncPoolOrchestrator
from user_agent_pool.pool_async import AsyncUserAgentPool, AsyncUAReserve
from dns_resolver_pool.pool_async import AsyncDNSResolverPool
from proxy_pool.pool_async import AsyncProxyPool


# ── 异步测试辅助 ────────────────────────────────────────────────────

def async_test(coro_func):
    """用 asyncio.run() 包装异步测试方法（支持 self）"""
    def wrapper(*args, **kwargs):
        coro = coro_func(*args, **kwargs)
        return asyncio.run(coro)
    return wrapper


# ═══════════════════════════════════════════════════════════════════════
# AsyncUserAgentPool 测试
# ═══════════════════════════════════════════════════════════════════════

class TestAsyncUserAgentPool:

    @async_test
    async def test_init_loads_defaults(self):
        pool = AsyncUserAgentPool()
        assert len(pool) > 0
        assert "desktop" in repr(pool)

    @async_test
    async def test_get_returns_string(self):
        pool = AsyncUserAgentPool()
        ua = await pool.get()
        assert isinstance(ua, str)
        assert "Mozilla" in ua

    @async_test
    async def test_get_by_category(self):
        pool = AsyncUserAgentPool()
        ua = await pool.get("mobile")
        assert isinstance(ua, str)

    @async_test
    async def test_get_headers(self):
        pool = AsyncUserAgentPool()
        headers = await pool.get_headers("desktop")
        assert "User-Agent" in headers
        assert "Mozilla" in headers["User-Agent"]

    @async_test
    async def test_get_headers_no_profile(self):
        pool = AsyncUserAgentPool()
        headers = await pool.get_headers("tablet")
        assert "User-Agent" in headers

    @async_test
    async def test_add_and_remove(self):
        pool = AsyncUserAgentPool()
        await pool.add("TestUA/1.0", "desktop", weight=3)
        assert "TestUA/1.0" in pool
        removed = await pool.remove("TestUA/1.0")
        assert removed == 1
        assert "TestUA/1.0" not in pool

    @async_test
    async def test_count(self):
        pool = AsyncUserAgentPool()
        cnt = await pool.count()
        assert isinstance(cnt, dict)
        assert "desktop" in cnt

    @async_test
    async def test_exhausted_category(self):
        pool = AsyncUserAgentPool()
        # 清空 mobile 分类
        await pool.remove("", "mobile")
        # 再获取应该仍然有数据（因为 remove("") 不会匹配任何 UA）
        # 换个方式：创建一个空池
        empty = AsyncUserAgentPool()
        # 清空所有
        for cat in ("desktop", "mobile", "tablet"):
            for ua in list(empty._agents.get(cat, [])):
                await empty.remove(ua["ua"], cat)
        with pytest.raises(PoolExhaustedError):
            await empty.get()

    @async_test
    async def test_contains(self):
        pool = AsyncUserAgentPool()
        ua = await pool.get("desktop")
        assert ua in pool
        assert "__nonexistent__" not in pool

    @async_test
    async def test_reserve_context_manager(self):
        pool = AsyncUserAgentPool()
        before = len(pool)
        async with pool.reserve("desktop") as ua:
            assert isinstance(ua, str)
            # 取出期间池子少一个
            assert len(pool) == before - 1
        # 归还后恢复
        assert len(pool) == before

    @async_test
    async def test_reserve_all_category(self):
        pool = AsyncUserAgentPool()
        before = len(pool)
        async with pool.reserve("all") as ua:
            assert len(pool) == before - 1
        assert len(pool) == before

    @async_test
    async def test_aiter(self):
        pool = AsyncUserAgentPool()
        uas = []
        async for ua in pool:
            uas.append(ua)
        assert len(uas) == len(pool)

    @async_test
    async def test_len(self):
        pool = AsyncUserAgentPool()
        assert len(pool) > 0

    @async_test
    async def test_thread_safe_off(self):
        pool = AsyncUserAgentPool(thread_safe=False)
        assert isinstance(pool._lock, AsyncDummyLock)
        ua = await pool.get()
        assert isinstance(ua, str)


# ═══════════════════════════════════════════════════════════════════════
# AsyncDNSResolverPool 测试
# ═══════════════════════════════════════════════════════════════════════

class TestAsyncDNSResolverPool:

    @async_test
    async def test_init_loads_defaults(self):
        pool = AsyncDNSResolverPool()
        assert len(pool) > 0
        assert "alive" in repr(pool)

    @async_test
    async def test_get_server(self):
        pool = AsyncDNSResolverPool()
        server = await pool.get_server()
        assert isinstance(server, str)
        # 应该是 IP 格式
        parts = server.split(".")
        assert len(parts) == 4

    @async_test
    async def test_resolve_real_domain(self):
        pool = AsyncDNSResolverPool()
        ip = await pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)

    @async_test
    async def test_resolve_all(self):
        pool = AsyncDNSResolverPool()
        ips = await pool.resolve_all("www.baidu.com", timeout=5.0)
        assert isinstance(ips, list)
        assert len(ips) >= 1

    @async_test
    async def test_cache_hit(self):
        pool = AsyncDNSResolverPool()
        ip1 = await pool.resolve("www.baidu.com", timeout=5.0)
        ip2 = await pool.resolve("www.baidu.com", timeout=5.0)
        assert ip1 == ip2  # 缓存命中应返回相同结果

    @async_test
    async def test_clear_cache(self):
        pool = AsyncDNSResolverPool()
        await pool.resolve("www.baidu.com", timeout=5.0)
        await pool.clear_cache()
        # 清空后再解析应成功
        ip = await pool.resolve("www.baidu.com", timeout=5.0)
        assert isinstance(ip, str)

    @async_test
    async def test_add_remove_server(self):
        pool = AsyncDNSResolverPool()
        await pool.add_server({"ip": "1.1.1.1", "name": "Cloudflare"})
        assert "1.1.1.1" in pool
        ok = await pool.remove_server("1.1.1.1")
        assert ok is True
        # remove_server 只禁用不禁用物理删除，__contains__ 仍可见
        assert "1.1.1.1" in pool
        # 但 get_server() 不会返回已禁用的服务器
        server = await pool.get_server()
        assert server != "1.1.1.1"

    @async_test
    async def test_enable_server(self):
        pool = AsyncDNSResolverPool()
        # 先禁用再启用
        server_ip = (await pool.get_server())
        await pool.remove_server(server_ip)
        ok = await pool.enable_server(server_ip)
        assert ok is True

    @async_test
    async def test_health_check(self):
        pool = AsyncDNSResolverPool()
        results = await pool.health_check(timeout=3.0)
        assert isinstance(results, dict)
        assert len(results) > 0

    @async_test
    async def test_stats(self):
        pool = AsyncDNSResolverPool()
        stats = await pool.stats()
        assert isinstance(stats, list)
        assert len(stats) > 0
        assert "ip" in stats[0]

    @async_test
    async def test_close(self):
        pool = AsyncDNSResolverPool()
        await pool.close()

    @async_test
    async def test_len_and_contains(self):
        pool = AsyncDNSResolverPool()
        assert len(pool) > 0
        server = await pool.get_server()
        assert server in pool

    @async_test
    async def test_bad_domain_raises(self):
        pool = AsyncDNSResolverPool()
        with pytest.raises(PoolExhaustedError):
            await pool.resolve("this-domain-definitely-does-not-exist-12345.invalid", timeout=2.0)


# ═══════════════════════════════════════════════════════════════════════
# AsyncProxyPool 测试
# ═══════════════════════════════════════════════════════════════════════

class TestAsyncProxyPool:

    def _make_pool(self):
        pool = AsyncProxyPool()
        pool.add_proxy({"host": "127.0.0.1", "port": 8080})
        pool.add_proxy({"host": "127.0.0.1", "port": 8081, "scheme": "https"})
        return pool

    @async_test
    async def test_init(self):
        pool = AsyncProxyPool()
        assert len(pool) == 0

    @async_test
    async def test_add_proxy(self):
        pool = self._make_pool()
        assert len(pool) == 2

    @async_test
    async def test_get(self):
        pool = self._make_pool()
        proxy = await pool.get()
        assert proxy.startswith("http://") or proxy.startswith("https://")

    @async_test
    async def test_get_dict(self):
        pool = self._make_pool()
        proxies = await pool.get_dict()
        assert "http" in proxies
        assert "https" in proxies

    @async_test
    async def test_get_exhausted(self):
        pool = AsyncProxyPool()
        with pytest.raises(PoolExhaustedError):
            await pool.get()

    @async_test
    async def test_remove_proxy(self):
        pool = self._make_pool()
        ok = pool.remove_proxy("127.0.0.1", 8080)
        assert ok is True
        assert len(pool) == 1

    @async_test
    async def test_enable_proxy(self):
        pool = self._make_pool()
        pool.remove_proxy("127.0.0.1", 8080)
        ok = pool.enable_proxy("127.0.0.1", 8080)
        assert ok is True

    @async_test
    async def test_mark_failed(self):
        pool = self._make_pool()
        ok = pool.mark_failed("127.0.0.1", 8080)
        assert ok is True

    @async_test
    async def test_mark_failed_nonexistent(self):
        pool = AsyncProxyPool()
        ok = pool.mark_failed("10.0.0.1", 9999)
        assert ok is False

    @async_test
    async def test_stats(self):
        pool = self._make_pool()
        stats = await pool.stats()
        assert len(stats) == 2

    @async_test
    async def test_contains(self):
        pool = self._make_pool()
        assert "http://127.0.0.1:8080" in pool
        assert "http://10.0.0.1:9999" not in pool

    @async_test
    async def test_invalid_scheme_raises(self):
        pool = AsyncProxyPool()
        with pytest.raises(ValueError, match="无效 scheme"):
            pool.add_proxy({"scheme": "ftp", "host": "127.0.0.1", "port": 21})

    @async_test
    async def test_missing_host_raises(self):
        pool = AsyncProxyPool()
        with pytest.raises(ValueError, match="必须包含 host 和 port"):
            pool.add_proxy({"port": 8080})

    @async_test
    async def test_health_check(self):
        pool = self._make_pool()
        results = await pool.health_check(timeout=2.0)
        assert isinstance(results, dict)
        assert len(results) == 2

    @async_test
    async def test_repr(self):
        pool = self._make_pool()
        r = repr(pool)
        assert "AsyncProxyPool" in r


# ═══════════════════════════════════════════════════════════════════════
# AsyncPoolOrchestrator 测试
# ═══════════════════════════════════════════════════════════════════════

class TestAsyncPoolOrchestrator:

    @async_test
    async def test_init_empty_raises(self):
        with pytest.raises(ValueError, match="至少需要注册"):
            AsyncPoolOrchestrator()

    @async_test
    async def test_init_with_pools(self):
        ua = AsyncUserAgentPool()
        pool = AsyncProxyPool()
        pool.add_proxy({"host": "127.0.0.1", "port": 8080})
        orch = AsyncPoolOrchestrator(ua=ua, proxy=pool)
        assert "ua" in orch.pool_names
        assert "proxy" in orch.pool_names

    @async_test
    async def test_register_unregister(self):
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        assert "ua" in orch.pool_names

        await orch.unregister("ua")
        assert "ua" not in orch.pool_names

        pool = AsyncProxyPool()
        pool.add_proxy({"host": "127.0.0.1", "port": 8080})
        await orch.register("proxy", pool)
        assert "proxy" in orch.pool_names

    @async_test
    async def test_next_ua_only(self):
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        combo = await orch.next()
        assert "ua" in combo
        assert isinstance(combo["ua"], dict)
        assert "User-Agent" in combo["ua"]

    @async_test
    async def test_next_ua_dns(self):
        ua = AsyncUserAgentPool()
        dns = AsyncDNSResolverPool()
        orch = AsyncPoolOrchestrator(ua=ua, dns=dns)
        combo = await orch.next()
        assert "ua" in combo
        assert "dns" in combo
        assert isinstance(combo["dns"], str)

    @async_test
    async def test_next_ua_proxy(self):
        ua = AsyncUserAgentPool()
        proxy = AsyncProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})
        orch = AsyncPoolOrchestrator(ua=ua, proxy=proxy)
        combo = await orch.next()
        assert "ua" in combo
        assert "proxy" in combo
        assert isinstance(combo["proxy"], dict)
        assert "http" in combo["proxy"]

    @async_test
    async def test_combos_iterator(self):
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        combos = []
        async for c in orch.combos(limit=3):
            combos.append(c)
        assert len(combos) == 3
        for c in combos:
            assert "ua" in c

    @async_test
    async def test_combos_stops_on_exhausted(self):
        class _ExhaustedPool(AsyncResourcePool):
            async def get(self):
                raise PoolExhaustedError("模拟耗尽")
            def __len__(self):
                return 0
            def __repr__(self):
                return "_ExhaustedPool()"

        orch = AsyncPoolOrchestrator(p=_ExhaustedPool())
        combos = []
        async for c in orch.combos(limit=10):
            combos.append(c)
        assert len(combos) == 0

    @async_test
    async def test_health_check_all(self):
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        results = await orch.health_check_all()
        assert "ua" in results
        assert results["ua"] == "N/A (池不支持健康检查)"

    @async_test
    async def test_repr(self):
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        r = repr(orch)
        assert "AsyncPoolOrchestrator" in r
        assert "ua" in r

    @async_test
    async def test_register_non_pool_raises(self):
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        with pytest.raises(TypeError, match="必须实现 AsyncResourcePool 协议"):
            await orch.register("bad", object())  # type: ignore[arg-type]

    @async_test
    async def test_fetch_dispatch_uses_registry(self):
        """验证 AsyncPoolOrchestrator 通过注册表分派"""
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)
        combo = await orch.next()
        # UA 池应返回完整 headers（get_headers），不是纯字符串（get）
        assert isinstance(combo["ua"], dict)
        assert "User-Agent" in combo["ua"]

    @async_test
    async def test_register_dispatch_invalid_type(self):
        with pytest.raises(TypeError, match="pool_type 必须是类型"):
            AsyncPoolOrchestrator.register_dispatch("not_a_type", "method")  # type: ignore[arg-type]

    @async_test
    async def test_register_dispatch_invalid_method(self):
        with pytest.raises(TypeError, match="method_name 必须是非空字符串"):
            AsyncPoolOrchestrator.register_dispatch(AsyncUserAgentPool, "")


# ═══════════════════════════════════════════════════════════════════════
# AsyncDummyLock 测试
# ═══════════════════════════════════════════════════════════════════════

class TestAsyncDummyLock:

    @async_test
    async def test_async_context(self):
        lock = AsyncDummyLock()
        async with lock:
            pass  # 不应抛异常

    @async_test
    async def test_nested_usage(self):
        lock = AsyncDummyLock()
        async with lock:
            async with lock:
                pass


# ═══════════════════════════════════════════════════════════════════════
# 并发测试
# ═══════════════════════════════════════════════════════════════════════

class TestAsyncConcurrency:

    @async_test
    async def test_concurrent_ua_get(self):
        """10 个协程同时获取 UA，不应崩溃"""
        pool = AsyncUserAgentPool()

        async def fetch():
            return await pool.get("desktop")

        tasks = [fetch() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        for r in results:
            assert isinstance(r, str)

    @async_test
    async def test_concurrent_ua_reserve(self):
        """并发暂存不应丢失 UA"""
        pool = AsyncUserAgentPool()
        before = len(pool)

        async def reserve_and_return():
            async with pool.reserve("desktop") as ua:
                await asyncio.sleep(0.01)
                return ua

        # 控制并发数量不超过池容量
        concurrency = min(5, before)
        tasks = [reserve_and_return() for _ in range(concurrency)]
        results = await asyncio.gather(*tasks)
        assert len(results) == concurrency
        # 归还后池大小不变
        assert len(pool) == before

    @async_test
    async def test_concurrent_orchestrator(self):
        """5 个协程同时从编排器获取组合"""
        ua = AsyncUserAgentPool()
        orch = AsyncPoolOrchestrator(ua=ua)

        async def fetch():
            combo = await orch.next()
            return combo

        tasks = [fetch() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 5
        for r in results:
            assert "ua" in r

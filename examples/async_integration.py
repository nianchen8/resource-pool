"""异步爬虫集成示例 —— 展示 AsyncPoolOrchestrator + httpx 的最佳实践

演示：
1. AsyncUA/AsyncDNS/AsyncProxy 三池初始化
2. AsyncPoolOrchestrator 编排组合
3. httpx 异步并发请求
4. 请求失败后 mark_failed 自动隔离
"""

import asyncio
import logging

from user_agent_pool.pool_async import AsyncUserAgentPool
from dns_resolver_pool.pool_async import AsyncDNSResolverPool
from proxy_pool.pool_async import AsyncProxyPool
from nurture_pool.orchestrator_async import AsyncPoolOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("async_demo")


async def demo_httpx_integration():
    """演示 httpx 异步客户端 + 三池编排"""

    # 尝试导入 httpx（可选依赖）
    try:
        import httpx
    except ImportError:
        logger.warning("httpx 未安装，演示仅展示 API 流程")
        return

    # ── 1. 初始化资源池 ──
    ua_pool = AsyncUserAgentPool()
    dns_pool = AsyncDNSResolverPool(regions=("domestic",))
    proxy_pool = AsyncProxyPool()
    # 添加几个本地代理（演示用，实际不会被用到因为本地代理不可达）
    proxy_pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 9999})

    # ── 2. 异步编排器 ──
    orch = AsyncPoolOrchestrator()
    orch.register("ua", ua_pool)
    orch.register("dns", dns_pool)
    orch.register("proxy", proxy_pool)

    # ── 3. 并发请求 ──
    urls = [
        "https://www.baidu.com",
        "https://www.example.com",
        "https://httpbin.org/ip",
    ]

    async def fetch(url: str, client: httpx.AsyncClient):
        # 获取资源组合
        headers = await ua_pool.get_headers("desktop")
        dns_ip = await dns_pool.resolve("www.baidu.com")  # 缓存命中
        _proxies = await proxy_pool.get_dict()

        logger.info("资源就绪: UA=%s..., DNS首选=%s", headers["User-Agent"][:30], dns_ip)

        try:
            resp = await client.get(
                url,
                headers=headers,
                # proxies=proxies,  # 取消注释以使用代理
                timeout=10.0,
            )
            logger.info("[%d] %s", resp.status_code, url)
            return resp.status_code
        except Exception as e:
            logger.error("请求失败 %s: %s", url, e)
            return None

    async with httpx.AsyncClient() as client:
        tasks = [fetch(url, client) for url in urls]
        results = await asyncio.gather(*tasks)
        logger.info("完成: %d/%d 成功", sum(1 for r in results if r), len(urls))


async def demo_aiohttp_concurrent():
    """演示 aiohttp 100并发爬虫 + 异步编排器"""

    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp 未安装，跳过演示")
        return

    ua_pool = AsyncUserAgentPool()
    dns_pool = AsyncDNSResolverPool(regions=("domestic",), cache_ttl=300)

    orch = AsyncPoolOrchestrator()
    orch.register("ua", ua_pool)
    orch.register("dns", dns_pool)

    target_url = "https://httpbin.org/get"
    concurrency = 10  # 并发数（演示用小值）

    async def worker(session: aiohttp.ClientSession, worker_id: int):
        """每个 worker 独立获取 UA + DNS"""
        headers = await ua_pool.get_headers("desktop")
        _dns_ip = await dns_pool.resolve("httpbin.org")

        try:
            async with session.get(
                target_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.text()
                logger.info("Worker#%d: status=%d, 响应长度=%d", worker_id, resp.status, len(body))
                return resp.status
        except Exception as e:
            logger.error("Worker#%d 失败: %s", worker_id, e)
            return None

    async with aiohttp.ClientSession() as session:
        workers = [worker(session, i) for i in range(concurrency)]
        results = await asyncio.gather(*workers)
        logger.info("aiohttp 并发完成: %d/%d 成功", sum(1 for r in results if r), concurrency)


async def demo_reserve_pattern():
    """演示 async with reserve 暂存模式 —— UA 互斥使用"""

    ua_pool = AsyncUserAgentPool()

    async def exclusive_task(task_id: int):
        async with ua_pool.reserve("desktop") as ua:
            logger.info("Task#%d 独占 UA: %s...", task_id, ua[:40])
            await asyncio.sleep(0.1)  # 模拟请求
            logger.info("Task#%d 完成，归还 UA", task_id)

    # 3个任务同时 reserve，不会拿到相同 UA
    await asyncio.gather(*[exclusive_task(i) for i in range(3)])
    logger.info("reserve 暂存演示完成，UA 已全部归还")


async def main():
    print("=" * 60)
    print("  nurture-pool 异步集成示例")
    print("=" * 60)

    print("\n[1] httpx 集成...")
    await demo_httpx_integration()

    print("\n[2] aiohttp 并发爬虫...")
    await demo_aiohttp_concurrent()

    print("\n[3] reserve 暂存模式...")
    await demo_reserve_pattern()

    print("\n" + "=" * 60)
    print("  异步集成示例运行完毕")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

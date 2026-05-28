"""异步脚本 —— create_resolver 修复验证（不绕过，10并发）"""
import asyncio
import aiohttp
from user_agent_pool.pool_async import AsyncUserAgentPool
from dns_resolver_pool.pool_async import AsyncDNSResolverPool
from nurture_pool.orchestrator_async import AsyncPoolOrchestrator

print("=" * 55)
print("  异步：create_resolver() 10并发验证")
print("=" * 55)

ua_pool = AsyncUserAgentPool()
print(f"UA  池: {ua_pool}")
dns = AsyncDNSResolverPool()
print(f"DNS 池: {dns}")
orch = AsyncPoolOrchestrator(ua=ua_pool, dns=dns)

async def fetch(session, i):
    c = await orch.next()
    async with session.get("https://www.baidu.com",
                           headers=c.ua,
                           timeout=aiohttp.ClientTimeout(total=15)) as resp:
        text = await resp.text()
        return i, resp.status, len(text)

async def main():
    results = []
    connector = aiohttp.TCPConnector(resolver=dns.create_resolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch(session, i) for i in range(10)]
        for coro in asyncio.as_completed(tasks):
            i, status, length = await coro
            print(f"  #{i}: {status} ({length} 字节)")
            results.append(status)

    assert all(s == 200 for s in results), f"有失败的请求: {results}"
    print(f"\n✅ create_resolver() 10并发全部通过: {results.count(200)}/10 个 200")

asyncio.run(main())

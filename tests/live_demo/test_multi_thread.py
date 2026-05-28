"""多线程脚本 —— 10并发 + with dns 包住线程池"""
import nurture_pool
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from user_agent_pool import UserAgentPool

print("=" * 55)
print("  多线程：10并发 + with dns 包线程池")
print("=" * 55)

# ── 三件套（UA 池内置 ReadWriteLock，多线程读自动并发安全）──
ua_pool = UserAgentPool()
print(f"UA  池: {ua_pool}")

dns = nurture_pool.DNS()
print(f"DNS 池: {dns}")

# ── with dns 包住整个线程池，所有线程的 DNS 解析走池内轮换 ──
results = []
with dns:
    def fetch(i):
        c = nurture_pool.combo(ua=ua_pool, dns=dns)
        resp = requests.get("https://www.baidu.com",
                            headers=c.ua, timeout=10)
        return i, resp.status_code, len(resp.text)

    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in as_completed([ex.submit(fetch, i) for i in range(10)]):
            i, status, length = f.result()
            print(f"  #{i}: {status} ({length} 字节)")
            results.append(status)

assert all(s == 200 for s in results), f"有失败的请求: {results}"
print(f"\n✅ 多线程 10 并发全部通过: {results.count(200)}/10 个 200")

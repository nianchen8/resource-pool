"""多进程脚本 —— 子进程独立建池 + thread_safe=False"""
import nurture_pool
import requests
from concurrent.futures import ProcessPoolExecutor
from user_agent_pool import UserAgentPool

print("=" * 55)
print("  多进程：子进程独立建池 + thread_safe=False")
print("=" * 55)

# ── 每个进程独立建池，thread_safe=False 消除锁开销 ──
def fetch(i):
    ua_pool = UserAgentPool(thread_safe=False)
    dns = nurture_pool.DNS()

    with dns:
        c = nurture_pool.combo(ua=ua_pool, dns=dns)
        resp = requests.get("https://www.baidu.com",
                            headers=c.ua, timeout=10)
    return i, resp.status_code, len(resp.text)

if __name__ == '__main__':
    with ProcessPoolExecutor(max_workers=4) as ex:
        results = []
        for f in ex.map(fetch, range(8)):
            i, status, length = f
            print(f"  #{i}: {status} ({length} 字节)")
            results.append(status)

    assert all(s == 200 for s in results), f"有失败的请求: {results}"
    print(f"\n✅ 多进程 8 任务全部通过: {results.count(200)}/8 个 200")

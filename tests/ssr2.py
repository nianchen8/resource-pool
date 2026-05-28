import nurture_pool
import requests

# ═══════════════════════════════════════════════
# 1. 手动复制的 headers（你的 curl 转换版本）
# ═══════════════════════════════════════════════
manual = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://scrape.center/',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-site',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

# ═══════════════════════════════════════════════
# 2. nurture_pool 生成的 headers
# ═══════════════════════════════════════════════
ua = nurture_pool.UA()
pool = ua.headers()

# ═══════════════════════════════════════════════
# 3. 并排对比
# ═══════════════════════════════════════════════
all_keys = sorted(set(manual.keys()) | set(pool.keys()))

print(f"{'请求头':40s} {'手动复制':35s} {'nurture_pool':35s}")
print("-" * 110)

missing_from_pool = []
for key in all_keys:
    m = manual.get(key, "[缺]")
    p = pool.get(key, "[缺]")
    status = ""
    if key not in pool:
        status = " ← 缺失"
        missing_from_pool.append(key)
    elif m != "[缺]" and m != p:
        status = " ← 值不同"
    print(f"{key:40s} {str(m)[:33]:33s}  {str(p)[:33]:33s}{status}")

print()
print(f"手动复制: {len(manual)} 个请求头")
print(f"nurture_pool: {len(pool)} 个请求头")
print(f"nurture_pool 缺失: {missing_from_pool}")

print()
print("=" * 60)
print("手动复制 → 发请求")
resp1 = requests.get('https://ssr2.scrape.center/', headers=manual)
print(f"  状态码: {resp1.status_code}")

print("nurture_pool → 发请求")
resp2 = requests.get('https://ssr2.scrape.center/', headers=pool)
print(f"  状态码: {resp2.status_code}")


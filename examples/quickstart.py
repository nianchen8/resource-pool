"""nurture_pool 开箱即用 —— 最简集成示例

高度集成的爬虫资源三件套：UA 请求头 / DNS 池加速 / 代理（可选）。
单线程开箱即用，两行拿到带完整请求头 + DNS 池加速的 Response。
"""

import nurture_pool
import requests
from user_agent_pool import UserAgentPool

# ── 创建资源池 ──
ua_pool = UserAgentPool()              # 自动加载 854 种子，可重组 31,496 个 UA
print(ua_pool)
# → UserAgentPool(desktop=161, mobile=676, tablet=17)


# ── ① 获取单个 UA 字符串 ──
ua_str = ua_pool.get("desktop")
print("① UA 字符串:", ua_str[:80], "...")
# → Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...
print()


# ── ② 获取完整请求头（14 字段，可直接传入 requests）──
headers = ua_pool.get_headers("desktop")
print(f"② 完整请求头: {len(headers)} 字段")
# 字段: User-Agent / Accept / Accept-Language / Cache-Control
#       Sec-Ch-Ua / Sec-Fetch-* / Connection / Upgrade-Insecure-Requests
print()


# ── ③ 可选：在线拉取（需 pip install fake-useragent）──
# from fake_useragent import UserAgent
# ua_pool = UserAgentPool()
# ua_pool.load_from_fakeua(browsers=["chrome", "firefox"], limit=50)


# ── ④ DNS 池加速 —— with 块内 socket 层自动 patch ──
#     requests / urllib3 的所有域名解析走池内 14 台 DNS 服务器轮询，
#     比系统 DNS 更快更稳，反爬场景下还能绕开运营商 DNS 劫持
dns = nurture_pool.DNS()              # 惰性包装器，首次使用时自动初始化

with dns:                              # 进入 → patch socket.getaddrinfo
    resp = requests.get("https://www.baidu.com",
                        headers=headers, timeout=10)
print(f"④ Response: {resp.status_code}")
# → 200


# ── ⑤ 加代理（可选）──
# 支持格式：ip:port / ip:port:user:pass / http://ip:port 等
#
# 方式一：直接填地址
# proxy = nurture_pool.Proxy("1.2.3.4:8080")
# proxy = nurture_pool.Proxy("1.2.3.4:8080:user:pass")        # 有鉴权
#
# 方式二：从供应商接口拉取
# from proxy_pool import ProxyPool
# proxy = ProxyPool()
# proxy.load_from_url("https://your-api.com/fetch")
#
# 然后用编排器一把抓：
# with dns:
#     c = nurture_pool.combo(ua=ua_pool, dns=dns, proxy=proxy)
#     resp = requests.get(url, headers=c.ua, proxies=c.proxy, timeout=10)
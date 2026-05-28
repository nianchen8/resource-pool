"""单线程脚本 —— 三件套实测"""
import nurture_pool
import requests
from user_agent_pool import UserAgentPool

print("=" * 55)
print("  单线程：UA + DNS + Proxy 三件套")
print("=" * 55)

# ── 创建三件套 ──
ua_pool = UserAgentPool()
print(f"UA  池: {ua_pool}")
# → UserAgentPool(desktop=161, mobile=676, tablet=17)

dns = nurture_pool.DNS()
print(f"DNS 池: {dns}")
# → DNS(14 servers), 健康检查完成

# ── ① 获取完整请求头 ──
headers = ua_pool.get_headers("desktop")
print(f"\n① 请求头: {len(headers)} 字段")
print(f"   User-Agent: {headers['User-Agent'][:70]}...")
# → 14 字段: User-Agent / Accept / Accept-Language / Sec-Ch-Ua / Sec-Fetch-* ...

# ── ② DNS 池加速 ──
print("\n② DNS 加速请求...")
with dns:
    resp = requests.get("https://www.baidu.com", headers=headers, timeout=10)
print(f"   状态码: {resp.status_code}")  # → 200
print(f"   响应长度: {len(resp.text)} 字节")

# ── ③ 编排器一把抓（UA + DNS + Proxy 一键组合）──
print("\n③ 编排器 combo（无代理模式，Proxy 省略）...")
with dns:
    c = nurture_pool.combo(ua=ua_pool, dns=dns)
    resp = requests.get("https://www.baidu.com", headers=c.ua, timeout=10)
print(f"   状态码: {resp.status_code}")  # → 200
print(f"   combo.ua 字段数: {len(c.ua)}")
# → combo.ua = 14 字段请求头 dict

print("\n✅ 单线程三件套全部通过")

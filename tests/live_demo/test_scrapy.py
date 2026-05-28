"""Scrapy 中间件测试 —— UA + DNS patch/unpatch"""
import nurture_pool
import requests
from user_agent_pool import UserAgentPool

print("=" * 55)
print("  Scrapy 中间件：UA + DNS patch/unpatch")
print("=" * 55)


class ResourcePoolMiddleware:
    def __init__(self):
        self.ua = UserAgentPool()
        self.dns = nurture_pool.DNS()

    def process_request(self, request, spider):
        self.dns.__enter__()
        request.headers.update(self.ua.get_headers())

    def process_response(self, request, response, spider):
        self.dns.__exit__(None, None, None)
        return response


# ── 模拟 Scrapy Request ──
class FakeRequest:
    def __init__(self):
        self.headers = {}
        self.meta = {}


class FakeSpider:
    pass


mw = ResourcePoolMiddleware()
print(f"UA  池: {mw.ua}")
print(f"DNS 池: {mw.dns}")

req = FakeRequest()
mw.process_request(req, FakeSpider())

print(f"\n请求头字段数: {len(req.headers)}")
print(f"User-Agent: {req.headers['User-Agent'][:70]}...")
print(f"Accept: {req.headers.get('Accept', '?')[:50]}...")
print(f"Sec-Ch-Ua: {req.headers.get('Sec-Ch-Ua', '?')[:50]}...")

# 验证 DNS patch → 发真实请求
try:
    resp = requests.get("https://www.baidu.com", headers=dict(req.headers), timeout=10)
    print(f"\n真实请求状态码: {resp.status_code}")
    assert resp.status_code == 200, "请求失败"
except Exception as e:
    print(f"\n真实请求失败: {e}")
    raise

# unpatch
mw.process_response(req, None, FakeSpider())

print("\n✅ Scrapy 中间件测试通过")

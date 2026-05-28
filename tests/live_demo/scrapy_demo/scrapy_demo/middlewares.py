"""nurture_pool 集成中间件 —— UA + DNS + Proxy 三件套"""
import nurture_pool
from user_agent_pool import UserAgentPool


class ResourcePoolMiddleware:
    def __init__(self):
        self.ua = UserAgentPool()
        self.dns = nurture_pool.DNS()

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_request(self, request, spider):
        self.dns.__enter__()           # patch socket，DNS 走池内轮换
        request.headers.update(self.ua.get_headers())

    def process_response(self, request, response, spider):
        self.dns.__exit__(None, None, None)  # 请求完成后 unpatch
        return response

    def process_exception(self, request, exception, spider):
        self.dns.__exit__(None, None, None)
        return None

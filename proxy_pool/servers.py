"""代理服务器注册表 —— 内置公开代理（仅供测试，生产请用自建代理）"""

from typing import TypedDict


class ProxyEntry(TypedDict, total=False):
    scheme: str      # http, https, socks5
    host: str
    port: int
    username: str
    password: str
    region: str
    enabled: bool
    weight: int


VALID_SCHEMES = ("http", "https", "socks5")

# 健康检查用探测 URL（通过代理访问）
# 优先使用国内可访问的站点，避免因网络封锁导致误判
HEALTH_CHECK_URLS = [
    "http://httpbin.org/ip",
    "https://httpbin.org/ip",
    "https://www.baidu.com",
]

# 内置空列表 —— 代理凭据敏感，不内置生产代理
_BUILTIN: list[ProxyEntry] = []

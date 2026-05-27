"""代理服务器注册表 —— 内置公开代理（仅供测试，生产请用自建代理）

优先从 resource_pool/data/proxy_servers.json 加载，
找不到或解析失败则回退到空列表。
"""

import json
import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)


class ProxyEntry(TypedDict, total=False):
    scheme: str      # http, https, socks5
    host: str
    port: int
    username: str
    password: str
    region: str
    enabled: bool
    weight: int
    source: str     # "builtin" | "fed"
    batch: str
    expires_at: str


def _load_from_data_dir() -> list[ProxyEntry] | None:
    """尝试从 resource_pool/data/proxy_servers.json 加载代理

    返回 None 表示数据文件不可用，调用方应回退到空列表。
    """
    try:
        data_dir = os.path.join(os.path.dirname(__file__), "..", "resource_pool", "data")
        path = os.path.join(data_dir, "proxy_servers.json")
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        if not items:
            return None
        result: list[ProxyEntry] = []
        for item in items:
            if isinstance(item, dict) and "host" in item and "port" in item:
                entry: ProxyEntry = {
                    "scheme": str(item.get("scheme", "http")),
                    "host": str(item["host"]),
                    "port": int(item["port"]),
                    "username": str(item.get("username", "")),
                    "password": str(item.get("password", "")),
                    "region": str(item.get("region", "unknown")),
                    "enabled": bool(item.get("enabled", True)),
                    "weight": int(item.get("weight", 5)),
                    "source": str(item.get("source", "builtin")),
                    "batch": str(item.get("batch", "")),
                    "expires_at": str(item.get("expires_at", "")),
                }
                result.append(entry)
        logger.info("从 data/proxy_servers.json 加载 %d 个代理", len(result))
        return result
    except Exception as e:
        logger.warning("data/proxy_servers.json 加载失败: %s，回退到空列表", e)
        return None


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

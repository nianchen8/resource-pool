"""内置 DNS 服务器注册表 —— 可作为蓝本自行扩展

优先从 resource_pool/data/dns_servers.json 加载，
找不到或解析失败则回退到下方硬编码数据。
"""

import json
import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)


class ServerEntry(TypedDict, total=False):
    ip: str
    name: str
    region: str
    enabled: bool
    weight: int


def _load_from_data_dir() -> list[ServerEntry] | None:
    """尝试从 resource_pool/data/dns_servers.json 加载

    返回 None 表示数据文件不可用，调用方应回退到硬编码。
    """
    try:
        data_dir = os.path.join(os.path.dirname(__file__), "..", "resource_pool", "data")
        path = os.path.join(data_dir, "dns_servers.json")
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items", [])
        if not items:
            return None
        result: list[ServerEntry] = []
        for item in items:
            entry: ServerEntry = {
                "ip": str(item["ip"]),
                "name": str(item.get("name", item["ip"])),
                "region": str(item.get("region", "unknown")),
                "enabled": bool(item.get("enabled", True)),
                "weight": int(item.get("weight", 5)),
            }
            result.append(entry)
        logger.info("从 data/dns_servers.json 加载 %d 台 DNS 服务器", len(result))
        return result
    except Exception as e:
        logger.warning("data/dns_servers.json 加载失败: %s，回退到硬编码", e)
        return None


# ── 硬编码回退（仅当 resource_pool/data/dns_servers.json 不可用时生效）──
# ⚠️ 同步提醒：修改下方数据时，必须同步更新 resource_pool/data/dns_servers.json，
#    否则正常路径走 JSON 不受影响，仅极端场景（JSON 损坏）才会出现数据漂移。
_DOMESTIC: list[ServerEntry] = [
    {"ip": "114.114.114.114", "name": "114DNS", "region": "domestic", "enabled": True, "weight": 10},
    {"ip": "223.5.5.5",       "name": "阿里 DNS", "region": "domestic", "enabled": True, "weight": 10},
    {"ip": "223.6.6.6",       "name": "阿里 DNS 备用", "region": "domestic", "enabled": True, "weight": 8},
    {"ip": "119.29.29.29",    "name": "DNSPod", "region": "domestic", "enabled": True, "weight": 9},
    {"ip": "180.76.76.76",    "name": "百度 DNS", "region": "domestic", "enabled": True, "weight": 7},
    {"ip": "101.226.4.6",     "name": "DNS派 电信", "region": "domestic", "enabled": True, "weight": 6},
    {"ip": "218.30.118.6",    "name": "DNS派 联通", "region": "domestic", "enabled": True, "weight": 6},
]

# ── 海外 DNS（同样需同步 dns_servers.json）──────────────────────────
_OVERSEAS: list[ServerEntry] = [
    {"ip": "8.8.8.8",        "name": "Google DNS", "region": "overseas", "enabled": True, "weight": 8},
    {"ip": "8.8.4.4",        "name": "Google DNS 备用", "region": "overseas", "enabled": True, "weight": 7},
    {"ip": "1.1.1.1",        "name": "Cloudflare", "region": "overseas", "enabled": True, "weight": 10},
    {"ip": "1.0.0.1",        "name": "Cloudflare 备用", "region": "overseas", "enabled": True, "weight": 8},
    {"ip": "9.9.9.9",        "name": "Quad9", "region": "overseas", "enabled": True, "weight": 6},
    {"ip": "208.67.222.222", "name": "OpenDNS", "region": "overseas", "enabled": True, "weight": 6},
    {"ip": "208.67.220.220", "name": "OpenDNS 备用", "region": "overseas", "enabled": True, "weight": 5},
]

# ── 健康检查探测域名 ─────────────────────────────────────────────────
HEALTH_CHECK_DOMAINS = [
    "www.baidu.com",
    "dns.google",
    "one.one.one.one",
    "resolver1.opendns.com",
]

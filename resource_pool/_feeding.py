"""喂养模块 —— 养成系持久化 API

让池子"越用越肥"：一次喂入，永久生效，pip upgrade 后需重新导入。

数据文件位置：
- UA  : user_agent_pool/ua_seeds.json（与内置种子同一文件）
- DNS : resource_pool/data/dns_servers.json
- Proxy: resource_pool/data/proxy_servers.json

每条养成数据标记 source="fed" + batch 批次号，与内置数据写在一起。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── 路径解析 ──────────────────────────────────────────────────────────

_FEEDING_DIR = os.path.dirname(os.path.abspath(__file__))       # resource_pool/
_ROOT_DIR = os.path.dirname(_FEEDING_DIR)                       # 项目根
_UA_DATA_PATH = os.path.join(_ROOT_DIR, "user_agent_pool", "ua_seeds.json")
_DNS_DATA_PATH = os.path.join(_FEEDING_DIR, "data", "dns_servers.json")
_PROXY_DATA_PATH = os.path.join(_FEEDING_DIR, "data", "proxy_servers.json")

_DATA_PATHS: dict[str, str] = {
    "ua":    _UA_DATA_PATH,
    "dns":   _DNS_DATA_PATH,
    "proxy": _PROXY_DATA_PATH,
}

# ── 事前备份提醒 ──────────────────────────────────────────────────────

_BACKUP_WARNING = (
    "⚠ 养成数据将写入安装目录。pip install --upgrade 会覆盖安装目录文件。\n"
    "  建议定期执行 resource_pool.export_fed() 备份养成数据。"
)

_WARNED: set[str] = set()  # 同进程内同类型只提醒一次


def _warn_once(pool_type: str) -> None:
    """对同一 pool_type 同进程只打印一次备份提醒"""
    if pool_type not in _WARNED:
        _WARNED.add(pool_type)
        print(_BACKUP_WARNING)


# ── 批次号生成 ────────────────────────────────────────────────────────

def _make_batch() -> str:
    """生成可读批次号：20260527_143052"""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ═══════════════════════════════════════════════════════════════════════
# 读取 / 写入帮助函数
# ═══════════════════════════════════════════════════════════════════════

def _read_json(path: str) -> dict[str, Any] | None:
    """安全读取 JSON 文件，失败返回 None"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return None


def _write_json(path: str, data: dict[str, Any]) -> bool:
    """原子写入 JSON（先写临时文件再重命名），返回是否成功"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.error("写入 %s 失败: %s", path, e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


# ═══════════════════════════════════════════════════════════════════════
# UA seeds 格式（复杂结构：_meta + _header_profiles + desktop/mobile/tablet）
# ═══════════════════════════════════════════════════════════════════════

def _load_ua_items() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """加载 UA seeds，返回 (完整 data, {分类: 条目列表})

    首次读取时自动为所有条目补 source="builtin"（幂等）。
    """
    data = _read_json(_UA_DATA_PATH)
    if not data or not isinstance(data, dict):
        logger.warning("ua_seeds.json 不可用，返回空")
        return {}, {}

    # 自动补 source="builtin"（幂等，只补缺失字段）
    modified = False
    for cat in ("desktop", "mobile", "tablet"):
        entries = data.get(cat)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and "source" not in entry:
                entry["source"] = "builtin"
                modified = True
    if modified:
        _write_json(_UA_DATA_PATH, data)

    cats: dict[str, list[dict[str, Any]]] = {}
    for cat in ("desktop", "mobile", "tablet"):
        entries = data.get(cat, [])
        cats[cat] = [e for e in entries if isinstance(e, dict) and "ua" in e]
    return data, cats


def _save_ua_data(data: dict[str, Any]) -> None:
    """写回 UA seeds 文件"""
    _write_json(_UA_DATA_PATH, data)


# ═══════════════════════════════════════════════════════════════════════
# DNS / Proxy 格式（简单结构：format_version + items 数组）
# ═══════════════════════════════════════════════════════════════════════

def _load_simple_items(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """加载简单格式数据文件，返回 (完整 data, items 列表)

    首次读取时自动为所有条目补 source="builtin"（幂等）。
    """
    data = _read_json(path)
    if not data or not isinstance(data, dict):
        return {}, []

    items = data.get("items", [])
    if not isinstance(items, list):
        return data, []

    modified = False
    for item in items:
        if isinstance(item, dict) and "source" not in item:
            item["source"] = "builtin"
            modified = True
    if modified:
        _write_json(path, data)

    return data, items


def _save_simple_items(path: str, data: dict[str, Any], items: list[dict[str, Any]]) -> None:
    """写回简单格式数据文件"""
    data["items"] = items
    _write_json(path, data)


# ═══════════════════════════════════════════════════════════════════════
# 去重
# ═══════════════════════════════════════════════════════════════════════

def _ua_key(entry: dict[str, Any]) -> str:
    """UA 去重依据：UA 字符串本身"""
    return str(entry.get("ua", "")).strip()


def _dns_key(entry: dict[str, Any]) -> str:
    """DNS 去重依据：IP 地址"""
    return str(entry.get("ip", "")).strip()


def _proxy_key(entry: dict[str, Any]) -> str:
    """Proxy 去重依据：scheme://host:port"""
    scheme = entry.get("scheme", "http")
    host = entry.get("host", "")
    port = entry.get("port", 0)
    return f"{scheme}://{host}:{port}"


_KEY_FNS: dict[str, Any] = {"ua": _ua_key, "dns": _dns_key, "proxy": _proxy_key}


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：单条喂养
# ═══════════════════════════════════════════════════════════════════════

def feed_ua(
    ua: str,
    weight: int = 5,
    profile: str | None = None,
    headers: dict[str, str] | None = None,
    batch: str | None = None,
) -> bool:
    """喂养一条 User-Agent，返回是否成功写入

    Args:
        ua: User-Agent 字符串（必填）
        weight: 权重 1-10，默认 5。权重越高被选中概率越大
        profile: Header Profile 键名（可选），如 "chrome_148_win"
        headers: 内联完整请求头字典（可选），优先级高于 profile
        batch: 批次号（可选），默认自动生成时间戳

    Returns:
        True 表示写入成功（含去重跳过），False 表示写入失败

    示例::

        resource_pool.feed_ua(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/148.0.0.0 ...",
            weight=8,
            profile="chrome_148_win",
        )
    """
    _warn_once("ua")
    if not ua or not ua.strip():
        logger.warning("feed_ua: UA 不能为空")
        return False

    ua_clean = ua.strip()
    if batch is None:
        batch = _make_batch()

    data, cats = _load_ua_items()
    if not data:
        return False

    # 去重：检查所有分类
    seen: set[str] = set()
    for cat_entries in cats.values():
        for e in cat_entries:
            seen.add(e.get("ua", "").strip())
    if ua_clean in seen:
        logger.info("feed_ua: UA 已存在，跳过: %s...", ua_clean[:60])
        return True  # 去重不算失败

    # 自动推断分类
    from user_agent_pool.agents import parse_ua_metadata
    metadata = parse_ua_metadata(ua_clean)
    browser = metadata.get("browser", "")
    os_name = metadata.get("os", "")
    version = metadata.get("version", 0)

    # 归类
    ua_lower = ua_clean.lower()
    if "tablet" in ua_lower or "ipad" in ua_lower:
        category = "tablet"
    elif "mobile" in ua_lower or "iphone" in ua_lower or "android" in ua_lower:
        category = "mobile"
    else:
        category = "desktop"

    entry: dict[str, Any] = {
        "ua": ua_clean,
        "weight": max(1, min(10, weight)),
        "source": "fed",
        "batch": batch,
    }
    if profile:
        entry["profile"] = profile
    if headers:
        entry["headers"] = dict(headers)
    if browser:
        entry["browser"] = browser
    if os_name:
        entry["os"] = os_name
    if version:
        entry["version"] = version

    data.setdefault(category, []).append(entry)
    ok = _save_ua_data(data)
    if ok:
        logger.info("feed_ua: 已喂入 %s → 分类 '%s', batch=%s", ua_clean[:50], category, batch)
    return ok


def feed_dns(
    ip: str,
    name: str = "",
    region: str = "domestic",
    weight: int = 5,
    enabled: bool = True,
    batch: str | None = None,
) -> bool:
    """喂养一台 DNS 服务器，返回是否成功写入

    Args:
        ip: DNS 服务器 IP 地址（必填）
        name: 名称（可选），默认同 ip
        region: 区域，"domestic"（国内）或 "overseas"（海外）
        weight: 权重 1-10
        enabled: 是否启用
        batch: 批次号（可选）

    Returns:
        True 表示写入成功
    """
    _warn_once("dns")
    ip_clean = ip.strip()
    if not ip_clean:
        logger.warning("feed_dns: IP 不能为空")
        return False

    if batch is None:
        batch = _make_batch()

    data, items = _load_simple_items(_DNS_DATA_PATH)

    # 去重
    existing = {str(it.get("ip", "")): it for it in items}
    if ip_clean in existing:
        # 更新权重
        existing[ip_clean]["weight"] = max(1, min(10, weight))
        existing[ip_clean]["region"] = region
        existing[ip_clean]["enabled"] = enabled
        logger.info("feed_dns: %s 已存在，已更新权重", ip_clean)
        return _save_simple_items(_DNS_DATA_PATH, data, items)

    entry: dict[str, Any] = {
        "ip": ip_clean,
        "name": name.strip() or ip_clean,
        "region": region,
        "enabled": enabled,
        "weight": max(1, min(10, weight)),
        "source": "fed",
        "batch": batch,
    }
    items.append(entry)
    ok = _save_simple_items(_DNS_DATA_PATH, data, items)
    if ok:
        logger.info("feed_dns: 已喂入 %s (%s), batch=%s", ip_clean, name or ip_clean, batch)
    return ok


def feed_proxy(
    proxy: str,
    weight: int = 5,
    region: str = "unknown",
    scheme: str = "",
    batch: str | None = None,
) -> bool:
    """喂养一个代理，返回是否成功写入

    Args:
        proxy: 代理字符串，支持格式：
               - "ip:port"
               - "ip:port:user:pass"
               - "http://ip:port"
               - "socks5://ip:port"
        weight: 权重 1-10
        region: 区域，如 "china" / "overseas"
        scheme: 协议（可选），自动从 proxy 字符串解析
        batch: 批次号（可选）

    Returns:
        True 表示写入成功
    """
    _warn_once("proxy")
    proxy_clean = proxy.strip()
    if not proxy_clean:
        logger.warning("feed_proxy: 代理不能为空")
        return False

    if batch is None:
        batch = _make_batch()

    # 复用 ProxyPool 的解析逻辑
    from proxy_pool.pool import ProxyPool as _SyncPool

    # 自动检测 scheme
    detected_scheme = scheme
    if not detected_scheme:
        if proxy_clean.startswith("https://"):
            detected_scheme = "https"
        elif proxy_clean.startswith("http://"):
            detected_scheme = "http"
        elif proxy_clean.startswith("socks5://"):
            detected_scheme = "socks5"
        else:
            detected_scheme = "http"

    entry_raw = _SyncPool._parse_proxy_str(proxy_clean, detected_scheme)
    if not entry_raw.get("host") or not entry_raw.get("port"):
        logger.warning("feed_proxy: 无效代理格式: %s", proxy_clean)
        return False

    data, items = _load_simple_items(_PROXY_DATA_PATH)

    key = f"{detected_scheme}://{entry_raw['host']}:{entry_raw['port']}"
    existing = {f"{it.get('scheme','http')}://{it.get('host','')}:{it.get('port',0)}": it for it in items}
    if key in existing:
        existing[key]["weight"] = max(1, min(10, weight))
        existing[key]["region"] = region
        logger.info("feed_proxy: %s 已存在，已更新权重", key)
        return _save_simple_items(_PROXY_DATA_PATH, data, items)

    entry: dict[str, Any] = {
        "scheme": detected_scheme,
        "host": entry_raw["host"],
        "port": entry_raw["port"],
        "weight": max(1, min(10, weight)),
        "region": region,
        "enabled": True,
        "source": "fed",
        "batch": batch,
    }
    if entry_raw.get("username"):
        entry["username"] = entry_raw["username"]
    if entry_raw.get("password"):
        entry["password"] = entry_raw["password"]

    items.append(entry)
    ok = _save_simple_items(_PROXY_DATA_PATH, data, items)
    if ok:
        logger.info("feed_proxy: 已喂入 %s, batch=%s", key, batch)
    return ok


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：批量导入（格式校验 + 去重 + 写入）
# ═══════════════════════════════════════════════════════════════════════

def import_ua(
    data: list[dict[str, Any]],
    batch: str | None = None,
) -> dict[str, int]:
    """批量导入 UA 种子（标准格式），返回导入统计

    标准格式（参见 data/schema/ua_format.json）：::

        [
            {"ua": "Mozilla/5.0 ...", "weight": 5, "profile": "chrome_148_win"},
            {"ua": "Mozilla/5.0 ...", "weight": 3}
        ]

    ua 字段必填，其余可选。browser/os/version 会自动从 UA 解析。

    Args:
        data: 符合 schema/ua_format.json 的条目列表
        batch: 批次号（可选），默认自动生成

    Returns:
        {"added": N, "skipped": N, "errors": N}
    """
    _warn_once("ua")
    if batch is None:
        batch = _make_batch()

    from user_agent_pool.agents import parse_ua_metadata

    result = {"added": 0, "skipped": 0, "errors": 0}
    if not isinstance(data, list):
        logger.warning("import_ua: data 必须是列表")
        result["errors"] = 1
        return result

    existing_data, cats = _load_ua_items()
    if not existing_data:
        result["errors"] = 1
        return result

    # 收集已有 UA 用于去重
    seen: set[str] = set()
    for cat_entries in cats.values():
        for e in cat_entries:
            seen.add(e.get("ua", "").strip())

    for item in data:
        if not isinstance(item, dict):
            result["errors"] += 1
            continue

        ua_str = str(item.get("ua", "")).strip()
        if not ua_str:
            result["errors"] += 1
            continue

        if ua_str in seen:
            result["skipped"] += 1
            continue

        weight = int(item.get("weight", 5))
        profile = str(item["profile"]) if item.get("profile") else None
        headers = item.get("headers")

        # 自动解析元数据
        metadata = parse_ua_metadata(ua_str)

        # 自动归类
        ua_lower = ua_str.lower()
        if "tablet" in ua_lower or "ipad" in ua_lower:
            category = "tablet"
        elif "mobile" in ua_lower or "iphone" in ua_lower or "android" in ua_lower:
            category = "mobile"
        else:
            category = "desktop"

        entry: dict[str, Any] = {
            "ua": ua_str,
            "weight": max(1, min(10, weight)),
            "source": "fed",
            "batch": batch,
        }
        if profile:
            entry["profile"] = profile
        if headers and isinstance(headers, dict):
            entry["headers"] = dict(headers)
        for key in ("browser", "os", "version"):
            if key in metadata:
                entry[key] = metadata[key]

        existing_data.setdefault(category, []).append(entry)
        seen.add(ua_str)
        result["added"] += 1

    if result["added"] > 0:
        _save_ua_data(existing_data)

    logger.info(
        "import_ua: added=%d, skipped=%d, errors=%d, batch=%s",
        result["added"], result["skipped"], result["errors"], batch,
    )
    return result


def import_dns(
    data: list[dict[str, Any]],
    batch: str | None = None,
) -> dict[str, int]:
    """批量导入 DNS 服务器，返回导入统计

    标准格式（参见 data/schema/dns_format.json）：::

        [
            {"ip": "192.168.1.1", "name": "我的 DNS", "region": "domestic", "weight": 8}
        ]

    ip 字段必填。

    Args:
        data: 符合 schema/dns_format.json 的条目列表
        batch: 批次号（可选）

    Returns:
        {"added": N, "skipped": N, "errors": N}
    """
    _warn_once("dns")
    if batch is None:
        batch = _make_batch()

    result = {"added": 0, "skipped": 0, "errors": 0}
    if not isinstance(data, list):
        logger.warning("import_dns: data 必须是列表")
        result["errors"] = 1
        return result

    file_data, items = _load_simple_items(_DNS_DATA_PATH)
    existing = {str(it.get("ip", "")): it for it in items}

    for item in data:
        if not isinstance(item, dict):
            result["errors"] += 1
            continue

        ip_str = str(item.get("ip", "")).strip()
        if not ip_str:
            result["errors"] += 1
            continue

        if ip_str in existing:
            # 更新权重
            existing[ip_str]["weight"] = max(1, min(10, int(item.get("weight", 5))))
            existing[ip_str]["region"] = str(item.get("region", "domestic"))
            result["skipped"] += 1
            continue

        entry: dict[str, Any] = {
            "ip": ip_str,
            "name": str(item.get("name", ip_str)),
            "region": str(item.get("region", "domestic")),
            "enabled": bool(item.get("enabled", True)),
            "weight": max(1, min(10, int(item.get("weight", 5)))),
            "source": "fed",
            "batch": batch,
        }
        items.append(entry)
        existing[ip_str] = entry
        result["added"] += 1

    if result["added"] > 0:
        _save_simple_items(_DNS_DATA_PATH, file_data, items)

    logger.info(
        "import_dns: added=%d, skipped=%d, errors=%d, batch=%s",
        result["added"], result["skipped"], result["errors"], batch,
    )
    return result


def import_proxy(
    data: list[dict[str, Any]],
    batch: str | None = None,
    auto_validate: bool = True,
) -> dict[str, int]:
    """批量导入代理，返回导入统计

    标准格式（参见 data/schema/proxy_format.json）：::

        [
            {"proxy": "127.0.0.1:8080", "weight": 5, "region": "china"},
            {"proxy": "http://1.2.3.4:3128", "weight": 8}
        ]

    proxy 字段必填。支持 proxy 字符串或分离的 host/port 字段。

    Args:
        data: 符合 schema/proxy_format.json 的条目列表
        batch: 批次号（可选）
        auto_validate: 导入后自动三次失败测试（默认 True）

    Returns:
        {"added": N, "skipped": N, "errors": N}
    """
    _warn_once("proxy")
    if batch is None:
        batch = _make_batch()

    from proxy_pool.pool import ProxyPool as _SyncPool

    result = {"added": 0, "skipped": 0, "errors": 0}
    if not isinstance(data, list):
        logger.warning("import_proxy: data 必须是列表")
        result["errors"] = 1
        return result

    file_data, items = _load_simple_items(_PROXY_DATA_PATH)
    existing_keys: set[str] = {
        f"{it.get('scheme','http')}://{it.get('host','')}:{it.get('port',0)}"
        for it in items
    }

    for item in data:
        if not isinstance(item, dict):
            result["errors"] += 1
            continue

        # 支持两种输入：proxy 字符串 或 分离的 host/port
        proxy_str = str(item.get("proxy", "")).strip()
        if proxy_str:
            # 从 proxy 字符串解析
            raw = proxy_str
            detected_scheme = ""
            if raw.startswith("https://"):
                detected_scheme = "https"
            elif raw.startswith("http://"):
                detected_scheme = "http"
            elif raw.startswith("socks5://"):
                detected_scheme = "socks5"
            else:
                detected_scheme = "http"
            entry_raw = _SyncPool._parse_proxy_str(raw, detected_scheme)
        else:
            # 分离字段
            host = str(item.get("host", "")).strip()
            port = int(item.get("port", 0))
            detected_scheme = str(item.get("scheme", "http")).strip()
            entry_raw = {"host": host, "port": port, "scheme": detected_scheme}
            if item.get("username"):
                entry_raw["username"] = str(item["username"])
            if item.get("password"):
                entry_raw["password"] = str(item["password"])

        if not entry_raw.get("host") or not entry_raw.get("port"):
            result["errors"] += 1
            continue

        key = f"{detected_scheme}://{entry_raw['host']}:{entry_raw['port']}"
        if key in existing_keys:
            result["skipped"] += 1
            continue

        entry: dict[str, Any] = {
            "scheme": detected_scheme,
            "host": entry_raw["host"],
            "port": int(entry_raw["port"]),
            "weight": max(1, min(10, int(item.get("weight", 5)))),
            "region": str(item.get("region", "unknown")),
            "enabled": True,
            "source": "fed",
            "batch": batch,
        }
        if entry_raw.get("username"):
            entry["username"] = entry_raw["username"]
        if entry_raw.get("password"):
            entry["password"] = entry_raw["password"]
        # 可选：过期时间、历史评分
        if item.get("expires_at"):
            entry["expires_at"] = item["expires_at"]
        if item.get("last_score") is not None:
            entry["last_score"] = float(item["last_score"])
        if item.get("last_latency_ms") is not None:
            entry["last_latency_ms"] = float(item["last_latency_ms"])

        items.append(entry)
        existing_keys.add(key)
        result["added"] += 1

    if result["added"] > 0:
        _save_simple_items(_PROXY_DATA_PATH, file_data, items)

    logger.info(
        "import_proxy: added=%d, skipped=%d, errors=%d, batch=%s",
        result["added"], result["skipped"], result["errors"], batch,
    )

    if auto_validate and result["added"] > 0:
        logger.info("import_proxy: 开始验证新导入的代理...")
        validate_fed_proxies(timeout=5.0, max_retries=3, batch=batch)

    return result


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：导出
# ═══════════════════════════════════════════════════════════════════════

def export_fed(
    pool_type: str,
    output_dir: str = ".",
    batch: str | None = None,
) -> str | None:
    """导出养成数据到指定目录，返回输出文件路径

    Args:
        pool_type: "ua" / "dns" / "proxy"
        output_dir: 输出目录，默认为当前工作目录
        batch: 按批次过滤（可选），None=导出所有 fed 条目

    Returns:
        输出文件的绝对路径，无数据则返回 None

    示例::

        # 导出所有养成 UA
        path = resource_pool.export_fed("ua", "./backup/")

        # 按批次导出
        path = resource_pool.export_fed("proxy", "./jd_project/", batch="20260527_001")
    """
    pool_type = pool_type.lower()
    if pool_type not in _DATA_PATHS:
        raise ValueError(f"无效 pool_type '{pool_type}'，可选: ua/dns/proxy")

    if pool_type == "ua":
        data, cats = _load_ua_items()
        fed_items: list[dict[str, Any]] = []
        for cat_entries in cats.values():
            for e in cat_entries:
                if e.get("source") == "fed":
                    if batch is None or e.get("batch") == batch:
                        fed_items.append(dict(e))
        if not fed_items:
            logger.info("export_fed(ua): 无养成数据")
            return None

        export_data: dict[str, Any] = {
            "_meta": {
                "description": "导出的养成 UA 种子",
                "exported_at": _make_batch(),
                "pool_type": "ua",
                "batch_filter": batch,
                "count": len(fed_items),
            },
        }
        # 按分类重组
        for cat in ("desktop", "mobile", "tablet"):
            cat_items = [e for e in fed_items if _classify_for_export(e, cat)]
            if cat_items:
                export_data[cat] = cat_items

    else:
        path = _DATA_PATHS[pool_type]
        _, items = _load_simple_items(path)
        fed_items = [
            dict(it) for it in items
            if it.get("source") == "fed"
            and (batch is None or it.get("batch") == batch)
        ]
        if not fed_items:
            logger.info("export_fed(%s): 无养成数据", pool_type)
            return None

        export_data = {
            "format_version": 2,
            "_meta": {
                "description": f"导出的养成 {pool_type} 数据",
                "exported_at": _make_batch(),
                "pool_type": pool_type,
                "batch_filter": batch,
                "count": len(fed_items),
            },
            "items": fed_items,
        }

    os.makedirs(output_dir, exist_ok=True)
    filename = f"{pool_type}_fed_export.json"
    out_path = os.path.join(output_dir, filename)
    _write_json(out_path, export_data)
    logger.info("export_fed(%s): 导出 %d 条到 %s", pool_type, len(fed_items), out_path)
    return out_path


def _classify_for_export(entry: dict[str, Any], category: str) -> bool:
    """辅助：根据 UA 内容判断是否属于指定分类"""
    ua = str(entry.get("ua", "")).lower()
    if category == "tablet":
        return "tablet" in ua or "ipad" in ua
    if category == "mobile":
        return ("mobile" in ua or "iphone" in ua or "android" in ua) and "tablet" not in ua and "ipad" not in ua
    return True  # desktop = 剩余


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：状态查询
# ═══════════════════════════════════════════════════════════════════════

def status() -> dict[str, dict[str, int]]:
    """查看各池养成数据概览

    Returns:
        {"ua": {"builtin": 854, "fed": 12}, "dns": {...}, "proxy": {...}}

    示例::

        import resource_pool
        print(resource_pool.status())
    """
    result: dict[str, dict[str, int]] = {}

    # UA
    _, cats = _load_ua_items()
    ua_builtin = 0
    ua_fed = 0
    for cat_entries in cats.values():
        for e in cat_entries:
            if e.get("source") == "fed":
                ua_fed += 1
            else:
                ua_builtin += 1
    result["ua"] = {"builtin": ua_builtin, "fed": ua_fed, "total": ua_builtin + ua_fed}

    # DNS & Proxy
    for pt in ("dns", "proxy"):
        _, items = _load_simple_items(_DATA_PATHS[pt])
        builtin = sum(1 for it in items if it.get("source") != "fed")
        fed = sum(1 for it in items if it.get("source") == "fed")
        result[pt] = {"builtin": builtin, "fed": fed, "total": builtin + fed}

    return result


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：移除养成数据
# ═══════════════════════════════════════════════════════════════════════

def reset(pool_type: str | None = None) -> dict[str, int]:
    """移除养成数据（不影响内置数据）

    Args:
        pool_type: "ua" / "dns" / "proxy"，None=全部

    Returns:
        {"ua": N, "dns": N, "proxy": N} 各类型移除条数
    """
    result = {"ua": 0, "dns": 0, "proxy": 0}
    types = [pool_type] if pool_type else ["ua", "dns", "proxy"]

    for pt in types:
        if pt not in _DATA_PATHS:
            continue
        if pt == "ua":
            data, _ = _load_ua_items()
            removed = 0
            for cat in ("desktop", "mobile", "tablet"):
                entries = data.get(cat, [])
                before = len(entries)
                data[cat] = [e for e in entries if e.get("source") != "fed"]
                removed += before - len(data[cat])
            if removed > 0:
                _save_ua_data(data)
            result["ua"] = removed
        else:
            path = _DATA_PATHS[pt]
            file_data, items = _load_simple_items(path)
            before = len(items)
            new_items = [it for it in items if it.get("source") != "fed"]
            after = len(new_items)
            if before != after:
                _save_simple_items(path, file_data, new_items)
            result[pt] = before - after

    logger.info("reset: %s", result)
    return result


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：同步 UA 零件池（手动触发）
# ═══════════════════════════════════════════════════════════════════════

def sync_seeds(pool: Any = None) -> int:
    """将当前池中新增的 UA 条目回写到 ua_seeds.json（方便跨脚本共享）

    如果传入 pool（UserAgentPool 实例），则将其 _agents 中的所有条目
    （不含 source="builtin" 的）追加到数据文件。

    Args:
        pool: UserAgentPool 实例（可选），None=无操作

    Returns:
        新增写入的条目数
    """
    if pool is None:
        return 0

    if not hasattr(pool, "_agents"):
        logger.warning("sync_seeds: pool 不是 UserAgentPool 实例")
        return 0

    data, cats = _load_ua_items()
    if not data:
        return 0

    # 收集已有 UA（去重依据）
    existing_ua: set[str] = set()
    for cat_entries in cats.values():
        for e in cat_entries:
            existing_ua.add(e.get("ua", "").strip())

    added = 0
    batch = _make_batch()
    for category, entries in pool._agents.items():
        data.setdefault(category, [])
        for entry in entries:
            ua_str = str(entry.get("ua", "")).strip()
            if not ua_str or ua_str in existing_ua:
                continue
            existing_ua.add(ua_str)
            fed_entry: dict[str, Any] = {
                "ua": ua_str,
                "weight": int(entry.get("weight", 5)),
                "source": "fed",
                "batch": batch,
            }
            if entry.get("profile"):
                fed_entry["profile"] = entry["profile"]
            for key in ("browser", "os", "version"):
                if key in entry:
                    fed_entry[key] = entry[key]
            data[category].append(fed_entry)
            added += 1

    if added > 0:
        _save_ua_data(data)
        logger.info("sync_seeds: 回写 %d 条 UA 到 ua_seeds.json", added)
    return added


# ═══════════════════════════════════════════════════════════════════════
# 公开 API：查看 / 管理养成数据
# ═══════════════════════════════════════════════════════════════════════

def list_fed(pool_type: str) -> list[dict[str, Any]]:
    """列出指定类型的所有养成条目

    Args:
        pool_type: "ua" / "dns" / "proxy"

    Returns:
        养成条目列表（仅 source=="fed"）
    """
    if pool_type not in _DATA_PATHS:
        raise ValueError(f"无效资源类型: {pool_type!r}，可选: ua, dns, proxy")

    if pool_type == "ua":
        _, cats = _load_ua_items()
        result: list[dict[str, Any]] = []
        for cat, entries in cats.items():
            for e in entries:
                if e.get("source") == "fed":
                    e_copy = dict(e)
                    e_copy["_category"] = cat
                    result.append(e_copy)
        return result
    else:
        path = _DATA_PATHS[pool_type]
        _, items = _load_simple_items(path)
        return [it for it in items if it.get("source") == "fed"]


def get_stats() -> dict[str, dict[str, int]]:
    """获取养成数据统计（同 status()，供程序化调用）

    Returns:
        {"ua": {"builtin": 854, "fed": 12, "total": 866}, ...}
    """
    return status()


def remove_fed(pool_type: str, index: int | str) -> bool:
    """移除一条养成数据

    Args:
        pool_type: "ua" / "dns" / "proxy"
        index: 基于 0 的索引（同 list_fed() 返回顺序），或 UA 字符串/代理 key 精确匹配

    Returns:
        True=已移除，False=未找到
    """
    if pool_type not in _DATA_PATHS:
        raise ValueError(f"无效资源类型: {pool_type!r}，可选: ua, dns, proxy")

    if pool_type == "ua":
        data, _ = _load_ua_items()
        fed_entries = []
        for cat in ("desktop", "mobile", "tablet"):
            for i, e in enumerate(data.get(cat, [])):
                if e.get("source") == "fed":
                    fed_entries.append((cat, i, e))

        if isinstance(index, int):
            if 0 <= index < len(fed_entries):
                cat, idx, _ = fed_entries[index]
                del data[cat][idx]
                _save_ua_data(data)
                logger.info("remove_fed: 已移除 UA 索引 %d", index)
                return True
        else:
            ua_str = str(index).strip()
            for cat, i, e in fed_entries:
                if e.get("ua", "").strip() == ua_str:
                    del data[cat][i]
                    _save_ua_data(data)
                    logger.info("remove_fed: 已移除 UA %s", ua_str[:50])
                    return True
        return False
    else:
        path = _DATA_PATHS[pool_type]
        file_data, items = _load_simple_items(path)
        fed_indices = [(i, it) for i, it in enumerate(items) if it.get("source") == "fed"]

        if isinstance(index, int):
            if 0 <= index < len(fed_indices):
                orig_idx, _ = fed_indices[index]
                del items[orig_idx]
                _save_simple_items(path, file_data, items)
                logger.info("remove_fed: 已移除 %s 索引 %d", pool_type, index)
                return True
        else:
            key_str = str(index).strip()
            key_fn = _KEY_FNS.get(pool_type)
            for orig_idx, it in fed_indices:
                if key_fn and key_fn(it) == key_str:
                    del items[orig_idx]
                    _save_simple_items(path, file_data, items)
                    logger.info("remove_fed: 已移除 %s %s", pool_type, key_str)
                    return True
        return False


def probe_proxy(proxy: str, timeout: float = 5.0) -> tuple[bool, str]:
    """探测单个代理是否可用

    通过 socket 连接 + HTTP 请求验证代理连通性。

    Args:
        proxy: 代理 URL，如 "http://1.2.3.4:8080" 或 "socks5://1.2.3.4:1080"
        timeout: 超时秒数

    Returns:
        (是否可用, 错误信息)
    """
    import socket
    from urllib import request, error as urllib_error
    from urllib.parse import urlparse

    # 解析代理地址
    try:
        parsed = urlparse(proxy)
        host = parsed.hostname or ""
        port = parsed.port or 80
    except Exception as e:
        return False, f"代理地址解析失败: {e}"

    if not host:
        return False, "代理地址缺少主机名"

    # 1. Socket 预检
    try:
        sock = socket.create_connection((host, port), timeout=min(timeout, 3.0))
        sock.close()
    except Exception as e:
        return False, f"连接失败 {host}:{port}: {e}"

    # 2. HTTP 代理验证（仅对 http/https 代理）
    if parsed.scheme in ("http", "https"):
        try:
            proxy_handler = request.ProxyHandler({parsed.scheme: proxy})
            opener = request.build_opener(proxy_handler)
            req = request.Request(
                "http://httpbin.org/ip",
                headers={"User-Agent": "resource_pool-probe/1.0"},
            )
            resp = opener.open(req, timeout=timeout)
            resp.read()
            resp.close()
            return True, ""
        except urllib_error.URLError as e:
            return False, f"HTTP 请求失败: {e.reason}"
        except Exception as e:
            return False, f"代理验证异常: {e}"
    else:
        # socks 代理仅做 socket 连通性检查
        return True, "(socks 仅连通性检查)"


def validate_fed_proxies(
    timeout: float = 5.0,
    max_retries: int = 3,
    batch: str | None = None,
) -> dict[str, Any]:
    """验证所有养成代理的连通性（三次失败测试）

    每个代理最多探测 max_retries 次。全部失败的代理会被收集，
    控制台打印提醒，并导出到 proxy_failed_export.json。

    Args:
        timeout: 单次探测超时秒数
        max_retries: 最大重试次数（默认 3）
        batch: 仅验证指定批次，None=全部养成代理

    Returns:
        {
            "total": 总fed代理数,
            "passed": 通过数,
            "failed": 失败数,
            "failed_list": [{"proxy": ..., "reason": ..., "retries": 3}, ...],
            "export_path": "proxy_failed_export.json" or None,
        }
    """
    path = _DATA_PATHS["proxy"]
    _, items = _load_simple_items(path)

    fed_proxies = [
        it
        for it in items
        if it.get("source") == "fed"
        and (batch is None or it.get("batch") == batch)
    ]

    if not fed_proxies:
        logger.info("validate_fed_proxies: 没有需要验证的养成代理")
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "failed_list": [],
            "export_path": None,
        }

    total = len(fed_proxies)
    passed = 0
    failed = 0
    failed_list: list[dict[str, Any]] = []

    for entry in fed_proxies:
        proxy_url = entry.get("proxy", "")
        if not proxy_url:
            scheme = entry.get("scheme", "http")
            host = entry.get("host", "")
            port = entry.get("port", 0)
            proxy_url = f"{scheme}://{host}:{port}"

        ok = False
        last_reason = ""
        for attempt in range(1, max_retries + 1):
            ok, reason = probe_proxy(proxy_url, timeout)
            if ok:
                break
            last_reason = reason
            if attempt < max_retries:
                logger.debug(
                    "代理 %s 第 %d/%d 次失败: %s，重试中...",
                    proxy_url,
                    attempt,
                    max_retries,
                    reason,
                )

        if ok:
            passed += 1
            logger.info("代理 %s 验证通过", proxy_url)
        else:
            failed += 1
            failed_list.append({
                "proxy": proxy_url,
                "reason": last_reason,
                "retries": max_retries,
                "batch": entry.get("batch", ""),
            })
            logger.warning(
                "代理 %s %d 次全部失败: %s", proxy_url, max_retries, last_reason
            )

    result: dict[str, Any] = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "failed_list": failed_list,
        "export_path": None,
    }

    if failed_list:
        _warn_once("proxy_validate")
        print(
            f"\n⚠ 代理验证结果: {total} 个养成代理，"
            f"{passed} 通过，{failed} 失败"
        )

        export_path = os.path.join(os.getcwd(), "proxy_failed_export.json")
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "exported_at": _make_batch(),
                        "note": "三次探测全部失败的养成代理，请检查或移除",
                        "failed_list": failed_list,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            result["export_path"] = export_path
            print(f"  失败代理列表已导出到: {export_path}")
        except Exception as e:
            logger.error("导出失败列表出错: %s", e)

    return result

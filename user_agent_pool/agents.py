"""内置 User-Agent 数据集 —— 包含完整 Header Profile 组"""

import re
import threading
from typing import TypedDict


class AgentEntry(TypedDict, total=False):
    ua: str
    weight: int
    profile: str  # Header Profile 键名
    headers: dict[str, str]  # 内联完整请求头（优先级高于 profile）
    browser: str  # chrome / firefox / safari / edge
    os: str       # windows / macos / linux / android / ios
    version: int  # 主版本号（如 131）


# ── 模块级锁 —— 保护 _HEADER_PROFILES 跨实例并发读写 ──
_PROFILE_LOCK = threading.Lock()


# ── Header Profile 组 ────────────────────────────────────────────────
# 各浏览器/平台对应的完整请求头集合，确保字段间语义一致

_HEADER_PROFILES: dict[str, dict[str, str]] = {
    # ── Chrome 131 / Windows ──
    "chrome_131_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 130 / Windows ──
    "chrome_130_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 129 / Windows ──
    "chrome_129_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 131 / macOS ──
    "chrome_131_mac": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 130 / macOS ──
    "chrome_130_mac": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Firefox 133 / Windows ──
    "firefox_133_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Firefox 132 / Windows ──
    "firefox_132_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Safari 18.1 / macOS ──
    "safari_18_1_mac": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Edge 131 / Windows ──
    "edge_131_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 131 / Linux ──
    "chrome_131_linux": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── iPhone Safari 18.1 ──
    "safari_18_1_iphone": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── iPhone Safari 17.6 ──
    "safari_17_6_iphone": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Android Chrome 131 ──
    "chrome_131_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Android Chrome 130 ──
    "chrome_130_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Android Chrome 129 ──
    "chrome_129_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Android Firefox 133 ──
    "firefox_133_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── iPad Safari 18.1 ──
    "safari_18_1_ipad": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── iPad Safari 17.6 ──
    "safari_17_6_ipad": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Android Tablet Chrome 131 ──
    "chrome_131_tablet": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Android Tablet Chrome 130 ──
    "chrome_130_tablet": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 148 / Windows ──
    "chrome_148_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    },
    # ── Chrome 145 / Windows ──
    "chrome_145_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="145", "Chromium";v="145", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    },
    # ── Chrome 148 / macOS ──
    "chrome_148_mac": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Edge 148 / Windows ──
    "edge_148_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Microsoft Edge";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Firefox 150 / Windows ──
    "firefox_150_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Firefox 151 / Windows (2026-05-21 最新) ──
    "firefox_151_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 148 / Linux ──
    "chrome_148_linux": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 148 / Android ──
    "chrome_148_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
    # ── Chrome 148 / Tablet ──
    "chrome_148_tablet": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
}


# ── Desktop ──────────────────────────────────────────────────────────
_DESKTOP: list[AgentEntry] = [
    # Chrome 148 / Windows (2026-05 最新稳定版)
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36", "weight": 12, "profile": "chrome_148_win"},
    # Chrome 145 / Windows
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36", "weight": 10, "profile": "chrome_145_win"},
    # Chrome 131~129 / Windows (保有量仍大)
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "weight": 6, "profile": "chrome_131_win"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "weight": 5, "profile": "chrome_130_win"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", "weight": 4, "profile": "chrome_129_win"},
    # Chrome 148 / macOS
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36", "weight": 8, "profile": "chrome_148_mac"},
    # Chrome 131 / macOS (保有)
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "weight": 5, "profile": "chrome_131_mac"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "weight": 4, "profile": "chrome_130_mac"},
    # Firefox 151 / Windows (2026-05-21 最新)
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0", "weight": 10, "profile": "firefox_151_win"},
    # Firefox 150 / Windows
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0", "weight": 7, "profile": "firefox_150_win"},
    # Firefox 133~132 / Windows (保有)
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0", "weight": 4, "profile": "firefox_133_win"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0", "weight": 3, "profile": "firefox_132_win"},
    # Safari 18.1 / macOS
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15", "weight": 6, "profile": "safari_18_1_mac"},
    # Edge 148 / Windows (2026-05 最新)
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0", "weight": 8, "profile": "edge_148_win"},
    # Edge 131 / Windows (保有)
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0", "weight": 3, "profile": "edge_131_win"},
    # Chrome 148 / Linux
    {"ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36", "weight": 5, "profile": "chrome_148_linux"},
    {"ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "weight": 2, "profile": "chrome_131_linux"},
]

# ── Mobile ───────────────────────────────────────────────────────────
_MOBILE: list[AgentEntry] = [
    # iPhone Safari
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1", "weight": 8, "profile": "safari_18_1_iphone"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", "weight": 7, "profile": "safari_17_6_iphone"},
    # Android Chrome 148 (最新)
    {"ua": "Mozilla/5.0 (Linux; Android 15; Pixel 9 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7727.56 Mobile Safari/537.36", "weight": 12, "profile": "chrome_148_android"},
    # Android Chrome 131~129 (保有)
    {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Mobile Safari/537.36", "weight": 6, "profile": "chrome_131_android"},
    {"ua": "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.58 Mobile Safari/537.36", "weight": 5, "profile": "chrome_130_android"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.100 Mobile Safari/537.36", "weight": 4, "profile": "chrome_129_android"},
    # Android Firefox
    {"ua": "Mozilla/5.0 (Android 14; Mobile; rv:133.0) Gecko/133.0 Firefox/133.0", "weight": 4, "profile": "firefox_133_android"},
    # Xiaomi / Huawei
    {"ua": "Mozilla/5.0 (Linux; Android 14; 23127PN0CC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.107 Mobile Safari/537.36", "weight": 3, "profile": "chrome_130_android"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; ALN-AL80) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.100 Mobile Safari/537.36", "weight": 2, "profile": "chrome_129_android"},
]

# ── Tablet ───────────────────────────────────────────────────────────
_TABLET: list[AgentEntry] = [
    # iPad
    {"ua": "Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1", "weight": 5, "profile": "safari_18_1_ipad"},
    {"ua": "Mozilla/5.0 (iPad; CPU OS 17_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", "weight": 4, "profile": "safari_17_6_ipad"},
    # Android Tablet Chrome 148 (最新)
    {"ua": "Mozilla/5.0 (Linux; Android 15; SM-X920) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7727.56 Safari/537.36", "weight": 6, "profile": "chrome_148_tablet"},
    # Android Tablet Chrome 131~130 (保有)
    {"ua": "Mozilla/5.0 (Linux; Android 14; SM-X910) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Safari/537.36", "weight": 3, "profile": "chrome_131_tablet"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; AGS6-W00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.58 Safari/537.36", "weight": 2, "profile": "chrome_130_tablet"},
]

# ── 默认分类 ─────────────────────────────────────────────────────────
DEFAULT_AGENTS: dict[str, list[AgentEntry]] = {
    "desktop": _DESKTOP,
    "mobile": _MOBILE,
    "tablet": _TABLET,
    # "all" 作为运行时聚合分类
}

VALID_CATEGORIES = ("desktop", "mobile", "tablet", "all")

# ── UA 元数据解析 ────────────────────────────────────────────────────
# 用于从 UA 字符串中提取浏览器、操作系统和版本号，支持细粒度筛选

_BROWSER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("edge", re.compile(r"Edg(?:e)?/(\d+)", re.I)),
    ("chrome", re.compile(r"Chrome/(\d+)", re.I)),
    ("firefox", re.compile(r"Firefox/(\d+)", re.I)),
    ("safari", re.compile(r"Version/(\d+)\.\d+.*Safari/", re.I)),
]

_OS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("windows", re.compile(r"Windows NT \d+\.\d+", re.I)),
    ("macos", re.compile(r"Mac OS X \d+[._]\d+", re.I)),
    ("linux", re.compile(r"Linux(?!.*Android)", re.I)),
    ("android", re.compile(r"Android \d+", re.I)),
    ("ios", re.compile(r"iPhone OS \d+[._]\d+|CPU (?:iPhone )?OS \d+[._]\d+", re.I)),
]


def parse_ua_metadata(ua: str) -> dict[str, object]:
    """从 User-Agent 字符串提取浏览器、操作系统和版本号

    Returns:
        {"browser": "chrome", "os": "windows", "version": 131}
        无法识别时返回空 dict
    """
    result: dict[str, object] = {}

    # 提取浏览器和版本
    for browser_name, pattern in _BROWSER_PATTERNS:
        m = pattern.search(ua)
        if m:
            result["browser"] = browser_name
            try:
                result["version"] = int(m.group(1))
            except (ValueError, IndexError):
                pass
            break

    # 提取操作系统
    for os_name, pattern in _OS_PATTERNS:
        if pattern.search(ua):
            result["os"] = os_name
            # iPad 特征：包含 iPad 字符串
            if os_name == "ios" and "iPad" in ua:
                pass  # 仍标记为 ios
            break

    return result


def get_available_profiles() -> tuple[str, ...]:
    """返回当前所有可用的 Header Profile 键名（含运行时动态注册的）

    与旧版 AVAILABLE_PROFILES 不同，此函数始终反映 _HEADER_PROFILES 的最新状态，
    包含通过 UserAgentPool.register_profile() 动态注册的 profile。
    """
    with _PROFILE_LOCK:
        return tuple(_HEADER_PROFILES.keys())


# ── OS → 平台短名映射（用于 Profile 自动匹配）────────────────────────
_OS_TO_PLATFORM: dict[str, str] = {
    "windows": "win",
    "macos": "mac",
    "linux": "linux",
    "android": "android",
    "ios": "iphone",  # 默认映射到 iPhone，iPad 由 UA 特征判断
}


# 预解析 Profile 键的 (browser, version_str, platform) 元数据缓存
_profile_key_cache: dict[str, tuple[str, str, str]] | None = None


def _parse_profile_key(key: str) -> tuple[str, str, str]:
    """解析 Profile 键名为 (browser, version_str, platform)

    示例：
        "chrome_131_win"  → ("chrome", "131", "win")
        "safari_18_1_mac" → ("safari", "18_1", "mac")
        "firefox_133_win" → ("firefox", "133", "win")
    """
    parts = key.split("_")
    # 最少需要 browser_version_platform 三段
    if len(parts) < 3:
        return ("", "", "")

    platform = parts[-1]
    # 尝试检测 safari 版本格式：safari_{major}_{minor}_{platform}
    browser = parts[0]
    if browser == "safari" and len(parts) >= 4:
        version = f"{parts[1]}_{parts[2]}"
    else:
        # chrome_131_win / firefox_133_win / edge_131_win
        version = parts[1] if len(parts) >= 3 else ""

    return (browser, version, platform)


def _build_profile_key_cache() -> dict[str, tuple[str, str, str]]:
    """构建 Profile 键解析缓存（双检锁模式）"""
    global _profile_key_cache
    if _profile_key_cache is not None:
        return _profile_key_cache
    with _PROFILE_LOCK:
        # 双重检查：锁内再次验证，防止锁外检查到锁获取之间已有线程完成构建
        if _profile_key_cache is None:
            # 先构建局部变量再赋值，避免 free-threaded 下赋值重排序
            data = {k: _parse_profile_key(k) for k in _HEADER_PROFILES}
            _profile_key_cache = data
    return _profile_key_cache


def _invalidate_profile_cache() -> None:
    """Profile 注册/修改后使缓存失效"""
    global _profile_key_cache
    _profile_key_cache = None


def match_profile(browser: str, os: str, version: int, ua: str = "") -> str | None:
    """根据浏览器/操作系统/版本号自动匹配最佳 Header Profile

    匹配优先级：
    1. 同浏览器 + 同平台 + 完全同版本
    2. 同浏览器 + 同平台 + 最接近的较低版本
    3. 同浏览器 + 同平台 + 最接近版本（不分高低）
    4. 同浏览器 + 任意平台 + 最接近版本
    5. 无匹配返回 None

    Args:
        browser: 浏览器名（chrome/firefox/safari/edge）
        os: 操作系统名（windows/macos/linux/android/ios）
        version: 主版本号
        ua: 完整 UA 字符串（用于 iPad 检测）

    Returns:
        匹配的 Profile 键名，或无匹配时返回 None
    """
    platform = _OS_TO_PLATFORM.get(os, "")
    if not platform:
        return None

    # iPad 特殊处理：iOS 设备但有 iPad 特征
    if os == "ios" and ua and "ipad" in ua.lower():
        platform = "ipad"

    cache = _build_profile_key_cache()

    # 1. 精确匹配：同浏览器 + 同平台
    candidates: list[tuple[str, int, str]] = []  # (key, parsed_version, platform)
    for key, (b, v_str, p) in cache.items():
        if b != browser or p != platform:
            continue
        try:
            v_num = int(v_str.split("_")[0])  # 取主版本号
        except (ValueError, IndexError):
            continue
        candidates.append((key, v_num, p))
        if v_num == version:
            return key  # 精确匹配，立即返回

    # 2. 同平台内最近似匹配
    if candidates:
        # 找最接近的较低版本
        lower = [(k, v) for k, v, _ in candidates if v < version]
        if lower:
            lower.sort(key=lambda x: x[1], reverse=True)
            return lower[0][0]
        # 没有较低版本，找最接近的（最近的较高版本）
        candidates.sort(key=lambda x: abs(x[1] - version))
        return candidates[0][0]

    # 3. 跨平台 fallback：同浏览器的任意版本
    cross: list[tuple[str, int]] = []
    for key, (b, v_str, _p) in cache.items():
        if b != browser:
            continue
        try:
            v_num = int(v_str.split("_")[0])
        except (ValueError, IndexError):
            continue
        cross.append((key, v_num))

    if cross:
        cross.sort(key=lambda x: abs(x[1] - version))
        return cross[0][0]

    return None


# 注意：AVAILABLE_PROFILES 为 import-time 快照，不反映运行时通过
# UserAgentPool.register_profile() 动态注册的 profile。
# 请优先使用 get_available_profiles() 获取最新列表。
AVAILABLE_PROFILES: tuple[str, ...] = get_available_profiles()

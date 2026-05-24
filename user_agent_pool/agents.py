"""内置 User-Agent 数据集 —— 包含完整 Header Profile 组"""

from typing import TypedDict


class AgentEntry(TypedDict, total=False):
    ua: str
    weight: int
    profile: str  # Header Profile 键名


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
    },
    # ── Firefox 133 / Windows ──
    "firefox_133_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    },
    # ── Firefox 132 / Windows ──
    "firefox_132_win": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    },
    # ── Safari 18.1 / macOS ──
    "safari_18_1_mac": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
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
    },
    # ── Chrome 131 / Linux ──
    "chrome_131_linux": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Sec-Ch-Ua-Mobile": "?0",
    },
    # ── iPhone Safari 18.1 ──
    "safari_18_1_iphone": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    },
    # ── iPhone Safari 17.6 ──
    "safari_17_6_iphone": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    },
    # ── Android Chrome 131 ──
    "chrome_131_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
    },
    # ── Android Chrome 130 ──
    "chrome_130_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
    },
    # ── Android Chrome 129 ──
    "chrome_129_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
    },
    # ── Android Firefox 133 ──
    "firefox_133_android": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
    },
    # ── iPad Safari 18.1 ──
    "safari_18_1_ipad": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    },
    # ── iPad Safari 17.6 ──
    "safari_17_6_ipad": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    },
    # ── Android Tablet Chrome 131 ──
    "chrome_131_tablet": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
    },
    # ── Android Tablet Chrome 130 ──
    "chrome_130_tablet": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Google Chrome";v="130", "Chromium";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Ch-Ua-Mobile": "?1",
    },
}


# ── Desktop ──────────────────────────────────────────────────────────
_DESKTOP: list[AgentEntry] = [
    # Chrome / Windows
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "weight": 10, "profile": "chrome_131_win"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "weight": 10, "profile": "chrome_130_win"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", "weight": 8, "profile": "chrome_129_win"},
    # Chrome / macOS
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "weight": 8, "profile": "chrome_131_mac"},
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36", "weight": 7, "profile": "chrome_130_mac"},
    # Firefox / Windows
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0", "weight": 6, "profile": "firefox_133_win"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0", "weight": 6, "profile": "firefox_132_win"},
    # Safari / macOS
    {"ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15", "weight": 5, "profile": "safari_18_1_mac"},
    # Edge / Windows
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0", "weight": 5, "profile": "edge_131_win"},
    # Chrome / Linux
    {"ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "weight": 4, "profile": "chrome_131_linux"},
]

# ── Mobile ───────────────────────────────────────────────────────────
_MOBILE: list[AgentEntry] = [
    # iPhone Safari
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1", "weight": 8, "profile": "safari_18_1_iphone"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", "weight": 7, "profile": "safari_17_6_iphone"},
    # Android Chrome
    {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Mobile Safari/537.36", "weight": 9, "profile": "chrome_131_android"},
    {"ua": "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.58 Mobile Safari/537.36", "weight": 8, "profile": "chrome_130_android"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.100 Mobile Safari/537.36", "weight": 7, "profile": "chrome_129_android"},
    # Android Firefox
    {"ua": "Mozilla/5.0 (Android 14; Mobile; rv:133.0) Gecko/133.0 Firefox/133.0", "weight": 4, "profile": "firefox_133_android"},
    # Xiaomi / Huawei
    {"ua": "Mozilla/5.0 (Linux; Android 14; 23127PN0CC) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.107 Mobile Safari/537.36", "weight": 5, "profile": "chrome_130_android"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; ALN-AL80) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.6668.100 Mobile Safari/537.36", "weight": 4, "profile": "chrome_129_android"},
]

# ── Tablet ───────────────────────────────────────────────────────────
_TABLET: list[AgentEntry] = [
    # iPad
    {"ua": "Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1", "weight": 5, "profile": "safari_18_1_ipad"},
    {"ua": "Mozilla/5.0 (iPad; CPU OS 17_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1", "weight": 4, "profile": "safari_17_6_ipad"},
    # Android Tablet
    {"ua": "Mozilla/5.0 (Linux; Android 14; SM-X910) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.135 Safari/537.36", "weight": 5, "profile": "chrome_131_tablet"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; AGS6-W00) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.58 Safari/537.36", "weight": 3, "profile": "chrome_130_tablet"},
]

# ── 默认分类 ─────────────────────────────────────────────────────────
DEFAULT_AGENTS: dict[str, list[AgentEntry]] = {
    "desktop": _DESKTOP,
    "mobile": _MOBILE,
    "tablet": _TABLET,
    # "all" 作为运行时聚合分类
}

VALID_CATEGORIES = ("desktop", "mobile", "tablet", "all")

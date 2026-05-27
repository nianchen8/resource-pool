"""User-Agent 资源池核心逻辑"""

import json
import logging
import os
import random
import re
from enum import Enum
from typing import Iterator

from user_agent_pool.exceptions import PoolExhaustedException, InvalidAgentException
from user_agent_pool.agents import (
    VALID_CATEGORIES,
    _HEADER_PROFILES,
    _PROFILE_LOCK,
    AgentEntry,
    parse_ua_metadata,
    _invalidate_profile_cache,
    match_profile,
    _build_sec_ch_ua,
    _OS_PLATFORM_META,
    AL_DESKTOP_5,
    AL_MACOS,
    AL_MOBILE_3,
    AL_FIREFOX,
    CACHE_CONTROL_VARIANTS,
    UPGRADE_VARIANTS,
    ACCEPT_CHROME,
    ACCEPT_FIREFOX,
    ACCEPT_SAFARI,
    _CHROME_UA_DESKTOP,
    _CHROME_UA_MOBILE,
    _FIREFOX_UA_DESKTOP,
    _FIREFOX_UA_MOBILE,
    _EDGE_UA_DESKTOP,
)
from resource_pool.base import DummyReadWriteLock, ReadWriteLock, ResourcePool

logger = logging.getLogger(__name__)


class UAStrategy(Enum):
    """UA 选取策略"""
    WEIGHTED = "weighted"
    UNIFORM = "uniform"


# 常量
CATEGORY_ALL: str = "all"  # 表示所有分类的特殊值

# ── Sec-Ch-Ua 动态版本补丁 ──────────────────────────────────────────
_SEC_CH_UA_VERSION_RE = re.compile(r'v="(\d+)"')
# Sec-CH-UA 键名别名：jsonl 使用大写 CH（如 Sec-CH-UA），派系组装使用小写 Ch（如 Sec-Ch-Ua）
_SEC_CH_UA_KEY_ALIASES: dict[str, list[str]] = {
    "Sec-Ch-Ua": ["Sec-CH-UA"],
    "Sec-Ch-Ua-Platform": ["Sec-CH-UA-Platform"],
    "Sec-Ch-Ua-Mobile": ["Sec-CH-UA-Mobile"],
}
_UA_VERSION_RE = re.compile(r'(?:Chrome|Edg|Edge)/(\d+)', re.I)
_UA_OS_RE = re.compile(r'\((.+?)\)')
_FX_RV_RE = re.compile(r'\s*;\s*rv:\S+$')
_UA_CHROME_VER_RE = re.compile(r'Chrome/[\d.]+', re.I)
_UA_FX_VER_RE = re.compile(r'Firefox/[\d.]+', re.I)
_UA_SAFARI_VER_RE = re.compile(r'Version/[\d.]+')
_UA_EDGE_VER_RE = re.compile(r'Edg/[\d.]+', re.I)
_WK_RE = re.compile(r'AppleWebKit/(\S+)')
_MOBILE_BUILD_RE = re.compile(r'Mobile/(\S+)')


def _extract_ua_version(ua: str) -> int | None:
    """从 UA 字符串提取浏览器主版本号"""
    m = _UA_VERSION_RE.search(ua)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_ua_os(ua: str, browser: str) -> str:
    """提取 UA 的 OS 平台串（第一个括号内的内容）

    Firefox 需剥离末尾的 '; rv:VER' 部分。
    """
    m = _UA_OS_RE.search(ua)
    if not m:
        return ""
    inner = m.group(1)
    if browser == "firefox":
        inner = _FX_RV_RE.sub("", inner)
    return inner


def _extract_ua_ver_token(ua: str, browser: str) -> str:
    """提取完整版本令牌（如 Chrome/148.0.0.0）"""
    if browser in ("chrome", "edge"):
        pattern = _UA_EDGE_VER_RE if browser == "edge" else _UA_CHROME_VER_RE
    elif browser == "firefox":
        pattern = _UA_FX_VER_RE
    elif browser == "safari":
        pattern = _UA_SAFARI_VER_RE
    else:
        return ""
    m = pattern.search(ua)
    return m.group(0) if m else ""


def _extract_num_from_ver(ver_token: str) -> str | int:
    """从版本令牌提取数字部分：'Chrome/148.0.0.0' → 148"""
    parts = ver_token.split("/", 1)
    if len(parts) < 2:
        return ""
    num_str = parts[1]
    try:
        return int(num_str.split(".")[0])
    except (ValueError, IndexError):
        return num_str


def _extract_webkit(ua: str) -> str:
    """提取 AppleWebKit 版本号"""
    m = _WK_RE.search(ua)
    return m.group(1) if m else ""


def _extract_mobile_build(ua: str) -> str:
    """提取 Mobile/ 构建号（仅 Safari/WebKit 移动端）"""
    m = _MOBILE_BUILD_RE.search(ua)
    return m.group(1) if m else ""


def _patch_sec_ch_ua(headers: dict[str, str], ua: str) -> None:
    """修正 Sec-Ch-Ua 版本号使其与 UA 一致

    解决 Profile 版本号（如 chrome_131_win 中 v="131"）与 UA 实际版本
    （如 Chrome/148）不一致导致的指纹矛盾。
    """
    sec_ch_ua = headers.get("Sec-Ch-Ua", "")
    if not sec_ch_ua:
        return
    ua_version = _extract_ua_version(ua)
    if not ua_version:
        return
    profile_match = _SEC_CH_UA_VERSION_RE.search(sec_ch_ua)
    if not profile_match:
        return
    try:
        profile_version = int(profile_match.group(1))
    except ValueError:
        return
    if profile_version == ua_version:
        return
    # 替换所有 v="N" 为 v="实际版本"
    headers["Sec-Ch-Ua"] = _SEC_CH_UA_VERSION_RE.sub(
        f'v="{ua_version}"', sec_ch_ua
    )


class UserAgentPool(ResourcePool):
    """线程安全的 User-Agent 资源池

    支持：
    - 按分类获取：desktop / mobile / tablet / all
    - 加权随机 / 均匀随机
    - 完整 Header Profile 组（User-Agent + Accept + Sec-Ch-Ua 等）
    - 动态增删
    - 上下文管理器（暂存池，取出时移除，用完自动归还）

    使用示例::

        pool = UserAgentPool()
        ua = pool.get()                    # 随机获取一个 UA 字符串
        ua = pool.get("mobile")           # 只拿 mobile
        ua = pool.get("desktop", weighted=False)  # 均匀随机
        headers = pool.get_headers("desktop")     # 获取完整请求头

        with pool.reserve("mobile") as ua:
            # 做请求...
            pass
    """

    def __init__(self, strategy: UAStrategy = UAStrategy.WEIGHTED,
                 thread_safe: bool = True,
                 data_dir: str | None = None,
                 load_builtin: bool = True,
                 load_fed: bool = True,
                 raw_only: bool = False) -> None:
        self._agents: dict[str, list[AgentEntry]] = {}
        self._strategy = strategy
        self._thread_safe = thread_safe
        self._lock = ReadWriteLock() if thread_safe else DummyReadWriteLock()
        self._ua_pools: dict[str, dict[str, list[str | int]]] = {}
        self._data_dir = data_dir
        self._load_builtin = load_builtin
        self._load_fed = load_fed
        self._raw_only = raw_only
        self._init_defaults()

    # ── 初始化 ───────────────────────────────────────────────────────

    def _init_defaults(self) -> None:
        """从统一配置文件加载全部 UA + Header Profiles

        加载优先级：
        1. data_dir 目录（若指定）
        2. resource_pool/data/ua_seeds.json（安装目录，含 fed 养成数据）
        3. user_agent_pool/ua_seeds.json（内置回退）

        raw_only=True 时不拆零件，fed 种子原样循环使用。
        """
        self._load_unified_seeds()
        if not self._raw_only:
            self._build_ua_component_pools()
        total = sum(len(v) for v in self._agents.values())
        logger.info("已加载 %d 个 User-Agent（desktop=%d, mobile=%d, tablet=%d），零件池=%d 组",
                    total, len(self._agents.get("desktop", [])),
                    len(self._agents.get("mobile", [])),
                    len(self._agents.get("tablet", [])),
                    len(self._ua_pools))

    @staticmethod
    def _copy_agent_entry(entry: AgentEntry) -> AgentEntry:
        """创建 AgentEntry 的浅拷贝（类型安全），含元数据字段

        若原始 entry 缺少 browser/os/version 元数据，
        自动从 UA 字符串解析补全，确保派系组装路径可用。
        """
        copied: AgentEntry = {"ua": entry["ua"], "weight": entry.get("weight", 5)}
        for key in ("profile", "headers", "browser", "os", "version"):
            if key in entry:
                copied[key] = entry[key]  # type: ignore[literal-required]
        # 自动检测元数据（确保内置 DEFAULT_AGENTS 也能走派系组装）
        if "browser" not in copied:
            metadata = parse_ua_metadata(copied["ua"])
            for key in ("browser", "os", "version"):
                if key in metadata:
                    copied[key] = metadata[key]  # type: ignore[literal-required]
        return copied

    # ── 公开 API ─────────────────────────────────────────────────────

    def get(self, category: str = CATEGORY_ALL, weighted: bool | None = None,
            exclude: set[str] | None = None,
            browser: str | None = None,
            os: str | None = None,
            min_version: int | None = None) -> str:
        """从池中获取一个 User-Agent 字符串

        Args:
            category: desktop | mobile | tablet | all
            weighted: True=按权重加权随机；False=均匀随机；
                      None=使用池级 strategy 默认值
            exclude: 排除包含这些关键词的 UA（如 {"Firefox", "Linux"}）
            browser: 限定浏览器（chrome / firefox / safari / edge）
            os: 限定操作系统（windows / macos / linux / android / ios）
            min_version: 最低主版本号（如 120 表示 Chrome 120+）

        Returns:
            User-Agent 字符串

        Raises:
            PoolExhaustedException: 该分类下无可用 UA
        """
        candidates = self._pick_candidates(category, exclude, browser, os, min_version)
        if not candidates:
            logger.error("UA 池分类 '%s' 已耗尽", category)
            raise PoolExhaustedException(resource_type=category)

        use_weighted = weighted if weighted is not None else (self._strategy == UAStrategy.WEIGHTED)
        if use_weighted:
            return self._weighted_choice(candidates)
        return random.choice(candidates)["ua"]

    def get_all(self, category: str = CATEGORY_ALL, exclude: set[str] | None = None,
                browser: str | None = None, os: str | None = None,
                min_version: int | None = None) -> list[str]:
        """获取该分类下所有 UA 字符串（不修改池）"""
        return [entry["ua"] for entry in self._pick_candidates(category, exclude, browser, os, min_version)]

    def get_headers(self, category: str = CATEGORY_ALL, weighted: bool | None = None,
                    exclude: set[str] | None = None,
                    browser: str | None = None,
                    os: str | None = None,
                    min_version: int | None = None) -> dict[str, str]:
        """获取完整的请求头 Profile（包含 User-Agent + 配套请求头）

        返回的字典可直接用于 requests.get(url, headers=headers)。
        各字段（Accept / Accept-Language / Sec-Ch-Ua 等）语义与 UA 一致，
        避免浏览器特征不匹配被反爬识别。

        如果所选 UA 没有关联 profile，则只返回 {"User-Agent": ua}。

        Args:
            category: desktop | mobile | tablet | all
            weighted: True=加权；False=均匀；None=使用池级默认策略
            exclude: 排除包含这些关键词的 UA
            browser: 限定浏览器（chrome / firefox / safari / edge）
            os: 限定操作系统（windows / macos / linux / android / ios）
            min_version: 最低主版本号（如 120）

        Raises:
            PoolExhaustedException: 该分类下无可用 UA
        """
        candidates = self._pick_candidates(category, exclude, browser, os, min_version)
        if not candidates:
            logger.error("UA 池分类 '%s' 已耗尽（get_headers）", category)
            raise PoolExhaustedException(resource_type=category)

        use_weighted = weighted if weighted is not None else (self._strategy == UAStrategy.WEIGHTED)
        if use_weighted:
            entry: AgentEntry = self._weighted_pick(candidates)
        else:
            entry = random.choice(candidates)
        return self._build_headers(entry)

    def add(self, ua: str, category: str, weight: int = 5, profile: str | None = None,
            headers: dict[str, str] | None = None) -> None:
        """向指定分类添加一个 UA

        Args:
            ua: User-Agent 字符串
            category: desktop | mobile | tablet
            weight: 权重（≥1）
            profile: Header Profile 键名（可选），见 agents._HEADER_PROFILES
            headers: 内联完整请求头字典（可选），优先级最高，不包含 User-Agent

        Raises:
            ValueError: 分类不合法
            InvalidAgentException: ua 为空
        """
        if category not in VALID_CATEGORIES or category == "all":
            raise ValueError(f"无效分类 '{category}'，可选: {VALID_CATEGORIES}")
        if not ua or not ua.strip():
            raise InvalidAgentException("UA 不能为空")

        ua_clean = ua.strip()
        entry: AgentEntry = {"ua": ua_clean, "weight": max(1, weight)}
        if profile:
            entry["profile"] = profile
        if headers:
            entry["headers"] = dict(headers)
        # 自动检测浏览器/操作系统/版本号（用于细粒度筛选）
        metadata = parse_ua_metadata(ua_clean)
        for key in ("browser", "os", "version"):
            if key in metadata:
                entry[key] = metadata[key]  # type: ignore[literal-required]
        with self._lock.write():
            self._agents.setdefault(category, []).append(entry)
        logger.debug("UA 已添加: %s → 分类 '%s'", ua_clean[:50], category)

    def load_from_file(self, path: str) -> int:
        """从 JSON / JSONL / CSV 文件批量导入 User-Agent

        支持的格式：

        **JSON（推荐）**::

            [
                {"ua": "Mozilla/5.0 ...", "category": "desktop", "weight": 5, "profile": "chrome_120"},
                {"ua": "Mozilla/5.0 ...", "category": "mobile", "weight": 3}
            ]

        **JSONL**::

            {"User-Agent": "Mozilla/5.0 ...", "Accept": "text/html,...", ...}
            {"User-Agent": "Mozilla/5.0 ...", "Accept-Language": "en-US,...", ...}

        JSONL 格式中每行的完整 headers（Accept、Accept-Language、Cache-Control 等）
        作为原子单位保留，确保字段间语义一致不被反爬识别。

        **CSV**::

            ua,category,weight,profile
            "Mozilla/5.0 ...",desktop,5,chrome_120
            "Mozilla/5.0 ...",mobile,3,

        CSV 首行为表头，字段名不区分大小写。
        只需 ``ua`` 和 ``category`` 两列，``weight`` 和 ``profile`` 可选。

        Args:
            path: JSON / JSONL / CSV 文件路径

        Returns:
            成功导入的 UA 数量

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式无法识别或内容为空
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f"UA 文件不存在: {path}")

        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            entries = self._parse_json_file(path)
        elif ext == ".jsonl":
            entries = self._parse_jsonl_file(path)
        elif ext == ".csv":
            entries = self._parse_csv_file(path)
        else:
            raise ValueError(
                f"不支持的文件格式 '{ext}'，仅支持 .json、.jsonl 和 .csv"
            )

        if not entries:
            raise ValueError(f"文件中未解析到任何有效 UA 条目: {path}")

        added = 0
        skipped = 0
        for entry in entries:
            try:
                self.add(
                    ua=entry["ua"],
                    category=entry.get("category", "desktop"),
                    weight=entry.get("weight", 5),
                    profile=entry.get("profile"),
                    headers=dict(entry.get("headers")) if isinstance(entry.get("headers"), dict) else None,
                )
                added += 1
            except (ValueError, InvalidAgentException) as e:
                logger.warning("跳过无效 UA 条目: %s", e)
                skipped += 1

        logger.info(
            "从文件加载 UA 完成: %d 个导入, %d 个跳过 (文件: %s)",
            added, skipped, path,
        )
        return added

    def load_from_fakeua(
        self,
        browsers: list[str] | None = None,
        os: list[str] | None = None,
        limit: int = 50,
    ) -> int:
        """从 fake_useragent 库批量导入 User-Agent（可选依赖）

        需要先安装：``pip install fake-useragent``

        若 fake_useragent 远程源不可用（返回 UA 过少），
        自动降级到本地 bundled headers_pool.jsonl 数据集。

        Args:
            browsers: 限定浏览器类型，如 ["chrome", "firefox"]，
                      None=全部
            os: 限定操作系统，如 ["windows", "macos"]，
                None=全部
            limit: 最多导入数量

        Returns:
            成功导入的 UA 数量

        Raises:
            ImportError: fake_useragent 未安装
        """
        try:
            from fake_useragent import UserAgent as FakeUA
        except ImportError:
            raise ImportError(
                "load_from_fakeua 需要 fake-useragent 库，请执行: pip install fake-useragent"
            ) from None

        fake_ua = FakeUA(
            browsers=browsers or ["chrome", "firefox", "safari", "edge"],
            os=os or ["windows", "macos", "linux"],
        )

        # 临时屏蔽 fake_useragent 内部的错误日志（远程源不稳定时避免刷屏）
        _fua_logger = logging.getLogger('fake_useragent')
        _fua_prev_level = _fua_logger.level
        _fua_logger.setLevel(logging.CRITICAL)

        added = 0
        seen: set[str] = set()
        # 收集已有 UA 用于去重
        with self._lock.read():
            for entries in self._agents.values():
                for e in entries:
                    seen.add(e["ua"])

        try:
            for _ in range(limit * 2):  # 尝试 2× limit 以应对重复
                if added >= limit:
                    break
                try:
                    ua_str = fake_ua.random
                    if ua_str in seen:
                        continue
                    seen.add(ua_str)
                    # 根据 UA 特征自动归类
                    category = self._guess_category(ua_str)
                    self.add(ua_str, category)
                    added += 1
                except Exception:
                    continue
        finally:
            _fua_logger.setLevel(_fua_prev_level)

        # ── 降级：fake_useragent 返回过少时，回退到本地 ua_seeds.json ──
        FALLBACK_THRESHOLD = 5
        if added < FALLBACK_THRESHOLD:
            logger.warning(
                "fake_useragent 仅返回 %d 条 UA（阈值=%d），降级到本地 ua_seeds.json",
                added, FALLBACK_THRESHOLD,
            )
            jsonl_added = self._load_unified_seeds()
            if jsonl_added > 0:
                logger.info(
                    "降级成功：从本地 ua_seeds.json 加载 %d 条 UA",
                    jsonl_added,
                )
                added += jsonl_added

        logger.info(
            "从 fake_useragent 导入完成: %d 个 UA (limit=%d)",
            added, limit,
        )
        return added

    def _load_unified_seeds(self) -> int:
        """从 ua_seeds.json 统一配置文件加载全部 UA + Header Profiles

        加载优先级：
        1. data_dir 目录（若指定）
        2. resource_pool/data/ua_seeds.json（安装目录，含 fed）
        3. user_agent_pool/ua_seeds.json（内置回退）

        支持两种格式：旧格式(desktop/mobile/tablet 键)和新格式(items 列表)。
        """
        import os as _os

        # ── 三层加载：data_dir → 安装目录 JSON → 内置回退 ──
        data: dict | None = None
        source_label = ""

        # 1) data_dir 优先
        if self._data_dir:
            path = _os.path.join(self._data_dir, "ua_seeds.json")
            if _os.path.isfile(path):
                data = self._try_load_json(path)
                if data is not None:
                    source_label = path

        # 2) 安装目录 JSON（resource_pool/data/ua_seeds.json，含 fed）
        if data is None:
            fed_path = _os.path.join(
                _os.path.dirname(__file__), "..", "resource_pool", "data", "ua_seeds.json"
            )
            if _os.path.isfile(fed_path):
                data = self._try_load_json(fed_path)
                if data is not None:
                    source_label = fed_path

        # 3) 内置回退
        if data is None:
            path = _os.path.join(_os.path.dirname(__file__), "ua_seeds.json")
            if _os.path.isfile(path):
                data = self._try_load_json(path)
                if data is not None and self._load_builtin:
                    source_label = path
            else:
                logger.warning("未找到任何 ua_seeds.json")
                return 0

        if data is None:
            return 0

        logger.debug("加载 UA 种子: %s", source_label)

        # ── 注册 Header Profiles ──
        profile_data = data.get("_header_profiles", {})
        if isinstance(profile_data, dict) and profile_data:
            with _PROFILE_LOCK:
                for key, headers in profile_data.items():
                    if isinstance(headers, dict) and key not in _HEADER_PROFILES:
                        _HEADER_PROFILES[key] = dict(headers)
            _invalidate_profile_cache()
            logger.debug("注册 %d 个 Header Profile", len(profile_data))

        # ── 加载 UA 种子 ──
        added = 0
        skipped = 0

        # 新格式：items 列表（含 source/batch 字段）
        items = data.get("items")
        if isinstance(items, list):
            for entry in items:
                if not isinstance(entry, dict) or "ua" not in entry:
                    skipped += 1
                    continue
                # source 过滤
                source = str(entry.get("source", "builtin"))
                if source == "builtin" and not self._load_builtin:
                    continue
                if source == "fed" and not self._load_fed:
                    continue
                cat = self._guess_category(str(entry["ua"]))
                self._agents.setdefault(cat, [])
                try:
                    agent = self._copy_agent_entry({
                        "ua": str(entry["ua"]),
                        "weight": int(entry.get("weight", 5)),
                        "profile": str(entry["profile"]) if entry.get("profile") else None,
                        "browser": str(entry["browser"]) if entry.get("browser") else None,
                        "os": str(entry["os"]) if entry.get("os") else None,
                        "version": int(entry["version"]) if entry.get("version") else None,
                    })
                    self._agents[cat].append(agent)
                    added += 1
                except (ValueError, InvalidAgentException) as e:
                    logger.warning("跳过无效 UA 条目: %s", e)
                    skipped += 1
        else:
            # 旧格式：desktop/mobile/tablet 分类键（默认 source="builtin"）
            for cat in ("desktop", "mobile", "tablet"):
                entries = data.get(cat, [])
                if not isinstance(entries, list):
                    continue
                self._agents.setdefault(cat, [])
                for entry in entries:
                    if not isinstance(entry, dict) or "ua" not in entry:
                        skipped += 1
                        continue
                    # source 过滤（旧格式默认 builtin，喂养后为 fed）
                    source = str(entry.get("source", "builtin"))
                    if source == "builtin" and not self._load_builtin:
                        continue
                    if source == "fed" and not self._load_fed:
                        continue
                    try:
                        agent = self._copy_agent_entry({
                            "ua": str(entry["ua"]),
                            "weight": int(entry.get("weight", 5)),
                            "profile": str(entry["profile"]) if entry.get("profile") else None,
                        })
                        self._agents[cat].append(agent)
                        added += 1
                    except (ValueError, InvalidAgentException) as e:
                        logger.warning("跳过无效 UA 条目: %s", e)
                        skipped += 1

        logger.info("ua_seeds.json: %d 导入, %d 跳过", added, skipped)
        return added

    @staticmethod
    def _try_load_json(path: str) -> dict | None:
        """安全加载 JSON 文件，失败返回 None"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning("解析 %s 失败: %s", path, e)
        return None

    def _build_ua_component_pools(self) -> None:
        """从 854 条 UA 提取零件池，按 (派系, 设备类型) 分组

        每个 UA 拆解为：
        - os_string:     括号内平台标识串（如 Windows NT 10.0; Win64; x64）
        - version_token: 完整版本令牌（如 Chrome/148.0.7727.56）
        - webkit_ver:    AppleWebKit 版本（如 537.36 / 605.1.15）
        - mobile_build:  Mobile/ 构建号（仅移动端 Safari）

        重组时跨零件随机 cross-pick，实现指数级 UA 暴增。
        """
        pools: dict[str, dict[str, list[str]]] = {}

        for entries in self._agents.values():
            for entry in entries:
                ua = entry.get("ua", "")
                browser = entry.get("browser", "")
                os_name = entry.get("os", "")
                if not browser or not os_name or not ua:
                    continue

                # 设备类型
                device = UserAgentPool._detect_device_type(ua, os_name)
                key = f"{browser}_{device}"
                if key not in pools:
                    pools[key] = {
                        "os_strings": [],
                        "version_tokens": [],
                        "versions": [],
                        "webkit_vers": [],
                        "mobile_builds": [],
                    }

                # 提取 OS 串
                os_str = _extract_ua_os(ua, browser)
                if os_str and os_str not in pools[key]["os_strings"]:
                    pools[key]["os_strings"].append(os_str)

                # 提取版本令牌（完整，不去主版本去重）
                ver_token = _extract_ua_ver_token(ua, browser)
                if ver_token and ver_token not in pools[key]["version_tokens"]:
                    pools[key]["version_tokens"].append(ver_token)

                # 主版本号（保留用于降级）
                ver = entry.get("version", 0)
                if ver and ver not in pools[key]["versions"]:
                    pools[key]["versions"].append(ver)

                # WebKit 版本
                wk = _extract_webkit(ua)
                if wk and wk not in pools[key]["webkit_vers"]:
                    pools[key]["webkit_vers"].append(wk)

                # Mobile/ 构建号（仅移动端有意义）
                mb = _extract_mobile_build(ua)
                if mb and mb not in pools[key]["mobile_builds"]:
                    pools[key]["mobile_builds"].append(mb)

        self._ua_pools = pools
        total_os = sum(len(p.get("os_strings", [])) for p in pools.values())
        total_ver = sum(len(p.get("version_tokens", [])) for p in pools.values())
        total_wk = sum(len(p.get("webkit_vers", [])) for p in pools.values())
        logger.info(
            "UA 零件池: %d 派系组 | OS=%d 版本=%d WebKit=%d",
            len(pools), total_os, total_ver, total_wk,
        )

    def _generate_ua_from_faction(self, browser: str, os_name: str, version: int) -> str:
        """从零件池随机组合生成一条新 UA 字符串

        完整版号令牌（不去主版本去重）+ WebKit 版本 + Mobile Build 跨零件随机组合。
        """
        device = "mobile" if os_name in ("android", "ios") else "desktop"
        key = f"{browser}_{device}"
        pool = self._ua_pools.get(key)

        if not pool or not pool.get("os_strings") or not pool.get("version_tokens"):
            return ""

        os_str: str = random.choice(pool["os_strings"])
        ver_token: str = random.choice(pool["version_tokens"])
        mb_pool = pool.get("mobile_builds") or []
        mobile_suffix = ""

        if browser in ("chrome", "edge"):
            # Chromium 派系 —— WebKit 永远是 537.36（不从池取，防 Safari 污染）
            wk_ver = "537.36"
            mobile_suffix = " Mobile" if device != "desktop" else ""
            ua = (
                f"Mozilla/5.0 ({os_str}) AppleWebKit/{wk_ver}"
                f" (KHTML, like Gecko) {ver_token}{mobile_suffix}"
                f" Safari/{wk_ver}"
            )
            if browser == "edge":
                edge_ver_num = _extract_num_from_ver(ver_token) or version
                ua += f" Edg/{edge_ver_num}.0.0.0"
            return ua

        elif browser == "firefox":
            # Firefox 派系 —— 无 WebKit，模板固定格式（Firefox/{v}.0 不存在 build 号差异）
            ver_num = _extract_num_from_ver(ver_token) or version
            if device != "desktop":
                return _FIREFOX_UA_MOBILE.format(os=os_str, v=ver_num)
            return _FIREFOX_UA_DESKTOP.format(os=os_str, v=ver_num)

        elif browser == "safari":
            # Safari 派系 —— WebKit + Version + Mobile Build 均可变
            wk_pool = pool.get("webkit_vers") or ["605.1.15"]
            wk_ver: str = random.choice(wk_pool)
            safari_ver = _extract_num_from_ver(ver_token) or "18.1"
            if mb_pool:
                mobile_suffix = f" Mobile/{random.choice(mb_pool)}"
            return (
                f"Mozilla/5.0 ({os_str}) AppleWebKit/{wk_ver}"
                f" (KHTML, like Gecko) Version/{safari_ver}{mobile_suffix}"
                f" Safari/{wk_ver}"
            )

        return ""

    @staticmethod
    def _guess_category(ua: str) -> str:
        """根据 UA 字符串猜测设备分类"""
        ua_lower = ua.lower()
        if "mobile" in ua_lower or "iphone" in ua_lower or "android" in ua_lower:
            if "tablet" in ua_lower or "ipad" in ua_lower:
                return "tablet"
            return "mobile"
        if "tablet" in ua_lower or "ipad" in ua_lower:
            return "tablet"
        return "desktop"

    @staticmethod
    def _parse_jsonl_file(path: str) -> list[dict[str, object]]:
        """解析 JSONL 文件（每行一个完整 headers JSON 对象）

        每行格式::

            {"User-Agent": "...", "Accept": "...", ...}

        提取 User-Agent 作为 UA 字符串，其余字段作为内联 headers（完整 Header Profile）
        直接存入 entry["headers"]，确保同一行的 Accept/Accept-Language/Cache-Control
        等字段作为原子单位使用，避免字段间不一致被反爬识别。
        分类由 UA 字符串自动推断。
        """
        entries: list[dict[str, object]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("跳过无效 JSONL 行: %s...", line[:60])
                    continue
                if not isinstance(data, dict):
                    continue
                ua = data.pop("User-Agent", "")
                if not ua:
                    continue
                entry: dict[str, object] = {
                    "ua": ua,
                    "category": UserAgentPool._guess_category(ua),
                    "weight": 5,
                }
                # 保留剩余字段作为完整 Header Profile（原子单位）
                if data:
                    entry["headers"] = dict(data)
                entries.append(entry)
        return entries

    @staticmethod
    def _parse_json_file(path: str) -> list[dict[str, object]]:
        """解析 JSON 文件，返回条目列表"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # 支持 {"user_agents": [...]} 或 {"data": [...]} 结构
            for key in ("user_agents", "data", "agents", "ua_list"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # 尝试将单个对象转为列表
                if "ua" in data:
                    data = [data]
        if not isinstance(data, list):
            raise ValueError("JSON 顶层应为数组或包含数组的对象")
        # 过滤掉非 dict 元素
        return [e for e in data if isinstance(e, dict) and "ua" in e]

    @staticmethod
    def _parse_csv_file(path: str) -> list[dict[str, object]]:
        """解析 CSV 文件，返回条目列表"""
        import csv

        entries: list[dict[str, object]] = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV 文件缺少表头")
            # 标准化列名（小写、去空格）
            field_map: dict[str, str] = {}
            for fn in reader.fieldnames:
                key = fn.strip().lower()
                field_map[key] = fn
            for row in reader:
                ua = row.get(field_map.get("ua", "ua"), "").strip()
                if not ua:
                    continue
                category = row.get(
                    field_map.get("category", "category"), "desktop"
                ).strip()
                weight_str = row.get(
                    field_map.get("weight", "weight"), "5"
                ).strip()
                profile = row.get(
                    field_map.get("profile", "profile"), ""
                ).strip()
                try:
                    weight = int(weight_str) if weight_str else 5
                except ValueError:
                    weight = 5
                entry: dict[str, object] = {
                    "ua": ua,
                    "category": category,
                    "weight": max(1, weight),
                }
                if profile:
                    entry["profile"] = profile
                entries.append(entry)
        return entries

    def remove(self, ua: str, category: str | None = None) -> int:
        """移除匹配的 UA，返回移除数量

        若未指定 category，则遍历所有分类。
        """
        removed = 0
        cats = [category] if category else list(self._agents.keys())
        with self._lock.write():
            for cat in cats:
                if cat not in self._agents:
                    continue
                before = len(self._agents[cat])
                self._agents[cat] = [
                    e for e in self._agents[cat] if e["ua"] != ua
                ]
                removed += before - len(self._agents[cat])
        if removed:
            logger.debug("已移除 %d 条 UA", removed)
        return removed

    def count(self, category: str | None = None) -> dict[str, int] | int:
        """统计各分类 UA 数量

        Args:
            category: 指定分类则返回 int，不指定则返回 dict
        """
        if category:
            return len(self._agents.get(category, []))
        return {c: len(v) for c, v in self._agents.items()}

    @staticmethod
    def register_profile(key: str, headers: dict[str, str]) -> None:
        """注册自定义 Header Profile（线程安全）

        注册后可在 add() 时通过 profile=key 引用，
        也可在 agents._HEADER_PROFILES 中直接添加。

        Args:
            key: Profile 唯一标识键
            headers: 请求头字典（不应包含 User-Agent）

        Raises:
            ValueError: key 已存在或 headers 包含 User-Agent
        """
        with _PROFILE_LOCK:
            if key in _HEADER_PROFILES:
                raise ValueError(f"Profile '{key}' 已存在")
            if "User-Agent" in headers:
                raise ValueError("Profile 不应包含 'User-Agent'，该字段由池自动填充")
            _HEADER_PROFILES[key] = dict(headers)
            _invalidate_profile_cache()  # 使匹配缓存失效
        logger.info("已注册 Header Profile: %s (%d 字段)", key, len(headers))

    def __contains__(self, ua: str) -> bool:
        """检查 UA 字符串是否在池中"""
        with self._lock.read():
            for entries in self._agents.values():
                if any(e["ua"] == ua for e in entries):
                    return True
        return False

    def reserve(self, category: str = CATEGORY_ALL, weighted: bool | None = None) -> "UAReserve":
        """上下文管理器 —— 取出一个 UA（从池中移除），退出时自动归还

        使用::

            with pool.reserve("mobile") as ua:
                requests.get(url, headers={"User-Agent": ua})
        """
        use_weighted = weighted if weighted is not None else (self._strategy == UAStrategy.WEIGHTED)
        return UAReserve(self, category, use_weighted)

    @property
    def strategy(self) -> UAStrategy:
        """池级默认选取策略（get/get_headers 未显式传 weighted 时生效）"""
        return self._strategy

    @strategy.setter
    def strategy(self, value: UAStrategy) -> None:
        if not isinstance(value, UAStrategy):
            raise TypeError(f"策略必须是 UAStrategy 枚举，收到: {type(value).__name__}")
        self._strategy = value

    # ── 内部方法 ─────────────────────────────────────────────────────

    def remove_one(self, ua: str, category: str) -> bool:
        """从指定分类移除一条匹配的 UA（仅移除第一条），返回是否成功"""
        with self._lock.write():
            entries = self._agents.get(category, [])
            for i, entry in enumerate(entries):
                if entry["ua"] == ua:
                    entries.pop(i)
                    return True
        return False

    def remove_from_all_categories(self, ua: str) -> tuple[str, bool]:
        """从所有分类中查找并移除指定 UA，返回 (实际分类, 是否成功)
        
        专供 UAReserve 内部使用，避免直接访问受保护成员。
        """
        with self._lock.write():
            for cat, entries in self._agents.items():
                for i, entry in enumerate(entries):
                    if entry["ua"] == ua:
                        entries.pop(i)
                        return cat, True
        return "", False

    def _pick_candidates(self, category: str, exclude: set[str] | None = None,
                         browser: str | None = None, os: str | None = None,
                         min_version: int | None = None) -> list[AgentEntry]:
        candidates: list[AgentEntry] = []
        if category == "all":
            with self._lock.read():
                for entries in self._agents.values():
                    candidates.extend(entries)
        else:
            with self._lock.read():
                candidates = list(self._agents.get(category, []))
        if exclude:
            candidates = [
                e for e in candidates
                if not any(kw.lower() in e["ua"].lower() for kw in exclude)
            ]
        # 细粒度筛选：按浏览器/操作系统/版本号过滤
        if browser:
            candidates = [
                e for e in candidates
                if e.get("browser", "").lower() == browser.lower()
            ]
        if os:
            candidates = [
                e for e in candidates
                if e.get("os", "").lower() == os.lower()
            ]
        if min_version is not None:
            candidates = [
                e for e in candidates
                if e.get("version", 0) >= min_version
            ]
        return candidates

    @staticmethod
    def _weighted_pick(entries: list[AgentEntry]) -> AgentEntry:
        """加权随机选择一个条目（返回完整 entry）

        使用 random.choices 替代手动累积求和，避免浮点累积误差。
        """
        weights = [e["weight"] for e in entries]
        if sum(weights) == 0:
            return random.choice(entries)
        return random.choices(entries, weights=weights, k=1)[0]

    @staticmethod
    def _weighted_choice(entries: list[AgentEntry]) -> str:
        """加权随机选择 UA 字符串"""
        return UserAgentPool._weighted_pick(entries)["ua"]

    @staticmethod
    def _detect_device_type(ua: str, os_name: str) -> str:
        """根据 UA 字符串和 OS 名推断设备类型

        Returns:
            'desktop' | 'mobile' | 'tablet'
        """
        ua_lower = ua.lower()
        if "ipad" in ua_lower or "tablet" in ua_lower:
            return "tablet"
        if os_name in ("android", "ios"):
            return "mobile"
        return "desktop"

    @staticmethod
    def _assemble_headers_from_faction(
        ua: str,
        browser: str,
        os_name: str,
        version: int,
    ) -> dict[str, str] | None:
        """派系化即时组装完整请求头

        核心约束（自动保证）：
        - UA 版本 == Sec-Ch-Ua 版本
        - UA 平台 == Sec-Ch-Ua-Platform
        - Accept-Language 段数匹配设备类型
        - 派系模板不可交叉
        - Firefox 无 Sec-Ch-Ua/Cache-Control，Safari 无 Sec-Ch-Ua/Upgrade

        Args:
            ua: 完整的 User-Agent 字符串
            browser: chrome / firefox / safari / edge
            os_name: windows / macos / linux / android / ios
            version: 主版本号

        Returns:
            完整的 headers 字典，或 None（无法识别的 faction）
        """
        import random as _random

        device_type = UserAgentPool._detect_device_type(ua, os_name)

        # ── Identity Block ───────────────────────────────────────────
        headers: dict[str, str] = {"User-Agent": ua}

        if browser in ("chrome", "edge"):
            # Chromium 派系
            headers["Accept"] = ACCEPT_CHROME
            headers["Accept-Encoding"] = "gzip, deflate, br"
            headers["Connection"] = "keep-alive"
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Site"] = "none"
            headers["Sec-Fetch-User"] = "?1"

            # Sec-Ch-Ua 系列（版本号与 UA 一致）
            sec_ch_ua = _build_sec_ch_ua(browser, version)
            if sec_ch_ua:
                headers["Sec-Ch-Ua"] = sec_ch_ua
            platform_meta = _OS_PLATFORM_META.get(os_name, {})
            headers["Sec-Ch-Ua-Platform"] = platform_meta.get("platform", '"Windows"')
            headers["Sec-Ch-Ua-Mobile"] = "?1" if device_type != "desktop" else "?0"

            # 可变: Cache-Control（桌面端）
            if device_type == "desktop":
                cc = _random.choice(CACHE_CONTROL_VARIANTS)
                if cc:
                    headers["Cache-Control"] = cc

            # 可变: Upgrade-Insecure-Requests
            up = _random.choice(UPGRADE_VARIANTS)
            if up:
                headers["Upgrade-Insecure-Requests"] = up

            # 可变: Accept-Language
            if os_name == "macos":
                headers["Accept-Language"] = _random.choice(AL_MACOS)
            elif device_type == "desktop":
                headers["Accept-Language"] = _random.choice(AL_DESKTOP_5)
            else:
                headers["Accept-Language"] = _random.choice(AL_MOBILE_3)

        elif browser == "firefox":
            # Firefox 派系（无 Sec-Ch-Ua / Cache-Control）
            headers["Accept"] = ACCEPT_FIREFOX
            headers["Accept-Language"] = _random.choice(AL_FIREFOX)
            headers["Accept-Encoding"] = "gzip, deflate, br"
            headers["Connection"] = "keep-alive"
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Site"] = "none"
            headers["Sec-Fetch-User"] = "?1"

            # 可变: Upgrade-Insecure-Requests
            up = _random.choice(UPGRADE_VARIANTS)
            if up:
                headers["Upgrade-Insecure-Requests"] = up

        elif browser == "safari":
            # Safari 派系（无 Sec-Ch-Ua / Upgrade）
            headers["Accept"] = ACCEPT_SAFARI
            headers["Accept-Encoding"] = "gzip, deflate, br"
            headers["Connection"] = "keep-alive"
            headers["Sec-Fetch-Dest"] = "document"
            headers["Sec-Fetch-Mode"] = "navigate"
            headers["Sec-Fetch-Site"] = "none"
            headers["Sec-Fetch-User"] = "?1"

            # 可变: Cache-Control
            cc = _random.choice(CACHE_CONTROL_VARIANTS)
            if cc:
                headers["Cache-Control"] = cc

            # 可变: Accept-Language
            if os_name == "macos":
                headers["Accept-Language"] = _random.choice(AL_MACOS)
            else:
                headers["Accept-Language"] = _random.choice(AL_MOBILE_3)

        else:
            return None  # 无法识别的 faction

        return headers

    def _build_headers(self, entry: AgentEntry) -> dict[str, str]:
        """从 entry 构建完整请求头字典

        优先级（四级降级）：
        1. entry 有 browser/os/version 元数据 → 派系即时组装（jsonl 条目也走这里）
        2. entry 有内联 headers 但无元数据（用户注入）→ 直接使用（兜底）
        3. entry 有显式 profile → 旧 Profile 匹配（向后兼容）
        4. 均无 → 仅返回 User-Agent

        派系组装为每次调用即时随机：Accept-Language / Cache-Control / Upgrade
        每个 UA 每次 3~20 种变体。jsonl 中 830 条 UA 种子也会过组装，
        Accept 按派系自动匹配，Sec-Ch-Ua 版本号自动对齐。
        """
        # ── 派系即时组装（最高优先级：包括 jsonl 条目也动态生成）──
        browser = entry.get("browser", "")
        os_name = entry.get("os", "")
        version = entry.get("version", 0)

        if browser and os_name and version:
            # ── 第一层：UA 零件池随机重组（数量暴增）──
            ua = self._generate_ua_from_faction(browser, os_name, version)
            if not ua:
                ua = entry["ua"]  # 降级：无零件池时用原始 UA
            # 从生成的 UA 重提取版本号，保证 Sec-Ch-Ua 一致
            gen_version = _extract_ua_version(ua) or version
            faction_headers = UserAgentPool._assemble_headers_from_faction(
                ua=ua,
                browser=str(browser),
                os_name=str(os_name),
                version=int(gen_version),
            )
            if faction_headers:
                logger.debug(
                    "派系组装 headers: faction=%s os=%s v=%s",
                    browser, os_name, version,
                )
                return faction_headers

        # ── 内联 headers（兜底：无元数据但有内联 headers 的条目）──
        inline_headers = entry.get("headers")
        if inline_headers:
            result = dict(inline_headers)
            result["User-Agent"] = entry["ua"]
            for canonical, variants in _SEC_CH_UA_KEY_ALIASES.items():
                for v in variants:
                    if v in result and v != canonical:
                        result[canonical] = result.pop(v)
                        break
            _patch_sec_ch_ua(result, entry["ua"])
            return result

        # ── 旧 Profile 匹配（向后兼容：显式指定 profile 或自动匹配）──
        headers: dict[str, str] = {"User-Agent": entry["ua"]}
        profile_key = entry.get("profile", "")

        # 自动匹配：无显式 profile 但有元数据时，自动查找最佳匹配
        if not profile_key:
            if browser and os_name and version:
                matched = match_profile(
                    browser=str(browser),
                    os=str(os_name),
                    version=int(version),
                    ua=entry["ua"],
                )
                if matched:
                    profile_key = matched
                    logger.debug(
                        "自动匹配 Profile: %s → %s (browser=%s, os=%s, v=%s)",
                        entry["ua"][:50], matched, browser, os_name, version,
                    )

        if profile_key:
            # 锁内只读 copy，解锁后 update（减少锁持有时间）
            with _PROFILE_LOCK:
                profile_data = _HEADER_PROFILES.get(profile_key)
            if profile_data is not None:
                headers.update(profile_data)
                # 动态补丁：修正 Sec-Ch-Ua 版本号与 UA 一致
                _patch_sec_ch_ua(headers, entry["ua"])
            else:
                logger.warning("Profile '%s' 不存在，仅返回 User-Agent", profile_key)
        return headers

    def __repr__(self) -> str:
        stats = ", ".join(f"{c}={len(v)}" for c, v in self._agents.items())
        return f"UserAgentPool({stats})"

    def __len__(self) -> int:
        """返回池中 UA 总数（含所有分类和状态，与 alive 概念无关）"""
        return sum(len(v) for v in self._agents.values())

    def __iter__(self) -> Iterator[str]:
        """迭代所有类别的所有 UA（线程安全快照）"""
        with self._lock.read():
            snapshot = [
                e["ua"]
                for entries in self._agents.values()
                for e in entries
            ]
        yield from snapshot


class UAReserve:
    """UA 暂存器 —— 上下文管理器，取出时从池中移除，退出时归还

    注意：高并发场景下，get() 与 remove 之间存在 TOCTOU（Time-Of-Check to Time-Of-Use）竞态窗口。
    当并发线程数超过池容量时，可能有少数 UA 无法被正确归还。
    此时被"泄漏"的 UA 将在 with 退出时 silently 跳过归还（不抛异常）。
    如需严格保证，建议控制并发度 ≤ 池容量，或使用独立池实例。
    """

    def __init__(self, pool: UserAgentPool, category: str, weighted: bool) -> None:
        self._pool = pool
        self._category = category
        self._weighted = weighted
        self.ua: str = ""
        self._removed = False

    def __enter__(self) -> str:
        self.ua = self._pool.get(self._category, self._weighted)
        # 从池中暂存取出（移除一条），避免同一 UA 被并发取到
        if self._category == "all":
            # category='all' 时需遍历所有分类找到 UA 的真实归属
            real_category, self._removed = self._pool.remove_from_all_categories(self.ua)
            if self._removed:
                self._category = real_category
        else:
            self._removed = self._pool.remove_one(self.ua, self._category)
        return self.ua

    def __exit__(self, *args: object) -> None:
        """退出时自动归还到池子"""
        if self.ua and self._removed:
            try:
                self._pool.add(self.ua, self._category)
            except (ValueError, InvalidAgentException):
                logger.warning(
                    "UAReserve 归还失败: UA=%s, category=%s",
                    self.ua[:80], self._category,
                )
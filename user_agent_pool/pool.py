"""User-Agent 资源池核心逻辑"""

import json
import logging
import os
import random
import threading
from enum import Enum
from typing import Iterator

from user_agent_pool.exceptions import PoolExhaustedException, InvalidAgentException
from user_agent_pool.agents import (
    DEFAULT_AGENTS,
    VALID_CATEGORIES,
    _HEADER_PROFILES,
    _PROFILE_LOCK,
    AgentEntry,
    parse_ua_metadata,
)
from resource_pool.base import DummyLock, DummyReadWriteLock, ReadWriteLock, ResourcePool

logger = logging.getLogger(__name__)


class UAStrategy(Enum):
    """UA 选取策略"""
    WEIGHTED = "weighted"
    UNIFORM = "uniform"


# 常量
CATEGORY_ALL: str = "all"  # 表示所有分类的特殊值


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
                 thread_safe: bool = True) -> None:
        self._agents: dict[str, list[AgentEntry]] = {}
        self._strategy = strategy
        self._init_defaults()
        self._thread_safe = thread_safe
        self._lock = ReadWriteLock() if thread_safe else DummyReadWriteLock()

    # ── 初始化 ───────────────────────────────────────────────────────

    def _init_defaults(self) -> None:
        """从 agents.py 导入内置数据集"""
        for cat in ("desktop", "mobile", "tablet"):
            self._agents[cat] = [
                self._copy_agent_entry(entry)
                for entry in DEFAULT_AGENTS[cat]
            ]
        total = sum(len(v) for v in self._agents.values())
        logger.info("已加载 %d 个 User-Agent（desktop=%d, mobile=%d, tablet=%d）",
                    total, len(self._agents["desktop"]), len(self._agents["mobile"]), len(self._agents["tablet"]))

    @staticmethod
    def _copy_agent_entry(entry: AgentEntry) -> AgentEntry:
        """创建 AgentEntry 的浅拷贝（类型安全），含元数据字段"""
        copied: AgentEntry = {"ua": entry["ua"], "weight": entry.get("weight", 5)}
        for key in ("profile", "browser", "os", "version"):
            if key in entry:
                copied[key] = entry[key]  # type: ignore[literal-required]
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

    def add(self, ua: str, category: str, weight: int = 5, profile: str | None = None) -> None:
        """向指定分类添加一个 UA

        Args:
            ua: User-Agent 字符串
            category: desktop | mobile | tablet
            weight: 权重（≥1）
            profile: Header Profile 键名（可选），见 agents._HEADER_PROFILES

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
        # 自动检测浏览器/操作系统/版本号（用于细粒度筛选）
        metadata = parse_ua_metadata(ua_clean)
        for key in ("browser", "os", "version"):
            if key in metadata:
                entry[key] = metadata[key]  # type: ignore[literal-required]
        with self._lock.write():
            self._agents.setdefault(category, []).append(entry)
        logger.debug("UA 已添加: %s → 分类 '%s'", ua_clean[:50], category)

    def load_from_file(self, path: str) -> int:
        """从 JSON 或 CSV 文件批量导入 User-Agent

        支持的格式：

        **JSON（推荐）**::

            [
                {"ua": "Mozilla/5.0 ...", "category": "desktop", "weight": 5, "profile": "chrome_120"},
                {"ua": "Mozilla/5.0 ...", "category": "mobile", "weight": 3}
            ]

        **CSV**::

            ua,category,weight,profile
            "Mozilla/5.0 ...",desktop,5,chrome_120
            "Mozilla/5.0 ...",mobile,3,

        CSV 首行为表头，字段名不区分大小写。
        只需 ``ua`` 和 ``category`` 两列，``weight`` 和 ``profile`` 可选。

        Args:
            path: JSON 或 CSV 文件路径

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
        elif ext == ".csv":
            entries = self._parse_csv_file(path)
        else:
            raise ValueError(
                f"不支持的文件格式 '{ext}'，仅支持 .json 和 .csv"
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

        added = 0
        seen: set[str] = set()
        # 收集已有 UA 用于去重
        with self._lock.read():
            for entries in self._agents.values():
                for e in entries:
                    seen.add(e["ua"])

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

        logger.info(
            "从 fake_useragent 导入完成: %d 个 UA (limit=%d)",
            added, limit,
        )
        return added

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
        """加权随机选择一个条目（返回完整 entry）"""
        total = sum(e["weight"] for e in entries)
        if total == 0:
            return random.choice(entries)
        r = random.uniform(0, total)
        cumulative = 0.0
        for entry in entries:
            cumulative += entry["weight"]
            if r <= cumulative:
                return entry
        return entries[-1]

    @staticmethod
    def _weighted_choice(entries: list[AgentEntry]) -> str:
        """加权随机选择 UA 字符串"""
        return UserAgentPool._weighted_pick(entries)["ua"]

    @staticmethod
    def _build_headers(entry: AgentEntry) -> dict[str, str]:
        """从 entry 构建完整请求头字典"""
        headers: dict[str, str] = {"User-Agent": entry["ua"]}
        profile_key = entry.get("profile", "")
        if profile_key:
            # 锁内只读 copy，解锁后 update（减少锁持有时间）
            with _PROFILE_LOCK:
                profile_data = _HEADER_PROFILES.get(profile_key)
            if profile_data is not None:
                headers.update(profile_data)
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
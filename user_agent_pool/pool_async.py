"""异步 User-Agent 资源池 —— asyncio 版本

与同步版 UserAgentPool 功能一致，但使用 asyncio.Lock 保证协程安全，
UAReserve 改为 async with 上下文管理器。
"""

import asyncio
import logging
import random
from typing import AsyncIterator

from user_agent_pool.pool import UAStrategy, UserAgentPool
from user_agent_pool.agents import (
    DEFAULT_AGENTS,
    VALID_CATEGORIES,
    _HEADER_PROFILES,
    _PROFILE_LOCK,
    AgentEntry,
    parse_ua_metadata,
    match_profile,
)
from user_agent_pool.exceptions import PoolExhaustedException, InvalidAgentException
from resource_pool.base_async import AsyncDummyLock, AsyncResourcePool
from resource_pool.orchestrator_async import AsyncPoolOrchestrator

logger = logging.getLogger(__name__)


class AsyncUserAgentPool(AsyncResourcePool):
    """协程安全的 User-Agent 资源池（asyncio 版本）

    与同步版 UserAgentPool 功能一致，使用 asyncio.Lock 替代 threading.Lock。

    使用示例::

        pool = AsyncUserAgentPool()
        ua = await pool.get("desktop")
        headers = await pool.get_headers("mobile")

        async with pool.reserve("desktop") as ua:
            ...
    """

    def __init__(self, strategy: UAStrategy = UAStrategy.WEIGHTED,
                 thread_safe: bool = True) -> None:
        self._agents: dict[str, list[AgentEntry]] = {}
        self._strategy: UAStrategy = strategy
        self._init_defaults()
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()

    # ── 初始化 ───────────────────────────────────────────────────────

    def _init_defaults(self) -> None:
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

    async def get(self, category: str = "all",
                  weighted: bool | None = None,
                  exclude: set[str] | None = None,
                  browser: str | None = None,
                  os: str | None = None,
                  min_version: int | None = None) -> str:
        """获取一个 User-Agent 字符串

        Args:
            category: desktop | mobile | tablet | all
            weighted: True=按权重加权随机；False=均匀随机；None=使用池级默认策略
            exclude: 排除包含这些关键词的 UA
            browser: 限定浏览器（chrome / firefox / safari / edge）
            os: 限定操作系统（windows / macos / linux / android / ios）
            min_version: 最低主版本号（如 120 表示 Chrome 120+）
        """
        candidates = self._pick_candidates(category, exclude, browser, os, min_version)
        if not candidates:
            logger.error("UA 池分类 '%s' 已耗尽", category)
            raise PoolExhaustedException(resource_type=category)
        use_weighted = weighted if weighted is not None else (self._strategy == UAStrategy.WEIGHTED)
        if use_weighted:
            return self._weighted_choice(candidates)
        return random.choice(candidates)["ua"]

    async def get_headers(self, category: str = "all",
                          weighted: bool | None = None,
                          exclude: set[str] | None = None,
                          browser: str | None = None,
                          os: str | None = None,
                          min_version: int | None = None) -> dict[str, str]:
        """获取完整的请求头 Profile

        Args:
            category: desktop | mobile | tablet | all
            weighted: True=加权；False=均匀；None=使用池级默认策略
            exclude: 排除包含这些关键词的 UA
            browser: 限定浏览器（chrome / firefox / safari / edge）
            os: 限定操作系统（windows / macos / linux / android / ios）
            min_version: 最低主版本号（如 120）
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

    async def add(self, ua: str, category: str, weight: int = 5,
                  profile: str | None = None) -> None:
        """向指定分类添加一个 UA

        Args:
            ua: User-Agent 字符串
            category: desktop | mobile | tablet
            weight: 权重（≥1）
            profile: Header Profile 键名（可选）
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
        async with self._lock:
            self._agents.setdefault(category, []).append(entry)
        logger.debug("UA 已添加: %s → 分类 '%s'", ua_clean[:50], category)

    async def remove(self, ua: str, category: str | None = None) -> int:
        """移除匹配的 UA，返回移除数量"""
        removed = 0
        cats = [category] if category else list(self._agents.keys())
        async with self._lock:
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

    async def count(self, category: str | None = None) -> dict[str, int] | int:
        """统计各分类 UA 数量"""
        if category:
            return len(self._agents.get(category, []))
        return {c: len(v) for c, v in self._agents.items()}

    def reserve(self, category: str = "all") -> "AsyncUAReserve":
        """异步上下文管理器 —— 取出一个 UA，退出时自动归还

        使用::

            async with pool.reserve("mobile") as ua:
                await do_request(headers={"User-Agent": ua})
        """
        return AsyncUAReserve(self, category)

    async def get_all(self, category: str = "all",
                      exclude: set[str] | None = None,
                      browser: str | None = None,
                      os: str | None = None,
                      min_version: int | None = None) -> list[str]:
        """获取该分类下所有 UA 字符串（不修改池）"""
        return [
            entry["ua"]
            for entry in self._pick_candidates(category, exclude, browser, os, min_version)
        ]

    @staticmethod
    def register_profile(key: str, headers: dict[str, str]) -> None:
        """注册自定义 Header Profile（线程安全）

        委托给同步版 UserAgentPool.register_profile()，
        避免代码重复。同步版已使用 threading.Lock 保证线程安全。

        Args:
            key: Profile 唯一标识键
            headers: 请求头字典（不应包含 User-Agent）

        Raises:
            ValueError: key 已存在或 headers 包含 User-Agent
        """
        UserAgentPool.register_profile(key, headers)

    async def load_from_file(self, path: str) -> int:
        """从 JSON 或 CSV 文件批量异步导入 User-Agent

        解析逻辑复用同步版 UserAgentPool，通过 asyncio.to_thread
        在后台线程执行文件读取和解析，不阻塞事件循环。

        支持的格式：JSON (*.json) 或 CSV (*.csv)

        Args:
            path: JSON 或 CSV 文件路径

        Returns:
            成功导入的 UA 数量

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式无法识别或内容为空
        """
        def _load_sync() -> list[dict[str, object]]:
            import os as _os
            if not _os.path.isfile(path):
                raise FileNotFoundError(f"UA 文件不存在: {path}")
            ext = _os.path.splitext(path)[1].lower()
            if ext == ".json":
                return UserAgentPool._parse_json_file(path)
            elif ext == ".csv":
                return UserAgentPool._parse_csv_file(path)
            else:
                raise ValueError(
                    f"不支持的文件格式 '{ext}'，仅支持 .json 和 .csv"
                )

        entries = await asyncio.to_thread(_load_sync)
        if not entries:
            raise ValueError(f"文件中未解析到任何有效 UA 条目: {path}")

        added = 0
        skipped = 0
        for entry in entries:
            try:
                await self.add(
                    ua=str(entry["ua"]),
                    category=str(entry.get("category", "desktop")),
                    weight=int(entry.get("weight", 5)),
                    profile=str(entry["profile"]) if entry.get("profile") else None,
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

    async def load_from_fakeua(
        self,
        browsers: list[str] | None = None,
        os_list: list[str] | None = None,
        limit: int = 50,
    ) -> int:
        """从 fake_useragent 库异步批量导入 User-Agent

        通过 asyncio.to_thread 在后台线程执行阻塞的 fake_useragent 调用。
        需要先安装：``pip install fake-useragent``

        Args:
            browsers: 限定浏览器类型，如 ["chrome", "firefox"]，None=全部
            os_list: 限定操作系统，如 ["windows", "macos"]，None=全部
            limit: 最多导入数量

        Returns:
            成功导入的 UA 数量

        Raises:
            ImportError: fake_useragent 未安装
        """
        def _import_fakeua() -> list[str]:
            try:
                from fake_useragent import UserAgent as FakeUA
            except ImportError:
                raise ImportError(
                    "load_from_fakeua 需要 fake-useragent 库，请执行: pip install fake-useragent"
                ) from None

            fake_ua = FakeUA(
                browsers=browsers or ["chrome", "firefox", "safari", "edge"],
                os=os_list or ["windows", "macos", "linux"],
            )

            # 收集已有 UA 用于去重
            seen: set[str] = set()
            for entries in self._agents.values():
                for e in entries:
                    seen.add(e["ua"])

            results: list[str] = []
            for _ in range(limit * 2):
                if len(results) >= limit:
                    break
                try:
                    ua_str = fake_ua.random
                except Exception:
                    continue
                if ua_str in seen:
                    continue
                seen.add(ua_str)
                results.append(ua_str)
            return results

        ua_strings = await asyncio.to_thread(_import_fakeua)

        added = 0
        for ua_str in ua_strings:
            try:
                category = UserAgentPool._guess_category(ua_str)
                await self.add(ua_str, category)
                added += 1
            except (ValueError, InvalidAgentException):
                continue

        logger.info(
            "从 fake_useragent 导入完成: %d 个 UA (limit=%d)",
            added, limit,
        )
        return added

    # ── 策略 ─────────────────────────────────────────────────────────

    @property
    def strategy(self) -> UAStrategy:
        """池级默认选取策略（get/get_headers 未显式传 weighted 时生效）"""
        return self._strategy

    @strategy.setter
    def strategy(self, value: UAStrategy) -> None:
        if not isinstance(value, UAStrategy):
            raise TypeError(
                f"策略必须是 UAStrategy 枚举，收到: {type(value).__name__}"
            )
        self._strategy = value

    # ── 魔术方法 ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        stats = ", ".join(f"{c}={len(v)}" for c, v in self._agents.items())
        return f"AsyncUserAgentPool({stats})"

    def __len__(self) -> int:
        return sum(len(v) for v in self._agents.values())

    def __contains__(self, ua: str) -> bool:
        return any(e["ua"] == ua for entries in self._agents.values() for e in entries)

    async def __aiter__(self) -> AsyncIterator[str]:
        """异步迭代所有 UA"""
        async with self._lock:
            snapshot = [
                e["ua"]
                for entries in self._agents.values()
                for e in entries
            ]
        for ua in snapshot:
            yield ua

    # ── 内部方法 ─────────────────────────────────────────────────────

    async def remove_one(self, ua: str, category: str) -> bool:
        """从指定分类移除一条匹配的 UA"""
        async with self._lock:
            entries = self._agents.get(category, [])
            for i, entry in enumerate(entries):
                if entry["ua"] == ua:
                    entries.pop(i)
                    return True
        return False

    async def remove_from_all_categories(self, ua: str) -> tuple[str, bool]:
        """从所有分类中查找并移除指定 UA"""
        async with self._lock:
            for cat, entries in self._agents.items():
                for i, entry in enumerate(entries):
                    if entry["ua"] == ua:
                        entries.pop(i)
                        return cat, True
        return "", False

    def _pick_candidates(self, category: str,
                         exclude: set[str] | None = None,
                         browser: str | None = None,
                         os: str | None = None,
                         min_version: int | None = None) -> list[AgentEntry]:
        candidates: list[AgentEntry] = []
        if category == "all":
            for entries in self._agents.values():
                candidates.extend(entries)
        else:
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
        return AsyncUserAgentPool._weighted_pick(entries)["ua"]

    @staticmethod
    def _build_headers(entry: AgentEntry) -> dict[str, str]:
        """从 entry 构建完整请求头字典

        优先级：
        1. entry 显式指定 profile → 直接使用
        2. entry 无 profile 但有 browser/os/version → 自动匹配最佳 Profile
        3. 均无 → 仅返回 User-Agent
        """
        headers: dict[str, str] = {"User-Agent": entry["ua"]}
        profile_key = entry.get("profile", "")

        # 自动匹配：无显式 profile 但有元数据时，自动查找最佳匹配
        if not profile_key:
            browser = entry.get("browser", "")
            os_name = entry.get("os", "")
            version = entry.get("version", 0)
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
            with _PROFILE_LOCK:
                profile_data = _HEADER_PROFILES.get(profile_key)
            if profile_data is not None:
                headers.update(profile_data)
            else:
                logger.warning("Profile '%s' 不存在，仅返回 User-Agent", profile_key)
        return headers


class AsyncUAReserve:
    """异步 UA 暂存器 —— async with 上下文管理器"""

    def __init__(self, pool: AsyncUserAgentPool, category: str) -> None:
        self._pool = pool
        self._category = category
        self.ua: str = ""
        self._removed = False

    async def __aenter__(self) -> str:
        self.ua = await self._pool.get(self._category)
        if self._category == "all":
            real_category, self._removed = await self._pool.remove_from_all_categories(self.ua)
            if self._removed:
                self._category = real_category
        else:
            self._removed = await self._pool.remove_one(self.ua, self._category)
        return self.ua

    async def __aexit__(self, *args: object) -> None:
        if self.ua and self._removed:
            try:
                await self._pool.add(self.ua, self._category)
            except (ValueError, InvalidAgentException):
                logger.warning(
                    "AsyncUAReserve 归还失败: UA=%s, category=%s",
                    self.ua[:80], self._category,
                )


# ── 自动注册到异步编排器 ──
AsyncPoolOrchestrator.register_dispatch(AsyncUserAgentPool, "get_headers")

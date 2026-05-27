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
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()
        self._init_defaults()

    # ── 初始化 ───────────────────────────────────────────────────────

    def _init_defaults(self) -> None:
        """从 agents.py 导入内置数据集 + 加载 headers_pool.jsonl

        headers_pool.jsonl（800+ 条真实 UA）作为本地降级路径的基数数据源。
        __init__ 阶段同步解析 jsonl 并直接扩展 self._agents, 无需走 async add()。
        """
        for cat in ("desktop", "mobile", "tablet"):
            self._agents[cat] = [
                self._copy_agent_entry(entry)
                for entry in DEFAULT_AGENTS[cat]
            ]
        # 加载 bundled headers_pool.jsonl 扩充默认池（同步解析 + 直接注入）
        jsonl_loaded = self._load_bundled_jsonl_sync()
        total = sum(len(v) for v in self._agents.values())
        logger.info("已加载 %d 个 User-Agent（desktop=%d, mobile=%d, tablet=%d, jsonl新增=%d）",
                    total, len(self._agents["desktop"]), len(self._agents["mobile"]),
                    len(self._agents["tablet"]), jsonl_loaded)

    @staticmethod
    def _copy_agent_entry(entry: AgentEntry) -> AgentEntry:
        """创建 AgentEntry 的浅拷贝（类型安全），含元数据字段

        若原始 entry 缺少 browser/os/version 元数据，
        自动从 UA 字符串解析补全，确保派系组装路径可用。
        """
        copied: AgentEntry = {"ua": entry["ua"], "weight": entry.get("weight", 5)}
        for key in ("profile", "browser", "os", "version"):
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
                  profile: str | None = None,
                  headers: dict[str, str] | None = None) -> None:
        """向指定分类添加一个 UA

        Args:
            ua: User-Agent 字符串
            category: desktop | mobile | tablet
            weight: 权重（≥1）
            profile: Header Profile 键名（可选）
            headers: 内联完整请求头字典（可选），优先级最高，不包含 User-Agent
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
        """从 JSON / JSONL / CSV 文件批量异步导入 User-Agent

        解析逻辑复用同步版 UserAgentPool，通过 asyncio.to_thread
        在后台线程执行文件读取和解析，不阻塞事件循环。

        支持的格式：JSON (*.json)、JSONL (*.jsonl) 或 CSV (*.csv)

        JSONL 格式中每行的完整 headers（Accept、Accept-Language 等）作为
        原子单位保留，确保字段间语义一致不被反爬识别。

        Args:
            path: JSON / JSONL / CSV 文件路径

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
            elif ext == ".jsonl":
                return UserAgentPool._parse_jsonl_file(path)
            elif ext == ".csv":
                return UserAgentPool._parse_csv_file(path)
            else:
                raise ValueError(
                    f"不支持的文件格式 '{ext}'，仅支持 .json、.jsonl 和 .csv"
                )

        entries = await asyncio.to_thread(_load_sync)
        if not entries:
            raise ValueError(f"文件中未解析到任何有效 UA 条目: {path}")

        added = 0
        skipped = 0
        for entry in entries:
            try:
                entry_headers = entry.get("headers")
                await self.add(
                    ua=str(entry["ua"]),
                    category=str(entry.get("category", "desktop")),
                    weight=int(entry.get("weight", 5)),
                    profile=str(entry["profile"]) if entry.get("profile") else None,
                    headers=dict(entry_headers) if isinstance(entry_headers, dict) else None,
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
        """加权随机选择一个条目（返回完整 entry）

        使用 random.choices 替代手动累积求和，避免浮点累积误差。
        """
        weights = [e["weight"] for e in entries]
        if sum(weights) == 0:
            return random.choice(entries)
        return random.choices(entries, weights=weights, k=1)[0]

    @staticmethod
    def _weighted_choice(entries: list[AgentEntry]) -> str:
        return AsyncUserAgentPool._weighted_pick(entries)["ua"]

    @staticmethod
    def _build_headers(entry: AgentEntry) -> dict[str, str]:
        """从 entry 构建完整请求头字典

        委托给同步版 UserAgentPool 实例（惰性单例），
        享受相同的优先级逻辑（内联 headers > 派系组装 > Profile 匹配）。
        """
        # 惰性单例：避免每次创建新实例，共享一份 _ua_pools
        if not hasattr(AsyncUserAgentPool, '_sync_builder'):
            AsyncUserAgentPool._sync_builder = UserAgentPool()
        return AsyncUserAgentPool._sync_builder._build_headers(entry)

    def _load_bundled_jsonl_sync(self) -> int:
        """同步加载 bundled headers_pool.jsonl（供 __init__ 阶段使用）

        直接解析 jsonl 并注入 self._agents，无需走 async add()。
        每条 UA 自动通过 parse_ua_metadata 提取 browser/os/version，
        并保留完整内联 headers（Accept/Accept-Language 等作为原子单位）。
        """
        import os as _os

        search_paths = [
            _os.path.join(_os.path.dirname(__file__), "headers_pool.jsonl"),
        ]

        for path in search_paths:
            if _os.path.isfile(path):
                logger.debug("AsyncUA 找到本地 headers_pool.jsonl: %s", path)
                try:
                    raw_entries = UserAgentPool._parse_jsonl_file(path)
                except Exception as e:
                    logger.warning("AsyncUA 解析 headers_pool.jsonl 失败: %s", e)
                    continue

                added = 0
                seen: set[str] = set()
                for cat_entries in self._agents.values():
                    for e in cat_entries:
                        seen.add(e["ua"])

                for raw in raw_entries:
                    ua_str = str(raw["ua"])
                    if ua_str in seen:
                        continue
                    seen.add(ua_str)
                    category = str(raw.get("category", UserAgentPool._guess_category(ua_str)))
                    entry: AgentEntry = {"ua": ua_str, "weight": 5}
                    metadata = parse_ua_metadata(ua_str)
                    for key in ("browser", "os", "version"):
                        if key in metadata:
                            entry[key] = metadata[key]  # type: ignore[literal-required]
                    # 保留完整内联 headers（来自 jsonl 同一行的 Accept/Accept-Language 等）
                    raw_headers = raw.get("headers")
                    if isinstance(raw_headers, dict):
                        entry["headers"] = dict(raw_headers)  # type: ignore[typeddict-item]
                    self._agents.setdefault(category, []).append(entry)
                    added += 1

                logger.info("AsyncUA headers_pool.jsonl: %d 导入", added)
                return added

        logger.debug("AsyncUA 未找到 headers_pool.jsonl 文件")
        return 0


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

"""异步 User-Agent 资源池 —— asyncio 版本

与同步版 UserAgentPool 功能一致，但使用 asyncio.Lock 保证协程安全，
UAReserve 改为 async with 上下文管理器。
"""

import asyncio
import logging
import random
from typing import AsyncIterator

from user_agent_pool.agents import (
    DEFAULT_AGENTS,
    VALID_CATEGORIES,
    _HEADER_PROFILES,
    _PROFILE_LOCK,
    AgentEntry,
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

    def __init__(self, thread_safe: bool = True) -> None:
        self._agents: dict[str, list[AgentEntry]] = {}
        self._init_defaults()
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()

    # ── 初始化 ───────────────────────────────────────────────────────

    def _init_defaults(self) -> None:
        for cat in ("desktop", "mobile", "tablet"):
            self._agents[cat] = [
                {"ua": e["ua"], "weight": e.get("weight", 5), **({"profile": e["profile"]} if "profile" in e else {})}
                for e in DEFAULT_AGENTS[cat]
            ]
        total = sum(len(v) for v in self._agents.values())
        logger.info("已加载 %d 个 User-Agent（desktop=%d, mobile=%d, tablet=%d）",
                    total, len(self._agents["desktop"]), len(self._agents["mobile"]), len(self._agents["tablet"]))

    # ── 公开 API ─────────────────────────────────────────────────────

    async def get(self, category: str = "all", exclude: set[str] | None = None) -> str:
        """获取一个 User-Agent 字符串（加权随机）"""
        candidates = self._pick_candidates(category, exclude)
        if not candidates:
            logger.error("UA 池分类 '%s' 已耗尽", category)
            raise PoolExhaustedException(resource_type=category)
        return self._weighted_choice(candidates)

    async def get_headers(self, category: str = "all",
                          exclude: set[str] | None = None) -> dict[str, str]:
        """获取完整的请求头 Profile"""
        candidates = self._pick_candidates(category, exclude)
        if not candidates:
            logger.error("UA 池分类 '%s' 已耗尽（get_headers）", category)
            raise PoolExhaustedException(resource_type=category)

        entry = self._weighted_pick(candidates)
        return self._build_headers(entry)

    async def add(self, ua: str, category: str, weight: int = 5,
                  profile: str | None = None) -> None:
        """向指定分类添加一个 UA"""
        if category not in VALID_CATEGORIES or category == "all":
            raise ValueError(f"无效分类 '{category}'，可选: {VALID_CATEGORIES}")
        if not ua or not ua.strip():
            raise InvalidAgentException("UA 不能为空")

        entry: AgentEntry = {"ua": ua.strip(), "weight": max(1, weight)}
        if profile:
            entry["profile"] = profile
        async with self._lock:
            self._agents.setdefault(category, []).append(entry)
        logger.debug("UA 已添加: %s → 分类 '%s'", ua[:50], category)

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
                         exclude: set[str] | None = None) -> list[AgentEntry]:
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
        headers: dict[str, str] = {"User-Agent": entry["ua"]}
        profile_key = entry.get("profile", "")
        if profile_key:
            with _PROFILE_LOCK:
                if profile_key in _HEADER_PROFILES:
                    headers.update(_HEADER_PROFILES[profile_key])
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

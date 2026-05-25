"""User-Agent 资源池核心逻辑"""

import logging
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
)
from resource_pool.base import DummyLock, ResourcePool

logger = logging.getLogger(__name__)


class UAStrategy(Enum):
    """UA 选取策略"""
    WEIGHTED = "weighted"
    UNIFORM = "uniform"


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
        self._lock = threading.Lock() if thread_safe else DummyLock()

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
        """创建 AgentEntry 的浅拷贝（类型安全）"""
        copied: AgentEntry = {"ua": entry["ua"], "weight": entry.get("weight", 5)}
        if "profile" in entry:
            copied["profile"] = entry["profile"]
        return copied

    # ── 公开 API ─────────────────────────────────────────────────────

    def get(self, category: str = "all", weighted: bool | None = None,
            exclude: set[str] | None = None) -> str:
        """从池中获取一个 User-Agent 字符串

        Args:
            category: desktop | mobile | tablet | all
            weighted: True=按权重加权随机；False=均匀随机；
                      None=使用池级 strategy 默认值
            exclude: 排除包含这些关键词的 UA（如 {"Firefox", "Linux"}）

        Returns:
            User-Agent 字符串

        Raises:
            PoolExhaustedException: 该分类下无可用 UA
        """
        candidates = self._pick_candidates(category, exclude)
        if not candidates:
            logger.error("UA 池分类 '%s' 已耗尽", category)
            raise PoolExhaustedException(resource_type=category)

        use_weighted = weighted if weighted is not None else (self._strategy == UAStrategy.WEIGHTED)
        if use_weighted:
            return self._weighted_choice(candidates)
        return random.choice(candidates)["ua"]

    def get_all(self, category: str = "all", exclude: set[str] | None = None) -> list[str]:
        """获取该分类下所有 UA 字符串（不修改池）"""
        return [entry["ua"] for entry in self._pick_candidates(category, exclude)]

    def get_headers(self, category: str = "all", weighted: bool | None = None,
                    exclude: set[str] | None = None) -> dict[str, str]:
        """获取完整的请求头 Profile（包含 User-Agent + 配套请求头）

        返回的字典可直接用于 requests.get(url, headers=headers)。
        各字段（Accept / Accept-Language / Sec-Ch-Ua 等）语义与 UA 一致，
        避免浏览器特征不匹配被反爬识别。

        如果所选 UA 没有关联 profile，则只返回 {"User-Agent": ua}。

        Args:
            category: desktop | mobile | tablet | all
            weighted: True=加权；False=均匀；None=使用池级默认策略
            exclude: 排除包含这些关键词的 UA

        Raises:
            PoolExhaustedException: 该分类下无可用 UA
        """
        candidates = self._pick_candidates(category, exclude)
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

        entry: AgentEntry = {"ua": ua.strip(), "weight": max(1, weight)}
        if profile:
            entry["profile"] = profile
        with self._lock:
            self._agents.setdefault(category, []).append(entry)
        logger.debug("UA 已添加: %s → 分类 '%s'", ua[:50], category)

    def remove(self, ua: str, category: str | None = None) -> int:
        """移除匹配的 UA，返回移除数量

        若未指定 category，则遍历所有分类。
        """
        removed = 0
        cats = [category] if category else list(self._agents.keys())
        with self._lock:
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
        with self._lock:
            for entries in self._agents.values():
                if any(e["ua"] == ua for e in entries):
                    return True
        return False

    def reserve(self, category: str = "all", weighted: bool | None = None) -> "UAReserve":
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
        with self._lock:
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
        with self._lock:
            for cat, entries in self._agents.items():
                for i, entry in enumerate(entries):
                    if entry["ua"] == ua:
                        entries.pop(i)
                        return cat, True
        return "", False

    def _pick_candidates(self, category: str, exclude: set[str] | None = None) -> list[AgentEntry]:
        candidates: list[AgentEntry] = []
        if category == "all":
            with self._lock:
                for entries in self._agents.values():
                    candidates.extend(entries)
        else:
            with self._lock:
                candidates = list(self._agents.get(category, []))
        if exclude:
            candidates = [
                e for e in candidates
                if not any(kw.lower() in e["ua"].lower() for kw in exclude)
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
            with _PROFILE_LOCK:
                if profile_key in _HEADER_PROFILES:
                    headers.update(_HEADER_PROFILES[profile_key])
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
        with self._lock:
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
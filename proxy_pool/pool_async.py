"""异步代理资源池 —— asyncio 版本

与同步版 ProxyPool 功能一致，但：
- 使用 aiohttp 替代 urllib.request 实现异步 HTTP 代理探测
- 使用 asyncio.open_connection 替代 socket.create_connection
- 使用 asyncio.Lock 替代 threading.Lock
"""

import asyncio
import json
import logging
import random
import time

from proxy_pool.exceptions import PoolExhaustedException
from proxy_pool.servers import (
    ProxyEntry,
    VALID_SCHEMES,
    HEALTH_CHECK_URLS,
)
from resource_pool.base_async import AsyncDummyLock, AsyncResourcePool
from resource_pool.orchestrator_async import AsyncPoolOrchestrator

logger = logging.getLogger(__name__)


class ProxyStrategy:
    """代理选择策略（与同步版共用枚举值）

    注意：异步版不导入同步版的 ProxyStrategy Enum，避免意外耦合。
    使用字符串常量保持接口一致。
    """
    LATENCY_WEIGHTED = "latency_weighted"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"

    _ALL = frozenset({LATENCY_WEIGHTED, ROUND_ROBIN, RANDOM})

    @classmethod
    def _validate(cls, value: str) -> None:
        if value not in cls._ALL:
            raise ValueError(f"无效策略 '{value}'，可选: {sorted(cls._ALL)}")


class AsyncProxyState:
    """异步代理运行时状态"""

    __slots__ = (
        "scheme", "host", "port", "username", "password",
        "region", "enabled", "weight",
        "latency_ms", "fail_count", "success_count",
        "consecutive_fails", "last_used", "last_health",
    )

    def __init__(self, entry: ProxyEntry) -> None:
        self.scheme: str = entry.get("scheme", "http")
        self.host: str = entry["host"]
        self.port: int = entry["port"]
        self.username: str = entry.get("username", "")
        self.password: str = entry.get("password", "")
        self.region: str = entry.get("region", "unknown")
        self.enabled: bool = entry.get("enabled", True)
        self.weight: int = entry.get("weight", 5)
        self.latency_ms: float = 0.0
        self.fail_count: int = 0
        self.success_count: int = 0
        self.consecutive_fails: int = 0
        self.last_used: float = 0.0
        self.last_health: float = 0.0

    @property
    def url(self) -> str:
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def masked_url(self) -> str:
        if self.username:
            return f"{self.scheme}://{self.username}:***@{self.host}:{self.port}"
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def key(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


class AsyncProxyPool(AsyncResourcePool):
    """协程安全的代理资源池（asyncio 版本）

    使用示例::

        pool = AsyncProxyPool()
        pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})
        await pool.health_check()
        proxy = await pool.get()
        proxies = await pool.get_dict()
    """

    def __init__(
        self,
        strategy: str = ProxyStrategy.LATENCY_WEIGHTED,
        max_consecutive_fails: int = 3,
        revive_after: int = 120,
        thread_safe: bool = True,
    ) -> None:
        ProxyStrategy._validate(strategy)
        self._proxies: list[AsyncProxyState] = []
        self._strategy: str = strategy
        self._max_fails = max_consecutive_fails
        self._revive_after = revive_after
        self._thread_safe = thread_safe
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()
        self._rr_index = 0
        self._last_revive_check: float = 0.0

    # ── 公开 API ─────────────────────────────────────────────────────

    async def get(self, scheme: str | None = None) -> str:
        """获取一个代理 URL"""
        state = self._pick_one(scheme)
        if state is None:
            raise PoolExhaustedException(detail="无可用代理")
        self._on_success(state)
        return state.url

    async def get_dict(self, scheme: str | None = None) -> dict[str, str]:
        """获取 requests 库兼容的代理字典"""
        state = self._pick_one(scheme)
        if state is None:
            raise PoolExhaustedException(detail="无可用代理")
        url = state.url
        self._on_success(state)
        return {"http": url, "https": url}

    def add_proxy(self, entry: ProxyEntry) -> None:
        """添加代理（同步操作，纯内存）"""
        scheme = entry.get("scheme", "http")
        if scheme not in VALID_SCHEMES:
            raise ValueError(f"无效 scheme '{scheme}'，可选: {VALID_SCHEMES}")
        if "host" not in entry or "port" not in entry:
            raise ValueError("ProxyEntry 必须包含 host 和 port")

        state = AsyncProxyState(entry)
        existing = [s for s in self._proxies if s.key == state.key]
        if existing:
            existing[0].enabled = True
            existing[0].weight = state.weight
            existing[0].username = state.username
            existing[0].password = state.password
            logger.debug("已更新代理: %s", state.key)
            return
        self._proxies.append(state)
        logger.info("已添加代理: %s", state.key)

    def remove_proxy(self, host: str, port: int, scheme: str = "http") -> bool:
        """移除（禁用）代理"""
        for s in self._proxies:
            if s.host == host and s.port == port and s.scheme == scheme:
                s.enabled = False
                return True
        return False

    def enable_proxy(self, host: str, port: int, scheme: str = "http") -> bool:
        """重新启用代理"""
        for s in self._proxies:
            if s.host == host and s.port == port and s.scheme == scheme:
                s.enabled = True
                s.consecutive_fails = 0
                return True
        return False

    async def health_check(self, timeout: float = 5.0) -> dict[str, str]:
        """全量异步健康检查"""
        results: dict[str, str] = {}
        snapshot = list(self._proxies)
        for state in snapshot:
            ok = await self._probe_proxy(state, timeout)
            if state not in self._proxies:
                continue
            if ok:
                if state.enabled:
                    state.consecutive_fails = 0
                    results[state.key] = "OK"
                else:
                    results[state.key] = "OK(隔离中)"
            else:
                state.consecutive_fails += 1
                if state.consecutive_fails >= self._max_fails:
                    state.enabled = False
                    logger.warning(
                        "代理 %s 连续失败 %d 次，已隔离",
                        state.key, state.consecutive_fails,
                    )
                results[state.key] = "FAIL"
            state.last_health = time.time()
        ok_count = sum(1 for v in results.values() if v == "OK")
        logger.info("代理健康检查完成: %d/%d 可用", ok_count, len(results))
        return results

    async def stats(self) -> list[dict]:
        """返回所有代理运行时状态"""
        return [
            {
                "proxy": s.masked_url,
                "region": s.region,
                "enabled": s.enabled,
                "latency_ms": round(s.latency_ms, 1),
                "success": s.success_count,
                "fail": s.fail_count,
                "last_used": s.last_used,
            }
            for s in self._proxies
        ]

    def mark_failed(self, host: str, port: int, scheme: str = "http") -> bool:
        """手动标记代理失败"""
        for s in self._proxies:
            if s.host == host and s.port == port and s.scheme == scheme:
                s.fail_count += 1
                s.consecutive_fails += 1
                s.last_used = time.time()
                if s.consecutive_fails >= self._max_fails:
                    s.enabled = False
                    logger.warning(
                        "代理 %s 连续失败 %d 次，已隔离",
                        s.key, s.consecutive_fails,
                    )
                return True
        return False

    # ── 魔术方法 ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        alive = len(self._get_alive())
        total = len(self._proxies)
        strategy_name = self._strategy
        return f"AsyncProxyPool(alive={alive}/{total}, strategy={strategy_name})"

    def __len__(self) -> int:
        return len(self._get_alive())

    def __contains__(self, proxy_key: str) -> bool:
        return any(s.key == proxy_key for s in self._proxies)

    # ── 内部 ─────────────────────────────────────────────────────────

    def _pick_one(self, scheme: str | None) -> AsyncProxyState | None:
        alive = self._get_alive()
        if scheme:
            alive = [s for s in alive if s.scheme == scheme]
        self._try_revive()
        if not alive:
            return None

        strat = self._strategy
        if strat == ProxyStrategy.LATENCY_WEIGHTED:
            ordered = sorted(
                alive,
                key=lambda s: (1.0 if s.latency_ms == 0 else s.latency_ms) / max(s.weight, 1)
            )
            return ordered[0]
        if strat == ProxyStrategy.ROUND_ROBIN:
            self._rr_index = (self._rr_index + 1) % len(alive)
            return alive[self._rr_index]
        if strat == ProxyStrategy.RANDOM:
            return random.choice(alive)
        return None

    @staticmethod
    async def _probe_proxy(state: AsyncProxyState, timeout: float) -> bool:
        """异步探测代理连通性"""
        # 1. socket 预检
        probe_timeout = min(timeout, 3.0)
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(state.host, state.port),
                timeout=probe_timeout,
            )
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError):
            return False

        # 2. HTTP 验证（通过 aiohttp）
        try:
            import aiohttp
        except ImportError:
            logger.warning(
                "aiohttp 未安装，跳过代理 %s 的 HTTP 验证（socket 预检已通过）",
                state.key,
            )
            return True  # socket 通了，乐观认为可用

        target = random.choice(HEALTH_CHECK_URLS)
        proxy_url = state.url
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as session:
                async with session.head(
                    target,
                    proxy=proxy_url,
                ) as resp:
                    if resp.status < 500:
                        elapsed = (time.monotonic() - start) * 1000
                        state.latency_ms = (
                            state.latency_ms * 0.7 + elapsed * 0.3
                            if state.latency_ms else elapsed
                        )
                        return True
        except Exception:
            pass
        return False

    def _get_alive(self) -> list[AsyncProxyState]:
        return [s for s in self._proxies if s.enabled]

    def _try_revive(self) -> None:
        now = time.time()
        if now - self._last_revive_check < 30:
            return
        self._last_revive_check = now
        for s in self._proxies:
            if not s.enabled and (now - s.last_health) > self._revive_after:
                s.enabled = True
                s.consecutive_fails = max(0, self._max_fails - 1)
                logger.info("代理 %s 超过复活时间，已重新启用（试用中）", s.masked_url)

    def _on_success(self, state: AsyncProxyState) -> None:
        state.success_count += 1
        state.consecutive_fails = 0
        state.last_used = time.time()


# ── 自动注册到异步编排器 ──
AsyncPoolOrchestrator.register_dispatch(AsyncProxyPool, "get_dict")

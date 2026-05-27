"""异步代理资源池 —— asyncio 版本

与同步版 ProxyPool 功能一致，但：
- 使用 aiohttp 替代 urllib.request 实现异步 HTTP 代理探测
- 使用 asyncio.open_connection 替代 socket.create_connection
- 使用 asyncio.Lock 替代 threading.Lock
"""

import asyncio
import json
import logging
import os
import random
import time
import urllib.request
import urllib.error
from enum import Enum

from proxy_pool.exceptions import PoolExhaustedException
from proxy_pool.servers import (
    ProxyEntry,
    VALID_SCHEMES,
    HEALTH_CHECK_URLS,
    _load_from_data_dir,
)
from resource_pool.base import StrategyProtocol
from resource_pool.base_async import AsyncDummyLock, AsyncResourcePool
from resource_pool.orchestrator_async import AsyncPoolOrchestrator

logger = logging.getLogger(__name__)


class ProxyStrategy(str, Enum):
    """代理选择策略（与同步版共用枚举值）"""
    LATENCY_WEIGHTED = "latency_weighted"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


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
        strategy: ProxyStrategy | str | StrategyProtocol = ProxyStrategy.LATENCY_WEIGHTED,
        max_consecutive_fails: int = 3,
        revive_after: int = 120,
        thread_safe: bool = True,
        min_alive: int = 0,
        auto_refill_url: str = "",
        data_dir: str | None = None,
        load_builtin: bool = True,
        load_fed: bool = True,
    ) -> None:
        if isinstance(strategy, str) and not isinstance(strategy, ProxyStrategy):
            try:
                strategy = ProxyStrategy(strategy)
            except ValueError:
                raise ValueError(f"无效策略 '{strategy}'，可选: {[e.value for e in ProxyStrategy]}") from None
        self._proxies: list[AsyncProxyState] = []
        self._strategy: ProxyStrategy | str | StrategyProtocol = strategy
        self._strategy_enum: ProxyStrategy | None = strategy if isinstance(strategy, ProxyStrategy) else None
        self._strategy_fn: StrategyProtocol | None = strategy if callable(strategy) else None
        self._max_fails = max_consecutive_fails
        self._revive_after = revive_after
        self._thread_safe = thread_safe
        self._lock = asyncio.Lock() if thread_safe else AsyncDummyLock()
        self._rr_index = 0
        self._last_revive_check: float = 0.0
        # 自动维护配置
        self._min_alive = min_alive
        self._auto_refill_url = auto_refill_url
        self._last_auto_maintain: float = 0.0
        # 养成系
        self._data_dir = data_dir
        self._load_builtin = load_builtin
        self._load_fed = load_fed
        self._load_defaults()

    # ── 初始化 ───────────────────────────────────────────────────────

    def _load_defaults(self) -> None:
        """加载默认代理（data_dir / JSON 数据文件 / 回退空列表）"""
        # 1) data_dir 优先
        if self._data_dir:
            path = os.path.join(self._data_dir, "proxy_servers.json")
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    items = data.get("items", []) if isinstance(data, dict) else []
                    for item in items:
                        if not isinstance(item, dict) or "host" not in item or "port" not in item:
                            continue
                        source = str(item.get("source", "builtin"))
                        if source == "builtin" and not self._load_builtin:
                            continue
                        if source == "fed" and not self._load_fed:
                            continue
                        self._proxies.append(AsyncProxyState({
                            "scheme": str(item.get("scheme", "http")),
                            "host": str(item["host"]),
                            "port": int(item["port"]),
                            "username": str(item.get("username", "")),
                            "password": str(item.get("password", "")),
                            "region": str(item.get("region", "unknown")),
                            "enabled": bool(item.get("enabled", True)),
                            "weight": int(item.get("weight", 5)),
                        }))
                    logger.info("已从 %s 加载 %d 个代理", path, len(self._proxies))
                    return
                except Exception as e:
                    logger.warning("data_dir 代理加载失败: %s，回退", e)

        # 2) 安装目录 JSON（含 fed 养成数据）
        if self._load_builtin or self._load_fed:
            json_proxies = _load_from_data_dir()
            if json_proxies:
                for entry in json_proxies:
                    source = entry.get("source", "builtin")
                    if source == "builtin" and not self._load_builtin:
                        continue
                    if source == "fed" and not self._load_fed:
                        continue
                    self._proxies.append(AsyncProxyState(entry))

        logger.info("已加载 %d 个代理", len(self._proxies))

    # ── 公开 API ─────────────────────────────────────────────────────

    async def get(self, scheme: str | None = None) -> str:
        """获取一个代理 URL

        选择逻辑在锁外执行（纯计算），仅状态访问/修改走锁，
        与同步版 ProxyPool 保持一致的并发模型，避免协程串行化。
        """
        state = await self._pick_one(scheme)
        if state is None:
            raise PoolExhaustedException(detail="无可用代理")
        await self._on_success(state)
        return state.url

    async def get_dict(self, scheme: str | None = None) -> dict[str, str]:
        """获取 requests 库兼容的代理字典

        选择逻辑在锁外执行（纯计算），仅状态访问/修改走锁。
        """
        state = await self._pick_one(scheme)
        if state is None:
            raise PoolExhaustedException(detail="无可用代理")
        url = state.url
        await self._on_success(state)
        return {"http": url, "https": url}

    async def add_proxy(self, entry: ProxyEntry) -> None:
        """添加代理（协程安全）"""
        scheme = entry.get("scheme", "http")
        if scheme not in VALID_SCHEMES:
            raise ValueError(f"无效 scheme '{scheme}'，可选: {VALID_SCHEMES}")
        if "host" not in entry or "port" not in entry:
            raise ValueError("ProxyEntry 必须包含 host 和 port")
        if not (0 < int(entry.get("port", 0)) < 65536):
            raise ValueError(f"端口号无效: {entry.get('port')}")

        state = AsyncProxyState(entry)
        async with self._lock:
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

    async def remove_proxy(self, host: str, port: int, scheme: str = "http") -> bool:
        """移除（禁用）代理（协程安全）"""
        async with self._lock:
            for s in self._proxies:
                if s.host == host and s.port == port and s.scheme == scheme:
                    s.enabled = False
                    return True
        return False

    async def enable_proxy(self, host: str, port: int, scheme: str = "http") -> bool:
        """重新启用代理（协程安全）"""
        async with self._lock:
            for s in self._proxies:
                if s.host == host and s.port == port and s.scheme == scheme:
                    s.enabled = True
                    s.consecutive_fails = 0
                    return True
        return False

    async def health_check(self, timeout: float = 5.0) -> dict[str, str]:
        """全量异步健康检查"""
        results: dict[str, str] = {}
        async with self._lock:
            snapshot = list(self._proxies)
        for state in snapshot:
            ok = await self._probe_proxy(state, timeout)
            async with self._lock:
                # 重新校验 state 仍在池中且未被其他协程修改
                if state not in self._proxies:
                    continue
                if ok:
                    # 仅在仍启用时才更新（避免覆盖并发隔离操作）
                    if state.enabled:
                        state.consecutive_fails = 0
                        results[state.key] = "OK"
                    else:
                        # 已被隔离但探测通过，保留隔离状态等待 _try_revive
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
        async with self._lock:
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

    async def mark_failed(self, host: str, port: int, scheme: str = "http") -> bool:
        """手动标记代理失败 —— 在请求失败后调用，用于运行时反馈

        返回 True 表示标记成功，False 表示代理不在池中。
        连续失败达到阈值后会自动隔离。
        """
        async with self._lock:
            for s in self._proxies:
                if s.host == host and s.port == port and s.scheme == scheme:
                    s.fail_count += 1
                    s.consecutive_fails += 1
                    s.last_used = time.time()
                    s.last_health = time.time()
                    if s.consecutive_fails >= self._max_fails:
                        s.enabled = False
                        logger.warning(
                            "代理 %s 连续失败 %d 次，已隔离",
                            s.key, s.consecutive_fails,
                        )
                    return True
        return False

    # ── 评分 ─────────────────────────────────────────────────────────

    async def scores(self) -> list[dict]:
        """返回所有代理评分（按分数降序），含脱敏 URL（协程安全）"""
        async with self._lock:
            scored = [
                {
                    "proxy": s.masked_url,
                    "score": self._calc_score(s),
                    "latency_ms": round(s.latency_ms, 1),
                    "success": s.success_count,
                    "fail": s.fail_count,
                    "enabled": s.enabled,
                }
                for s in self._proxies
            ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    @staticmethod
    def _calc_score(state: AsyncProxyState) -> float:
        """代理综合评分（0-100）

        评分维度：
        - 响应时间（40%）：延迟越低分越高
        - 成功率（40%）：success / (success + fail)
        - 稳定性（20%）：连续失败越多扣分越多
        """
        total_requests = state.success_count + state.fail_count
        if total_requests == 0:
            return 50.0

        if state.latency_ms <= 0:
            latency_score = 100.0
        else:
            latency_score = max(0.0, 100.0 * (1.0 - state.latency_ms / 5000.0))

        success_rate = state.success_count / total_requests
        success_score = success_rate * 100.0

        stability_penalty = min(100.0, state.consecutive_fails * 25.0)
        stability_score = max(0.0, 100.0 - stability_penalty)

        return round(
            latency_score * 0.4 + success_score * 0.4 + stability_score * 0.2,
            1,
        )

    # ── 加载 / 持久化 ────────────────────────────────────────────────

    async def load_from_url(
        self,
        url: str,
        timeout: float = 10.0,
        default_scheme: str = "http",
        headers: dict[str, str] | None = None,
    ) -> int:
        """从代理提取 API 链接异步批量加载代理

        使用 asyncio.to_thread 在后台线程执行 HTTP 请求，不阻塞事件循环。
        解析逻辑复用同步版 ProxyPool 的 _parse_response。

        Args:
            url: 代理提取 API 链接
            timeout: 请求超时（秒）
            default_scheme: 未指定协议时代理的默认 scheme
            headers: 自定义请求头（如 API Key 鉴权）

        Returns:
            成功添加的代理数量

        Raises:
            ValueError: URL 无效或无法解析任何代理
            OSError: 网络请求失败
        """
        from proxy_pool.pool import ProxyPool as SyncProxyPool

        def _fetch() -> bytes:
            req = urllib.request.Request(url)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except urllib.error.URLError as e:
                raise OSError(f"代理 API 请求失败: {e}") from e

        raw = await asyncio.to_thread(_fetch)
        body = raw.decode("utf-8", errors="replace").strip()

        entries = SyncProxyPool._parse_response(body, default_scheme)
        if not entries:
            raise ValueError(f"未能从响应中解析出任何代理，响应前 200 字符: {body[:200]}")

        added = 0
        for entry in entries:
            try:
                await self.add_proxy(entry)
                added += 1
            except ValueError as e:
                logger.warning("跳过无效代理 %s: %s", entry.get("host", "?"), e)

        logger.info("从 URL 加载代理完成: %d/%d 个入库", added, len(entries))
        return added

    async def load_from_urls(
        self,
        urls: list[str],
        timeout: float = 10.0,
        default_scheme: str = "http",
        headers: dict[str, str] | None = None,
        max_workers: int = 5,
    ) -> int:
        """从多个代理供应商 URL 并发拉取代理，去重合并

        使用 asyncio.to_thread + ThreadPoolExecutor 实现并发拉取。

        Args:
            urls: 代理提取 API 链接列表
            timeout: 单次请求超时（秒）
            default_scheme: 默认代理协议
            headers: 统一请求头（各 URL 共用）
            max_workers: 并发线程数

        Returns:
            成功添加的代理总数

        Raises:
            ValueError: 所有 URL 均失败或未解析出任何代理
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from proxy_pool.pool import ProxyPool as SyncProxyPool

        all_entries: list[ProxyEntry] = []
        errors: list[str] = []

        def _fetch_one(u: str) -> list[ProxyEntry]:
            req = urllib.request.Request(u)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            body = raw.decode("utf-8", errors="replace").strip()
            return SyncProxyPool._parse_response(body, default_scheme)

        def _fetch_all() -> tuple[list[ProxyEntry], list[str]]:
            all_e: list[ProxyEntry] = []
            errs: list[str] = []
            with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
                future_map = {executor.submit(_fetch_one, u): u for u in urls}
                for future in as_completed(future_map):
                    u = future_map[future]
                    try:
                        entries = future.result()
                        all_e.extend(entries)
                        logger.debug("供应商 %s 返回 %d 条代理", u, len(entries))
                    except Exception as e:
                        logger.warning("供应商 %s 拉取失败: %s", u, e)
                        errs.append(f"{u}: {e}")
            return all_e, errs

        all_entries, errors = await asyncio.to_thread(_fetch_all)

        if not all_entries:
            raise ValueError(
                f"所有 {len(urls)} 个供应商均未返回有效代理，错误: {'; '.join(errors[:3])}"
            )

        # 去重入库
        added = 0
        seen: set[str] = {s.key for s in self._proxies}
        for entry in all_entries:
            key = f"{entry.get('scheme', default_scheme)}://{entry['host']}:{entry['port']}"
            if key in seen:
                continue
            try:
                await self.add_proxy(entry)
                seen.add(key)
                added += 1
            except ValueError as e:
                logger.warning("跳过无效代理 %s: %s", entry.get("host", "?"), e)

        logger.info(
            "多供应商拉取完成: %d 个 URL, %d 条去重入库, %d 个失败",
            len(urls), added, len(errors),
        )
        return added

    async def save_to_file(self, path: str) -> int:
        """将代理池状态异步持久化到 JSON 文件

        密码字段明文保存，请确保文件权限安全。

        Args:
            path: 输出 JSON 文件路径

        Returns:
            写入的代理数量
        """
        async with self._lock:
            data = [
                {
                    "scheme": s.scheme,
                    "host": s.host,
                    "port": s.port,
                    "username": s.username,
                    "password": s.password,
                    "region": s.region,
                    "enabled": s.enabled,
                    "weight": s.weight,
                    "latency_ms": round(s.latency_ms, 1),
                    "success_count": s.success_count,
                    "fail_count": s.fail_count,
                    "consecutive_fails": s.consecutive_fails,
                    "last_used": s.last_used,
                    "last_health": s.last_health,
                }
                for s in self._proxies
            ]

        import os as _os
        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        await asyncio.to_thread(_write)
        logger.info("代理池已保存到 %s (%d 个代理)", path, len(data))
        return len(data)

    async def load_from_file(self, path: str) -> int:
        """从 JSON 文件异步恢复代理池

        Args:
            path: JSON 文件路径

        Returns:
            成功恢复的代理数量

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: JSON 格式无效
        """
        def _read() -> list[dict]:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        data = await asyncio.to_thread(_read)
        if not isinstance(data, list):
            raise ValueError("JSON 顶层应为数组")

        added = 0
        for item in data:
            if not isinstance(item, dict) or "host" not in item or "port" not in item:
                continue
            try:
                entry: ProxyEntry = {
                    "host": item["host"],
                    "port": int(item["port"]),
                    "scheme": item.get("scheme", "http"),
                }
                if item.get("username"):
                    entry["username"] = item["username"]
                if item.get("password"):
                    entry["password"] = item["password"]
                if item.get("region"):
                    entry["region"] = item["region"]
                if "weight" in item:
                    entry["weight"] = int(item["weight"])
                if "enabled" in item:
                    entry["enabled"] = bool(item["enabled"])
                await self.add_proxy(entry)
                added += 1
            except (ValueError, TypeError) as e:
                logger.warning("跳过无效代理条目: %s", e)

        logger.info("从文件恢复代理池完成: %s (%d 个代理)", path, added)
        return added

    async def auto_maintain(self, timeout: float = 10.0) -> dict:
        """自动维护：评分淘汰低分代理 + 低于 min_alive 阈值自动补充

        Returns:
            {"removed": int, "refilled": int, "alive": int}
        """
        result: dict = {"removed": 0, "refilled": 0, "alive": 0}
        now = time.time()

        async with self._lock:
            # 防抖：60 秒内不重复执行
            if now - self._last_auto_maintain < 60:
                result["alive"] = len([s for s in self._proxies if s.enabled])
                return result
            self._last_auto_maintain = now

            # 1. 淘汰评分过低的代理（<10 分且至少完成过 3 次请求）
            to_remove: list[int] = []
            for i, s in enumerate(self._proxies):
                total = s.success_count + s.fail_count
                if total >= 3 and self._calc_score(s) < 10.0:
                    to_remove.append(i)
            for i in reversed(to_remove):
                removed = self._proxies.pop(i)
                logger.info(
                    "自动淘汰低分代理 %s (score=%.1f)",
                    removed.masked_url, self._calc_score(removed),
                )
                result["removed"] += 1

            alive = len([s for s in self._proxies if s.enabled])
            result["alive"] = alive

        # 2. 低于阈值自动补充（锁外调用 load_from_url）
        if self._min_alive > 0 and alive < self._min_alive and self._auto_refill_url:
            try:
                refilled = await self.load_from_url(self._auto_refill_url, timeout=timeout)
                result["refilled"] = refilled
                result["alive"] = alive + refilled
            except (OSError, ValueError) as e:
                logger.warning("自动补充代理失败: %s", e)

        return result

    # ── 魔术方法 ─────────────────────────────────────────────────────

    @property
    def strategy(self) -> ProxyStrategy | StrategyProtocol:
        """当前选择策略"""
        if self._strategy_fn is not None:
            return self._strategy_fn
        return self._strategy_enum or self._strategy

    @strategy.setter
    def strategy(self, value: ProxyStrategy | str | StrategyProtocol) -> None:
        """运行时切换策略"""
        if isinstance(value, str) and not isinstance(value, ProxyStrategy):
            try:
                value = ProxyStrategy(value)
            except ValueError:
                raise ValueError(f"无效策略 '{value}'，可选: {[e.value for e in ProxyStrategy]}") from None
        if isinstance(value, ProxyStrategy):
            self._strategy_enum = value
            self._strategy_fn = None
        elif callable(value):
            self._strategy_enum = None
            self._strategy_fn = value
        else:
            raise TypeError(
                f"策略必须是 ProxyStrategy 常量或 callable，收到: {type(value).__name__}"
            )
        self._strategy = value

    def __repr__(self) -> str:
        # asyncio 单线程环境下简单属性读取原子安全
        alive = sum(1 for s in self._proxies if s.enabled)
        total = len(self._proxies)
        if self._strategy_fn is not None:
            strategy_name = type(self._strategy_fn).__name__
        else:
            strategy_name = self._strategy_enum or str(self._strategy)
        return f"AsyncProxyPool(alive={alive}/{total}, strategy={strategy_name})"

    def __len__(self) -> int:
        return sum(1 for s in self._proxies if s.enabled)

    def __contains__(self, proxy_key: str) -> bool:
        return any(s.key == proxy_key for s in self._proxies)

    # ── 内部 ─────────────────────────────────────────────────────────

    async def _pick_one(self, scheme: str | None) -> AsyncProxyState | None:
        """按策略选一个可用代理

        锁仅保护状态读（_get_alive）和复活（_try_revive），
        策略选择（排序/随机/轮询偏移更新）在锁外执行，减少锁持有时间。
        """
        alive = await self._get_alive()
        if scheme:
            alive = [s for s in alive if s.scheme == scheme]
        await self._try_revive()
        if not alive:
            return None

        # 优先枚举策略，其次 callable（纯计算，锁外执行）
        if self._strategy_enum is not None:
            strat = self._strategy_enum
            if strat == ProxyStrategy.LATENCY_WEIGHTED:
                ordered = sorted(
                    alive,
                    key=lambda s: (1.0 if s.latency_ms == 0 else s.latency_ms) / max(s.weight, 1)
                )
                return ordered[0]
            if strat == ProxyStrategy.ROUND_ROBIN:
                async with self._lock:
                    self._rr_index = (self._rr_index + 1) % len(alive)
                    return alive[self._rr_index]
            if strat == ProxyStrategy.RANDOM:
                return random.choice(alive)
            return None
        if self._strategy_fn is not None:
            it = self._strategy_fn(alive)
            try:
                return next(it)
            except StopIteration:
                return None
        return None

    _PROBE_MAX_URLS: int = 3  # 最多探测几个目标 URL

    @staticmethod
    async def _probe_proxy(state: AsyncProxyState, timeout: float) -> bool:
        """异步探测代理连通性

        先做 socket 快速预检，再走多目标 HTTP 验证：
        最多探测 3 个不同 URL，任一成功即判定存活。
        """
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

        # 打乱 URL 顺序，避免每次从同一个开始
        urls = list(HEALTH_CHECK_URLS)
        random.shuffle(urls)
        proxy_url = state.url
        per_url_timeout = max(timeout / min(len(urls), AsyncProxyPool._PROBE_MAX_URLS), 3.0)

        success = False
        for i, target in enumerate(urls):
            if i >= AsyncProxyPool._PROBE_MAX_URLS:
                break
            start = time.monotonic()
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=per_url_timeout),
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
                            success = True
                            break
            except Exception:
                logger.debug("代理 %s 探测 %s 失败", state.masked_url, target)
                continue

        return success

    async def _get_alive(self) -> list[AsyncProxyState]:
        """获取存活代理快照（锁内操作，返回独立 list）"""
        async with self._lock:
            return [s for s in self._proxies if s.enabled]

    async def _try_revive(self) -> None:
        """检查并复活超时隔离的代理（锁内操作，与同步版一致）"""
        now = time.time()
        async with self._lock:
            # 时间戳检查纳入锁范围，避免多协程重复复活
            if now - self._last_revive_check < 30:
                return
            self._last_revive_check = now
            for s in self._proxies:
                if not s.enabled and (now - s.last_health) > self._revive_after:
                    s.enabled = True
                    # 只给一次机会：再失败立即重新隔离
                    s.consecutive_fails = max(0, self._max_fails - 1)
                    logger.info("代理 %s 超过复活时间，已重新启用（试用中）", s.masked_url)

    async def _on_success(self, state: AsyncProxyState) -> None:
        """记录一次成功的代理选取（锁内操作）"""
        async with self._lock:
            state.success_count += 1
            state.consecutive_fails = 0
            state.last_used = time.time()


# ── 自动注册到异步编排器 ──
AsyncPoolOrchestrator.register_dispatch(AsyncProxyPool, "get_dict")

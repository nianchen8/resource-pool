"""代理资源池 —— 可扩展核心"""

import json
import logging
import random
import socket
import threading
import time
import urllib.request
import urllib.error
from enum import Enum

from proxy_pool.exceptions import PoolExhaustedException
from proxy_pool.servers import (
    ProxyEntry,
    VALID_SCHEMES,
    HEALTH_CHECK_URLS,
)
from resource_pool.base import DummyLock, ResourcePool, StrategyProtocol

logger = logging.getLogger(__name__)


class ProxyStrategy(Enum):
    """代理选择策略"""
    LATENCY_WEIGHTED = "latency_weighted"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


class ProxyState:
    """代理运行时状态"""

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
        """代理 URL 字符串"""
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def masked_url(self) -> str:
        """脱敏后的 URL（隐藏密码）"""
        if self.username:
            return f"{self.scheme}://{self.username}:***@{self.host}:{self.port}"
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def key(self) -> str:
        """唯一标识"""
        return f"{self.scheme}://{self.host}:{self.port}"


class ProxyPool(ResourcePool):
    """线程安全的代理资源池

    支持 HTTP/HTTPS/SOCKS5 代理，延迟加权/轮询/随机策略，
    自动健康检查、故障隔离、定时复活。

    使用示例::

        pool = ProxyPool(strategy=ProxyStrategy.LATENCY_WEIGHTED)
        pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})
        pool.health_check()
        proxy = pool.get()               # "http://127.0.0.1:8080"
        proxies = pool.get_dict()        # {"http": "...", "https": "..."}
    """

    def __init__(
        self,
        strategy: ProxyStrategy | StrategyProtocol = ProxyStrategy.LATENCY_WEIGHTED,
        max_consecutive_fails: int = 3,
        revive_after: int = 120,
        thread_safe: bool = True,
    ) -> None:
        self._proxies: list[ProxyState] = []
        self._strategy: ProxyStrategy | StrategyProtocol = strategy
        self._max_fails = max_consecutive_fails
        self._revive_after = revive_after
        self._thread_safe = thread_safe
        self._lock = threading.Lock() if thread_safe else DummyLock()
        self._rr_index = 0
        self._last_revive_check: float = 0.0

    # ── 公开 API ─────────────────────────────────────────────────────

    def load_from_url(
        self,
        url: str,
        timeout: float = 10.0,
        default_scheme: str = "http",
        headers: dict[str, str] | None = None,
    ) -> int:
        """从代理提取 API 链接批量加载代理

        支持市面上主流代理服务商的返回格式：

        **纯文本**（逐行 ip:port）::

            183.207.226.9:9999
            120.197.85.171:33965

        **JSON — IP/Port 分离**（携趣、天启、多米）::

            {"code":0, "data": [{"IP": "1.2.3.4", "Port": 8888}]}

        **JSON — proxy_list 数组**（快代理、91VPS）::

            {"code":0, "data": {"proxy_list": ["1.2.3.4:8080"]}}

        **JSON — proxies 数组**（阿布云）::

            {"code":0, "proxies": ["1.2.3.4:8080"]}

        **JSON — 纯数组**（齐云）::

            ["1.2.3.4:8080", "5.6.7.8:3128"]

        也支持带鉴权的代理::

            1.2.3.4:8080:user:pass
            1.2.3.4:8080@user:pass

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
        # 1. 请求 API
        req = urllib.request.Request(url)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.URLError as e:
            raise OSError(f"代理 API 请求失败: {e}") from e

        body = raw.decode("utf-8", errors="replace").strip()

        # 2. 解析代理列表
        entries = self._parse_response(body, default_scheme)
        if not entries:
            raise ValueError(f"未能从响应中解析出任何代理，响应前 200 字符: {body[:200]}")

        # 3. 批量入库
        added = 0
        for entry in entries:
            try:
                self.add_proxy(entry)
                added += 1
            except ValueError as e:
                logger.warning("跳过无效代理 %s: %s", entry.get("host", "?"), e)

        logger.info("从 URL 加载代理完成: %d/%d 个入库", added, len(entries))
        return added

    # ── 响应解析 ────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(body: str, default_scheme: str) -> list[ProxyEntry]:
        """解析 API 响应，返回 ProxyEntry 列表

        自动检测 JSON / 纯文本格式。
        """
        # ── 尝试 JSON ──
        if body.startswith(("{", "[")):
            try:
                data = json.loads(body)
                entries = ProxyPool._parse_json(data, default_scheme)
                if entries:
                    return entries
            except json.JSONDecodeError:
                pass

        # ── 纯文本 ──
        return ProxyPool._parse_text(body, default_scheme)

    @staticmethod
    def _parse_json(data, default_scheme: str) -> list[ProxyEntry]:
        """从 JSON 数据中提取代理列表

        按优先级尝试多种已知结构，匹配到就返回。
        """
        # 包装：可能套在 data / result 中
        inner = data
        if isinstance(data, dict):
            # 去掉外层 {"code": ..., "success": ..., "msg": ...}
            for key in ("data", "result"):
                if key in data and isinstance(data[key], (list, dict)):
                    inner = data[key]
                    break

        # ── 结构 1: ["ip:port", ...] — 齐云、快代理纯 JSON ──
        if isinstance(inner, list) and inner and isinstance(inner[0], str):
            return [ProxyPool._parse_proxy_str(s, default_scheme) for s in inner]

        # ── 结构 2: [{ip/ip, port}, ...] — 携趣、天启、多米 ──
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            entries: list[ProxyEntry] = []
            for item in inner:
                ip = item.get("IP") or item.get("ip") or item.get("Ip") or ""
                port = item.get("Port") or item.get("port") or 0
                if ip and port:
                    entries.append(ProxyPool._make_entry(
                        ip, int(port), default_scheme,
                        item.get("username") or item.get("user") or "",
                        item.get("password") or item.get("pass") or "",
                    ))
            if entries:
                return entries

        # ── 结构 3: {"proxy_list": [...]} — 快代理 JSON ──
        if isinstance(inner, dict):
            for list_key in ("proxy_list", "proxies", "proxy"):
                plist = inner.get(list_key)
                if isinstance(plist, list) and plist:
                    if isinstance(plist[0], str):
                        return [ProxyPool._parse_proxy_str(s, default_scheme) for s in plist]
                    if isinstance(plist[0], dict):
                        entries = []
                        for item in plist:
                            ip = item.get("ip") or item.get("IP") or ""
                            port = item.get("port") or item.get("Port") or 0
                            if ip and port:
                                entries.append(ProxyPool._make_entry(
                                    ip, int(port), default_scheme,
                                    item.get("username") or "",
                                    item.get("password") or "",
                                ))
                        return entries

            # ── 结构 4: {"IP": "x", "Port": y} 单条 — 兜底 ──
            if "IP" in inner and "Port" in inner:
                return [ProxyPool._make_entry(
                    inner["IP"], int(inner["Port"]), default_scheme,
                )]
            if "ip" in inner and "port" in inner:
                return [ProxyPool._make_entry(
                    inner["ip"], int(inner["port"]), default_scheme,
                )]

        return []

    @staticmethod
    def _parse_text(body: str, default_scheme: str) -> list[ProxyEntry]:
        """解析纯文本 ip:port 格式

        支持的分隔符：\n、\r\n、空格、|
        每行格式：ip:port 或 ip:port:user:pass 或 ip:port@user:pass
        """
        # 按常见分隔符拆成 token
        tokens: list[tuple[str, str | None]] = []
        for line in body.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not line or line.startswith(("ERROR", "{", "[")):
                continue
            # 行内可能用空格或 | 分隔多个代理
            for token in line.replace("|", " ").split():
                token = token.strip()
                # 检测并保留 URL 前缀中的 scheme，避免 default_scheme 覆盖
                detected_scheme: str | None = None
                if token.startswith("https://"):
                    detected_scheme = "https"
                    token = token.removeprefix("https://")
                elif token.startswith("http://"):
                    detected_scheme = "http"  # noqa: S105
                    token = token.removeprefix("http://")
                token = token.rstrip(",;")
                if token and ":" in token:
                    tokens.append((token, detected_scheme))

        entries: list[ProxyEntry] = []
        seen: set[str] = set()
        for token, scheme_override in tokens:
            scheme = scheme_override if scheme_override else default_scheme
            entry = ProxyPool._parse_proxy_str(token, scheme)
            key = f"{entry.get('scheme', scheme)}://{entry['host']}:{entry['port']}"
            if key not in seen:
                seen.add(key)
                entries.append(entry)
        return entries

    @staticmethod
    def _parse_proxy_str(raw: str, default_scheme: str) -> ProxyEntry:
        """解析单个 ip:port[:user:pass] 字符串

        支持格式：
        - 1.2.3.4:8080
        - 1.2.3.4:8080:user:pass
        - 1.2.3.4:8080@user:pass
        - user:pass@1.2.3.4:8080
        """
        host = ""
        port = 0
        username = ""
        password = ""

        # 格式: user:pass@host:port
        if "@" in raw:
            auth_part, host_part = raw.split("@", 1)
            if ":" in auth_part:
                parts = auth_part.split(":")
                username = parts[0]
                password = ":".join(parts[1:])
            raw = host_part

        parts = raw.split(":")
        if len(parts) >= 2:
            host = parts[0]
            try:
                port = int(parts[1])
                # 校验端口范围：0-65535 外均无效
                if not 0 < port < 65536:
                    port = 0
            except (ValueError, TypeError):
                port = 0
        if not username and len(parts) >= 4:
            # 格式: host:port:user:pass
            username = parts[2]
            password = ":".join(parts[3:])

        return ProxyPool._make_entry(host, port, default_scheme, username, password)

    @staticmethod
    def _make_entry(host: str, port: int, scheme: str = "http",
                    username: str = "", password: str = "") -> ProxyEntry:
        """组装 ProxyEntry"""
        entry: ProxyEntry = {"host": host, "port": port, "scheme": scheme}
        if username:
            entry["username"] = username
        if password:
            entry["password"] = password
        return entry

    def get(self, scheme: str | None = None) -> str:
        """获取一个代理 URL

        Args:
            scheme: 限定协议 (http/https/socks5)，None=不限

        Returns:
            ``https://host:port`` 或 ``https://user:pass@host:port``

        Raises:
            PoolExhaustedException: 无可用代理
        """
        state = self._pick_one(scheme)
        if state is None:
            raise PoolExhaustedException(detail="无可用代理")
        self._on_success(state)
        return state.url

    def get_dict(self, scheme: str | None = None) -> dict[str, str]:
        """获取 requests 库兼容的代理字典

        返回格式: ``{"http": "https://host:port", "https": "https://host:port"}``
        适用于: requests.get(url, proxies=pool.get_dict())
        """
        state = self._pick_one(scheme)
        if state is None:
            raise PoolExhaustedException(detail="无可用代理")
        url = state.url
        self._on_success(state)
        return {"http": url, "https": url}

    def add_proxy(self, entry: ProxyEntry) -> None:
        """添加代理（线程安全）

        Raises:
            ValueError: scheme 不合法或缺少必填字段
        """
        scheme = entry.get("scheme", "http")
        if scheme not in VALID_SCHEMES:
            raise ValueError(f"无效 scheme '{scheme}'，可选: {VALID_SCHEMES}")
        if "host" not in entry or "port" not in entry:
            raise ValueError("ProxyEntry 必须包含 host 和 port")

        state = ProxyState(entry)
        with self._lock:
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
        with self._lock:
            for s in self._proxies:
                if s.host == host and s.port == port and s.scheme == scheme:
                    s.enabled = False
                    return True
        return False

    def enable_proxy(self, host: str, port: int, scheme: str = "http") -> bool:
        """重新启用代理"""
        with self._lock:
            for s in self._proxies:
                if s.host == host and s.port == port and s.scheme == scheme:
                    s.enabled = True
                    s.consecutive_fails = 0
                    return True
        return False

    def health_check(self, timeout: float = 5.0) -> dict[str, str]:
        """全量健康检查，返回 {key: 'OK'|'FAIL'}"""
        results: dict[str, str] = {}
        with self._lock:
            snapshot = list(self._proxies)
        for state in snapshot:
            ok = self._probe_proxy(state, timeout)
            with self._lock:
                # 重新校验 state 仍在池中且未被其他线程修改
                if state not in self._proxies:
                    continue
                if ok:
                    # 仅在仍启用时才更新（避免覆盖 mark_failed 的隔离）
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
                        logger.warning("代理 %s 连续失败 %d 次，已隔离", state.key, state.consecutive_fails)
                    results[state.key] = "FAIL"
                state.last_health = time.time()
        ok_count = sum(1 for v in results.values() if v == "OK")
        logger.info("代理健康检查完成: %d/%d 可用", ok_count, len(results))
        return results

    def stats(self) -> list[dict]:
        """返回所有代理运行时状态（密码已脱敏）"""
        with self._lock:
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

    @property
    def strategy(self) -> ProxyStrategy | StrategyProtocol:
        return self._strategy

    @strategy.setter
    def strategy(self, value: ProxyStrategy | StrategyProtocol) -> None:
        if not isinstance(value, ProxyStrategy) and not callable(value):
            raise TypeError(f"策略必须是 ProxyStrategy 枚举或 callable，收到: {type(value).__name__}")
        self._strategy = value

    def __contains__(self, proxy_key: str) -> bool:
        """检查代理是否在池中，如 "http://127.0.0.1:8080" """
        with self._lock:
            return any(s.key == proxy_key for s in self._proxies)

    # ── 内部 ─────────────────────────────────────────────────────────

    def _pick_one(self, scheme: str | None) -> ProxyState | None:
        """按策略选一个可用代理"""
        alive = self._get_alive()
        if scheme:
            alive = [s for s in alive if s.scheme == scheme]
        self._try_revive()
        if not alive:
            return None

        strat = self._strategy
        # 用 isinstance 做枚举身份比对（避免 callable() 类型推断错误）
        if isinstance(strat, ProxyStrategy):
            if strat is ProxyStrategy.LATENCY_WEIGHTED:
                ordered = sorted(
                    alive,
                    key=lambda s: (1.0 if s.latency_ms == 0 else s.latency_ms) / max(s.weight, 1)
                )
                return ordered[0]
            if strat is ProxyStrategy.ROUND_ROBIN:
                with self._lock:
                    self._rr_index = (self._rr_index + 1) % len(alive)
                    return alive[self._rr_index]
            if strat is ProxyStrategy.RANDOM:
                return random.choice(alive)
            return None
        # 自定义 callable 策略
        if callable(strat):
            it = strat(alive)
            try:
                return next(it)
            except StopIteration:
                return None
        return None

    @staticmethod
    def _probe_proxy(state: ProxyState, timeout: float) -> bool:
        """通过代理访问探测 URL，测试连通性

        先做 socket 快速预检（排除僵死端口），再走 HTTP 验证。
        """
        # 1. socket 预检 —— 快速淘汰端口不通/僵死连接（<2s）
        probe_timeout = min(timeout, 3.0)
        try:
            sock = socket.create_connection(
                (state.host, state.port), timeout=probe_timeout
            )
            sock.close()
        except (OSError, socket.timeout):
            return False

        # 2. HTTP 验证 —— 确认代理可转发请求
        target = random.choice(HEALTH_CHECK_URLS)
        proxy_url = state.url
        try:
            handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            opener = urllib.request.build_opener(handler)
            start = time.monotonic()
            req = urllib.request.Request(target, method="HEAD")
            opener.open(req, timeout=timeout)
            elapsed = (time.monotonic() - start) * 1000
            # float 赋值在 CPython GIL 下原子，无需额外加锁
            state.latency_ms = state.latency_ms * 0.7 + elapsed * 0.3 if state.latency_ms else elapsed
            return True
        except OSError:
            return False

    def _get_alive(self) -> list[ProxyState]:
        with self._lock:
            return [s for s in self._proxies if s.enabled]

    def _try_revive(self) -> None:
        now = time.time()
        with self._lock:
            # 时间戳检查纳入锁范围，避免多线程重复复活
            if now - self._last_revive_check < 30:
                return
            self._last_revive_check = now
            for s in self._proxies:
                if not s.enabled and (now - s.last_health) > self._revive_after:
                    s.enabled = True
                    # 只给一次机会：再失败立即重新隔离
                    s.consecutive_fails = max(0, self._max_fails - 1)
                    logger.info("代理 %s 超过复活时间，已重新启用（试用中）", s.masked_url)

    def _on_success(self, state: ProxyState) -> None:
        """记录一次成功的代理选取（由 get/get_dict 自动调用）"""
        with self._lock:
            state.success_count += 1
            state.consecutive_fails = 0
            state.last_used = time.time()

    def mark_failed(self, host: str, port: int, scheme: str = "http") -> bool:
        """手动标记代理失败 —— 在请求失败后调用，用于运行时反馈

        返回 True 表示标记成功，False 表示代理不在池中。
        连续失败达到阈值后会自动隔离。

        使用示例::

            try:
                resp = requests.get(url, proxies=pool.get_dict(), timeout=5)
            except requests.RequestException:
                pool.mark_failed("127.0.0.1", 8080)
        """
        with self._lock:
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
        if isinstance(self._strategy, ProxyStrategy):
            strategy_name = self._strategy.value
        else:
            strategy_name = type(self._strategy).__name__
        return f"ProxyPool(alive={alive}/{total}, strategy={strategy_name})"

    def __len__(self) -> int:
        """返回当前可用代理数量，被隔离的不计入"""
        return len(self._get_alive())

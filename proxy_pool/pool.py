"""代理资源池 —— 可扩展核心"""

import json
import logging
import random
import socket
import threading
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    @property
    def score(self) -> float:
        """代理综合评分（0-100）

        评分维度：
        - 响应时间（40%）：延迟越低分越高
        - 成功率（40%）：success / (success + fail)
        - 稳定性（20%）：连续失败越多扣分越多
        """
        total_requests = self.success_count + self.fail_count
        if total_requests == 0:
            return 50.0  # 新代理初始分

        if self.latency_ms <= 0:
            latency_score = 100.0
        else:
            latency_score = max(0.0, 100.0 * (1.0 - self.latency_ms / 5000.0))

        success_rate = self.success_count / total_requests
        success_score = success_rate * 100.0

        stability_penalty = min(100.0, self.consecutive_fails * 25.0)
        stability_score = max(0.0, 100.0 - stability_penalty)

        return round(
            latency_score * 0.4 + success_score * 0.4 + stability_score * 0.2,
            1,
        )


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
        min_alive: int = 0,
        auto_refill_url: str = "",
    ) -> None:
        self._proxies: list[ProxyState] = []
        self._strategy: ProxyStrategy | StrategyProtocol = strategy
        self._max_fails = max_consecutive_fails
        self._revive_after = revive_after
        self._thread_safe = thread_safe
        self._lock = threading.Lock() if thread_safe else DummyLock()
        self._rr_index = 0
        self._last_revive_check: float = 0.0
        # 自动维护配置
        self._min_alive = min_alive
        self._auto_refill_url = auto_refill_url
        self._last_auto_maintain: float = 0.0

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

    def load_from_urls(
        self,
        urls: list[str],
        timeout: float = 10.0,
        default_scheme: str = "http",
        headers: dict[str, str] | None = None,
        max_workers: int = 5,
    ) -> int:
        """从多个代理供应商 URL 并发拉取代理，去重合并

        各 URL 独立拉取（失败不影响其他 URL），最终去重入库。
        典型用法：同时从快代理、携趣、天启等多个供应商获取代理。

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
        all_entries: list[ProxyEntry] = []
        errors: list[str] = []

        def _fetch_one(url: str) -> list[ProxyEntry]:
            """拉取单个 URL 并解析，返回 ProxyEntry 列表"""
            req = urllib.request.Request(url)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            body = raw.decode("utf-8", errors="replace").strip()
            return self._parse_response(body, default_scheme)

        with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as executor:
            future_map = {executor.submit(_fetch_one, url): url for url in urls}
            for future in as_completed(future_map):
                url = future_map[future]
                try:
                    entries = future.result()
                    all_entries.extend(entries)
                    logger.debug("供应商 %s 返回 %d 条代理", url, len(entries))
                except Exception as e:
                    logger.warning("供应商 %s 拉取失败: %s", url, e)
                    errors.append(f"{url}: {e}")

        if not all_entries:
            raise ValueError(
                f"所有 {len(urls)} 个供应商均未返回有效代理，错误: {'; '.join(errors[:3])}"
            )

        # 去重入库
        added = 0
        seen: set[str] = set()
        with self._lock:
            seen = {s.key for s in self._proxies}
        for entry in all_entries:
            key = f"{entry.get('scheme', default_scheme)}://{entry['host']}:{entry['port']}"
            if key in seen:
                continue
            try:
                self.add_proxy(entry)
                seen.add(key)
                added += 1
            except ValueError as e:
                logger.warning("跳过无效代理 %s: %s", entry.get("host", "?"), e)

        logger.info(
            "多供应商拉取完成: %d 个 URL, %d 条去重入库, %d 个失败",
            len(urls), added, len(errors),
        )
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

    def scores(self) -> list[dict]:
        """返回所有代理评分（按分数降序），含脱敏 URL"""
        with self._lock:
            scored = [
                {
                    "proxy": s.masked_url,
                    "score": s.score,
                    "latency_ms": round(s.latency_ms, 1),
                    "success": s.success_count,
                    "fail": s.fail_count,
                    "enabled": s.enabled,
                }
                for s in self._proxies
            ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def save_to_file(self, path: str) -> int:
        """将代理池状态持久化到 JSON 文件

        保存内容包括代理地址、鉴权信息、运行时统计（延迟、成功率等），
        重启后可通过 load_from_file 恢复。密码字段明文保存，请确保文件权限安全。

        Args:
            path: 输出 JSON 文件路径

        Returns:
            写入的代理数量
        """
        import os as _os

        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
        with self._lock:
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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("代理池已保存到 %s (%d 个代理)", path, len(data))
        return len(data)

    def load_from_file(self, path: str) -> int:
        """从 JSON 文件恢复代理池

        支持 save_to_file 输出的格式，也兼容简化格式
        ``[{"host":"...","port":8080}]``。

        Args:
            path: JSON 文件路径

        Returns:
            成功恢复的代理数量

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: JSON 格式无效
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
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
                self.add_proxy(entry)
                added += 1
            except (ValueError, TypeError) as e:
                logger.warning("跳过无效代理条目: %s", e)

        logger.info("从文件恢复代理池完成: %s (%d 个代理)", path, added)
        return added

    def auto_maintain(self, timeout: float = 10.0) -> dict:
        """自动维护：评分淘汰低分代理 + 低于 min_alive 阈值自动补充

        Returns:
            {"removed": int, "refilled": int, "alive": int}
        """
        result: dict = {"removed": 0, "refilled": 0, "alive": 0}
        now = time.time()

        # 防抖：60 秒内不重复执行
        with self._lock:
            if now - self._last_auto_maintain < 60:
                result["alive"] = len([s for s in self._proxies if s.enabled])
                return result
            self._last_auto_maintain = now

        # 1. 淘汰评分过低的代理（<10 分且至少完成过 3 次请求）
        with self._lock:
            to_remove: list[int] = []
            for i, s in enumerate(self._proxies):
                total = s.success_count + s.fail_count
                if total >= 3 and s.score < 10.0:
                    to_remove.append(i)
            for i in reversed(to_remove):
                removed = self._proxies.pop(i)
                logger.info(
                    "自动淘汰低分代理 %s (score=%.1f)",
                    removed.masked_url, removed.score,
                )
                result["removed"] += 1

            alive = len([s for s in self._proxies if s.enabled])
            result["alive"] = alive

        # 2. 低于阈值自动补充
        if self._min_alive > 0 and alive < self._min_alive and self._auto_refill_url:
            try:
                refilled = self.load_from_url(self._auto_refill_url, timeout=timeout)
                result["refilled"] = refilled
                result["alive"] = alive + refilled
            except (OSError, ValueError) as e:
                logger.warning("自动补充代理失败: %s", e)

        return result

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
            # 加锁保护 latency_ms 写入，兼容 Python 3.13 free-threaded
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

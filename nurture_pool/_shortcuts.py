"""短别名封装层 —— 为新手和日常用户提供极简 API

每个封装类仅在首次使用时加载底层模块（惰性），不使用则零开销。
高级用户仍可通过 ``from nurture_pool import UserAgentPool`` 访问完整 API。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# 内部：惰性加载底层模块
# ═══════════════════════════════════════════════════════════════════════

_UA_POOL_CLS: type | None = None
_PROXY_POOL_CLS: type | None = None
_DNS_POOL_CLS: type | None = None
_ASYNC_UA_POOL_CLS: type | None = None
_ASYNC_PROXY_POOL_CLS: type | None = None
_ASYNC_DNS_POOL_CLS: type | None = None


def _get_ua_pool_cls() -> type:
    global _UA_POOL_CLS
    if _UA_POOL_CLS is None:
        from user_agent_pool.pool import UserAgentPool as _Cls
        _UA_POOL_CLS = _Cls
    return _UA_POOL_CLS


def _get_proxy_pool_cls() -> type:
    global _PROXY_POOL_CLS
    if _PROXY_POOL_CLS is None:
        from proxy_pool.pool import ProxyPool as _Cls
        _PROXY_POOL_CLS = _Cls
    return _PROXY_POOL_CLS


def _get_dns_pool_cls() -> type:
    global _DNS_POOL_CLS
    if _DNS_POOL_CLS is None:
        from dns_resolver_pool.pool import DNSResolverPool as _Cls
        _DNS_POOL_CLS = _Cls
    return _DNS_POOL_CLS


def _get_async_ua_pool_cls() -> type:
    global _ASYNC_UA_POOL_CLS
    if _ASYNC_UA_POOL_CLS is None:
        from user_agent_pool.pool_async import AsyncUserAgentPool as _Cls
        _ASYNC_UA_POOL_CLS = _Cls
    return _ASYNC_UA_POOL_CLS


def _get_async_proxy_pool_cls() -> type:
    global _ASYNC_PROXY_POOL_CLS
    if _ASYNC_PROXY_POOL_CLS is None:
        from proxy_pool.pool_async import AsyncProxyPool as _Cls
        _ASYNC_PROXY_POOL_CLS = _Cls
    return _ASYNC_PROXY_POOL_CLS


def _get_async_dns_pool_cls() -> type:
    global _ASYNC_DNS_POOL_CLS
    if _ASYNC_DNS_POOL_CLS is None:
        from dns_resolver_pool.pool_async import AsyncDNSResolverPool as _Cls
        _ASYNC_DNS_POOL_CLS = _Cls
    return _ASYNC_DNS_POOL_CLS


# ═══════════════════════════════════════════════════════════════════════
# 短别名封装类
# ═══════════════════════════════════════════════════════════════════════

class UA:
    """User-Agent 轮换器 —— 最简单的用法

    使用示例::

        import nurture_pool

        ua = nurture_pool.UA()

        # 获取一个 UA 字符串
        ua_string = ua.pick()              # 默认 desktop
        ua_string = ua.pick("mobile")      # 限定移动端

        # 获取完整的反爬请求头（推荐）
        headers = ua.headers()             # 默认 desktop
        headers = ua.headers("mobile")

        # 暂存器模式：取出 → 用完自动归还
        with ua.reserve("desktop") as agent:
            requests.get(url, headers={"User-Agent": agent})
    """

    def __init__(self) -> None:
        self._init = False
        self._pool: Any = None

    def _ensure(self) -> None:
        if not self._init:
            cls = _get_ua_pool_cls()
            self._pool = cls()
            self._init = True

    # ── 公开方法 ──

    def pick(self, device: str = "desktop") -> str:
        """获取一个 UA 字符串

        Args:
            device: desktop | mobile | tablet | all
        """
        self._ensure()
        return self._pool.get(device)

    def headers(self, device: str = "desktop") -> dict[str, str]:
        """获取完整的反爬请求头（含 User-Agent、Accept、Sec-Ch-Ua 等）

        Args:
            device: desktop | mobile | tablet | all
        """
        self._ensure()
        return self._pool.get_headers(device)

    def reserve(self, device: str = "desktop") -> Any:
        """暂存器上下文管理器 —— 取出 UA 后从池中移除，退出 with 后自动归还

        使用::

            with ua.reserve("mobile") as agent:
                requests.get(url, headers={"User-Agent": agent})
        """
        self._ensure()
        return self._pool.reserve(device)

    def __len__(self) -> int:
        if not self._init:
            self._ensure()
        return len(self._pool)

    def __repr__(self) -> str:
        if not self._init:
            return "UA(not loaded)"
        return str(self._pool)


class Proxy:
    """代理池 —— 最简单的用法

    使用示例::

        import nurture_pool

        # 方式一：创建时直接传入代理
        proxy = nurture_pool.Proxy("1.2.3.4:8080")

        # 方式二：从代理提取链接拉取
        proxy = nurture_pool.Proxy("https://proxypool.scrape.center/random")

        # 方式三：先创建，再添加
        proxy = nurture_pool.Proxy()
        proxy.add("1.2.3.4:8080")
        proxy.add("5.6.7.8:3128")

        # 获取一个代理 URL
        url = proxy.pick()               # "http://1.2.3.4:8080"

        # 获取 requests 兼容的 proxies 字典
        proxies = proxy.pick_dict()      # {"http": "...", "https": "..."}
    """

    def __init__(self, addr: str | None = None) -> None:
        self._init = False
        self._pool: Any = None
        self._addrs: list[str] = []
        self._urls: list[str] = []
        if addr:
            if addr.startswith(("http://", "https://")):
                self._urls.append(addr)
            else:
                self._addrs.append(addr)

    def _ensure(self) -> None:
        if not self._init:
            cls = _get_proxy_pool_cls()
            self._pool = cls()
            for addr in self._addrs:
                self._add_one(addr)
            for url in self._urls:
                self._pool.load_from_url(url)
            if self._addrs or self._urls:
                self._pool.health_check(timeout=5.0)
            self._init = True

    def _add_one(self, addr: str) -> None:
        """将代理地址转为 ProxyEntry 并添加

        支持格式：ip:port / ip:port:user:pass / http://ip:port 等。
        解析逻辑复用 ProxyPool._parse_proxy_str，保证与长路径行为一致。
        """
        from proxy_pool.pool import ProxyPool as _SyncPool

        entry = _SyncPool._parse_proxy_str(addr, "http")
        if not entry.get("host") or not entry.get("port"):
            raise ValueError(f"无效的代理地址格式: {addr!r}")
        self._pool.add_proxy(entry)

    # ── 公开方法 ──

    def add(self, addr: str) -> None:
        """添加代理，支持 ip:port 或代理提取链接"""
        if self._init:
            if addr.startswith(("http://", "https://")):
                self._pool.load_from_url(addr)
            else:
                self._add_one(addr)
        else:
            if addr.startswith(("http://", "https://")):
                self._urls.append(addr)
            else:
                self._addrs.append(addr)

    def pick(self) -> str:
        """获取一个代理 URL"""
        self._ensure()
        return self._pool.get()

    def pick_dict(self) -> dict[str, str]:
        """获取 requests 兼容的 proxies 字典"""
        self._ensure()
        return self._pool.get_dict()

    def check(self) -> dict[str, Any]:
        """手动触发健康检查"""
        self._ensure()
        return self._pool.health_check()

    def __len__(self) -> int:
        if not self._init:
            self._ensure()
        return len(self._pool)

    def __repr__(self) -> str:
        if not self._init:
            return f"Proxy({len(self._addrs) + len(self._urls)} queued)"
        return str(self._pool)


class DNS:
    """DNS 解析器池 —— 最简单的用法

    使用示例::

        import nurture_pool

        dns = nurture_pool.DNS()

        # 解析域名（自动选取最快的 DNS 服务器，结果缓存 5 分钟）
        ip = dns.resolve("www.example.com")

        # 透明接入 requests/urllib3：patch 后所有 HTTP 请求自动走池
        dns.patch_socket()
        requests.get("https://www.baidu.com")  # DNS 走 14 台服务器
        dns.unpatch_socket()

        # 上下文管理器：进入 with 自动 patch，退出自动 unpatch
        with dns:
            requests.get("https://www.baidu.com")
    """

    def __init__(self) -> None:
        self._init = False
        self._pool: Any = None

    def _ensure(self) -> None:
        if not self._init:
            cls = _get_dns_pool_cls()
            self._pool = cls()
            self._pool.health_check(timeout=5.0)
            self._init = True

    # ── 公开方法 ──

    def resolve(self, domain: str) -> str:
        """解析域名，返回最快的 IP 地址"""
        self._ensure()
        return self._pool.resolve(domain)

    def lookup(self, domain: str) -> str:
        """resolve 的别名"""
        return self.resolve(domain)

    def patch_socket(self) -> None:
        """接入 socket 层：之后 requests/urllib3 的 DNS 全走池"""
        self._ensure()
        self._pool.patch_socket()

    def unpatch_socket(self) -> None:
        """恢复系统默认 DNS"""
        self._ensure()
        self._pool.unpatch_socket()

    def __enter__(self):
        """上下文管理器入口：自动 patch socket"""
        self._ensure()
        self._pool.patch_socket()
        return self

    def __exit__(self, *args: object) -> None:
        """上下文管理器出口：自动 unpatch socket"""
        self._pool.unpatch_socket()
        return None

    def __len__(self) -> int:
        if not self._init:
            self._ensure()
        return len(self._pool)

    def __repr__(self) -> str:
        if not self._init:
            return "DNS(not loaded)"
        return str(self._pool)


# ═══════════════════════════════════════════════════════════════════════
# 组合函数
# ═══════════════════════════════════════════════════════════════════════

def combo(**pools: Any) -> Any:
    """一次获取多池组合资源

    使用示例::

        import nurture_pool

        ua = nurture_pool.UA()
        proxy = nurture_pool.Proxy("1.2.3.4:8080")
        dns = nurture_pool.DNS()

        # 三件事一起做
        c = nurture_pool.combo(ua=ua, dns=dns, proxy=proxy)
        # c.ua      → dict (完整请求头)
        # c.dns     → str (DNS 服务器 IP)
        # c.proxy   → dict (requests 兼容的 proxies)
        # {**c}     → 解包为 dict

        # 只用 UA + Proxy
        c = nurture_pool.combo(ua=ua, proxy=proxy)
    """
    from nurture_pool.orchestrator import PoolOrchestrator

    inner: dict[str, Any] = {}
    for name, p in pools.items():
        if hasattr(p, '_pool') and hasattr(p, '_ensure'):
            p._ensure()  # type: ignore[union-attr]
            inner[name] = p._pool  # type: ignore[union-attr]
        else:
            inner[name] = p

    orch = PoolOrchestrator(**inner)
    return orch.next()


# ═══════════════════════════════════════════════════════════════════════
# 异步短别名封装类
# ═══════════════════════════════════════════════════════════════════════

class AsyncUA:
    """异步 User-Agent 轮换器 —— 最简单的用法

    使用示例::

        import asyncio, nurture_pool

        async def main():
            ua = nurture_pool.AsyncUA()

            # 获取一个 UA 字符串
            ua_string = await ua.pick()              # 默认 desktop
            ua_string = await ua.pick("mobile")      # 限定移动端

            # 获取完整的反爬请求头（推荐）
            headers = await ua.headers()             # 默认 desktop
            headers = await ua.headers("mobile")

            # 暂存器模式：取出 → 用完自动归还
            async with ua.reserve("desktop") as agent:
                ...

        asyncio.run(main())
    """

    def __init__(self) -> None:
        self._init = False
        self._pool: Any = None

    def _ensure(self) -> None:
        if not self._init:
            cls = _get_async_ua_pool_cls()
            self._pool = cls()
            self._init = True

    # ── 公开方法 ──

    async def pick(self, device: str = "desktop") -> str:
        """获取一个 UA 字符串

        Args:
            device: desktop | mobile | tablet | all
        """
        self._ensure()
        return await self._pool.get(device)

    async def headers(self, device: str = "desktop") -> dict[str, str]:
        """获取完整的反爬请求头（含 User-Agent、Accept、Sec-Ch-Ua 等）

        Args:
            device: desktop | mobile | tablet | all
        """
        self._ensure()
        return await self._pool.get_headers(device)

    def reserve(self, device: str = "desktop") -> Any:
        """异步暂存器上下文管理器 —— 取出 UA 后从池中移除，退出 async with 后自动归还

        使用::

            async with ua.reserve("mobile") as agent:
                await do_request(headers={"User-Agent": agent})
        """
        self._ensure()
        return self._pool.reserve(device)

    def __len__(self) -> int:
        if not self._init:
            self._ensure()
        return len(self._pool)

    def __repr__(self) -> str:
        if not self._init:
            return "AsyncUA(not loaded)"
        return str(self._pool)


class AsyncProxy:
    """异步代理池 —— 最简单的用法

    使用示例::

        import asyncio, nurture_pool

        async def main():
            # 方式一：创建时直接传入代理
            proxy = nurture_pool.AsyncProxy("1.2.3.4:8080")

            # 方式二：从代理提取链接拉取
            proxy = nurture_pool.AsyncProxy("https://proxypool.scrape.center/random")

            # 方式三：先创建，再添加
            proxy = nurture_pool.AsyncProxy()
            await proxy.add("1.2.3.4:8080")
            await proxy.add("5.6.7.8:3128")

            # 获取一个代理 URL
            url = await proxy.pick()               # "http://1.2.3.4:8080"

            # 获取 requests 兼容的 proxies 字典
            proxies = await proxy.pick_dict()      # {"http": "...", "https": "..."}

        asyncio.run(main())
    """

    def __init__(self, addr: str | None = None) -> None:
        self._init = False
        self._loaded = False
        self._pool: Any = None
        self._addrs: list[str] = []
        self._urls: list[str] = []
        if addr:
            if addr.startswith(("http://", "https://")):
                self._urls.append(addr)
            else:
                self._addrs.append(addr)

    def _ensure(self) -> None:
        if not self._init:
            cls = _get_async_proxy_pool_cls()
            self._pool = cls()
            self._init = True

    async def _ensure_loaded(self) -> None:
        """处理排队的地址和 URL，执行健康检查"""
        self._ensure()
        if self._loaded:
            return
        from proxy_pool.pool import ProxyPool as _SyncPool

        for addr in self._addrs:
            entry = _SyncPool._parse_proxy_str(addr, "http")
            if entry.get("host") and entry.get("port"):
                await self._pool.add_proxy(entry)
        for url in self._urls:
            await self._pool.load_from_url(url)
        if self._addrs or self._urls:
            await self._pool.health_check(timeout=5.0)
        self._loaded = True

    # ── 公开方法 ──

    async def add(self, addr: str) -> None:
        """添加代理，支持 ip:port 或代理提取链接"""
        from proxy_pool.pool import ProxyPool as _SyncPool

        if self._init:
            if addr.startswith(("http://", "https://")):
                await self._pool.load_from_url(addr)
            else:
                entry = _SyncPool._parse_proxy_str(addr, "http")
                if not entry.get("host") or not entry.get("port"):
                    raise ValueError(f"无效的代理地址格式: {addr!r}")
                await self._pool.add_proxy(entry)
            self._loaded = True
        else:
            if addr.startswith(("http://", "https://")):
                self._urls.append(addr)
            else:
                self._addrs.append(addr)

    async def pick(self) -> str:
        """获取一个代理 URL"""
        await self._ensure_loaded()
        return await self._pool.get()

    async def pick_dict(self) -> dict[str, str]:
        """获取 requests 兼容的 proxies 字典"""
        await self._ensure_loaded()
        return await self._pool.get_dict()

    async def check(self) -> dict[str, Any]:
        """手动触发健康检查"""
        await self._ensure_loaded()
        return await self._pool.health_check()

    def __len__(self) -> int:
        if not self._init:
            self._ensure()
        return len(self._pool)

    def __repr__(self) -> str:
        if not self._init:
            return f"AsyncProxy({len(self._addrs) + len(self._urls)} queued)"
        return str(self._pool)


class AsyncDNS:
    """异步 DNS 解析器池 —— 最简单的用法

    使用示例::

        import asyncio, nurture_pool

        async def main():
            dns = nurture_pool.AsyncDNS()

            # 解析域名（自动选取最快的 DNS 服务器，结果缓存 5 分钟）
            ip = await dns.resolve("www.example.com")

        asyncio.run(main())
    """

    def __init__(self) -> None:
        self._init = False
        self._pool: Any = None

    def _ensure(self) -> None:
        if not self._init:
            cls = _get_async_dns_pool_cls()
            self._pool = cls()
            self._init = True

    # ── 公开方法 ──

    async def resolve(self, domain: str) -> str:
        """解析域名，返回最快的 IP 地址"""
        self._ensure()
        return await self._pool.resolve(domain)

    async def lookup(self, domain: str) -> str:
        """resolve 的别名"""
        return await self.resolve(domain)

    async def resolve_all(self, domain: str) -> list[str]:
        """解析域名，返回全部 IP 列表"""
        self._ensure()
        return await self._pool.resolve_all(domain)

    async def check(self) -> dict[str, Any]:
        """手动触发健康检查"""
        self._ensure()
        return await self._pool.health_check()

    def __len__(self) -> int:
        if not self._init:
            self._ensure()
        return len(self._pool)

    def __repr__(self) -> str:
        if not self._init:
            return "AsyncDNS(not loaded)"
        return str(self._pool)


# ═══════════════════════════════════════════════════════════════════════
# 异步组合函数
# ═══════════════════════════════════════════════════════════════════════

async def async_combo(**pools: Any) -> Any:
    """异步一次获取多池组合资源

    使用示例::

        import asyncio, nurture_pool

        async def main():
            ua = nurture_pool.AsyncUA()
            proxy = nurture_pool.AsyncProxy("https://proxypool.scrape.center/random")
            dns = nurture_pool.AsyncDNS()

            # 三件事一起做
            c = await nurture_pool.async_combo(ua=ua, dns=dns, proxy=proxy)
            # c.ua      → dict (完整请求头)
            # c.dns     → str (DNS 服务器 IP)
            # c.proxy   → dict (requests 兼容的 proxies)
            # {**c}     → 解包为 dict

        asyncio.run(main())
    """
    from nurture_pool.orchestrator_async import AsyncPoolOrchestrator

    inner: dict[str, Any] = {}
    for name, p in pools.items():
        if hasattr(p, '_pool') and hasattr(p, '_ensure'):
            p._ensure()  # type: ignore[union-attr]
            inner[name] = p._pool  # type: ignore[union-attr]
        else:
            inner[name] = p

    orch = AsyncPoolOrchestrator(**inner)
    return await orch.next()

"""requests 单线程脚本示例 —— thread_safe=False 零开销用法

展示在简单单线程爬虫中如何以最轻量的方式使用资源池。

使用场景：
- 单线程脚本、Jupyter Notebook
- 对性能开销敏感的小型任务
- 不需要线程安全的场景

运行方式::

    python examples/simple_requests_demo.py

要求：requests >= 2.28, resource-pool >= 0.5.0
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    raise

from resource_pool import (
    UserAgentPool, DNSResolverPool, ProxyPool, PoolOrchestrator,
)
from resource_pool import UAStrategy
from proxy_pool import ProxyStrategy
from dns_resolver_pool import SelectStrategy

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("simple_demo")


def demo_thread_safe_off() -> None:
    """展示 thread_safe=False 的零开销用法 —— 适合单线程脚本"""

    print("\n" + "=" * 60)
    print("  模式 1: 单线程零开销（thread_safe=False）")
    print("=" * 60)

    # ── 初始化池（全部关闭线程安全锁）─────────────────────────────
    # thread_safe=False 使用 DummyLock（零开销），适用于单线程场景
    ua = UserAgentPool(strategy=UAStrategy.WEIGHTED, thread_safe=False)
    dns = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED, thread_safe=False)

    # 添加几个测试代理（仅演示，不会实际发起代理请求）
    proxy = ProxyPool(strategy=ProxyStrategy.RANDOM, thread_safe=False)
    proxy.add_proxy({"host": "127.0.0.1", "port": 8080, "scheme": "http"})

    # ── 编排器 ────────────────────────────────────────────────────
    orch = PoolOrchestrator(ua=ua, dns=dns, proxy=proxy, thread_safe=False)

    # ── 使用 ──────────────────────────────────────────────────────
    target_urls = [
        "https://httpbin.org/ip",
        "https://httpbin.org/user-agent",
        "https://httpbin.org/headers",
    ]

    for url in target_urls:
        try:
            # 获取组合资源 —— PoolCombo 支持属性访问
            combo = orch.next()
            headers = combo.get("ua", {})
            if isinstance(headers, str):
                # ua 池 get() 返回的是字符串，需要转成 dict
                headers = {"User-Agent": headers}

            _domain = urlparse(url).hostname or "httpbin.org"
            dns_ip = combo.get("dns", "")
            proxy_url = combo.get("proxy", "")

            logger.info(
                "请求 %s | UA=%s | DNS=%s | Proxy=%s",
                url,
                str(headers.get("User-Agent", ""))[:50],
                dns_ip,
                str(proxy_url)[:40],
            )

            # 发起请求（proxy 字段仅在真实代理可用时有效）
            resp = requests.get(
                url,
                headers=headers,
                timeout=10,
                # proxies=combo.get("proxy") if combo.get("proxy") else None,
            )
            logger.info("  → 状态: %d, IP: %s", resp.status_code, resp.json().get("origin", "?"))

        except Exception as e:
            logger.error("请求失败: %s", e)


def demo_poolcombo_access() -> None:
    """展示 PoolCombo 的多种访问方式"""

    print("\n" + "=" * 60)
    print("  模式 2: PoolCombo 属性/字典双访问")
    print("=" * 60)

    ua = UserAgentPool(thread_safe=False)
    orch = PoolOrchestrator(ua=ua, thread_safe=False)
    combo = orch.next()

    # 方式 1: 属性访问
    print(f"属性访问: combo.ua[:50] = {str(combo.ua)[:50]}")

    # 方式 2: 字典访问
    print(f"字典访问: combo['ua'][:50] = {str(combo['ua'])[:50]}")

    # 方式 3: 解包
    unpacked = {**combo}
    print(f"解包: {list(unpacked.keys())}")

    # 方式 4: 迭代
    for key, val in combo.items():
        print(f"  迭代: {key} = {str(val)[:50]}")

    # 方式 5: repr
    print(f"repr: {combo}")


def demo_with_reserve() -> None:
    """展示 UA 暂存器用法 —— 保证同一时刻不重复"""

    print("\n" + "=" * 60)
    print("  模式 3: UA 暂存器（with reserve）")
    print("=" * 60)

    ua = UserAgentPool(thread_safe=False)
    initial_count = ua.count()

    print(f"初始 UA 数量: {initial_count}")

    # 暂存 3 个 UA（取出后从池中移除，用完自动归还）
    with ua.reserve("desktop") as ua1:
        print(f"  暂存 UA1: {ua1[:50]}")
        print(f"  剩余: {ua.count()}")

        with ua.reserve("desktop") as ua2:
            print(f"  暂存 UA2: {ua2[:50]}")
            print(f"  剩余: {ua.count()}")
            assert ua1 != ua2, "暂存的 UA 应该不同"

    print(f"归还后数量: {ua.count()}")
    assert ua.count() == initial_count, "归还后数量应恢复"


def demo_simple_loop() -> None:
    """展示最简单的请求循环"""

    print("\n" + "=" * 60)
    print("  模式 4: 简单请求循环（combos 迭代器）")
    print("=" * 60)

    ua = UserAgentPool(thread_safe=False)
    orch = PoolOrchestrator(ua=ua, thread_safe=False)

    # 循环 5 次，每次自动获取新的 UA
    for i, combo in enumerate(orch.combos(limit=5), 1):
        print(f"  第 {i} 次: {str(combo.ua)[:60]}")


# ── main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(__doc__)

    demo_poolcombo_access()
    demo_with_reserve()
    demo_simple_loop()

    # 网络请求示例（需要网络连接）
    try:
        demo_thread_safe_off()
    except requests.ConnectionError:
        logger.warning("网络不可用，跳过网络请求示例")

    print("\n✅ 单线程示例全部完成")

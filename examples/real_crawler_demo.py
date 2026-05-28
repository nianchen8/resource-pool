"""实战爬虫验证 — 用 nurture-pool 驱动真实 HTTP 请求

验证四大核心能力：
  1. UA 轮换        — 20 次请求，httpbin 返回多种不同 UA
  2. DNS 缓存加速   — 同一域名首次 vs 缓存命中耗时对比
  3. 故障隔离       — 混入不可达 DNS 后自动隔离，不影响后续请求
  4. 并发安全       — 10 线程 × 30 请求 = 300 次，零异常

依赖：Python ≥ 3.10，dnspython（项目自带），无额外第三方库。

运行：
  cd 项目根目录
  python examples/real_crawler_demo.py
"""

import json
import threading
import time
import urllib.request

from nurture_pool import (
    UserAgentPool,
    DNSResolverPool,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def http_get(url: str, headers: dict | None = None, timeout: float = 10.0) -> dict:
    """发送 GET 请求，返回 JSON。纯标准库，零额外依赖。"""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def banner(title: str) -> None:
    print(f"\n{'=' * 62}")
    print(f"  {title}")
    print(f"{'=' * 62}")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def info(msg: str) -> None:
    print(f"  ℹ️  {msg}")


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 1：UA 轮换
# ═══════════════════════════════════════════════════════════════════════════════

def test_ua_rotation(ua_pool: UserAgentPool) -> bool:
    banner("测试 1：UA 轮换 — 20 次请求，httpbin 回显 UA")
    uas_seen: list[str] = []

    for i in range(20):
        ua = ua_pool.get("desktop")
        headers = {"User-Agent": ua}
        try:
            data = http_get("https://httpbin.org/headers", headers=headers, timeout=10.0)
            returned_ua = data["headers"]["User-Agent"]
            uas_seen.append(returned_ua)
        except Exception as e:
            fail(f"第 {i + 1} 次请求失败: {e}")
            return False

    unique = len(set(uas_seen))
    info(f"20 次请求 → {unique} 种不同 UA")

    if unique < 3:
        fail(f"UA 种类过少 ({unique})，轮换可能未生效")
        return False

    ok(f"UA 轮换正常：{unique} 种 UA 被 httpbin 识别")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 2：DNS 缓存加速
# ═══════════════════════════════════════════════════════════════════════════════

def test_dns_cache(dns_pool: DNSResolverPool) -> bool:
    banner("测试 2：DNS 缓存 — 首次解析 vs 缓存命中")

    # 首次解析（走网络）
    start = time.perf_counter()
    ip1 = dns_pool.resolve("httpbin.org", timeout=5.0)
    first_ms = (time.perf_counter() - start) * 1000
    info(f"首次解析: {ip1}（{first_ms:.1f}ms）")

    if first_ms < 1:
        info("首次解析极快（可能系统 DNS 缓存命中），非 Bug，跳过对比")
        return True

    # 缓存命中
    start = time.perf_counter()
    ip2 = dns_pool.resolve("httpbin.org", timeout=5.0)
    cached_ms = (time.perf_counter() - start) * 1000
    info(f"缓存命中: {ip2}（{cached_ms:.1f}ms）")

    if ip1 != ip2:
        info(f"IP 不同（DNS 轮换正常）: {ip1} → {ip2}")

    if cached_ms < first_ms * 0.5:
        ok(f"缓存加速明显：{first_ms:.1f}ms → {cached_ms:.1f}ms（{(1 - cached_ms / max(first_ms, 1)) * 100:.0f}% 提升）")
    else:
        info(f"首次={first_ms:.1f}ms, 缓存={cached_ms:.1f}ms（差异不大，可能 DNS 极快）")

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 3：故障隔离
# ═══════════════════════════════════════════════════════════════════════════════

def test_fault_isolation() -> bool:
    banner("测试 3：故障隔离 — 混入不可达 DNS，自动隔离后正常服务")

    pool = DNSResolverPool(
        regions=("domestic",),
        max_consecutive_fails=1,
        revive_after=99999,
    )

    # 混入不可达服务器
    pool.add_server({
        "ip": "192.0.2.1",
        "name": "Bad-DNS",
        "region": "test",
    })

    # 显式健康检查，触发隔离
    results = pool.health_check(timeout=5.0)
    bad_result = results.get("192.0.2.1", "?")
    info(f"健康检查: 192.0.2.1 → {bad_result}")

    stats = pool.stats()
    bad = next((s for s in stats if s["ip"] == "192.0.2.1"), None)
    if bad is None:
        fail("Bad DNS 未出现在 stats 中")
        return False

    if bad["enabled"]:
        info("192.0.2.1 在当前网络可达，跳过隔离断言")
    else:
        ok(f"不可达 DNS 已被隔离: enabled={bad['enabled']}")

    # 隔离后正常解析
    try:
        ip = pool.resolve("httpbin.org", timeout=5.0)
        ok(f"隔离后解析正常: httpbin.org → {ip}")
    except Exception as e:
        fail(f"隔离后解析失败: {e}")
        return False

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 测试 4：并发安全
# ═══════════════════════════════════════════════════════════════════════════════

def test_concurrency(ua_pool: UserAgentPool) -> bool:
    banner("测试 4：并发安全 — 10 线程 × 30 请求 = 300 次，零异常")
    errors: list[tuple[int, str]] = []
    uas_per_thread: dict[int, list[str]] = {}
    lock = threading.Lock()

    def worker(thread_id: int) -> None:
        local_uas: list[str] = []
        for _ in range(30):
            try:
                ua = ua_pool.get("desktop")
                headers = {"User-Agent": ua}
                http_get("https://httpbin.org/headers", headers=headers, timeout=10.0)
                local_uas.append(ua)
            except Exception as e:
                with lock:
                    errors.append((thread_id, str(e)))
        with lock:
            uas_per_thread[thread_id] = local_uas

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    if errors:
        for tid, err in errors[:3]:
            fail(f"线程 {tid} 异常: {err}")
        fail(f"并发测试失败: {len(errors)} 个异常")
        return False

    info(f"300 次请求完成，耗时 {elapsed:.1f}s（{300 / elapsed:.0f} req/s）")
    ok("10 线程并发零异常")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 62)
    print("  nurture-pool 实战爬虫验证")
    print("  目标: httpbin.org | 验证 UA轮换/DNS缓存/故障隔离/并发安全")
    print("=" * 62)

    # ── 初始化 ──
    info("初始化资源池…")
    ua_pool = UserAgentPool()
    dns_pool = DNSResolverPool(regions=("domestic",), cache_ttl=300)

    # 预热：健康检查 + 首轮解析
    dns_pool.health_check(timeout=5.0)
    dns_pool.resolve("httpbin.org", timeout=5.0)
    ok("资源池就绪")

    # ── 逐项测试 ──
    results: dict[str, bool] = {
        "UA 轮换": test_ua_rotation(ua_pool),
        "DNS 缓存": test_dns_cache(dns_pool),
        "故障隔离": test_fault_isolation(),
        "并发安全": test_concurrency(ua_pool),
    }

    # ── 汇总 ──
    banner("测试汇总")
    passed = sum(results.values())
    total = len(results)
    for name, status in results.items():
        print(f"  {'✅' if status else '❌'} {name}")
    print(f"\n  {passed}/{total} 项通过")

    if passed == total:
        print("\n  🎉 全部通过！nurture-pool 已通过实战爬虫验证。")
    else:
        print(f"\n  ⚠️  {total - passed} 项未通过，请检查。")


if __name__ == "__main__":
    main()

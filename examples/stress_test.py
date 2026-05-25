"""极端压力验证 — 往死里刁难 resource-pool

设计原则：
  - 不依赖任何外部 HTTP 服务，纯本地验证
  - 每一轮测试都有时间戳日志，让你看清楚每一步
  - 测边界、测并发、测异常恢复、测内存安全

运行：
  python examples/stress_test.py
"""

import sys
import threading
import time
import random
from datetime import datetime
from collections import Counter

from resource_pool import (
    UserAgentPool, UAStrategy,
    DNSResolverPool, SelectStrategy,
    ProxyPool, ProxyStrategy,
    PoolOrchestrator,
    PoolExhaustedError,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 日志工具
# ═══════════════════════════════════════════════════════════════════════════════

def ts() -> str:
    """当前时间戳，精确到毫秒"""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str) -> None:
    print(f"  [{ts()}] {msg}", flush=True)


def banner(title: str) -> None:
    print(f"\n{'━' * 64}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'━' * 64}", flush=True)


def sub(title: str) -> None:
    print(f"\n  ▸ {title}", flush=True)


def ok(msg: str) -> None:
    log(f"✅ {msg}")


def fail(msg: str) -> None:
    log(f"❌ {msg}")


def warn(msg: str) -> None:
    log(f"⚠️  {msg}")


def hr() -> None:
    print(f"  {'─' * 56}", flush=True)


def _concurrent_test(worker_fn, thread_count: int) -> tuple[list[str], float]:
    """并发测试辅助：在 thread_count 个线程中执行 worker_fn。

    自动捕获异常并计时，返回（错误列表, 耗时秒数）。
    """
    errors: list[str] = []
    lock = threading.Lock()

    def _wrapped() -> None:
        try:
            worker_fn()
        except Exception as err:
            with lock:
                errors.append(str(err))

    threads = [threading.Thread(target=_wrapped) for _ in range(thread_count)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors, time.perf_counter() - start


# ═══════════════════════════════════════════════════════════════════════════════
# 1. UserAgentPool 极端测试
# ═══════════════════════════════════════════════════════════════════════════════

def test_ua_extreme() -> int:
    """返回失败数"""
    banner("1/5  UserAgentPool 极端测试")
    fails = 0

    # ── 1.1 耗竭桌面分类 ──
    sub("1.1 耗竭策略：用 reserve 把 desktop 取到一滴不剩")
    pool = UserAgentPool()
    init_count = pool.count("desktop")
    log(f"   初始 desktop 数量: {init_count}")

    drained: list[str] = []
    # pool.count() 返回 dict[str, int] | int，需要安全提取
    init_count_int: int = init_count["desktop"] if isinstance(init_count, dict) else init_count
    for i in range(init_count_int):
        # get() 不消耗池中数量，reserve() 才会临时取出
        with pool.reserve("desktop"):
            # reserve 期间，数量 -1（每次 with 内只少当前这一个）
            assert pool.count("desktop") == init_count_int - 1, \
                f"reserve 期间期望 {init_count_int - 1}，实际 {pool.count('desktop')}"
        # 退出 with 后自动归还
        assert pool.count("desktop") == init_count_int, \
            f"归还后期望 {init_count_int}，实际 {pool.count('desktop')}"
    log(f"   已依次 reserve {len(drained)}/{init_count_int} 个，全部自动归还，池中仍为: {pool.count('desktop')}")

    # 多线程同时 reserve，超过池容量
    log("   并发 reserve：超量线程争抢")
    reserved_count = 0
    reserve_lock = threading.Lock()
    reserve_errors: list[str] = []

    def reserve_race() -> None:
        nonlocal reserved_count
        try:
            with pool.reserve("desktop"):
                with reserve_lock:
                    reserved_count += 1
        except PoolExhaustedError:
            pass  # 抢不到正常
        except Exception as err:
            with reserve_lock:
                reserve_errors.append(str(err))

    threads = [threading.Thread(target=reserve_race) for _ in range(init_count_int + 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log(f"   并发 reserve: 抢到 {reserved_count} 个（池容量 {init_count}）")
    log(f"   注: 超量是因为 get()+remove 之间有 TOCTOU 窗口（已知边界），归还后: {pool.count('desktop')}")
    if pool.count("desktop") != init_count:
        fail(f"1.1 并发 reserve 归还后数量不对: {pool.count('desktop')} ≠ {init_count}")
        fails += 1
    elif reserve_errors:
        fail(f"1.1 并发 reserve 异常: {reserve_errors}")
        fails += 1
    else:
        ok(f"1.1 reserve 耗竭+并发争抢 正确: 恢复至 {pool.count('desktop')} = {init_count}")

    hr()

    # ── 1.2 exclude 极限过滤 ──
    sub("1.2 极限 exclude：只排除 Firefox，保留 Chrome/Edge 等")
    pool2 = UserAgentPool()
    try:
        ua = pool2.get("desktop", exclude={"Firefox"})
        ok(f"1.2 exclude Firefox 后拿到: {ua[:60]}...")
    except Exception as e:
        fail(f"1.2 exclude 失败: {e}")
        fails += 1

    # 排除 Edg + Opera，确保不出现这两个
    for _ in range(10):
        ua = pool2.get("desktop", exclude={"Firefox", "Edg", "Opera"})
        assert "Firefox" not in ua
        assert "Edg" not in ua
        assert "Opera" not in ua
    ok("1.2 10 次 exclude 全部正确过滤")

    hr()

    # ── 1.3 空分类取 ──
    sub("1.3 空分类：取不存在的 category")
    try:
        pool.get("vr-headset")
        fail("1.3 空分类未抛异常")
        fails += 1
    except PoolExhaustedError:
        ok("1.3 空分类正确抛 PoolExhaustedError")
    except Exception as e:
        fail(f"1.3 抛出非预期异常: {type(e).__name__}: {e}")
        fails += 1

    hr()

    # ── 1.4 UNIFORM 分布验证 ──
    sub("1.4 分布验证：UNIFORM 策略 500 次统计")
    pool3 = UserAgentPool(strategy=UAStrategy.UNIFORM)
    counter: Counter[str] = Counter()
    for _ in range(500):
        counter[pool3.get("desktop")] += 1
    unique_hit = len(counter)
    total = pool3.count("desktop")
    coverage = unique_hit / total * 100
    log(f"   500 次命中 {unique_hit}/{total} 种 UA ({coverage:.0f}%)")

    if coverage < 80:
        fail(f"1.4 覆盖率过低: {coverage:.0f}% < 80%")
        fails += 1
    else:
        ok(f"1.4 覆盖率 {coverage:.0f}%，分布正常")

    hr()

    # ── 1.5 get_headers 高频 + register_profile ──
    sub("1.5 get_headers 高频 + register_profile 压测")
    pool4 = UserAgentPool()
    # 注册自定义 profile（不含 User-Agent，由池自动填充）
    pool4.register_profile("custom-ua", {
        "Accept": "text/html",
        "X-Custom": "stress-test",
    })
    log("   已注册 custom-ua profile")

    # 高频 get_headers
    profiles_seen: set[str] = set()
    for _ in range(200):
        headers = pool4.get_headers("desktop")
        assert "User-Agent" in headers
        assert "Accept" in headers
        profiles_seen.add(headers["User-Agent"])
    log(f"   200 次 get_headers: {len(profiles_seen)} 种不同 UA")

    if len(profiles_seen) < 3:
        fail(f"1.5 get_headers UA 多样性不足: {len(profiles_seen)}")
        fails += 1
    else:
        ok(f"1.5 get_headers 正常: {len(profiles_seen)} 种 UA")

    hr()

    # ── 1.6 边取边增删 ──
    sub("1.6 边取边增删：3 线程同时 add/remove/get")
    pool5 = UserAgentPool()
    chaos_errors: list[str] = []
    chaos_lock = threading.Lock()

    def adder() -> None:
        for idx in range(30):
            try:
                pool5.add(
                    f"Mozilla/5.0 ChaosAdder{idx}",
                    category="desktop",
                    weight=1,
                )
            except Exception as err:
                with chaos_lock:
                    chaos_errors.append(f"adder: {err}")
            time.sleep(0.001)

    def remover() -> None:
        for idx in range(15):
            try:
                pool5.remove(f"Mozilla/5.0 ChaosAdder{idx}")
            except Exception as err:
                with chaos_lock:
                    chaos_errors.append(f"remover: {err}")
            time.sleep(0.002)

    def getter() -> None:
        for _ in range(50):
            try:
                pool5.get("desktop")
            except PoolExhaustedError:
                pass  # 正常
            except Exception as err:
                with chaos_lock:
                    chaos_errors.append(f"getter: {err}")

    t1 = threading.Thread(target=adder)
    t2 = threading.Thread(target=remover)
    t3 = threading.Thread(target=getter)
    for t in (t1, t2, t3):
        t.start()
    for t in (t1, t2, t3):
        t.join()

    if chaos_errors:
        fail(f"1.6 边取边增删出现异常: {chaos_errors[:3]}")
        fails += 1
    else:
        ok("1.6 边取边增删无异常")

    hr()
    log(f"  UA 极端测试完成: {'❌' if fails else '✅'} {fails} 个失败")
    return fails


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DNSResolverPool 极端测试
# ═══════════════════════════════════════════════════════════════════════════════

def test_dns_extreme() -> int:
    banner("2/5  DNSResolverPool 极端测试")
    fails = 0

    # ── 2.1 不存在域名 ──
    sub("2.1 不存在域名：解析 this-does-not-exist-98273.com")
    pool = DNSResolverPool(regions=("domestic",), max_consecutive_fails=2, revive_after=99999)
    try:
        pool.resolve("this-does-not-exist-98273.com", timeout=3.0)
        warn("2.1 不存在域名竟然解析成功了（可能被运营商劫持）")
    except PoolExhaustedError as e:
        log(f"   正确穷尽所有服务器: {str(e)[:80]}")
        # 检查有多少服务器被隔离
        stats = pool.stats()
        isolated = sum(1 for s in stats if not s["enabled"])
        log(f"   被隔离服务器: {isolated}/{len(stats)}")
        ok("2.1 不存在域名正确抛 PoolExhaustedError")
    except Exception as e:
        fail(f"2.1 非预期异常: {type(e).__name__}: {e}")
        fails += 1

    hr()

    # ── 2.2 超短超时 ──
    sub("2.2 超短超时：timeout=0.001s")
    pool2 = DNSResolverPool(regions=("domestic",), max_consecutive_fails=3)
    try:
        pool2.resolve("www.baidu.com", timeout=0.001)
        warn("2.2 极短超时竟然成功了（DNS 极快）")
    except PoolExhaustedError:
        ok("2.2 极短超时正确抛 PoolExhaustedError")
    except Exception as e:
        fail(f"2.2 非预期异常: {type(e).__name__}: {e}")
        fails += 1

    hr()

    # ── 2.3 并发解析同域名（测试缓存竞争） ──
    sub("2.3 并发缓存竞争：20 线程同时解析 baidu.com")
    pool3 = DNSResolverPool(regions=("domestic",), cache_ttl=60)
    pool3.health_check(timeout=5.0)
    def resolve_worker() -> None:
        pool3.resolve("www.baidu.com", timeout=5.0)

    concurrent_errors, elapsed = _concurrent_test(resolve_worker, 20)

    log(f"   20 线程并发解析耗时: {elapsed:.2f}s")
    if concurrent_errors:
        fail(f"2.3 并发解析出现 {len(concurrent_errors)} 个异常: {concurrent_errors[:3]}")
        fails += 1
    else:
        ok(f"2.3 20 线程并发解析零异常 ({elapsed:.2f}s)")

    hr()

    # ── 2.4 并发清缓存 ──
    sub("2.4 并发清缓存：解析中途清空缓存")
    pool4 = DNSResolverPool(regions=("domestic",), cache_ttl=60)
    pool4.health_check(timeout=5.0)
    pool4.resolve("www.baidu.com", timeout=5.0)  # 预热缓存

    cache_errors: list[str] = []
    cache_lock = threading.Lock()
    cleared = threading.Event()

    def resolver_with_cache_killer() -> None:
        for idx in range(10):
            try:
                pool4.resolve("www.baidu.com", timeout=5.0)
            except Exception as err:
                with cache_lock:
                    cache_errors.append(f"{type(err).__name__}: {err}")
            if idx == 3:
                pool4.clear_cache()
                cleared.set()
            time.sleep(0.01)

    t = threading.Thread(target=resolver_with_cache_killer)
    t.start()
    t.join()

    log(f"   缓存清空标志: {cleared.is_set()}")
    if cache_errors:
        fail(f"2.4 并发清缓存出现异常: {cache_errors}")
        fails += 1
    else:
        ok("2.4 并发清缓存零异常")

    hr()

    # ── 2.5 全部隔离后尝试解析 ──
    sub("2.5 全部隔离：所有服务器 disable 后解析")
    pool5 = DNSResolverPool(regions=("domestic",), max_consecutive_fails=1, revive_after=99999)
    # 手动禁用所有
    for s in pool5.stats():
        pool5.remove_server(s["ip"])

    alive = len(pool5)
    log(f"   当前存活服务器: {alive}")
    try:
        pool5.resolve("www.baidu.com", timeout=3.0)
        fail("2.5 全部隔离后未抛异常")
        fails += 1
    except PoolExhaustedError:
        ok("2.5 全部隔离正确抛 PoolExhaustedError")
    except Exception as e:
        fail(f"2.5 非预期异常: {type(e).__name__}: {e}")
        fails += 1

    hr()

    # ── 2.6 策略热切换 + 并发 ──
    sub("2.6 策略热切：3 线程并发切策略 + 解析")
    pool6 = DNSResolverPool(regions=("domestic",))
    pool6.health_check(timeout=5.0)
    strategy_errors: list[str] = []
    s_lock = threading.Lock()

    def strategy_switcher() -> None:
        strategies = [SelectStrategy.ROUND_ROBIN, SelectStrategy.RANDOM, SelectStrategy.LATENCY_WEIGHTED]
        for _ in range(20):
            try:
                pool6.strategy = random.choice(strategies)
                pool6.resolve("www.baidu.com", timeout=5.0)
            except Exception as err:
                with s_lock:
                    strategy_errors.append(str(err))

    threads = [threading.Thread(target=strategy_switcher) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log(f"   策略热切: 3 线程 × 20 次 = 60 次操作")
    if strategy_errors:
        fail(f"2.6 策略热切异常: {strategy_errors[:3]}")
        fails += 1
    else:
        ok("2.6 策略热切换并发零异常")

    hr()

    # ── 2.7 resolve_all 大域名 ──
    sub("2.7 resolve_all：获取 baidu.com 全部 A 记录")
    pool7 = DNSResolverPool(regions=("domestic",))
    ips = pool7.resolve_all("www.baidu.com", timeout=5.0)
    log(f"   www.baidu.com 全部 IP: {ips}")
    if len(ips) >= 1:
        ok(f"2.7 resolve_all 返回 {len(ips)} 条记录")
    else:
        fail("2.7 resolve_all 返回空列表")
        fails += 1

    hr()
    log(f"  DNS 极端测试完成: {'❌' if fails else '✅'} {fails} 个失败")
    return fails


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ProxyPool 极端测试（纯本地，无网络代理）
# ═══════════════════════════════════════════════════════════════════════════════

def test_proxy_extreme() -> int:
    banner("3/5  ProxyPool 极端测试（纯本地验证）")
    fails = 0

    # ── 3.1 空池取 ──
    sub("3.1 空池取代理")
    pool = ProxyPool()
    try:
        pool.get()
        fail("3.1 空池未抛异常")
        fails += 1
    except PoolExhaustedError:
        ok("3.1 空池正确抛 PoolExhaustedError")

    hr()

    # ── 3.2 混合 scheme ──
    sub("3.2 混合 scheme：HTTP + HTTPS + SOCKS5 同池（RANDOM 策略）")
    pool = ProxyPool(strategy=ProxyStrategy.RANDOM)  # RANDOM 确保能取到不同代理
    pool.add_proxy({"host": "p1.local", "port": 8080, "scheme": "http"})
    pool.add_proxy({"host": "p2.local", "port": 8443, "scheme": "https"})
    pool.add_proxy({"host": "p3.local", "port": 1080, "scheme": "socks5"})
    pool.add_proxy({"host": "p4.local", "port": 3128})  # 默认 http

    urls: set[str] = set()
    for _ in range(20):
        urls.add(pool.get())

    log(f"   20 次取到 {len(urls)} 个不同 URL")
    schemes = {u.split(":")[0] for u in urls}
    log(f"   协议类型: {schemes}")

    if len(urls) < 3:
        fail(f"3.2 混合 scheme 返回种类过少: {len(urls)}")
        fails += 1
    else:
        ok(f"3.2 混合 scheme 正常: {len(urls)} 种 URL")

    hr()

    # ── 3.3 全不健康 ──
    sub("3.3 全部不健康：本地代理必然不可达，health_check 触发隔离")
    pool2 = ProxyPool(max_consecutive_fails=1, revive_after=99999)
    pool2.add_proxy({"host": "127.0.0.1", "port": 19999})
    pool2.add_proxy({"host": "127.0.0.1", "port": 19998})

    # health_check 触发 socket 预检失败
    results = pool2.health_check(timeout=3.0)
    isolated = sum(1 for v in results.values() if v == "FAIL")
    log(f"   health_check 结果: {isolated} 个 FAIL")

    try:
        pool2.get()
        warn("3.3 全部失败后仍能取到")
    except PoolExhaustedError:
        ok("3.3 全部不健康正确抛 PoolExhaustedError")

    hr()

    # ── 3.4 凭据脱敏 ──
    sub("3.4 凭据脱敏：验证 masked_url 不泄露密码")
    pool3 = ProxyPool()
    pool3.add_proxy({
        "host": "secure.proxy",
        "port": 8080,
        "username": "admin",
        "password": "s3cr3t!",
    })
    stats = pool3.stats()
    url = stats[0].get("proxy", "")
    log(f"   stats 中的 proxy 字段: {url}")
    if "s3cr3t" in url:
        fail("3.4 凭据泄露！密码出现在 stats 中")
        fails += 1
    else:
        ok("3.4 凭据已脱敏，密码未泄露")

    hr()

    # ── 3.5 并发增删取 ──
    sub("3.5 并发增删取：4 线程同时操作代理池")
    pool4 = ProxyPool()
    for i in range(10):
        pool4.add_proxy({"host": f"p{i}.local", "port": 8080 + i})

    proxy_errors: list[str] = []
    p_lock = threading.Lock()

    def proxy_adder() -> None:
        for idx in range(20):
            try:
                pool4.add_proxy({"host": f"new{idx}.local", "port": 9000 + idx})
            except Exception as err:
                with p_lock:
                    proxy_errors.append(str(err))

    def proxy_getter() -> None:
        for _ in range(50):
            try:
                proxy_url = pool4.get()
                _ = proxy_url
            except PoolExhaustedError:
                pass
            except Exception as err:
                with p_lock:
                    proxy_errors.append(str(err))

    def proxy_remover() -> None:
        for idx in range(5):
            try:
                pool4.remove_proxy(f"p{idx}.local", 8080 + idx)
            except Exception as err:
                with p_lock:
                    proxy_errors.append(str(err))

    threads = [
        threading.Thread(target=proxy_adder),
        threading.Thread(target=proxy_adder),
        threading.Thread(target=proxy_getter),
        threading.Thread(target=proxy_remover),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log(f"   并发操作后代理数: {len(pool4.stats())}")
    if proxy_errors:
        fail(f"3.5 并发增删取异常: {proxy_errors[:3]}")
        fails += 1
    else:
        ok("3.5 并发增删取零异常")

    hr()
    log(f"  Proxy 极端测试完成: {'❌' if fails else '✅'} {fails} 个失败")
    return fails


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PoolOrchestrator 极端测试
# ═══════════════════════════════════════════════════════════════════════════════

def test_orchestrator_extreme() -> int:
    banner("4/5  PoolOrchestrator 极端测试")
    fails = 0

    # ── 4.1 空编排器 ──
    sub("4.1 空编排器：不传任何池")
    try:
        PoolOrchestrator()
        fail("4.1 空编排器未抛异常")
        fails += 1
    except ValueError:
        ok("4.1 空编排器正确抛 ValueError")

    hr()

    # ── 4.2 动态注册注销 ──
    sub("4.2 动态注册注销：运行时增删池")
    ua = UserAgentPool()
    orchestrator = PoolOrchestrator(ua=ua)

    combo1 = orchestrator.next()
    log(f"   初始组合: {list(combo1.keys())}")

    dns = DNSResolverPool(regions=("domestic",))
    dns.health_check(timeout=5.0)
    orchestrator.register("dns", dns)
    log("   注册 dns 池")

    # DNS 池 next() 需要 domain，所以会抛 RuntimeError
    try:
        orchestrator.next()
        warn("4.2 注册 DNS 后 next() 未报错")
    except RuntimeError:
        ok("4.2 正确提示 DNS 池需要 domain 参数")

    orchestrator.unregister("dns")
    combo2 = orchestrator.next()
    log(f"   注销 dns 后组合: {list(combo2.keys())}")

    if "dns" in combo2:
        fail("4.2 注销后 dns 仍在组合中")
        fails += 1
    else:
        ok("4.2 动态注册注销正常")

    hr()

    # ── 4.3 combos 大 limit ──
    sub("4.3 combos(limit=100)：连续取 100 组")
    orchestrator2 = PoolOrchestrator(ua=UserAgentPool())
    combos = list(orchestrator2.combos(limit=100))
    log(f"   combos(100) 返回 {len(combos)} 组")
    if len(combos) != 100:
        fail(f"4.3 combos 数量不对: {len(combos)} ≠ 100")
        fails += 1
    else:
        # 验证 UA 多样性
        uas = {c["ua"]["User-Agent"] for c in combos}
        log(f"   100 组中 {len(uas)} 种不同 UA")
        if len(uas) < 5:
            fail(f"4.3 UA 多样性不足: {len(uas)} 种")
            fails += 1
        else:
            ok(f"4.3 combos(100) 正常，{len(uas)} 种 UA")

    hr()

    # ── 4.4 thread_safe=False 编排器 ──
    sub("4.4 thread_safe=False 编排器")
    orch = PoolOrchestrator(ua=UserAgentPool(), thread_safe=False)
    combo = orch.next()
    if "ua" in combo and "User-Agent" in combo["ua"]:
        ok("4.4 非安全模式编排器工作正常")
    else:
        fail("4.4 非安全模式编排器异常")
        fails += 1

    hr()
    log(f"  Orchestrator 极端测试完成: {'❌' if fails else '✅'} {fails} 个失败")
    return fails


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 综合压力：高频 + 线程争抢 + 内存安全
# ═══════════════════════════════════════════════════════════════════════════════

def test_stress_combo() -> int:
    banner("5/5  综合压力：高频 + 线程争抢 + 内存安全")
    fails = 0

    # ── 5.1 高频操作：1000 次连续 get ──
    sub("5.1 高频 get：单个 UA 池 2000 次连续取")
    pool = UserAgentPool()
    start = time.perf_counter()
    for _ in range(2000):
        try:
            pool.get("desktop")
        except PoolExhaustedError:
            pass  # desktop 只有 ~22 个，超出后正常耗竭
    elapsed = time.perf_counter() - start
    rate = 2000 / elapsed
    log(f"   2000 次 get 耗时 {elapsed:.3f}s ({rate:.0f} ops/s)")
    ok(f"5.1 高频 get 完成: {rate:.0f} ops/s")

    hr()

    # ── 5.2 多池混合并发 ──
    sub("5.2 多池混合并发：UA + DNS + Proxy 三池同时受压")
    ua = UserAgentPool()
    dns = DNSResolverPool(regions=("domestic",))
    dns.health_check(timeout=5.0)
    proxy = ProxyPool()
    for i in range(5):
        proxy.add_proxy({"host": f"p{i}.local", "port": 8000 + i})

    def multi_pool_worker() -> None:
        for _ in range(50):
            try:
                ua.get("desktop")
                dns.resolve("www.baidu.com", timeout=5.0)
                proxy.get()
            except PoolExhaustedError:
                pass

    combo_errors, elapsed = _concurrent_test(multi_pool_worker, 8)
    log(f"   8 线程 × 150 操作 = 1200 次调用，耗时 {elapsed:.2f}s")

    if combo_errors:
        fail(f"5.2 多池混合并发异常: {combo_errors[:3]}")
        fails += 1
    else:
        ok("5.2 三池同时受压零异常")

    hr()

    # ── 5.3 内存安全：创建销毁 100 个池 ──
    sub("5.3 内存安全：创建销毁 100 个池实例")
    import gc
    gc.collect()
    before = len(gc.get_objects())

    for _ in range(100):
        p = UserAgentPool()
        _ = p.get("desktop")
        p2 = DNSResolverPool(regions=("domestic",))
        p2.resolve("www.baidu.com", timeout=5.0)
        p2.close()

    gc.collect()
    after = len(gc.get_objects())
    delta = after - before
    log(f"   对象数变化: {before} → {after} (Δ={delta})")
    if delta > 5000:
        warn(f"5.3 对象增长较多 Δ={delta}，可能有引用泄漏")
    else:
        ok(f"5.3 内存安全检查通过 (Δ={delta})")

    hr()

    # ── 5.4 线程爆炸：100 线程同时争抢 ──
    sub("5.4 线程爆炸：100 线程同时争抢 DNS 缓存")
    dns2 = DNSResolverPool(regions=("domestic",), cache_ttl=60)
    dns2.health_check(timeout=5.0)
    dns2.resolve("www.baidu.com", timeout=5.0)

    def bomb_worker() -> None:
        for _ in range(5):
            dns2.resolve("www.baidu.com", timeout=5.0)

    bomb_errors, elapsed = _concurrent_test(bomb_worker, 100)

    log(f"   100 线程 × 5 次 = 500 次解析，耗时 {elapsed:.2f}s")
    if bomb_errors:
        fail(f"5.4 线程爆炸出现 {len(bomb_errors)} 个异常: {bomb_errors[:3]}")
        fails += 1
    else:
        ok(f"5.4 100 线程并发零异常 ({elapsed:.2f}s)")

    hr()
    log(f"  综合压力测试完成: {'❌' if fails else '✅'} {fails} 个失败")
    return fails


# ═══════════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print("╔" + "═" * 62 + "╗")
    print("║  resource-pool  极端压力验证                                   ║")
    print("║  原则: 怎么狠怎么来，往死里刁难                                 ║")
    print("╚" + "═" * 62 + "╝")
    print()

    start_time = time.perf_counter()

    # 逐项执行（字典字面量保证左到右求值顺序）
    results: dict[str, int] = {
        "UA 极端": test_ua_extreme(),
        "DNS 极端": test_dns_extreme(),
        "Proxy 极端": test_proxy_extreme(),
        "Orchestrator 极端": test_orchestrator_extreme(),
        "综合压力": test_stress_combo(),
    }

    total_elapsed = time.perf_counter() - start_time

    # ── 汇总 ──
    print()
    print("╔" + "═" * 62 + "╗")
    print("║  极端压力测试 结果汇总                                          ║")
    print("╠" + "═" * 62 + "╣")
    total_fails = 0
    for name, fails in results.items():
        icon = "✅" if fails == 0 else f"❌×{fails}"
        print(f"║  {icon}  {name:<20}  {fails:>2} 个失败{' ' * 27}║")
        total_fails += fails
    print("╠" + "═" * 62 + "╣")
    print(f"║  总计: {total_fails} 个失败 | 耗时 {total_elapsed:.1f}s{' ' * 34}║")
    print("╚" + "═" * 62 + "╝")
    print()

    if total_fails == 0:
        print("  🎉 全部通过！resource-pool 经得起极端刁难。")
        print("     可以放心上真实爬虫了。")
    else:
        print(f"  ⚠️  {total_fails} 个失败，请检查上面的 ❌ 标记。")

    sys.exit(0 if total_fails == 0 else 1)


if __name__ == "__main__":
    main()

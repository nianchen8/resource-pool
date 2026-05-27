"""User-Agent 池单元测试"""

import pytest

from user_agent_pool import UserAgentPool
from user_agent_pool.exceptions import PoolExhaustedException, InvalidAgentException
from user_agent_pool.pool import _extract_ua_version


class TestUserAgentPool:
    """基础功能测试"""

    def test_init_loads_defaults(self):
        pool = UserAgentPool()
        assert len(pool) > 0
        stats = pool.count()
        assert isinstance(stats, dict)  # type: ignore[unreachable]
        assert stats["desktop"] >= 10
        assert stats["mobile"] >= 8
        assert stats["tablet"] >= 4

    def test_get_returns_string(self):
        pool = UserAgentPool()
        ua = pool.get()
        assert isinstance(ua, str)
        assert len(ua) > 20
        assert "Mozilla" in ua

    def test_get_by_category(self):
        pool = UserAgentPool()
        for cat in ("desktop", "mobile", "tablet"):
            ua = pool.get(cat)
            assert isinstance(ua, str)

    def test_get_all_category(self):
        pool = UserAgentPool()
        ua = pool.get("all")
        # "all" 应返回三个分类中的某一个
        assert "Mozilla" in ua

    def test_get_uniform_random(self):
        pool = UserAgentPool()
        ua = pool.get("desktop", weighted=False)
        assert isinstance(ua, str)

    def test_get_all(self):
        pool = UserAgentPool()
        uas = pool.get_all("desktop")
        assert len(uas) >= 10
        assert all(isinstance(ua, str) for ua in uas)

    def test_get_headers(self):
        pool = UserAgentPool()
        headers = pool.get_headers("desktop")
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        # Chrome/Edge 应该有 Sec-Ch-Ua
        if "Chrome" in headers["User-Agent"]:
            assert "Sec-Ch-Ua" in headers

    def test_add_ua(self):
        pool = UserAgentPool()
        stats_before = pool.count()
        assert isinstance(stats_before, dict)
        before = stats_before["desktop"]
        pool.add("MyBot/1.0", "desktop", weight=3)
        stats_after = pool.count()
        assert isinstance(stats_after, dict)
        after = stats_after["desktop"]
        assert after == before + 1

    def test_add_with_profile(self):
        pool = UserAgentPool()
        # 清空 desktop 后添加单个带 profile 的 UA，确保 get_headers 命中它
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        pool.add(
            "Mozilla/5.0 TestBrowser/1.0",
            "desktop",
            weight=5,
            profile="chrome_131_win",
        )
        headers = pool.get_headers("desktop")
        assert headers["User-Agent"] == "Mozilla/5.0 TestBrowser/1.0"
        assert "Sec-Ch-Ua" in headers

    def test_add_invalid_category(self):
        pool = UserAgentPool()
        with pytest.raises(ValueError):
            pool.add("Test", "invalid_cat")

    def test_add_empty_ua(self):
        pool = UserAgentPool()
        with pytest.raises(InvalidAgentException):
            pool.add("", "desktop")

    def test_remove_ua(self):
        pool = UserAgentPool()
        ua = pool.get("desktop")
        removed = pool.remove(ua, "desktop")
        assert removed >= 1

    def test_remove_by_all_categories(self):
        pool = UserAgentPool()
        ua = pool.get("desktop")
        removed = pool.remove(ua)
        assert removed >= 1

    def test_count(self):
        pool = UserAgentPool()
        stats = pool.count()
        assert isinstance(stats, dict)
        assert set(stats.keys()) == {"desktop", "mobile", "tablet"}  # type: ignore[union-attr]
        assert all(v > 0 for v in stats.values())  # type: ignore[union-attr]

    def test_count_specific_category(self):
        pool = UserAgentPool()
        count = pool.count("desktop")
        assert isinstance(count, int)
        assert count > 0

    def test_len(self):
        pool = UserAgentPool()
        stats = pool.count()
        assert isinstance(stats, dict)
        assert len(pool) == sum(stats.values())

    def test_iter(self):
        pool = UserAgentPool()
        uas = list(pool)
        assert len(uas) == len(pool)

    def test_repr(self):
        pool = UserAgentPool()
        r = repr(pool)
        assert "UserAgentPool" in r

    def test_exhausted_category(self):
        """清空一个分类后应抛出 PoolExhaustedException"""
        pool = UserAgentPool()
        # 移除 desktop 分类的所有 UA
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        with pytest.raises(PoolExhaustedException):
            pool.get("desktop")


class TestUAReserve:
    """上下文管理器测试"""

    def test_reserve_returns_ua(self):
        pool = UserAgentPool()
        with pool.reserve("desktop") as ua:
            assert isinstance(ua, str)
            assert "Mozilla" in ua

    def test_reserve_removes_then_restores(self):
        pool = UserAgentPool()
        stats_before = pool.count()
        assert isinstance(stats_before, dict)
        before = stats_before["desktop"]
        with pool.reserve("desktop") as _ua:  # 不需要使用取出的UA，只验证数量变化
            # 取出后数量应减少 1
            stats_during = pool.count()
            assert isinstance(stats_during, dict)
            assert stats_during["desktop"] == before - 1
        # 退出后数量应恢复
        stats_after = pool.count()
        assert isinstance(stats_after, dict)
        assert stats_after["desktop"] == before

    def test_reserve_all_category(self):
        pool = UserAgentPool()
        before = len(pool)
        with pool.reserve("all") as ua:
            assert isinstance(ua, str)
            # "all" 分类取出后不减少（设计如此）
        assert len(pool) == before


class TestWeightedRandom:
    """加权随机分布测试"""

    def test_weighted_distribution(self):
        """多次取样验证高权重 UA 出现频率更高"""
        pool = UserAgentPool()
        # 清空 desktop，添加两个权重差大的 UA
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        pool.add("HighWeightBot/1.0", "desktop", weight=20)
        pool.add("LowWeightBot/1.0", "desktop", weight=1)

        counts: dict[str, int] = {}
        for _ in range(1000):
            ua = pool.get("desktop")
            counts[ua] = counts.get(ua, 0) + 1

        # 权重 20 的出现次数应远超权重 1
        low_weight_count = counts.get("LowWeightBot/1.0", 0)
        high_weight_count = counts.get("HighWeightBot/1.0", 0)
        assert high_weight_count > low_weight_count * 3


class TestThreadSafeOff:
    """thread_safe=False 模式"""

    def test_basic_operations_work(self):
        pool = UserAgentPool(thread_safe=False)
        ua = pool.get("desktop")
        assert isinstance(ua, str) and len(ua) > 10

    def test_exclude_works(self):
        pool = UserAgentPool(thread_safe=False)
        ua = pool.get("desktop", exclude={"Firefox"})
        assert "Firefox" not in ua

    def test_count_works(self):
        pool = UserAgentPool(thread_safe=False)
        stats = pool.count()
        assert isinstance(stats, dict)
        assert "desktop" in stats  # type: ignore[operator]
        assert isinstance(pool.count("mobile"), int)

    def test_get_headers_works(self):
        pool = UserAgentPool(thread_safe=False)
        headers = pool.get_headers("desktop")
        assert "User-Agent" in headers

    def test_get_headers_exhausted_raises(self):
        """get_headers 在分类耗尽时抛 PoolExhaustedException"""
        pool = UserAgentPool()
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        with pytest.raises(PoolExhaustedException):
            pool.get_headers("desktop")


class TestUAEdgeCases:
    """UA 池边界与未覆盖路径测试"""

    def test_register_profile(self):
        """register_profile 注册自定义 Header Profile"""
        pool = UserAgentPool()
        pool.register_profile("custom_test", {
            "Accept": "text/html",
            "Accept-Language": "en-US",
        })
        # 清空 desktop 后添加带该 profile 的单个 UA，确保 get_headers 命中它
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        pool.add("TestAgent/1.0", "desktop", weight=1, profile="custom_test")
        headers = pool.get_headers("desktop")
        assert headers["User-Agent"] == "TestAgent/1.0"
        assert headers["Accept"] == "text/html"

    def test_register_profile_duplicate_raises(self):
        """register_profile 注册重复 key 抛 ValueError"""
        pool = UserAgentPool()
        pool.register_profile("dup_test", {"X-Custom": "1"})
        with pytest.raises(ValueError, match="已存在"):
            pool.register_profile("dup_test", {"X-Other": "2"})

    def test_register_profile_with_ua_raises(self):
        """register_profile 包含 User-Agent 字段抛 ValueError"""
        pool = UserAgentPool()
        with pytest.raises(ValueError, match="不应包含 'User-Agent'"):
            pool.register_profile("bad_profile", {
                "User-Agent": "BadAgent/1.0",
                "Accept": "text/html",
            })

    def test_contains(self):
        """__contains__ 检查 UA 是否在池中"""
        pool = UserAgentPool()
        ua = pool.get("desktop")
        assert ua in pool
        assert "NonexistentAgent/99.9" not in pool

    def test_strategy_setter_invalid_type(self):
        """strategy setter 传入非 UAStrategy 枚举抛 TypeError"""
        pool = UserAgentPool()
        with pytest.raises(TypeError, match="策略必须是 UAStrategy"):
            pool.strategy = "WEIGHTED"  # type: ignore[assignment]

    def test_reserve_all_category_restore(self):
        """reserve('all') 从池中取出并归还"""
        pool = UserAgentPool()
        before = len(pool)
        with pool.reserve("all") as ua:
            assert isinstance(ua, str)
            # 'all' 分类取出后会减少 1（实际代码 remove_from_all_categories 遍历所有分类）
        after = len(pool)
        assert after == before

    def test_remove_one_nonexistent(self):
        """remove_one 对不存在的 UA 返回 False"""
        pool = UserAgentPool()
        assert pool.remove_one("NonexistentUA/99.0", "desktop") is False

    def test_remove_from_all_categories_nonexistent(self):
        """remove_from_all_categories 对不存在的 UA 返回 ('', False)"""
        pool = UserAgentPool()
        cat, ok = pool.remove_from_all_categories("NonexistentUA/99.0")
        assert ok is False
        assert cat == ""

    def test_weighted_pick_zero_total_weight(self):
        """所有条目权重为 0 时仍能选出一个"""
        pool = UserAgentPool()
        # 清空 desktop
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        # 添加两个权重为 0 的条目
        pool.add("ZeroA/1.0", "desktop", weight=0)
        pool.add("ZeroB/1.0", "desktop", weight=0)
        # 即使权重为 0 也应能选出一个
        ua = pool.get("desktop")
        assert ua in ("ZeroA/1.0", "ZeroB/1.0")

    def test_get_headers_no_profile(self):
        """UA 无关联 profile 时 get_headers 仅返回 User-Agent"""
        pool = UserAgentPool()
        # 清空 desktop 后添加不带 profile 的 UA
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        pool.add("PlainAgent/1.0", "desktop", weight=5)
        headers = pool.get_headers("desktop")
        assert headers["User-Agent"] == "PlainAgent/1.0"
        # 不带 profile 只返回 User-Agent
        assert len(headers) == 1

    def test_get_headers_with_weighted_strategy(self):
        """get_headers 使用池级加权策略"""
        from user_agent_pool import UAStrategy
        pool = UserAgentPool(strategy=UAStrategy.WEIGHTED)
        headers = pool.get_headers("desktop")
        assert "User-Agent" in headers

    def test_all_profiles_have_required_headers(self):
        """所有 Profile 必须包含浏览器必带的 8 个请求头"""
        from user_agent_pool.agents import _HEADER_PROFILES

        def _is_standard_profile_key(key: str) -> bool:
            """判断是否标准命名 Profile（排除测试桩）"""
            known_browsers = ("chrome_", "firefox_", "safari_", "edge_")
            return key.startswith(known_browsers) and key.count("_") >= 2

        REQUIRED = {
            "Accept", "Accept-Language", "Accept-Encoding",
            "Connection",
            "Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User",
        }
        CHROMIUM_REQUIRED = {"Sec-Ch-Ua", "Sec-Ch-Ua-Platform", "Sec-Ch-Ua-Mobile"}

        # 只检查遵循命名规范的 Profile（排除测试桩如 custom_test/dup_test）
        for key, profile in _HEADER_PROFILES.items():
            # 标准命名: {browser}_{version}_{platform} 如 chrome_131_win
            if not _is_standard_profile_key(key):
                continue
            missing = REQUIRED - set(profile.keys())
            assert not missing, f"Profile '{key}' 缺失必带头: {missing}"

            # Chromium 系浏览器还应有 Sec-Ch-Ua 系列
            if key.startswith(("chrome_", "edge_")):
                missing_ch = CHROMIUM_REQUIRED - set(profile.keys())
                assert not missing_ch, f"Profile '{key}' 缺失 Chromium 头: {missing_ch}"


class TestFactionAssembly:
    """派系组装架构测试 —— 即时生成 Header 的合法性验证"""

    def test_faction_isolation_chrome_vs_firefox(self):
        """Chrome 派系不应出现 Firefox 特征（如缺失 Sec-Ch-Ua）"""
        pool = UserAgentPool()
        headers = pool.get_headers("desktop", browser="chrome")
        # Chrome/Chromium 必须有 Sec-Ch-Ua 系列
        assert "Sec-Ch-Ua" in headers, f"Chrome headers 缺失 Sec-Ch-Ua: {sorted(headers.keys())}"
        assert "Sec-Ch-Ua-Platform" in headers
        assert "Sec-Ch-Ua-Mobile" in headers
        # Chrome 的 Accept 含 image/avif,image/webp (与 Firefox 的 */* 不同)
        assert "image/avif" in headers["Accept"]
        assert "image/apng" in headers["Accept"]

    def test_faction_isolation_firefox(self):
        """Firefox 派系不应有 Chrome 特征 Sec-Ch-Ua"""
        pool = UserAgentPool()
        headers = pool.get_headers("desktop", browser="firefox")
        # Firefox 无 Sec-Ch-Ua 系列
        assert "Sec-Ch-Ua" not in headers
        assert "Sec-Ch-Ua-Platform" not in headers
        assert "Sec-Ch-Ua-Mobile" not in headers
        # Firefox 的 Accept 不含 image/apng (Chrome 特征)
        assert "image/apng" not in headers.get("Accept", "")

    def test_faction_isolation_safari(self):
        """Safari 派系不应有 Chromium 特征"""
        pool = UserAgentPool()
        headers = pool.get_headers("desktop", browser="safari")
        # Safari 无 Sec-Ch-Ua
        assert "Sec-Ch-Ua" not in headers
        # Safari 的 Accept 不含 image/avif (更简洁)
        assert "image/apng" not in headers.get("Accept", "")

    def test_ua_version_consistency(self):
        """Chromium 派系：UA 版本号 必须与 Sec-Ch-Ua 版本号一致"""
        import re
        pool = UserAgentPool()
        headers = pool.get_headers("desktop", browser="chrome")
        ua = headers["User-Agent"]
        sec_ch_ua = headers.get("Sec-Ch-Ua", "")
        if not sec_ch_ua:
            return  # 非 Chromium 跳过
        # 从 UA 提取 Chrome 版本号
        ua_match = re.search(r"Chrome/(\d+)", ua)
        assert ua_match, f"UA 中未找到 Chrome 版本: {ua}"
        ua_version = ua_match.group(1)
        # 从 Sec-Ch-Ua 提取版本号（取第一个 v="N"）
        sec_match = re.search(r'v="(\d+)"', sec_ch_ua)
        assert sec_match, f"Sec-Ch-Ua 中未找到版本号: {sec_ch_ua}"
        sec_version = sec_match.group(1)
        assert ua_version == sec_version, (
            f"UA 版本 ({ua_version}) != Sec-Ch-Ua 版本 ({sec_version})\n"
            f"  UA: {ua}\n  Sec-Ch-Ua: {sec_ch_ua}"
        )

    def test_platform_consistency(self):
        """Chromium 派系：UA 操作系统 必须与 Sec-Ch-Ua-Platform 一致"""
        pool = UserAgentPool()
        # Windows
        headers = pool.get_headers("desktop", browser="chrome", os="windows")
        assert '"Windows"' in headers.get("Sec-Ch-Ua-Platform", "")
        # macOS
        headers = pool.get_headers("desktop", browser="chrome", os="macos")
        assert '"macOS"' in headers.get("Sec-Ch-Ua-Platform", "")
        # Android mobile
        headers = pool.get_headers("mobile", browser="chrome", os="android")
        assert '"Android"' in headers.get("Sec-Ch-Ua-Platform", "")
        assert headers.get("Sec-Ch-Ua-Mobile") == "?1"

    def test_device_language_match(self):
        """Accept-Language 段数应匹配设备类型（desktop≥5 段, mobile≤3 段）"""
        pool = UserAgentPool()
        # Desktop
        headers = pool.get_headers("desktop", browser="chrome", os="windows")
        al = headers.get("Accept-Language", "")
        segments = al.count(",")
        assert segments >= 4, f"Desktop Accept-Language 应 ≥5 段: '{al}' (只有 {segments+1} 段)"
        # Mobile
        headers = pool.get_headers("mobile", browser="chrome", os="android")
        al = headers.get("Accept-Language", "")
        segments = al.count(",")
        assert segments <= 3, f"Mobile Accept-Language 应 ≤3 段: '{al}' (有 {segments+1} 段)"

    def test_multiple_calls_produce_variations(self):
        """多次调用 get_headers 应产生不同的 Header 组合（可变字段随机化）"""
        pool = UserAgentPool()
        headers_set: set[str] = set()
        for _ in range(100):
            h = pool.get_headers("desktop", browser="chrome")
            # 用关键可变字段签名做指纹
            sig = f"{h.get('Accept-Language','')}|{h.get('Cache-Control','')}|{h.get('Upgrade-Insecure-Requests','')}"
            headers_set.add(sig)
        # 100 次调用中应该产生多种不同组合（至少 3 种）
        assert len(headers_set) >= 3, (
            f"100 次调用只产生了 {len(headers_set)} 种变体，预期 ≥3"
        )

    def test_firefox_no_cache_control(self):
        """Firefox 派系不应包含 Cache-Control 头"""
        pool = UserAgentPool()
        # 多次采样确保不是碰巧
        for _ in range(20):
            headers = pool.get_headers("desktop", browser="firefox")
            assert "Cache-Control" not in headers, (
                f"Firefox headers 不应有 Cache-Control: {headers}"
            )

    def test_online_path_fakeua_ua_with_faction_assembly(self):
        """模拟在线路径：fake_useragent 提供的 UA + 派系组装补充头

        验证：当 entry 有 browser/os/version 元数据时，
        _build_headers 走派系组装而非旧 Profile 匹配。
        """
        pool = UserAgentPool()
        # 清空 desktop
        for ua in pool.get_all("desktop"):
            pool.remove(ua, "desktop")
        # 模拟 fake_useragent 导入：添加一个带元数据的 UA（无 profile）
        fake_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        pool.add(fake_ua, "desktop", weight=5)
        headers = pool.get_headers("desktop")
        # 应有完整的 Chrome 派系请求头
        assert "User-Agent" in headers
        assert "Sec-Ch-Ua" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        # 版本号一致：Sec-Ch-Ua 的 v= 与 UA 中 Chrome/ 版本一致
        ua_version = _extract_ua_version(headers["User-Agent"])
        assert ua_version is not None
        assert f'v="{ua_version}"' in headers["Sec-Ch-Ua"]
        # 平台匹配
        assert '"Windows"' in headers.get("Sec-Ch-Ua-Platform", "")

    def test_local_fallback_uses_default_agents_with_faction_assembly(self):
        """验证本地降级路径：内置 DEFAULT_AGENTS 走派系组装

        默认 UAs 有 browser/os/version 元数据，应自动走派系组装产生可变 headers。
        """
        pool = UserAgentPool()
        # 正常初始化后直接调用
        headers = pool.get_headers("desktop")
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        # 多个调用应产生不同 Accept-Language/Cache-Control 组合
        al_values: set[str] = set()
        for _ in range(30):
            h = pool.get_headers("desktop", browser="chrome")
            al_values.add(h.get("Accept-Language", ""))
        assert len(al_values) >= 2, f"只产生 {len(al_values)} 种 Accept-Language 变体"

    def test_generate_ua_basic(self):
        """generate_ua() 基本功能验证"""
        from user_agent_pool.agents import generate_ua
        # Chrome desktop
        ua = generate_ua("chrome", "windows", 148)
        assert "Chrome/148" in ua
        assert "Mozilla/5.0" in ua
        # Firefox desktop
        ua = generate_ua("firefox", "windows", 150)
        assert "Firefox/150" in ua
        assert "rv:150" in ua
        # Edge desktop
        ua = generate_ua("edge", "windows", 148)
        assert "Edg/148" in ua
        # Safari desktop
        ua = generate_ua("safari", "macos", 0)
        assert "Safari" in ua
        assert "Version/18.1" in ua

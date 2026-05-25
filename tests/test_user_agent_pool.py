"""User-Agent 池单元测试"""

import pytest

from user_agent_pool import UserAgentPool
from user_agent_pool.exceptions import PoolExhaustedException, InvalidAgentException


class TestUserAgentPool:
    """基础功能测试"""

    def test_init_loads_defaults(self):
        pool = UserAgentPool()
        assert len(pool) > 0
        stats = pool.count()
        assert isinstance(stats, dict)  # type: ignore[unreachable]
        assert stats["desktop"] == 10
        assert stats["mobile"] == 8
        assert stats["tablet"] == 4

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
        assert len(uas) == 10
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
        from user_agent_pool import UAStrategy
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

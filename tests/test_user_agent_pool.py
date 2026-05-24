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
        before = pool.count()["desktop"]
        pool.add("MyBot/1.0", "desktop", weight=3)
        after = pool.count()["desktop"]
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
        assert set(stats.keys()) == {"desktop", "mobile", "tablet"}
        assert all(v > 0 for v in stats.values())

    def test_count_specific_category(self):
        pool = UserAgentPool()
        stats = pool.count("desktop")
        assert set(stats.keys()) == {"desktop"}

    def test_len(self):
        pool = UserAgentPool()
        assert len(pool) == sum(pool.count().values())

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
        before = pool.count()["desktop"]
        with pool.reserve("desktop") as ua:
            # 取出后数量应减少 1
            assert pool.count()["desktop"] == before - 1
        # 退出后数量应恢复
        assert pool.count()["desktop"] == before

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

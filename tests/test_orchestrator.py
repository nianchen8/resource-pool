"""编排器测试"""

import pytest
from user_agent_pool import UserAgentPool
from proxy_pool import ProxyPool

from nurture_pool.base import ResourcePool
from nurture_pool.exceptions import PoolExhaustedError
from nurture_pool.orchestrator import PoolOrchestrator


# ── 用于 _fetch_from_pool 分派测试的 Mock 池 ──────────────────────────

class _PoolWithGetOnly(ResourcePool):
    """仅实现 get() 的池"""
    def __init__(self):
        self._data = ["res_a", "res_b"]
    def get(self) -> str:
        return self._data.pop(0) if self._data else "fallback"
    def __len__(self) -> int:
        return len(self._data)
    def __repr__(self) -> str:
        return "_PoolWithGetOnly()"


class _PoolWithGetServer(ResourcePool):
    """仅实现 get_server() 的池"""
    def get_server(self) -> str:
        return "8.8.8.8"
    def __len__(self) -> int:
        return 1
    def __repr__(self) -> str:
        return "_PoolWithGetServer()"


class _PoolNoMethod(ResourcePool):
    """不实现任何资源获取方法"""
    def __len__(self) -> int:
        return 0
    def __repr__(self) -> str:
        return "_PoolNoMethod()"


class TestOrchestrator:
    """PoolOrchestrator 基本操作"""

    def test_init_with_pools(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        assert "ua" in orch.pool_names
        assert "proxy" in orch.pool_names

    def test_init_empty_raises(self):
        with pytest.raises(ValueError, match="至少需要注册"):
            PoolOrchestrator()

    def test_register_unregister(self):
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        assert "ua" in orch.pool_names

        orch.unregister("ua")
        assert "ua" not in orch.pool_names

        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})
        orch.register("proxy", proxy)
        assert "proxy" in orch.pool_names

    def test_register_non_pool_raises(self):
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        with pytest.raises(TypeError, match="必须实现 ResourcePool 协议"):
            orch.register("bad", object())  # type: ignore[arg-type]

    def test_next_returns_combo(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        combo = orch.next()

        assert "ua" in combo
        assert "proxy" in combo
        assert isinstance(combo["ua"], dict)   # UA 池返回完整 headers 字典
        assert isinstance(combo["proxy"], dict)  # Proxy 返回 proxies 字典
        assert "User-Agent" in combo["ua"]       # headers 含 UA 字段

    def test_next_ua_proxy_only(self):
        """UA + Proxy 组合（不含 DNS）"""
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "10.0.0.1", "port": 3128})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        combo = orch.next()

        assert "User-Agent" in combo["ua"]   # headers 字典含 UA 字段
        assert "http" in combo["proxy"]      # 代理字典含 http 键

    def test_combos_iterator(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        combos = list(orch.combos(limit=3))

        assert len(combos) == 3
        for c in combos:
            assert "ua" in c
            assert "proxy" in c

    def test_health_check_all(self):
        ua = UserAgentPool()
        proxy = ProxyPool()
        proxy.add_proxy({"host": "127.0.0.1", "port": 8080})

        orch = PoolOrchestrator(ua=ua, proxy=proxy)
        results = orch.health_check_all(timeout=2.0)

        assert "ua" in results
        assert "proxy" in results
        assert results["ua"] == "N/A (池不支持健康检查)"

    def test_repr(self):
        ua = UserAgentPool()
        orch = PoolOrchestrator(ua=ua)
        r = repr(orch)
        assert "PoolOrchestrator" in r
        assert "ua" in r

    # ── 以下测试主要覆盖 _fetch_from_pool 分派 & combos 异常路径 ──────

    def test_fetch_from_pool_with_get_only(self):
        """_fetch_from_pool: 池只有 get() 时走 get 分派"""
        pool = _PoolWithGetOnly()
        result = PoolOrchestrator._fetch_from_pool("test", pool)
        assert result == "res_a"

    def test_fetch_from_pool_with_get_server(self):
        """_fetch_from_pool: 池只有 get_server() 时走 get_server 分派"""
        pool = _PoolWithGetServer()
        result = PoolOrchestrator._fetch_from_pool("dns", pool)
        assert result == "8.8.8.8"

    def test_fetch_from_pool_no_method_raises(self):
        """_fetch_from_pool: 池没有任何可获取方法时抛 RuntimeError"""
        pool = _PoolNoMethod()
        with pytest.raises(RuntimeError, match="无可用的资源获取方法"):
            PoolOrchestrator._fetch_from_pool("bad", pool)

    def test_next_error_propagation(self):
        """next() 在 _fetch_from_pool 失败时应传播异常"""
        pool = _PoolNoMethod()
        orch = PoolOrchestrator(test=pool)
        with pytest.raises(RuntimeError, match="无可用的资源获取方法"):
            orch.next()

    def test_combos_stops_on_pool_exhausted(self):
        """combos() 在 PoolExhaustedError 时终止迭代"""
        class _ExhaustedPool(ResourcePool):
            def get(self) -> str:
                raise PoolExhaustedError("模拟耗尽")
            def __len__(self) -> int:
                return 0
            def __repr__(self) -> str:
                return "_ExhaustedPool()"

        orch = PoolOrchestrator(p=_ExhaustedPool())
        combos = list(orch.combos(limit=10))
        assert len(combos) == 0

    def test_combos_stops_on_unknown_exception(self):
        """combos() 在非预期异常时终止迭代"""
        class _ErrorPool(ResourcePool):
            def get(self) -> str:
                raise OSError("模拟致命异常")
            def __len__(self) -> int:
                return 0
            def __repr__(self) -> str:
                return "_ErrorPool()"

        orch = PoolOrchestrator(p=_ErrorPool())
        combos = list(orch.combos(limit=10))
        assert len(combos) == 0

    # ── register_dispatch 测试 ─────────────────────────────────────

    def test_register_dispatch_basic(self):
        """register_dispatch 注册后 _fetch_from_pool 走 isinstance 分派"""
        class _CustomPool(ResourcePool):
            def fetch(self) -> str:
                return "custom_result"
            def get(self) -> str:
                return "should_not_be_called"
            def __len__(self) -> int:
                return 1
            def __repr__(self) -> str:
                return "_CustomPool()"

        PoolOrchestrator.register_dispatch(_CustomPool, "fetch")
        result = PoolOrchestrator._fetch_from_pool("custom", _CustomPool())
        assert result == "custom_result"

    def test_register_dispatch_priority_over_hasattr(self):
        """注册表匹配优先于 hasattr 探测"""
        class _AmbiguousPool(ResourcePool):
            def get_dict(self) -> str:
                return "dict"
            def get(self) -> str:
                return "single"
            def __len__(self) -> int:
                return 1
            def __repr__(self) -> str:
                return "_AmbiguousPool()"

        # 注册为 get，但池也实现了 get_dict
        PoolOrchestrator.register_dispatch(_AmbiguousPool, "get")
        result = PoolOrchestrator._fetch_from_pool("amb", _AmbiguousPool())
        assert result == "single"  # 走注册表，不是 hasattr 的 get_dict

    def test_register_dispatch_invalid_type(self):
        """register_dispatch 非 type 参数抛 TypeError"""
        with pytest.raises(TypeError, match="pool_type 必须是类型"):
            PoolOrchestrator.register_dispatch("not_a_type", "method")  # type: ignore[arg-type]

    def test_register_dispatch_invalid_method_name(self):
        """register_dispatch 空/非字符串 method_name 抛 TypeError"""
        with pytest.raises(TypeError, match="method_name 必须是非空字符串"):
            PoolOrchestrator.register_dispatch(_PoolNoMethod, "")

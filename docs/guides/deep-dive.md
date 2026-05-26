# 深入架构

> 目标读者：需要定制、调优、或理解底层设计的工程师。

---

## 架构全景

```
┌──────────────────────────────────────────────┐
│              应用层                           │
│   requests / Scrapy / aiohttp / httpx        │
└──────┬──────────────────┬────────────────────┘
       │                  │
       │  短路径 (v1.0.5+)│  长路径
       │  import          │  from resource_pool
       │  resource_pool   │  import UserAgentPool
       │                  │
┌──────▼──────────┐ ┌─────▼────────────────────┐
│   _shortcuts.py  │ │  PoolOrchestrator (编排器) │
│  UA / Proxy /    │ │  isinstance 注册表分派     │
│  DNS / combo()   │ │  PoolCombo 抽象            │
└──────┬──────────┘ └─────┬────────────────────┘
       │                  │
┌──────▼───┐ ┌───▼────┐ ┌──▼──────────────┐
│UA Pool   │ │DNS Pool│ │  Proxy Pool      │
│ReadWrite │ │16-shard│ │  Lock / asyncio  │
│Lock      │ │cache   │ │  .Lock           │
│Strategy  │ │Strategy│ │  Strategy        │
└──────────┘ └────────┘ └──────────────────┘
       │          │          │
┌──────▼──────────▼──────────▼─────────────────┐
│            ResourcePool ABC (基类)             │
│   StrategyProtocol · DummyLock · 惰性导入     │
└──────────────────────────────────────────────┘
```

四个子包通过 `resource_pool/__init__.py` 的 `__getattr__` 惰性加载。

### 短别名层 (`_shortcuts.py`)

v1.0.5 新增的上层包装，为日常用户提供极简 API：

- `UA()` / `Proxy()` / `DNS()` —— 每个类在实例化时才加载底层模块，不使用零开销
- 自动 `health_check`：DNS 和 Proxy 首次 `resolve()`/`pick()` 时自动触发
- `combo(**pools)` —— 提取快捷类内部的真实池实例，组建成 `PoolOrchestrator` 后返回组合结果
- 短别名是**纯包装**：`.pick()` → 底层 `.get()`，不做功能阉割

```python
# 短别名背后 —— 完全透明
ua = resource_pool.UA()          # 惰性创建 UserAgentPool()
ua.pick()                        # → ua._pool.get("desktop")
ua.headers()                     # → ua._pool.get_headers("desktop")
```

### UA 数据源与 Header 组装链路

`UserAgentPool` 支持多数据源，所有来源的 UA 统一走同一套 Profile 匹配管道：

```
fake_useragent (远程)                 headers_pool.jsonl (本地 830 条)
        │                                        │
        │  返回 UA < 5 条时自动降级               │
        └────────────────→  ─────────────────────→│
                         │                       │
                         ▼                       ▼
                   self.add(ua, ...)
                         │
                         ▼
                parse_ua_metadata()
                  → browser / os / version
                         │
                         ▼
         get_headers() → _build_headers()
                         │
                         ▼
                  match_profile()
             → 最近版本号匹配 + Sec-CH-UA 版本修正
                         │
                         ▼
              组装完整的 20 项请求头
```

**关键设计**：jsonl 仅作为 UA 池扩充（830 条），不存储预制 headers。
所有请求头字段由 `_HEADER_PROFILES` 模板 + `match_profile()` 运行时组装，
确保不同数据源产出的 headers 指纹一致性。

> `load_from_fakeua()` 降级阈值 = 5，用户可通过 `_load_bundled_jsonl()` 显式触发本地加载。

---

## 锁层级与并发模型

### 同步版

```
高层（慢）：auto_maintain、load_from_url、health_check
    │  秒级，低频
    ▼
中层：add、remove、mark_failed（写锁独占）
    │  微秒-毫秒级，中频
    ▼
低层：get、get_headers、resolve、get_dict（读锁，多线程并发进入）
    │  微秒级，高频。UA 池 ReadWriteLock：读并发 N 倍
    ▼
无锁：_do_resolve、_probe_proxy（I/O 密集）
```

UA 池使用 `ReadWriteLock`（写者优先），读操作（`get`/`get_headers`/`count`）可多线程并发进入。DNS 缓存使用 16 路分片锁——按域名首字符 `ord(key[0]) % 16` 哈希，减少争用。

### 异步版（v1.0.4+）

```
高层（慢）：auto_maintain、load_from_url(s)、health_check
    │  asyncio.to_thread 后台线程不阻塞事件循环
    ▼
中层：add、remove、mark_failed
    │  各自 async with self._lock
    ▼
低层：_get_alive、_try_revive、_on_success（内部方法各自加锁）
    │  get() 不持外层锁，选择逻辑（排序/随机）在锁外执行
    ▼
无锁：_do_resolve、_probe_proxy
```

> **关键设计**：异步版 `asyncio.Lock` 不可重入。内部方法各自加锁，`get()` 仅在调用它们时短暂持锁——与同步版的并发模型一致，避免协程串行化。

---

## StrategyProtocol：可插拔策略

所有池的 `strategy` 属性接受两种形式：

```python
# 1. 内置枚举
proxy.strategy = ProxyStrategy.LATENCY_WEIGHTED
dns.strategy = SelectStrategy.ROUND_ROBIN
ua.strategy = UAStrategy.WEIGHTED

# 2. 任意 callable（实现 StrategyProtocol）
class MyStrategy:
    def __call__(self, items: list) -> Iterator:
        # 你的选择逻辑
        return iter(sorted(items, key=...))

pool.strategy = MyStrategy()
```

`strategy` setter 有类型校验，传入非法值会立即抛 `TypeError`。

---

## 故障隔离与复活

三层机制：

1. **连续失败计数**：`max_consecutive_fails`（默认 3-5），达到阈值自动 `enabled=False`
2. **定时复活**：超过 `revive_after`（默认 120-300s）后试用复活——`consecutive_fails = max_fails - 1`（只给一次机会，再失败立即重新隔离）
3. **健康检查**：`health_check()` 全量探测，可手动或定时调用

复活逻辑（`_try_revive`）在锁内执行时间戳检查，避免多线程/多协程重复复活。

---

## 自定义资源池

继承 `ResourcePool` ABC，接入编排器生态：

```python
from resource_pool import ResourcePool, PoolOrchestrator

class CookiePool(ResourcePool):
    def __init__(self):
        self._cookies = []
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._cookies)

    def __repr__(self):
        return f"CookiePool({len(self)})"

    def get(self, domain: str) -> str:
        """编排器通过 register_dispatch 调用此方法"""
        with self._lock:
            return self._cookies.pop()

# 注册分派（告诉编排器用哪个方法拿资源）
PoolOrchestrator.register_dispatch(CookiePool, "get")

# 使用
orch = PoolOrchestrator(cookie=CookiePool(), ua=ua_pool)
combo = orch.next()  # combo["cookie"] 自动调用 cookie_pool.get()
```

---

## 异步池 Concurrency model

`AsyncDNSResolverPool` 使用 `contextvars.ContextVar` 替代 `threading.local()`——每个 `asyncio.Task` 独立持有 `dns.asyncresolver.Resolver` 实例。

`AsyncProxyPool` 的网络/文件 I/O 通过 `asyncio.to_thread` 在后台线程执行，不阻塞事件循环。健康检查使用 `asyncio.open_connection` + 可选 `aiohttp`。

---

## 性能基准

| 池 | 1000 并发 | 锁方案 |
|---|:--:|---|
| UA | ~111k ops/s | ReadWriteLock |
| DNS cache | ~200k ops/s | 16 路分片锁 |
| Proxy | ~62k ops/s | threading.Lock |

> 详见 `tests/test_stress_benchmark.py`。

---

## 调优建议

| 场景 | 建议 |
|------|------|
| UA 池读多写少 | 默认 ReadWriteLock 无需调整 |
| DNS 高并发 | 增大 `cache_ttl`、提升 `max_cache_size` |
| 代理质量差 | 开启 `auto_maintain()`、设 `min_alive` |
| 数百线程 | 为不同业务线创建独立池实例 |
| 单线程脚本 | `thread_safe=False` 消除所有锁开销 |
| 异步爬虫 | 用 `Async*` 版本，`asyncio.to_thread` 处理 IO |

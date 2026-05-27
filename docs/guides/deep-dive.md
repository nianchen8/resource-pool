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

### UA 数据源与 Header 组装链路（v1.0.9 零件池架构）

`UserAgentPool` 初始化时自动加载 854 条 UA 种子（`ua_seeds.json`），
覆盖 4 浏览器引擎家族 × 7 平台 × 3 设备类型。
每条 UA 拆解为 OS 串/版本令牌/WebKit/Mobile Build 四个零件维度，
跨零件随机重组 → 31,496 独立 UA → 193,633 完整 headers 组合。
所有来源的 UA 统一走**零件池+派系组装管道**：

```
                     UserAgentPool()
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ua_seeds.json 854条  fake_useragent
         (自动加载)   (load_from_
                       fakeua)
              │            │
              │            │            │
              └─────┬──────┘            │
                    │                   │
                    ▼                   ▼
           _copy_agent_entry()   parse_ua_metadata()
           → 自动补全 browser / os / version 元数据
                    │
                    ▼
              get_headers()
                    │
                    ▼
            _build_headers()
           ┌────────────────────────────────────────────┐
           │  3级降级                                   │
           │  ① 元数据 → 零件池重组 + 派系即时组装       │
           │  ② 内联 headers（用户注入兜底）             │
           │  ③ Profile 匹配（向后兼容）                 │
           └────────────────────────────────────────────┘
                    │ (全部走 ①)
                    ▼
       _assemble_headers_from_faction()
       ┌──────────────────────────────────────┐
       │ 引擎家族 → 平台 → 设备类型 三维路由     │
       │                                      │
       │ Chromium (Chrome/Edge/CriOS)          │
       │   ├─ Desktop: Windows/macOS/Linux     │
       │   ├─ Mobile:  Android                │
       │   └─ ChromeOS                         │
       │ Firefox                               │
       │   ├─ Desktop: Windows/macOS/Linux     │
       │   └─ Mobile:  Android                │
       │ Safari (WebKit)                       │
       │   ├─ Desktop: macOS                   │
       │   └─ Mobile:  iOS (iPhone/iPad/GSA)   │
       └──────────────────────────────────────┘
                    │
                    ▼
       ┌──────────────────────────────────┐
       │ Identity Block (引擎家族固有)      │
       │  Accept / Accept-Encoding /       │
       │  Connection / Sec-Fetch-*×4       │
       │  Sec-Ch-Ua* (仅 Chromium)         │
       ├──────────────────────────────────┤
       │ 可变字段（每次随机选取）            │
       │  Accept-Language: 5 种池          │
       │  Cache-Control: max-age=0/no-cache│
       │  Upgrade-Insecure-Requests: 有/无 │
       └──────────────────────────────────┘
                    │
                    ▼
           完整 headers (指数级变化)
```

**双路径**：
- **零件池路径**：ua_seeds.json 每条 UA 拆解为 OS 串/版本令牌/WebKit/Mobile Build → 跨零件随机重组 → 31,496 独立 UA → 派系引擎组装 14 项请求头
- **在线路径**：fake_useragent 提供 UA → 零件池重组 + 派系引擎组装请求头
- **本地降级**：内置 UA → 零件池重组 + 派系引擎组装（自动，零配置）

**关键约束自动保证**：
- UA 版本 == Sec-Ch-Ua 版本（`_build_sec_ch_ua` 动态生成）
- UA 平台 == Sec-Ch-Ua-Platform（`_OS_PLATFORM_META` 映射 6 平台）
- Accept-Language 段数匹配设备类型（桌面 ≥5 段，移动 ≤3 段）
- Firefox 不包含 Sec-Ch-Ua / Cache-Control
- Safari 不包含 Sec-Ch-Ua / Upgrade-Insecure-Requests
- 引擎家族不可交叉（Chrome ←/→ Firefox ←/→ Safari 不会混用）

**组合爆炸**：854 UA 种子 → 零件池随机重组 → 31,496 独立 UA → 每次生成即时组装 14 项请求头 → 193,633 种完整 headers 组合。

> `_build_headers` v1.0.9 改为：元数据存在时走零件池随机重组 + 派系组装（最高优先级），
> 内联 headers 兜底，Profile 匹配为向后兼容。

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

# Resource Pool ![version](https://img.shields.io/badge/version-1.0.4-blue)

> 一套可扩展的网络资源池框架，为爬虫工程提供开箱即用的资源调度能力。

**爬虫三件套**：User-Agent 池 + DNS 解析器池 + 代理池，内置编排器一键协同。支持同步/异步双模。

---

## 为什么需要资源池

| 资源类型 | 无池状态 | 有池效果 |
|---------|---------|---------|
| User-Agent | 固定一个，高频请求秒被识别 | 22+ 个 UA 按设备分类加权随机 + 完整 Header Profile 组 + 支持 fake_useragent 批量导入 + 浏览器/OS/版本号细粒度筛选 |
| DNS 解析 | 单点 DNS 频次过高被限流 | 14 台 DNS 轮换解析 + 延迟排序 + 故障隔离 + LRU 缓存（16路分片锁）+ 自动复活 |
| 代理 | 单代理被封全部瘫痪 | HTTP/HTTPS/SOCKS5 代理池，健康检查 + 故障隔离 + 凭据脱敏 |

---

## 安装

```bash
pip install git+https://github.com/nianchen8/resource-pool.git

# 开发环境
pip install git+https://github.com/nianchen8/resource-pool.git[dev]
```

Python ≥ 3.10，仅依赖 `dnspython ≥ 2.6`。

---

## 30 秒上手

```python
from resource_pool import (
    UserAgentPool, DNSResolverPool, ProxyPool,
    SelectStrategy, PoolOrchestrator,
)

# 初始化三件套
ua = UserAgentPool()
dns = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
proxy = ProxyPool()
proxy.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})

dns.health_check()
proxy.health_check()

# 编排器一键拿全套
orch = PoolOrchestrator(ua=ua, dns=dns, proxy=proxy)
combo = orch.next()
# → PoolCombo 对象，支持属性访问 combo.ua 和字典访问 combo["ua"]

requests.get(url, headers=combo["ua"], proxies=combo["proxy"])
```

---

## 各池详解

### User-Agent 池

```python
from resource_pool import UserAgentPool, UAStrategy

pool = UserAgentPool(strategy=UAStrategy.WEIGHTED)  # 默认加权随机

# 基础获取
ua = pool.get("desktop")                             # 加权随机
ua = pool.get("mobile", weighted=False)              # 均匀随机
ua = pool.get("desktop", exclude={"Firefox"})        # 排除特定关键词
ua = pool.get(browser="chrome", os="windows", min_version=120)  # 细粒度筛选

# 批量导入
pool.load_from_file("ua_list.json")                  # JSON/CSV 导入
pool.load_from_fakeua(limit=100)                     # 从 fake_useragent 导入（可选依赖）

# 完整 Header Profile（推荐反爬场景）
headers = pool.get_headers("desktop")
# → {"User-Agent": "...", "Accept": "...", "Sec-Ch-Ua": "...", "Accept-Language": "...", ...}
requests.get(url, headers=headers)

# 池级策略切换
pool.strategy = UAStrategy.UNIFORM                   # 运行时切均匀随机

# 上下文管理器 —— 取出时移除，用完自动归还
with pool.reserve("mobile") as ua:
    requests.get(url, headers={"User-Agent": ua})

# 注册自定义 Header Profile
pool.register_profile("my_app", {
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
})
pool.add("MyCrawler/2.0", "desktop", weight=3, profile="my_app")

# 统计与迭代
print(pool.count())          # {'desktop': 10, 'mobile': 8, 'tablet': 4}
print(pool.count("desktop")) # 10
print("Mozilla/5.0..." in pool)   # True
for ua_str in pool:
    print(ua_str[:60])
```

### DNS 解析器池

```python
from resource_pool import DNSResolverPool, SelectStrategy

pool = DNSResolverPool(
    regions=("domestic", "overseas"),          # 加载国内外 DNS
    strategy=SelectStrategy.LATENCY_WEIGHTED,  # 低延迟优先
    cache_ttl=300,                             # 缓存 5 分钟
    max_cache_size=4096,                       # LRU 淘汰上限
    max_consecutive_fails=3,                   # 连续失败 3 次隔离
    revive_after=120,                          # 120s 后尝试复活
)
pool.health_check()

ip = pool.resolve("www.example.com")           # 单个最优 IP
ips = pool.resolve_all("www.example.com")      # 全部 IP

# 运行时状态
for s in pool.stats():
    print(f"{s['name']:12s} 延迟={s['latency_ms']:5.1f}ms  可用={s['enabled']}")

# 自定义策略
def prefer_google(servers):
    return iter(sorted(servers, key=lambda s: "google" not in s.name))
pool.strategy = prefer_google

# 长期运行的服务可定期释放线程本地对象
pool.close()
```

### 代理池

```python
from resource_pool import ProxyPool, ProxyStrategy

pool = ProxyPool(strategy=ProxyStrategy.LATENCY_WEIGHTED)

# 添加代理
pool.add_proxy({"scheme": "http", "host": "127.0.0.1", "port": 8080})
pool.add_proxy({
    "scheme": "socks5", "host": "10.0.0.1", "port": 1080,
    "username": "user", "password": "pass",
    "region": "us", "weight": 8,
})

pool.health_check()                            # 含 socket 预检 + HTTP 验证

# 获取代理
proxy_url = pool.get()                         # "http://127.0.0.1:8080"
proxy_url = pool.get(scheme="socks5")          # 按协议筛选
proxies = pool.get_dict()                      # {"http": "...", "https": "..."}
requests.get(url, proxies=proxies)

# 从代理 API 批量加载（支持 9 种主流供应商格式）
count = pool.load_from_url("http://provider.com/api?key=xxx&count=10")
print(f"加载了 {count} 个代理")

# 多供应商并发拉取 + 去重
count = pool.load_from_urls([
    "http://provider1.com/api",
    "http://provider2.com/api",
])

# 代理评分 + 自动维护
scores = pool.scores()                               # 按评分降序
result = pool.auto_maintain()                         # 淘汰低分 + 自动补充

# 持久化
pool.save_to_file("proxy_backup.json")               # 保存完整状态
pool.load_from_file("proxy_backup.json")             # 重启后恢复

# stats 输出已自动脱敏
for s in pool.stats():
    print(f"{s['proxy']} 延迟={s['latency_ms']}ms")  # user:***@host:port
```

### 编排器

```python
from resource_pool import PoolOrchestrator, PoolCombo

orch = PoolOrchestrator(ua=ua_pool, dns=dns_pool, proxy=proxy_pool)

# 一次拿全套 —— 返回 PoolCombo（属性 + 字典双访问）
combo = orch.next()
print(combo.ua)          # 属性访问
print(combo["dns_ip"])   # 字典访问
headers = {**combo}      # 解包为普通 dict

# 迭代获取
for combo in orch.combos(limit=100):
    requests.get(url, headers=combo["ua"], proxies=combo["proxy"])

# 动态管理
orch.register("backup_proxy", ProxyPool())
orch.unregister("backup_proxy")

# 健康检查所有池
orch.health_check_all()
```

---

## 架构特性

| 能力 | 说明 |
|------|------|
| **Header Profile** | 20 组完整请求头 + 自动匹配浏览器/版本号，精准模拟真实浏览器 |
| **线程安全** | UA 池 ReadWriteLock（读并发 N 倍）、Proxy 池 Lock、DNS 池 16 路缓存分片锁 |
| **异步支持** | 完整 asyncio 版：AsyncUserAgentPool / AsyncDNSResolverPool / AsyncProxyPool / AsyncPoolOrchestrator，功能与同步版完全对等 |
| **按需开关** | `thread_safe=False` 关闭所有锁，单线程脚本零开销 |
| **故障隔离** | 连续失败达阈值自动隔离，到期后试用复活（一次机会） |
| **策略校验** | `strategy` setter 类型校验，非法值立即抛 `TypeError`，避免静默失效 |
| **可插拔策略** | `StrategyProtocol` —— 传入 callable 即可自定义选择策略 |
| **编排器注册表** | `isinstance` 精确分派 + `register_dispatch` 扩展，告别 `hasattr` 探测 |
| **统一异常** | `PoolExhaustedError` / `ResourceUnhealthyError` 一把捕获 |
| **惰性导入** | `from resource_pool import X` 按需加载，不拖慢启动 |
| **凭据脱敏** | 代理 stats 输出 `user:***@host`，杜绝日志泄露 |
| **类型完整** | PEP 561 `py.typed`，IDE 智能提示全覆盖 |

---

## API 参考

### UserAgentPool

| 方法 | 说明 |
|------|------|
| `get(category="all", weighted=None, exclude=None, browser=None, os=None, min_version=None) → str` | 获取 UA。支持细粒度筛选 |
| `get_headers(category="all", weighted=None, exclude=None, browser=None, os=None, min_version=None) → dict` | 完整 Header Profile |
| `get_all(category="all", exclude=None, browser=None, os=None, min_version=None) → list[str]` | 全部 UA 列表 |
| `add(ua, category, weight=5, profile=None)` | 添加 UA（自动检测浏览器/OS/版本） |
| `remove(ua, category=None) → int` | 移除 UA |
| `count(category=None) → dict[str,int] \| int` | 统计数量 |
| `reserve(category, weighted=None) → UAReserve` | 上下文管理器 |
| `register_profile(key, headers)` | 注册自定义 Header Profile（静态方法） |
| `load_from_file(path) → int` | 从 JSON/CSV 文件批量导入 |
| `load_from_fakeua(browsers=None, os=None, limit=50) → int` | 从 fake_useragent 导入（可选依赖） |

**分类**: `desktop` / `mobile` / `tablet` / `all`

**策略**: `UAStrategy.WEIGHTED`（默认）/ `UAStrategy.UNIFORM`

> 异步版 `AsyncUserAgentPool` 具有完全相同的 API，并额外支持 `__aiter__` 异步迭代。

### DNSResolverPool

| 方法 | 说明 |
|------|------|
| `resolve(domain, record_type="A", timeout=5.0) → str` | 解析单个 IP |
| `resolve_all(domain, record_type="A", timeout=5.0) → list[str]` | 解析全部 IP |
| `get_server() → str` | 返回当前最优 DNS 服务器 IP（供编排器调用） |
| `add_server(entry)` / `remove_server(ip)` / `enable_server(ip)` | 服务器管理 |
| `health_check(timeout=3.0) → dict` | 全量健康检查 |
| `stats() → list[dict]` | 运行时状态 |
| `clear_cache()` / `close()` | 缓存清理 / 释放线程本地对象 |

**选择策略**: `SelectStrategy.LATENCY_WEIGHTED` / `ROUND_ROBIN` / `RANDOM` — 也支持 callable 自定义

### ProxyPool

| 方法 | 说明 |
|------|------|
| `get(scheme=None) → str` | 获取代理 URL |
| `get_dict(scheme=None) → dict` | requests 兼容的 proxies 字典 |
| `load_from_url(url, timeout=10, default_scheme="http", headers=None) → int` | 从代理提取 API 批量加载（支持 JSON/纯文本/带鉴权格式） |
| `load_from_urls(urls, timeout=10, ...) → int` | 多供应商并发拉取 + 去重合并 |
| `save_to_file(path) → int` | 持久化到 JSON（含运行时统计） |
| `load_from_file(path) → int` | 从 JSON 恢复代理池 |
| `add_proxy(entry)` / `remove_proxy(host, port, scheme)` / `enable_proxy(...)` | 代理管理 |
| `health_check(timeout=5.0) → dict` | 含 socket 预检 + HTTP 验证 |
| `mark_failed(host, port, scheme="http") → bool` | 手动标记代理失败，连续失败达阈值自动隔离 |
| `scores() → list[dict]` | 代理评分（延迟/成功率/稳定性），按降序排列 |
| `auto_maintain(timeout=10.0) → dict` | 自动淘汰低分代理 + 低于阈值补充 |
| `stats() → list[dict]` | 运行时状态（凭据已脱敏） |

**选择策略**: `ProxyStrategy.LATENCY_WEIGHTED` / `ROUND_ROBIN` / `RANDOM` — 也支持 callable 自定义

> 异步版 `AsyncProxyPool` 具有等价 API，网络 I/O 通过 `asyncio.to_thread` 异步化，不阻塞事件循环。

### PoolOrchestrator

| 方法 | 说明 |
|------|------|
| `next() → PoolCombo` | 获取一组组合资源（属性 + 字典双访问） |
| `combos(limit=None) → Iterator[PoolCombo]` | 组合资源迭代器 |
| `register(name, pool)` / `unregister(name)` | 动态管理池 |
| `health_check_all() → dict` | 健康检查所有池 |
| `register_dispatch(pool_type, method_name)` | 注册自定义池分派（类方法） |

**PoolCombo** 支持：属性访问 `combo.ua`、字典访问 `combo["ua"]`、解包 `{**combo}`、迭代 `for k, v in combo`

---

## 统一异常处理

```python
from resource_pool import PoolExhaustedError, ResourceUnhealthyError

try:
    ip = dns_pool.resolve("blocked.example.com")
except PoolExhaustedError:
    print("所有 DNS 都失败了")       # DNS / UA / Proxy 耗尽都可统一捕获
except ResourceUnhealthyError:
    print("单台 DNS 挂了但已自动隔离")  # 不影响其他服务器
```

编排器 `combos()` 在池耗尽时记录 WARNING 日志后优雅终止；
其他异常记录 ERROR 日志后终止，不再静默丢弃。

> 详见 [EXCEPTIONS.md](docs/EXCEPTIONS.md) 异常体系文档与代码审查报告。

---

## 高并发建议

- UA 池使用 ReadWriteLock，读多写少场景下读并发度从 1 提升至 N（1000 并发 ~111k ops/s）
- DNS 缓存采用 16 路分片锁，1000 并发下 P99 延迟仅 0.027ms
- 百级以上并发建议为不同业务线创建独立池实例，进一步减少锁争用
- 单线程脚本可传 `thread_safe=False` 关闭所有锁开销
- DNS 池配合缓存命中率可大幅降低锁持有时间
- 编排器内部 `_fetch_from_pool` 在锁外执行，并发友好
- 异步版 `AsyncProxyPool.get()` 选择逻辑在锁外执行（纯计算），仅状态读/写持锁，避免协程串行化
- 长期运行的服务可定期调用 `dns_pool.close()` 释放退出的线程本地对象

---

## 项目结构

```
resource_pool/
├── pyproject.toml
├── resource_pool/                  # 统一入口 + 框架层
│   ├── __init__.py                 # 惰性导入 + __all__
│   ├── base.py                     # ResourcePool ABC + StrategyProtocol + ReadWriteLock
│   ├── base_async.py               # AsyncResourcePool ABC + AsyncReadWriteLock
│   ├── exceptions.py               # 公共异常基类
│   ├── orchestrator.py             # 编排器 + PoolCombo
│   └── orchestrator_async.py       # AsyncPoolOrchestrator
├── user_agent_pool/
│   ├── __init__.py
│   ├── agents.py                   # 22 UA + 20 Header Profile 组 + UA 元数据解析
│   ├── exceptions.py
│   ├── pool.py                     # UserAgentPool + UAStrategy
│   └── pool_async.py               # AsyncUserAgentPool
├── dns_resolver_pool/
│   ├── __init__.py
│   ├── servers.py                  # 14 台国内外 DNS
│   ├── exceptions.py
│   ├── pool.py                     # DNSResolverPool + SelectStrategy + 16路分片锁
│   └── pool_async.py               # AsyncDNSResolverPool
├── proxy_pool/
│   ├── __init__.py
│   ├── servers.py                  # ProxyEntry TypedDict
│   ├── exceptions.py
│   ├── pool.py                     # ProxyPool + ProxyStrategy + 评分系统
│   └── pool_async.py               # AsyncProxyPool
├── examples/
│   ├── real_crawler_demo.py        # 同步爬虫集成示例
│   ├── async_integration.py        # httpx + aiohttp 异步集成
│   ├── scrapy_integration.py       # Scrapy Middleware 集成
│   ├── simple_requests_demo.py     # 单线程零开销示例
│   └── stress_test.py              # 极端压力测试
├── docs/
│   ├── EXCEPTIONS.md               # 异常体系文档
│   ├── PRODUCTION.md               # 生产部署指南（配置/监控/排障/架构图）
│   └── UPGRADE_PLAN.md             # 升级规划
├── .github/
│   └── workflows/
│       └── test.yml                # CI/CD 多版本矩阵测试
├── .pre-commit-config.yaml         # ruff pre-commit hooks
└── tests/                          # 274 个测试
```

---

## 扩展

### 自定义选择策略

```python
from resource_pool import StrategyProtocol

class HighestWeight:
    """永远选权重最高的"""
    def __call__(self, servers):
        return iter(sorted(servers, key=lambda s: s.weight, reverse=True))

dns_pool.strategy = HighestWeight()
proxy_pool.strategy = HighestWeight()
```

### 自定义资源池

```python
from resource_pool import ResourcePool

class CookiePool(ResourcePool):
    """继承 ResourcePool ABC，接入编排器生态"""
    def __len__(self): ...
    def __repr__(self): ...
    def get(self, domain): ...
```

---

## 更新日志

### v1.0.4 (2026-05-26)

- 🛡️ **AsyncProxyPool 锁粒度优化**：`get()`/`get_dict()` 选择逻辑移出锁外，内部方法（`_get_alive`/`_try_revive`/`_on_success`）各自加锁，与同步版并发模型一致，避免协程串行化
- 🛡️ **AsyncDNSResolverPool TOCTOU 修复**：`_try_revive` 时间戳检查纳入锁范围，与同步版对齐
- 🛡️ **协程检测健壮化**：`_fetch_from_pool_async` 使用 `inspect.isawaitable()` 替代 `asyncio.iscoroutine()`
- 🛡️ **编排器弃用警告**：同步/异步版 hasattr 回退添加 `logger.warning` 弃用提示，引导用户使用 `register_dispatch()`
- ⚡ **加权选择优化**：`_weighted_pick` 使用 `random.choices` 替代手动累积，消除浮点误差
- 📝 注释与测试命名修正

### v1.0.3 (2026-05-26)

- 🚀 **AsyncProxyPool 功能补齐**：`StrategyProtocol` callable 策略支持、`scores()` 评分、`load_from_url()`/`load_from_urls()` 异步加载、`save_to_file()`/`load_from_file()` 持久化、`auto_maintain()` 自动维护、`strategy` property
- 🚀 **AsyncUserAgentPool 功能补齐**：`UAStrategy` 枚举 + `weighted` 参数、`get_all()`、`register_profile()`（委托同步版）、`load_from_file()`、`load_from_fakeua()`、`strategy` property
- 🛡️ **`__repr__` 锁粒度一致**：`ProxyPool` / `DNSResolverPool` 的 `alive` 和 `total` 统一在持锁下计算
- 🛡️ **编排器异常完整性**：`PoolOrchestrator.combos()` 区分 `PoolExhaustedError`（显式 raise）与其他异常（ERROR 日志后 raise）
- 🔧 **CI glob 修复**：`paths-ignore` 中 `"**.md"` → `"**/*.md"`
- 🔧 **pre-commit 升级**：ruff `v0.11.0` → `v0.11.8`
- 🧹 **残留清理**：删除 `test_result.txt`

### v1.0.2 (2026-05-26)

- 🐛 **异步编排器 PoolCombo 对齐**：`AsyncPoolOrchestrator.next()` 返回 `PoolCombo` 而非 `dict`，与同步版 API 一致
- 🐛 **异步 UA 池元数据拷贝**：`_init_defaults` 改用 `_copy_agent_entry` 方法，确保 `browser`/`os`/`version` 字段正确拷贝
- 🐛 **示例代码字段名修复**：`simple_requests_demo.py` 中 `dns_ip` → `dns`，匹配编排器键名
- 📝 **注释补充**：`AsyncDNSResolverPool._try_revive` 添加 asyncio 原子安全说明

### v1.0.1 (2026-05-26)

- 🛡️ **异步池并发安全加固**：`AsyncProxyPool` 6 个方法改为 `async def` + `asyncio.Lock` 保护
- 🛡️ **AsyncDNSResolverPool 策略对称**：添加 `StrategyProtocol` 支持，与同步版 API 对齐
- 🛡️ **AsyncUserAgentPool 功能补齐**：添加 `browser`/`os`/`min_version` 细粒度筛选 + `_build_headers` 自动 Profile 匹配
- 🛡️ **可观测性提升**：`_parse_response` 中 `JSONDecodeError` 添加 debug 日志
- 📝 **文档更新**：UPGRADE_PLAN 第六阶段报告、PRODUCTION 异步锁层级说明

### v1.0.0 (2026-05-26)

- 🚀 **Header Profile 自动匹配**：`get_headers()` 根据 UA 的浏览器+版本号自动选择最接近的 Profile 组
- 📝 **生产部署指南**：`docs/PRODUCTION.md` — TOML 配置模板 + Prometheus 监控 + 排障 Q&A + 架构图
- 🔧 **CI/CD 质量门禁**：`.github/workflows/test.yml` 多版本矩阵测试 (3.10-3.13) + `.pre-commit-config.yaml` ruff hooks
- 🛡️ **Python 3.13 free-threaded 兼容标注**：latency_ms 写入处加锁，兼容无 GIL 模式

### v0.7.0 (2026-05-26)

- 🚀 **PoolCombo**：编排器 `next()/combos()` 返回 `PoolCombo` 对象，支持属性访问（`combo.ua`）+ 字典访问 + 解包
- 🚀 **代理持久化**：`ProxyPool.save_to_file()` / `load_from_file()` JSON 格式，含运行时统计
- 🚀 **多供应商拉取**：`ProxyPool.load_from_urls()` ThreadPoolExecutor 并发拉取 + 去重合并
- 🚀 **fake_useragent 集成**：`UserAgentPool.load_from_fakeua()` 可选依赖，批量导入
- 🚀 **UA 细粒度筛选**：`get(browser="chrome", os="windows", min_version=120)` 浏览器/OS/版本号过滤
- 🚀 **UA 元数据自动检测**：`add()` 自动提取浏览器/OS/版本信息
- 🚀 **集成示例**：Scrapy Middleware + requests 单线程零开销示例
- 📝 README 全面更新：API 参考、架构特性、项目结构

### v0.6.0 (2026-05-25)

- 🚀 **异步支持**：AsyncUserAgentPool / AsyncDNSResolverPool / AsyncProxyPool / AsyncPoolOrchestrator
- 🚀 **读写锁**：UA 池 ReadWriteLock 替换 Lock，读并发度从 1 提升至 N
- 🚀 **DNS 16路分片锁**：缓存操作按域名首字符分片，1000 并发 P99 延迟 0.027ms
- 🚀 **编排器注册表**：`isinstance` + `register_dispatch` 精确分派，告别 `hasattr` 探测
- 🚀 **代理评分**：`ProxyState.score` + `ProxyPool.scores()` + `auto_maintain()` 自动淘汰+补充
- 🚀 **UA 批量导入**：`UserAgentPool.load_from_file()` 支持 JSON/CSV
- 🚀 **基准压力测试**：100/500/1000 并发吞吐量基准报告
- 🛡️ `CATEGORY_ALL` 常量替代魔法字符串、Profile 锁粒度优化

### v0.5.1 (2026-05-25)

- 🛡️ 修复 ProxyPool / DNSResolverPool `_try_revive` 竞态条件
- 🛡️ `PoolOrchestrator.combos()` 区分 PoolExhaustedError 与非预期异常，不再静默终止
- 🛡️ `PoolOrchestrator.__repr__` 加锁，保证线程安全一致性
- 🛡️ `UserAgentPool._init_defaults` 移除双重 `cast` hack
- 🛡️ DNSResolverPool 构造函数类型标注支持 `StrategyProtocol`
- 🛡️ `strategy` setter 添加类型校验，非法值抛 `TypeError`
- 📝 `user_agent_pool/exceptions.py` 补充模块文档字符串
- 📝 `AVAILABLE_PROFILES` 标记为导入时快照，引导使用 `get_available_profiles()`
- 📝 `ResourcePool` 基类添加 `__init_subclass__` 钩子和 `_lock` 初始化文档

### v0.5.0 (2026-05-25)

- 🎉 首次公开发布：User-Agent 池 + DNS 解析器池 + 代理池 + 编排器
- 完整的异常继承体系（统一捕获 + 精确捕获）
- 线程安全、故障隔离、可插拔策略、惰性导入

---

## License

MIT

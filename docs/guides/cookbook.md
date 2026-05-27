# 场景实战

> 目标读者：日常写爬虫的工程师，遇到具体需求时来找配方。

每个场景给出"最短可运行代码"——你复制走改改就能用。

> **双路径提示**：本指南使用完整版 API（`from resource_pool import UserAgentPool` 等）。日常简单轮换推荐用[短别名](quickstart.md)：`import resource_pool; ua = resource_pool.UA()`。两条路径共享同一套底层实现，随时混合使用。

---

## User-Agent 池

### 只轮换 User-Agent

```python
from user_agent_pool import UserAgentPool

ua = UserAgentPool()
# 创建时刻自动加载 854 条 UA 种子（ua_seeds.json），覆盖 Chrome/Edge/Firefox/Safari + 桌面/移动/平板
# 零件池随机重组 → 31,496 独立 UA → 193,633 完整 headers
for _ in range(10):
    print(ua.get())
# 每次输出不同 UA，加权随机（权重高的更常出现）
```

### 完整请求头（反反爬推荐）

单换 UA 不够——真实浏览器携带 Accept、Sec-Ch-Ua、Accept-Language 等 14 项请求头。

**v1.0.9 零件池深度拆解**：`get_headers()` 将 854 条 UA 拆解为 OS 串/版本令牌/WebKit/Mobile Build 四个维度，跨零件随机重组 → 31,496 独立 UA → 193,633 完整 headers 组合。引擎约束自动保证：Chrome 的 Sec-Ch-Ua 不会错配 Firefox 的 Accept-Language，UA 版本号与 Sec-Ch-Ua 版本号始终同步。

```python
headers = ua.get_headers("desktop")
# {"User-Agent": "...", "Accept": "...", "Sec-Ch-Ua": "...", ...}
requests.get(url, headers=headers)
```

支持 `desktop` / `mobile` / `tablet` 三类设备分组，自动选取对应派系模板。

### 按浏览器/系统/版本筛选

```python
ua.get(browser="chrome", os="windows", min_version=120)
ua.get(browser="firefox", os="macos")
```

前提是 UA 已带元数据——`add()` 时自动检测（`parse_ua_metadata`），内置 UA 和 jsonl 加载时自动补全。

> 854 条 UA 种子已全部标注元数据，`browser`/`os`/`min_version` 筛选零等待。

### 暂存器模式（取出用完自动归还）

高并发下避免两个请求拿到同一个 UA：

```python
with ua.reserve("desktop") as agent:
    # agent 被暂时从池中移除，其他请求拿不到
    requests.get(url, headers={"User-Agent": agent})
# 离开 with 块自动归还
```

### 从文件批量导入 UA

```python
# JSON 格式：[{"ua": "...", "category": "desktop", "weight": 5}]
ua.load_from_file("ua_list.json")

# JSONL 格式：每行一个完整 headers JSON 对象（如 headers_pool.jsonl）
# jsonl 每行将完整请求头（Accept/Accept-Language/Cache-Control 等）作为原子单位导入
# ✅ 字段间语义一致，不会出现 Chrome 的 Accept 配 Firefox 的 Accept-Language
ua.load_from_file("headers_pool.jsonl")

# CSV 格式：ua,category,weight
ua.load_from_file("ua_list.csv")

# 从 fake_useragent 库导入（需先 pip install fake_useragent）
# 在线路径：fake_useragent UA + 派系引擎组装请求头
# 本地降级：返回 < 5 条时自动回退内置 830+ 条 jsonl UA
ua.load_from_fakeua(limit=100, browsers=["chrome", "firefox"])
```

### 注册自定义 Header Profile

```python
ua.register_profile("my_bot", {
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
})
ua.add("MyBot/2.0", "desktop", profile="my_bot")
ua.get_headers("desktop")  # 立即生效
```

---

## DNS 解析器池

### 基本用法

```python
from dns_resolver_pool import DNSResolverPool, SelectStrategy

dns = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
dns.health_check()                       # 探测 14 台 DNS

ip = dns.resolve("www.example.com")      # 最优一台 DNS 解析的结果
ips = dns.resolve_all("www.example.com") # 所有 IP
```

### 缓存策略

```python
dns = DNSResolverPool(cache_ttl=600, max_cache_size=8192)

dns.resolve("www.example.com")  # 真实查询
dns.resolve("www.example.com")  # 缓存命中，< 0.1ms

dns.clear_cache()               # 强制刷新
```

### 国内 / 海外 DNS

```python
# 仅国内
DNSResolverPool(regions=("domestic",))
# 仅海外
DNSResolverPool(regions=("overseas",))
# 全部（默认）
DNSResolverPool(regions=("domestic", "overseas"))
```

### 监控 DNS 状态

```python
for s in dns.stats():
    print(f"{s['name']:12s} {s['ip']:15s} "
          f"延迟={s['latency_ms']:5.1f}ms 可用={s['enabled']}")
```

---

## 代理池

### 基本用法

```python
from proxy_pool import ProxyPool, ProxyStrategy

proxy = ProxyPool(strategy=ProxyStrategy.LATENCY_WEIGHTED)

# 添加代理
proxy.add_proxy({"scheme": "http", "host": "1.2.3.4", "port": 8080})
proxy.add_proxy({
    "scheme": "socks5", "host": "5.6.7.8", "port": 1080,
    "username": "user", "password": "pass",
})

proxy.health_check()  # 探测所有代理

# 获取
url = proxy.get()                # "http://1.2.3.4:8080"
url = proxy.get(scheme="socks5") # 按协议筛选

# requests 用
proxies = proxy.get_dict()  # {"http": "...", "https": "..."}
requests.get(url, proxies=proxies)
```

### 从供应商 API 批量加载

```python
# 单个供应商
n = proxy.load_from_url("http://provider.com/api?key=xxx&count=20")

# 多个供应商并发拉取 + 自动去重
n = proxy.load_from_urls([
    "http://provider1.com/api?key=xxx",
    "http://provider2.com/api?key=yyy",
])
```

支持 9 种主流格式自动识别（JSON 数组/对象/嵌套、纯文本 ip:port）。

### 代理生命周期管理

```python
# 标记失败（连续 N 次自动隔离）
proxy.mark_failed("1.2.3.4", 8080)

# 评分系统
for s in proxy.scores():
    print(f"{s['proxy']:30s} 评分={s['score']:5.1f}")

# 自动维护：淘汰低分 + 低于阈值自动补充
proxy = ProxyPool(min_alive=10, auto_refill_url="http://api/...")
result = proxy.auto_maintain()
# → {"removed": 2, "refilled": 5, "alive": 13}
```

### 持久化（重启后恢复）

```python
proxy.save_to_file("backup.json")   # 保存含运行时统计
proxy.load_from_file("backup.json") # 恢复（含延迟、成功率等）
```

---

## 编排器

### 一次拿全套

```python
from resource_pool import PoolOrchestrator

orch = PoolOrchestrator(ua=ua_pool, dns=dns_pool, proxy=proxy_pool)

combo = orch.next()
# combo.ua      → User-Agent 字符串
# combo["ua"]   → 同上（字典访问）
# combo["proxy"] → {"http": "...", "https": "..."}
# {**combo}     → 解包为普通 dict
```

### 批量迭代

```python
for combo in orch.combos(limit=100):
    requests.get(
        url,
        headers=combo["ua"],
        proxies=combo["proxy"],
    )
```

编排器 `combos()` 在任一子池耗尽时记录 WARNING 后优雅终止。

### 动态管理池

```python
orch.register("backup_proxy", ProxyPool())
orch.unregister("backup_proxy")
```

---

## 异步版

同步版和异步版 API 完全一致，类名前加 `Async` 即可：

```python
from resource_pool import AsyncUserAgentPool, AsyncPoolOrchestrator

async def crawl():
    ua = AsyncUserAgentPool()
    proxy = AsyncProxyPool()

    async with ua.reserve("desktop") as agent:
        ...

    async for combo in AsyncPoolOrchestrator(
        ua=ua, proxy=proxy
    ).combos(limit=100):
        ...
```

详见 [async_integration.py](../../examples/async_integration.py) 完整异步示例。

### 异步代理池注意事项

`AsyncProxyPool` 的 IO 操作（`load_from_url`、`save_to_file` 等）通过 `asyncio.to_thread` 在后台线程执行，不阻塞事件循环。`get()` 的选择逻辑在锁外执行，仅状态读写持锁，避免协程串行化。

---

## Scrapy 集成

完整 Middleware 示例见 [scrapy_integration.py](../../examples/scrapy_integration.py)：

```
examples/scrapy_integration.py    ← 可运行的 Middleware + Spider
```

核心思路：在 `process_request` 中设置 `request.headers` 和 `request.meta["proxy"]`，在 `process_response` / `process_exception` 中调用 `mark_failed`。

---

## 自定义策略

三种池都接受 callable 作为策略：

```python
from resource_pool import StrategyProtocol

class PickFastest:
    def __call__(self, items):
        return iter(sorted(items, key=lambda x: x.latency_ms))

proxy.strategy = PickFastest()
dns.strategy = PickFastest()
```

---

## 线程安全开关

```python
# 多线程场景（默认）
pool = UserAgentPool(thread_safe=True)

# 单线程脚本——所有锁替换为空操作，零开销
pool = UserAgentPool(thread_safe=False)
```

---

## 统一异常处理

```python
from resource_pool import PoolExhaustedError, ResourceUnhealthyError

try:
    ip = dns.resolve("example.com")
except PoolExhaustedError:
    # DNS / UA / Proxy 耗尽都可统一捕获
    print("所有资源均已耗尽")
except ResourceUnhealthyError:
    # 单个资源挂了但已自动隔离
    print("某个资源不健康，已自动处理")
```

---

## API 速查

### UserAgentPool

| 方法 | 说明 |
|------|------|
| `get(category, weighted, exclude, browser, os, min_version) → str` | 获取 UA |
| `get_headers(category, ...) → dict` | 完整 Header Profile |
| `get_all(category, ...) → list[str]` | 全部 UA |
| `add(ua, category, weight=5, profile=None, headers=None)` | 添加 UA（可附带内联完整请求头） |
| `remove(ua, category=None) → int` | 移除 |
| `count(category=None) → dict[str,int] \| int` | 统计 |
| `reserve(category, weighted=None) → UAReserve` | 暂存器 |
| `register_profile(key, headers)` | 注册 Header Profile（静态） |
| `load_from_file(path) → int` | JSON/JSONL/CSV 导入 |
| `load_from_fakeua(limit=50, ...) → int` | fake_useragent 导入（远程优先+自动降级） |

### DNSResolverPool

| 方法 | 说明 |
|------|------|
| `resolve(domain, record_type="A", timeout=5.0) → str` | 解析单个 IP |
| `resolve_all(domain, ...) → list[str]` | 解析全部 IP |
| `get_server() → str` | 当前最优 DNS IP |
| `add_server(entry)` / `remove_server(ip)` / `enable_server(ip)` | 服务器管理 |
| `health_check(timeout=3.0) → dict` | 全量探测 |
| `stats() → list[dict]` | 运行时状态 |
| `clear_cache()` / `close()` | 缓存清理 / 释放线程本地对象 |

### ProxyPool

| 方法 | 说明 |
|------|------|
| `get(scheme=None) → str` | 获取代理 URL |
| `get_dict(scheme=None) → dict` | requests 兼容字典 |
| `load_from_url(url, ...) → int` | 从 API 批量加载 |
| `load_from_urls(urls, ...) → int` | 多供应商并发拉取 |
| `save_to_file(path) → int` / `load_from_file(path) → int` | 持久化 |
| `add_proxy(entry)` / `remove_proxy(host, port, scheme)` | 代理管理 |
| `mark_failed(host, port, scheme) → bool` | 标记失败 |
| `scores() → list[dict]` | 代理评分 |
| `auto_maintain(timeout) → dict` | 自动淘汰+补充 |
| `stats() → list[dict]` | 运行时状态（凭据脱敏） |

### PoolOrchestrator

| 方法 | 说明 |
|------|------|
| `next() → PoolCombo` | 一组组合资源 |
| `combos(limit=None) → Iterator[PoolCombo]` | 迭代获取 |
| `register(name, pool)` / `unregister(name)` | 动态管理 |
| `health_check_all() → dict` | 全量健康检查 |
| `register_dispatch(pool_type, method_name)` | 注册自定义池分派 |

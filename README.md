# Resource Pool

> 一套可扩展的网络资源池框架，为爬虫工程提供开箱即用的资源调度能力。

**爬虫三件套**：User-Agent 池 + DNS 解析器池 + 代理池，内置编排器一键协同。

---

## 为什么需要资源池

| 资源类型 | 无池状态 | 有池效果 |
|---------|---------|---------|
| User-Agent | 固定一个，高频请求秒被识别 | 22 个 UA 按设备分类加权随机 + 完整 Header Profile 组，模拟真实浏览器 |
| DNS 解析 | 单点 DNS 频次过高被限流 | 14 台 DNS 轮换解析 + 延迟排序 + 故障隔离 + LRU 缓存 + 自动复活 |
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
# → {"ua": {"User-Agent": "...", "Accept": "..."}, "dns_ip": "8.8.8.8", "proxy": {"http": "...", "https": "..."}}

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

# stats 输出已自动脱敏
for s in pool.stats():
    print(f"{s['proxy']} 延迟={s['latency_ms']}ms")  # user:***@host:port
```

### 编排器

```python
from resource_pool import PoolOrchestrator

orch = PoolOrchestrator(ua=ua_pool, dns=dns_pool, proxy=proxy_pool)

# 一次拿全套
combo = orch.next()
# → {"ua": {"User-Agent": "...", ...}, "dns_ip": "...", "proxy": {"http": "...", "https": "..."}}

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
| **线程安全** | 全部池 `threading.Lock` 保护，DNS 池 `threading.local` 每线程独立 Resolver |
| **按需开关** | `thread_safe=False` 关闭所有锁 + thread-local，单线程脚本零开销 |
| **故障隔离** | 连续失败达阈值自动隔离，到期后试用复活（一次机会） |
| **可插拔策略** | `StrategyProtocol` —— 传入 callable 即可自定义选择策略 |
| **统一异常** | `PoolExhaustedError` / `ResourceUnhealthyError` 一把捕获 |
| **惰性导入** | `from resource_pool import X` 按需加载，不拖慢启动 |
| **凭据脱敏** | 代理 stats 输出 `user:***@host`，杜绝日志泄露 |
| **类型完整** | PEP 561 `py.typed`，IDE 智能提示全覆盖 |

---

## API 参考

### UserAgentPool

| 方法 | 说明 |
|------|------|
| `get(category="all", weighted=None, exclude=None) → str` | 获取 UA。weighted=None 使用池级策略 |
| `get_headers(category="all", weighted=None, exclude=None) → dict` | 完整 Header Profile |
| `get_all(category="all", exclude=None) → list[str]` | 全部 UA 列表 |
| `add(ua, category, weight=5, profile=None)` | 添加 UA |
| `remove(ua, category=None) → int` | 移除 UA |
| `count(category=None) → dict[str,int] \| int` | 统计数量 |
| `reserve(category, weighted=None) → UAReserve` | 上下文管理器 |
| `register_profile(key, headers)` | 注册自定义 Header Profile |

**分类**: `desktop` / `mobile` / `tablet` / `all`

**策略**: `UAStrategy.WEIGHTED`（默认）/ `UAStrategy.UNIFORM`

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
| `load_from_url(url, timeout=10, default_scheme="http", headers=None) → int` | 从代理提取 API 批量加载代理（支持 JSON/纯文本/带鉴权格式） |
| `add_proxy(entry)` / `remove_proxy(host, port, scheme)` / `enable_proxy(...)` | 代理管理 |
| `health_check(timeout=5.0) → dict` | 含 socket 预检 + HTTP 验证 |
| `stats() → list[dict]` | 运行时状态（凭据已脱敏） |

**选择策略**: `ProxyStrategy.LATENCY_WEIGHTED` / `ROUND_ROBIN` / `RANDOM` — 也支持 callable 自定义

### PoolOrchestrator

| 方法 | 说明 |
|------|------|
| `next() → dict` | 获取一组组合资源 |
| `combos(limit=None) → Iterator` | 组合资源迭代器 |
| `register(name, pool)` / `unregister(name)` | 动态管理池 |
| `health_check_all() → dict` | 健康检查所有池 |

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

---

## 高并发建议

- 百级以上并发建议为不同业务线创建独立池实例，减少锁争用
- 单线程脚本可传 `thread_safe=False` 关闭所有锁开销
- DNS 池配合缓存命中率可大幅降低锁持有时间
- 编排器内部 `_fetch_from_pool` 在锁外执行，并发友好
- 长期运行的服务可定期调用 `dns_pool.close()` 释放退出的线程本地对象

---

## 项目结构

```
resource_pool/
├── pyproject.toml
├── resource_pool/                  # 统一入口 + 框架层
│   ├── __init__.py                 # 惰性导入 + __all__
│   ├── base.py                     # ResourcePool ABC + StrategyProtocol
│   ├── exceptions.py               # 公共异常基类
│   └── orchestrator.py             # 编排器
├── user_agent_pool/
│   ├── __init__.py
│   ├── agents.py                   # 22 UA + 22 Header Profile 组
│   ├── exceptions.py
│   └── pool.py                     # UserAgentPool + UAStrategy
├── dns_resolver_pool/
│   ├── __init__.py
│   ├── servers.py                  # 14 台国内外 DNS
│   ├── exceptions.py
│   └── pool.py                     # DNSResolverPool + SelectStrategy
├── proxy_pool/
│   ├── __init__.py
│   ├── servers.py                  # ProxyEntry TypedDict
│   ├── exceptions.py
│   └── pool.py                     # ProxyPool + ProxyStrategy
└── tests/                          # 142 个测试
    ├── test_user_agent_pool.py     # 26 tests
    ├── test_dns_resolver_pool.py   # 27 tests
    ├── test_proxy_pool.py          # 51 tests (含 load_from_url)
    ├── test_orchestrator.py        # 10 tests
    ├── test_concurrency.py         # 7 tests
    └── test_real_world.py          # 23 tests
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

## License

MIT

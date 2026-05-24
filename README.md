# Resource Pool

> 一套可扩展的网络资源池框架，为爬虫工程提供开箱即用的资源调度能力。

当前内置 **User-Agent 池**（含完整 Header Profile 组）与 **DNS 解析器池**，框架预留适配器层可接入 aiohttp / httpx / Scrapy。

---

## 为什么需要资源池

| 资源类型 | 无池状态 | 有池效果 |
|---------|---------|---------|
| User-Agent | 固定一个，高频请求秒被识别 | 按设备分类加权随机 + 完整 Header Profile 组，模拟真实浏览器 |
| DNS 解析 | 单点 DNS 频次过高被限流 | 14 台 DNS 轮换解析 + 延迟排序 + 故障隔离 + 自动复活 |

---

## 安装

```bash
# 基础安装（UA 池 + DNS 池）
pip install -e /path/to/resource_pool

# 含框架适配器
pip install -e /path/to/resource_pool[aiohttp,httpx]

# 开发环境（含测试）
pip install -e /path/to/resource_pool[dev]
```

Python ≥ 3.10，依赖 `dnspython ≥ 2.6`。

---

## 快速上手

### User-Agent 资源池

```python
from user_agent_pool import UserAgentPool

pool = UserAgentPool()

# 加权随机拿一个 desktop UA
ua = pool.get("desktop")

# 均匀随机
ua = pool.get("mobile", weighted=False)

# 获取完整请求头 Profile（推荐反爬场景使用）
headers = pool.get_headers("desktop")
# → {"User-Agent": "...", "Accept": "...", "Accept-Language": "...", "Sec-Ch-Ua": "...", ...}
requests.get(url, headers=headers)

# 统计各分类数量
print(pool.count())   # {'desktop': 10, 'mobile': 8, 'tablet': 4}

# 上下文管理器 —— 取出时移除，用完自动归还
with pool.reserve("desktop") as ua:
    requests.get(url, headers={"User-Agent": ua})

# 动态增删（支持可选 Header Profile）
pool.add("MyCrawlerBot/2.0", "desktop", weight=3, profile="chrome_131_win")
pool.remove("MyCrawlerBot/2.0")
```

### DNS 解析器资源池

```python
from dns_resolver_pool import DNSResolverPool, SelectStrategy

pool = DNSResolverPool(strategy=SelectStrategy.LATENCY_WEIGHTED)
pool.health_check(timeout=3.0)

# 解析单个最优 IP
ip = pool.resolve("www.baidu.com")

# 解析全部 IP
ips = pool.resolve_all("www.baidu.com")

# 查看各 DNS 服务器运行时状态
for s in pool.stats():
    print(f"{s['name']:12s} 延迟={s['latency_ms']:5.1f}ms  可用={s['enabled']}")
```

---

## API 参考

### UserAgentPool

| 方法 | 说明 |
|------|------|
| `get(category="all", weighted=True) → str` | 获取一个 UA |
| `get_headers(category="all", weighted=True) → dict[str,str]` | 获取完整 Header Profile |
| `get_all(category="all") → list[str]` | 获取该分类全部 UA |
| `add(ua, category, weight=5, profile=None)` | 添加 UA（可选 profile） |
| `remove(ua, category=None) → int` | 移除 UA，返回移除数 |
| `count(category=None) → dict[str,int]` | 统计各分类数量 |
| `reserve(category, weighted) → UAReserve` | 上下文管理器 |

**分类**：`desktop` / `mobile` / `tablet` / `all`

### DNSResolverPool

| 方法 | 说明 |
|------|------|
| `resolve(domain, record_type="A", timeout=5.0) → str` | 解析单个 IP |
| `resolve_all(domain, record_type="A", timeout=5.0) → list[str]` | 解析全部 IP |
| `add_server(entry: ServerEntry)` | 添加 DNS 服务器 |
| `remove_server(ip) → bool` | 移除服务器 |
| `enable_server(ip) → bool` | 重新启用 |
| `health_check(timeout=3.0) → dict[str,str]` | 全量健康检查 |
| `stats() → list[dict]` | 运行时状态 |
| `clear_cache()` | 清空 DNS 缓存 |

**选择策略**：

| 策略值 | 行为 |
|--------|------|
| `SelectStrategy.LATENCY_WEIGHTED` | 低延迟 + 高权重优先（默认） |
| `SelectStrategy.ROUND_ROBIN` | 严格轮流 |
| `SelectStrategy.RANDOM` | 均匀随机 |

运行时切换：`pool.strategy = SelectStrategy.ROUND_ROBIN`

---

## 项目结构

```
resource_pool/
├── pyproject.toml
├── README.md
├── resource_pool/            # 统一入口
│   └── __init__.py
├── user_agent_pool/
│   ├── __init__.py
│   ├── exceptions.py
│   ├── agents.py             # UA 数据集 + Header Profile 定义
│   └── pool.py
├── dns_resolver_pool/
│   ├── __init__.py
│   ├── exceptions.py
│   ├── servers.py
│   └── pool.py
└── tests/
    ├── __init__.py
    ├── test_user_agent_pool.py
    └── test_dns_resolver_pool.py
```

---

## 扩展指南

### 添加自定义 DNS 服务器

```python
pool.add_server({
    "ip": "10.0.0.53",
    "name": "公司内网 DNS",
    "region": "private",
    "weight": 10,
})
```

### 自定义健康检查逻辑

```python
class MyPool(DNSResolverPool):
    def _probe_server(self, state, timeout):
        # 只关心国内域名解析速度
        return super()._probe_server(state, timeout) and "cn" in state.region
```

---

## License

MIT

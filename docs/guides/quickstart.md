# 5 分钟快速上手

> 目标读者：刚接触爬虫，想要一个"拿来就能用"的资源调度工具。

本指南不预设你了解资源池、线程安全、异步编程——跟着走就能跑起来。

---

## 1. 安装

```bash
pip install git+https://github.com/nianchen8/resource-pool.git
```

Python ≥ 3.10 即可，只有一个硬依赖（`dnspython`）。

---

## 2. 第一个 User-Agent 轮换

固定 UA 是爬虫第一课被反的原因。只需一个 import：

```python
import resource_pool

ua = resource_pool.UA()
print(ua.pick())           # 默认 desktop
print(ua.pick("mobile"))   # 限定移动端
```

每次 `pick()` 返回不同 UA，自动加权随机——常用 UA 命中率更高。

> 池创建时已自动加载 854 条 UA 种子（ua_seeds.json），覆盖 Chrome/Edge/Firefox/Safari 4 引擎 × 7 平台。
> 854 条 UA 拆解为 OS 串/版本令牌/WebKit/Mobile Build 四个零件维度，跨零件随机重组 → 31,496 独立 UA → 193,633 完整 headers 组合。

> 需要完整请求头？改用 `ua.headers()` 即可——派系引擎实时组装 14 项请求头并随机选取可变字段。

> 需要细粒度筛选（浏览器/版本号）？[cookbook → UA 池](cookbook.md#user-agent-池)。

---

## 3. 第一个 DNS 解析

单点 DNS 频次过高会被限流，14 台轮换：

```python
import resource_pool

dns = resource_pool.DNS()
ip = dns.resolve("www.example.com")  # 自动选取最优 DNS，启动前自动健康检查
```

健康检查自动触发，不用手动调用。解析结果自动缓存 5 分钟。

---

## 4. 第一个代理

```python
import resource_pool

# 创建时直接传入代理（自动做健康检查）
proxy = resource_pool.Proxy("1.2.3.4:8080")

# 也可以先创建再添加
proxy = resource_pool.Proxy()
proxy.add("1.2.3.4:8080")

url = proxy.pick()  # "http://1.2.3.4:8080"
```

健康检查和故障隔离自动完成——首次使用时自动探测，失败的代理自动隔离、到期复活。

> 需要 socks5 代理？从供应商 API 批量加载？[cookbook → 代理池](cookbook.md#代理池)。

---

## 5. 三件事一起做

```python
import resource_pool

ua = resource_pool.UA()
proxy = resource_pool.Proxy("1.2.3.4:8080")
dns = resource_pool.DNS()

# 一行拿全套
c = resource_pool.combo(ua=ua, dns=dns, proxy=proxy)

# c.ua      → dict (完整请求头)
# c.dns     → str  (DNS 服务器 IP)
# c.proxy   → dict (requests 兼容格式)

import requests
requests.get("https://httpbin.org/ip", headers=c.ua, proxies=c.proxy)
```

---

## 6. 有现成的代理 API？

短别名层不包含供应商加载——用完整版 API 只需加减几行：

```python
from resource_pool import ProxyPool

proxy = ProxyPool()
proxy.load_from_url("http://你的代理供应商.com/api?key=xxx&count=20")
# → 自动识别 9 种主流供应商格式

# 然后包装进短别名
from resource_pool import Proxy
p = Proxy()  # Proxy 也可以接收已创建好的 Pool
```

> 短别名 `UA`/`Proxy`/`DNS`/`combo` 是完整版 API 的上层包装，随时可以混合使用——短别名背后就是完整的 `UserAgentPool`/`ProxyPool`/`DNSResolverPool`/`PoolOrchestrator`。

---

## 接下来看什么？

| 你想做…… | 去看 |
|---------|------|
| 反反爬——完整请求头伪装 | [cookbook → UA 池](cookbook.md#user-agent-池) |
| Scrapy 项目接进来 | [cookbook → Scrapy 集成](cookbook.md#scrapy-集成) |
| 理解底层怎么设计的 | [深入架构](deep-dive.md) |
| 生产环境部署 | [PRODUCTION.md](../PRODUCTION.md) |

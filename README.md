# Resource Pool ![version](https://img.shields.io/badge/version-1.0.6-blue)

> 可扩展的爬虫资源池微框架 —— **爬虫三件套**开箱即用，同步/异步双模。

短路径只需一个 import，长路径支持深度定制。

```python
import resource_pool

ua = resource_pool.UA()
proxy = resource_pool.Proxy("1.2.3.4:8080")
dns = resource_pool.DNS()

# 单独使用
ua_string = ua.pick()              # 轮换 User-Agent
headers = ua.headers()              # 完整反爬请求头
proxy_url = proxy.pick()            # 轮换代理
ip = dns.resolve("www.example.com") # 轮换 DNS

# 一次拿全套
c = resource_pool.combo(ua=ua, proxy=proxy, dns=dns)
print(c.ua, c.proxy, c.dns)
```

---

## 为什么需要资源池

| 资源 | 无池 | 有池 |
|------|------|------|
| User-Agent | 固定一个，高频秒被识别 | 22+ 内置 UA + 830 条本地数据集 + 20 组 Header Profile 自动匹配，支持 fake_useragent 远程扩充+自动降级 |
| DNS 解析 | 单点 DNS 频次过高被限流 | 14 台 DNS 轮换 + LRU 缓存（16路分片锁）+ 故障隔离 + 自动复活 |
| 代理 | 单代理被封全部瘫痪 | HTTP/HTTPS/SOCKS5 代理池，质量评分 + 自动淘汰补充 + 持久化 |

---

## 安装

```bash
pip install git+https://github.com/nianchen8/resource-pool.git
```

Python ≥ 3.10。核心依赖：`dnspython ≥ 2.6`。可选：`aiohttp`、`fake_useragent`。

---

## 30 秒跑起来

```python
import resource_pool

# 换 UA
ua = resource_pool.UA()
headers = ua.headers()                   # dict，完整反爬请求头（Profile 自动匹配）

# 换代理
proxy = resource_pool.Proxy("1.2.3.4:8080")
proxies = proxy.pick_dict()              # dict，直接传给 requests

# 换 DNS
dns = resource_pool.DNS()
ip = dns.resolve("www.example.com")       # str

# 一次拿全套
c = resource_pool.combo(ua=ua, proxy=proxy, dns=dns)
requests.get(url, headers=c.ua, proxies=c.proxy)
```

---

## 按你的水平开始

| 我是…… | 从这里开始 | 内容 |
|---------|-----------|------|
| 🟢 刚学爬虫 | [5 分钟快速上手](docs/guides/quickstart.md) | 安装 → 第一个 UA 轮换 → 三件事一起做 |
| 🔵 日常写爬虫 | [场景实战](docs/guides/cookbook.md) | 反反爬 / 代理生命周期 / Scrapy 集成 / 异步版 / API 速查 |
| 🟣 架构/调优 | [深入架构](docs/guides/deep-dive.md) | 锁层级 / 策略协议 / 自定义池 / 性能基准 / 调优 |

> 短别名（`UA`/`Proxy`/`DNS`/`combo`）包装了完整版 API。需要深度定制时，同样用 `from resource_pool import UserAgentPool, PoolOrchestrator`。

生产部署参考 → [PRODUCTION.md](docs/PRODUCTION.md)

完整升级路线 → [UPGRADE_PLAN.md](docs/UPGRADE_PLAN.md)

可运行示例 → [`examples/`](examples/)
- `simple_requests_demo.py` — 单线程零开销用法
- `async_integration.py` — httpx + aiohttp 异步集成
- `scrapy_integration.py` — Scrapy Middleware 完整实现
- `stress_test.py` — 极端压力测试

---

## 架构特性

| 能力 | 说明 |
|------|------|
| **Header Profile** | 20 组完整请求头 + 自动匹配浏览器/版本号 |
| **线程安全** | UA 池 ReadWriteLock（读并发 N 倍）、Proxy 池 Lock、DNS 池 16 路缓存分片 |
| **异步支持** | AsyncUserAgentPool / AsyncDNSResolverPool / AsyncProxyPool / AsyncPoolOrchestrator，API 与同步版完全对等 |
| **按需开关** | `thread_safe=False` 关闭所有锁，单线程零开销 |
| **故障隔离** | 连续失败达阈值自动隔离 → 到期试用复活（一次机会） |
| **可插拔策略** | 内置枚举 + `StrategyProtocol` callable 自定义 |
| **编排器注册表** | `isinstance` 精确分派，告别 `hasattr` 探测 |
| **统一异常** | `PoolExhaustedError` / `ResourceUnhealthyError` 一把捕获 |
| **凭据脱敏** | stats 输出 `user:***@host`，杜绝日志泄露 |
| **类型完整** | PEP 561 `py.typed`，IDE 智能提示全覆盖 |

---

## 各池一句话

| 池 | 一句话 | 详细 |
|---|--------|------|
| UA 池 | 加权随机轮换 UA + 完整 Header Profile + 暂存器模式 | [cookbook → UA 池](docs/guides/cookbook.md#user-agent-池) |
| DNS 池 | 14 台 DNS 轮换解析 + LRU 缓存 + 故障隔离 | [cookbook → DNS 池](docs/guides/cookbook.md#dns-解析器池) |
| Proxy 池 | 代理评分 + 自动补充淘汰 + 多供应商并发拉取 | [cookbook → 代理池](docs/guides/cookbook.md#代理池) |
| 编排器 | 一行拿全套：UA + DNS + Proxy，返回 PoolCombo | [cookbook → 编排器](docs/guides/cookbook.md#编排器) |

---

## 项目结构

```
resource_pool/        ← 统一入口 + 框架层 (ABC / 编排器 / 锁基础设施)
user_agent_pool/      ← UA 池 (22 UA + 830 JSONL + 20 Profile + 细粒度筛选)
dns_resolver_pool/    ← DNS 池 (14 DNS + 16路缓存分片 + ContextVar)
proxy_pool/           ← 代理池 (评分系统 + 9种格式解析 + 持久化)
examples/             ← 5 个可运行示例
tests/                ← 275 个测试 (覆盖率 94%+)
docs/
├── guides/
│   ├── quickstart.md  ← 新手 5 分钟入门
│   ├── cookbook.md    ← 日常场景配方 + API 速查
│   └── deep-dive.md   ← 架构 / 锁 / 策略 / 调优
├── PRODUCTION.md      ← 部署 / 监控 / 排障
├── UPGRADE_PLAN.md    ← 升级路线图
├── EXCEPTIONS.md      ← 异常体系 + 审查报告
└── CHANGELOG.md       ← 完整版本历史
```

---

## 更新日志

### v1.0.6 (2026-05-26)

- 🚀 **本地 UA 数据集**：打包 830 条 headers_pool.jsonl，fake_useragent 不可用时自动降级
- 🚀 **降级策略**：远程 fake_useragent 优先，不可用/UA 过少时自动回退本地
- 🚀 **JSONL 导入**：`load_from_file()` 支持 `.jsonl` 格式
- 🛡️ **架构一致**：所有数据源统一走 Profile 匹配组装请求头

### v1.0.5 (2026-05-26)

- 🚀 **短别名封装层**：`import resource_pool` 一行搞定日常使用

### v1.0.4 (2026-05-26)

- 🛡️ **AsyncProxyPool 锁粒度优化**：`get()`/`get_dict()` 选择逻辑移出锁外，与同步版并发模型一致
- 🛡️ **AsyncDNSResolverPool TOCTOU 修复**：复活时间戳检查纳入锁范围
- 🛡️ **协程检测健壮化**：`inspect.isawaitable()` 替代 `iscoroutine()`
- 🛡️ **编排器弃用警告**：hasattr 回退添加 `logger.warning`
- ⚡ **加权选择优化**：`random.choices` 替代手动累积，消除浮点误差

[完整历史 → CHANGELOG.md](docs/CHANGELOG.md)

---

## License

MIT

# Resource Pool ![version](https://img.shields.io/badge/version-1.0.9-blue)

> 爬虫资源池，给懒人用的。UA / 代理 / DNS——全部帮你准备好，一行拿出来。

## 安装

```bash
pip install git+https://github.com/nianchen8/resource-pool.git
```

Python ≥ 3.10。核心依赖：`dnspython ≥ 2.6`。可选：`aiohttp`、`fake_useragent`。

## 代码有多短

```python
import resource_pool
import requests
from user_agent_pool import UserAgentPool

# ── 准备好 ──
ua = UserAgentPool()                       # 854 条 UA 种子 → 零件池重组 → 31,496 独立 UA → 193,633 完整 headers
# proxy = resource_pool.Proxy("1.2.3.4:8080")  # 代理（有代理时取消注释）
dns = resource_pool.DNS()                  # 14 台 DNS 自动轮换

# ── 一把抓，发给百度 ──
c = resource_pool.combo(ua=ua, dns=dns)
resp = requests.get("https://www.baidu.com", headers=c.ua, timeout=10)
print(resp.status_code)  # 200

# c.ua 是完整请求头 dict（不是 UA 字符串），desktop Chrome 示例：
# {
#     "User-Agent":            "Mozilla/5.0 … Chrome/134 …",
#     "Accept":                "text/html,application/xhtml+xml,…",
#     "Accept-Encoding":       "gzip, deflate, br",
#     "Accept-Language":       "zh-CN,zh;q=0.9,en;q=0.8",
#     "Cache-Control":         "max-age=0",
#     "Connection":            "keep-alive",
#     "Sec-Ch-Ua":             "\"Chromium\";v=\"134\"…",
#     "Sec-Ch-Ua-Mobile":      "?0",
#     "Sec-Ch-Ua-Platform":    "\"Windows\"",
#     "Sec-Fetch-Dest":        "document",
#     "Sec-Fetch-Mode":        "navigate",
#     "Sec-Fetch-Site":        "none",
#     "Sec-Fetch-User":        "?1",
#     "Upgrade-Insecure-Requests": "1",
# }
# 14 字段，覆盖浏览器必发全部关键请求头。每次调用自动轮换。
```

> 💡 就这么短。想在线拉 UA？装 `pip install fake-useragent` 然后 `ua.load_from_fakeua()`。每个场景的完整写法（单线程/多线程/异步/Scrapy/会话保持），见下方 [开箱即用](#1-开箱即用)。

## 准备得有多全

| 资源 | 没池子 | 有池子 |
|------|------|------|
| User-Agent | 固定一个，高频秒封 | 854 条 UA 种子 → 零件池随机重组 → 31,496 独立 UA → 193,633 完整 headers，覆盖 4 引擎（Chrome/Firefox/Safari/Edge）× 7 平台，每次随机换 |
| DNS | 单台 DNS，频次高被限流 | 14 台 DNS 轮换 + 故障自动隔离恢复 |
| 代理 | 单代理，一封全军覆没 | 代理池，自动评分淘汰补充 |

## 按你的深度开始

| 我想…… | 从这里开始 | 内容 |
|---------|-----------|------|
| 🟢 抄了就���，啥都不管 | [开箱即用](docs/guides/从零到反反爬.md#1-开箱即用) | 安装 → 单/多线程 → 多进程 → 异步 → Scrapy，每段 3~8 行 |
| 🔵 搞明白为什么这样写 | [初级定制](docs/guides/从零到反反爬.md#2-初级定制) | 原理、策略选择、数据源、UA+Proxy联动 |
| 🟣 全部能力随我调度 | [深度定制](docs/guides/从零到反反爬.md#3-深度定制) | 三池协同、主从推送、生产运维、全 API |
| ⚫ 源码我都能改 | [底层源码](docs/guides/从零到反反爬.md#4-底层源码) | 派系引擎、锁与协议、怎么扩展自己的池 |

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
| **派系化 Header 组装** | 854 UA 种子 → 零件池随机重组 → 31,496 独立 UA → 193,633 完整 headers |
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
| UA 池 | 加权随机轮换 UA + 派系引擎组装完整请求头 + 暂存器模式 + 细粒度筛选 | [cookbook → UA 池](docs/guides/cookbook.md#user-agent-池) |
| DNS 池 | 14 台 DNS 轮换解析 + LRU 缓存 + 故障隔离 | [cookbook → DNS 池](docs/guides/cookbook.md#dns-解析器池) |
| Proxy 池 | 代理评分 + 自动补充淘汰 + 多供应商并发拉取 | [cookbook → 代理池](docs/guides/cookbook.md#代理池) |
| 编排器 | 一行拿全套：UA + DNS + Proxy，返回 PoolCombo | [cookbook → 编排器](docs/guides/cookbook.md#编排器) |

---

## 项目结构

```
resource_pool/        ← 统一入口 + 框架层 (ABC / 编排器 / 锁基础设施)
user_agent_pool/      ← UA 池 (850+ UA 自动加载 + 派系组装引擎 + 细粒度筛选)
dns_resolver_pool/    ← DNS 池 (14 DNS + 16路缓存分片 + ContextVar)
proxy_pool/           ← 代理池 (评分系统 + 9种格式解析 + 持久化)
examples/             ← 5 个可运行示例
tests/                ← 275 个测试 (覆盖率 94%+)
docs/
├── guides/
│   ├── 从零到反反爬.md  ← 四层指南（开箱即用 → 初级定制 → 深度定制 → 底层源码）
│   ├── cookbook.md    ← API 速查表 + 场景配方
│   └── deep-dive.md   ← 架构 / 锁 / 策略 / 原理
├── PRODUCTION.md      ← 部署 / 监控 / 排障
├── UPGRADE_PLAN.md    ← 升级路线图
├── EXCEPTIONS.md      ← 异常体系 + 审查报告
└── CHANGELOG.md       ← 完整版本历史
```

---

## 更新日志

### v1.0.9 (2026-05-27)

- 🚀 UA 零件池深度拆解：854→31,496 独立 UA（×10），193,633 完整 headers 组合
- 🛡️ DNS 14 台全失败后自动回退系统 DNS，避免 PoolExhaustedException

### v1.0.8 (2026-05-27)

- 🚀 **JSONL 完整 Header Profile 原子化**：同一真实设备的 Accept/Accept-Language/Cache-Control 等字段不再拆散，作为原子单位使用，在 `_build_headers` 优先级 1（内联 headers）命中
- 🚀 **`add()` 新增 `headers` 参数**：支持直接注入完整请求头

### v1.0.7 (2026-05-27)

- 🚀 **派系化 Header 组装**：Chromium/Firefox/Safari × 6 平台三维路由，组合爆炸 12 万+
- 🚀 **jsonl 自动加载**：`UserAgentPool()` 创建时自动加载 830+ 条真实 UA，覆盖 4 引擎 × 7 平台
- 🚀 **ChromeOS / iPad GSA / CriOS 覆盖修复**：100% jsonl 条目可解析元数据并走派系组装
- 🚀 **双路径架构**：在线（fake_useragent）+ 本地降级（内置 UA）共享同一套派系引擎
- 🛡️ **4 级 `_build_headers` 优先级**：内联 headers > 派系组装 > Profile 匹配 > 仅 UA

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

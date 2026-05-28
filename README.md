# Nurture Pool ![version](https://img.shields.io/badge/version-1.2.4-blue)

> 养成系资源池——UA 请求头、DNS、代理，越用越肥的三件套。

## 安装

```bash
pip install nurture-pool
```

Python ≥ 3.10。核心依赖 `dnspython ≥ 2.6`，可选 `aiohttp`、`fake_useragent`。

## 5 秒上手

```python
import nurture_pool, requests
from user_agent_pool import UserAgentPool

ua = UserAgentPool()                    # 自动加载 854 种子 → 31,496 独立 UA
dns = nurture_pool.DNS()               # 14 台 DNS 轮换，惰性初始化

with dns:                               # patch socket，requests 的 DNS 走池
    resp = requests.get("https://www.baidu.com",
                        headers=ua.get_headers(), timeout=10)
# → 200
```

> 每次请求自动换一套完整的浏览器请求头（14 字段）。有代理加一行 `nurture_pool.Proxy("ip:port")`。

养成——让池子越用越肥：

```python
# 喂一条新 UA，下次启动自动加载
nurture_pool.feed_ua("Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/148.0.0.0 ...")

# 喂一个代理（支持 ip:port:user:pass）
nurture_pool.feed_proxy("1.2.3.4:8080:user:pass", weight=8)

# 查看喂养统计
print(nurture_pool.status())
# → {"ua": {"builtin": 854, "fed": 2, "total": 856}, ...}
```

> 养成数据写入安装目录。pip upgrade 前务必 `nurture_pool.export_fed("proxy", "./backup/")` 备份。

## 按你的深度开始

四层文档，每层都有**单线程 / 多线程 / 多进程 / 异步 / Scrapy** 五种写法的完整可运行代码：

| 我想…… | 从这里开始 | 5 种写法 | 内容 |
|---------|-----------|:--:|------|
| 🟢 抄了就跑，啥都不管 | [开箱即用](docs/guides/开箱即用.md) | ✅ | 三件套默认配置，每段复制能跑 |
| 🔵 搞明白为什么这样写 | [初级定制](docs/guides/初级定制.md) | ✅ | 14 个旋钮逐个详解：英文名/中文名/类型/默认值/作用/场景 |
| 🟣 全部能力随我调度 | [深度定制](docs/guides/深度定制.md) | ✅ | StrategyProtocol 写策略、register_dispatch 造池、三种锁与死锁预防 |
| ⚫ 源码我都能改 | [底层源码](docs/guides/底层源码.md) | ✅ | 六大机制源码拆解：派系引擎 / ReadWriteLock / socket patch / dispatch / ABC / 短别名 |

> 每层文档的 5 种写法都能直接跑——但写法完全不同。开箱即用用默认配置，初级定制拧旋钮，深度定制自己造池，底层源码展示内部机制。

## 三件套能力速览

| 资源 | 无池 | 有池 |
|------|------|------|
| UA 请求头 | 固定一条，秒封 | 854 种子 → 零件重组 → 31,496 UA → 193,633 headers，引擎家族约束保证一致性 |
| DNS | 单台 DNS，频次高被限流 | 14 台轮换 + LRU 缓存 + 故障隔离 + socket 透明 patch |
| 代理 | 单代理，一封全挂 | 评分淘汰 + 自动补充 + 9 种供应商格式自动识别 |
| 养成 | 每次重装丢数据 | feed_ua/proxy/dns 持久化 + export_fed 备份 + reset 清除 |

## 架构速览

| 能力 | 说明 |
|------|------|
| 派系引擎 | Chromium / Firefox / Safari 三维路由，版本号/平台/语言段数自动同步 |
| 线程安全 | UA 池 ReadWriteLock（读并发 N 倍）、DNS 16 路缓存分片 |
| 异步对等 | Async* 全系列，API 与同步版一致 |
| 可插拔 | 内置枚举 + StrategyProtocol callable + isinstance 分派注册表 |
| 故障隔离 | 连续失败隔离 → 定时复活 → 健康检查（三探验活），全自动 |
| 数据持久化 | 养成 API 写入安装目录 → 下次启动自动加载 → export_fed 跨项目迁移 |
| 零开销 | `thread_safe=False` 关闭所有锁，单线程无锁竞争 |

## 项目结构

```
nurture_pool/        ← 统一入口 + 框架层 (ABC / 编排器 / 锁 / 养成API)
│   ├── _feeding.py   ← 养成系持久化 (feed/import/export/reset)
│   ├── data/         ← 养成数据 + schema + 模板
user_agent_pool/      ← UA 池 (派系引擎 + 零件重组 + 细粒度筛选)
dns_resolver_pool/    ← DNS 池 (14 服务器 + 16路缓存 + socket patch)
proxy_pool/           ← 代理池 (评分系统 + 9 格式解析 + 持久化)
examples/             ← 可运行示例
tests/                ← 全量测试
docs/
├── guides/
│   ├── 开箱即用.md    ← 🟢 入门：默认配置 5 种写法
│   ├── 初级定制.md    ← 🔵 进阶：拧旋钮 5 种写法
│   ├── 深度定制.md    ← 🟣 高级：自定义池 5 种写法
│   └── 底层源码.md    ← ⚫ 深入：内部机制 5 种写法
├── PRODUCTION.md      ← 部署 / 监控 / 排障
└── CHANGELOG.md       ← 完整版本历史
```

## 更新日志

### v1.2.3 (2026-05-28)

- 🔧 **DNS 故障隔离测试修复**：`test_invalid_server_raises` / `test_consecutive_fail_isolation` 添加 `fallback_to_system=False`，隔离系统 DNS 干扰
- 🔧 **`ServerState.last_health` 假复活修复**：初始值从 `0.0` 改为 `time.time()`，防止被禁用服务器立即意外复活（同步+异步）
- 🧪 286 测试全部通过

### v1.2.2 (2026-05-28)

- 🐛 **致命修复**：`DNSResolverPool._load_defaults` 参数错误导致 CI 全红，4 个 Python 版本测试全部崩溃
- 🚀 **`nurture_pool.probe_proxy()` / `validate_fed_proxies()`**：代理连通性探测 + 养成代理批量三次验证
- 🔧 **CI lint 全绿**：8 个 F401 修复，ruff check 零错误
- 🔧 **`.gitignore`**: `data/` → `/data/` 精确化，避免误伤 `nurture_pool/data/`
- 🧹 **冗余消除**：移除 pool.py 重复 import、AsyncProxyState 补齐 score 属性、ProxyPool 支持字符串策略、编排器异常分级
- 🧪 286 测试全部通过

### v1.2.0 (2026-05-27)

- 🚀 **养成系持久化 API**：`feed_ua()` / `feed_dns()` / `feed_proxy()` 养成，`import_*()` 批量导入，`export_fed()` 备份
- 🚀 **四层文档**：开箱即用/初级定制/深度定制/底层源码，每层 5 种写法
- 🐛 **host 字段解析 + 三探验活**：荷花代理兼容，代理误杀率 70%→0

### v1.1.2 (2026-05-27)

- 🐛 **`create_resolver()` 修复**：返回 `_Resolver` 类实例替代裸函数，aiohttp `TCPConnector` 的 `.resolve()` 调用不再报 `AttributeError`

### v1.1.1 (2026-05-27)

- 🐛 **致命修复**：`ua_seeds.json` 加入打包清单，pip install 后 UA 池不再为空
- 🐛 **代理解析修复**：短别名 `Proxy("ip:port:user:pass")` 复用 `_parse_proxy_str`，支持鉴权/协议前缀等多种格式
- 🐛 **异步编排器增强**：`_fetch_from_pool_async` 添加 `isawaitable` 兜底，兼容返回 coroutine 的非 async 方法
- 🐛 **故障隔离修复**：`mark_failed` 同步更新 `last_health`，避免被隔离代理被立即复活（同步+异步均已修复）
- 🐛 **`__repr__` 修复**：DNS 池纯 callable 策略时不再抛 AttributeError（两步均有 None 守卫）
- 🐛 **异常体系统一**：`InvalidAgentException` 纳入 `ResourceUnhealthyError` 继承体系
- 🐛 **异步 UA 池修复**：`_build_headers` 委托同步实例，修复 8 个之前隐藏的异步 header 构建测试
- 🔧 根目录 `headers_pool.jsonl` 不再参与搜索，仅使用包内 bundled 版本
- 🧪 全量 286 测试通过

### v1.1.0 (2026-05-27)

- 🚀 **DNS Socket 透明补丁**：`DNSResolverPool.patch_socket()` monkey-patch `socket.getaddrinfo`，
  `requests` / `urllib3` 的 DNS 解析自动走池内 14 台 DNS 服务器，无需修改任何请求代码
- 🚀 **DNS 上下文管理器**：`with dns:` 进入自动 patch，退出自动 unpatch，一行代码搞定
- 🚀 **异步 aiohttp DNS 集成**：`AsyncDNSResolverPool.create_resolver()` 返回 aiohttp `TCPConnector` 兼容的异步 resolver，
  异步请求同样走 DNS 池
- 🚀 **短别名 DNS 增强**：`nurture_pool.DNS()` 支持 `patch_socket()` / `unpatch_socket()` + 上下文管理器

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

- 🚀 **短别名封装层**：`import nurture_pool` 一行搞定日常使用

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

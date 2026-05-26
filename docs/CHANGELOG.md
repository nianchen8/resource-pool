# 更新日志

## v1.0.6 (2026-05-26)

- 🚀 **本地 UA 数据集（headers_pool.jsonl）**：打包 830 条多浏览器/多平台 UA 到 `user_agent_pool/headers_pool.jsonl`，`load_from_fakeua()` 不可用时自动降级
- 🚀 **fake_useragent 降级策略**：`load_from_fakeua()` 远程优先：fake_useragent 可用时取其 UA + 架构 Profile 组装请求头；返回 < 5 条时自动回退到本地 jsonl 数据集
- 🚀 **JSONL 文件导入**：`load_from_file()` 新增 `.jsonl` 格式支持（每行一个 JSON 对象）
- 🛡️ **架构一致性**：jsonl 仅提取 UA 字符串，请求头统一走 Profile 匹配机制组装，不再使用预制 headers。`load_from_fakeua()` 和本地降级走同一套 pipeline
- 🔧 `AgentEntry` TypedDict 新增 `headers` 字段支持内联完整请求头（供高级用户自定义使用）
- 🔧 `_build_headers` 优先级：内联 headers > 显式 profile > 自动匹配 > 仅 UA

## v1.0.5 (2026-05-26)

- 🚀 **短别名封装层**：`import resource_pool` 一行搞定日常使用
  - `resource_pool.UA()` — `pick()`/`headers()`/`reserve()`，包装 UserAgentPool
  - `resource_pool.Proxy("ip:port")` — 直传地址格式，`pick()`/`pick_dict()`
  - `resource_pool.DNS()` — 自动 health_check，`resolve()`/`lookup()`
  - `resource_pool.combo(ua=ua, proxy=proxy, dns=dns)` — 一行拿全套
- 🔧 短别名纯包装设计：惰性加载零开销、底层 API 完全不变
- 📝 文档同步：quickstart 改用短 API、cookbook 标注双路径、deep-dive 架构图更新
- 🧪 274 测试全部通过，零破坏

## v1.0.4 (2026-05-26)

- 🛡️ **AsyncProxyPool 锁粒度优化**：`get()`/`get_dict()` 选择逻辑移出锁外，内部方法（`_get_alive`/`_try_revive`/`_on_success`）各自加锁，与同步版并发模型一致，避免协程串行化
- 🛡️ **AsyncDNSResolverPool TOCTOU 修复**：`_try_revive` 时间戳检查纳入锁范围，与同步版对齐
- 🛡️ **协程检测健壮化**：`_fetch_from_pool_async` 使用 `inspect.isawaitable()` 替代 `asyncio.iscoroutine()`
- 🛡️ **编排器弃用警告**：同步/异步版 hasattr 回退添加 `logger.warning` 弃用提示
- ⚡ **加权选择优化**：`_weighted_pick` 使用 `random.choices` 替代手动累积，消除浮点误差
- 📝 注释与测试命名修正

## v1.0.3 (2026-05-26)

- 🚀 **AsyncProxyPool 功能补齐**：`StrategyProtocol` callable 策略支持、`scores()` 评分、`load_from_url()`/`load_from_urls()` 异步加载、`save_to_file()`/`load_from_file()` 持久化、`auto_maintain()` 自动维护、`strategy` property
- 🚀 **AsyncUserAgentPool 功能补齐**：`UAStrategy` 枚举 + `weighted` 参数、`get_all()`、`register_profile()`（委托同步版）、`load_from_file()`、`load_from_fakeua()`、`strategy` property
- 🛡️ **`__repr__` 锁粒度一致**：`ProxyPool` / `DNSResolverPool` 的 `alive` 和 `total` 统一在持锁下计算
- 🛡️ **编排器异常完整性**：`PoolOrchestrator.combos()` 区分 `PoolExhaustedError`（显式 raise）与其他异常（ERROR 日志后 raise）
- 🔧 **CI glob 修复**：`paths-ignore` 中 `"**.md"` → `"**/*.md"`
- 🔧 **pre-commit 升级**：ruff `v0.11.0` → `v0.11.8`
- 🧹 **残留清理**：删除 `test_result.txt`

## v1.0.2 (2026-05-26)

- 🐛 **异步编排器 PoolCombo 对齐**：`AsyncPoolOrchestrator.next()` 返回 `PoolCombo` 而非 `dict`，与同步版 API 一致
- 🐛 **异步 UA 池元数据拷贝**：`_init_defaults` 改用 `_copy_agent_entry` 方法，确保 `browser`/`os`/`version` 字段正确拷贝
- 🐛 **示例代码字段名修复**：`simple_requests_demo.py` 中 `dns_ip` → `dns`，匹配编排器键名
- 📝 **注释补充**：`AsyncDNSResolverPool._try_revive` 添加 asyncio 原子安全说明

## v1.0.1 (2026-05-26)

- 🛡️ **异步池并发安全加固**：`AsyncProxyPool` 6 个方法改为 `async def` + `asyncio.Lock` 保护
- 🛡️ **AsyncDNSResolverPool 策略对称**：添加 `StrategyProtocol` 支持，与同步版 API 对齐
- 🛡️ **AsyncUserAgentPool 功能补齐**：添加 `browser`/`os`/`min_version` 细粒度筛选 + `_build_headers` 自动 Profile 匹配
- 🛡️ **可观测性提升**：`_parse_response` 中 `JSONDecodeError` 添加 debug 日志
- 📝 **文档更新**：UPGRADE_PLAN 第六阶段报告、PRODUCTION 异步锁层级说明

## v1.0.0 (2026-05-26)

- 🚀 **Header Profile 自动匹配**：`get_headers()` 根据 UA 的浏览器+版本号自动选择最接近的 Profile 组
- 📝 **生产部署指南**：`docs/PRODUCTION.md` — TOML 配置模板 + Prometheus 监控 + 排障 Q&A + 架构图
- 🔧 **CI/CD 质量门禁**：`.github/workflows/test.yml` 多版本矩阵测试 (3.10-3.13) + `.pre-commit-config.yaml` ruff hooks
- 🛡️ **Python 3.13 free-threaded 兼容标注**：latency_ms 写入处加锁，兼容无 GIL 模式

## v0.7.0 (2026-05-26)

- 🚀 **PoolCombo**：编排器 `next()/combos()` 返回 `PoolCombo` 对象，支持属性访问（`combo.ua`）+ 字典访问 + 解包
- 🚀 **代理持久化**：`ProxyPool.save_to_file()` / `load_from_file()` JSON 格式，含运行时统计
- 🚀 **多供应商拉取**：`ProxyPool.load_from_urls()` ThreadPoolExecutor 并发拉取 + 去重合并
- 🚀 **fake_useragent 集成**：`UserAgentPool.load_from_fakeua()` 可选依赖，批量导入
- 🚀 **UA 细粒度筛选**：`get(browser="chrome", os="windows", min_version=120)` 浏览器/OS/版本号过滤
- 🚀 **UA 元数据自动检测**：`add()` 自动提取浏览器/OS/版本信息
- 🚀 **集成示例**：Scrapy Middleware + requests 单线程零开销示例
- 📝 README 全面更新：API 参考、架构特性、项目结构

## v0.6.0 (2026-05-25)

- 🚀 **异步支持**：AsyncUserAgentPool / AsyncDNSResolverPool / AsyncProxyPool / AsyncPoolOrchestrator
- 🚀 **读写锁**：UA 池 ReadWriteLock 替换 Lock，读并发度从 1 提升至 N
- 🚀 **DNS 16路分片锁**：缓存操作按域名首字符分片，1000 并发 P99 延迟 0.027ms
- 🚀 **编排器注册表**：`isinstance` + `register_dispatch` 精确分派，告别 `hasattr` 探测
- 🚀 **代理评分**：`ProxyState.score` + `ProxyPool.scores()` + `auto_maintain()` 自动淘汰+补充
- 🚀 **UA 批量导入**：`UserAgentPool.load_from_file()` 支持 JSON/CSV
- 🚀 **基准压力测试**：100/500/1000 并发吞吐量基准报告
- 🛡️ `CATEGORY_ALL` 常量替代魔法字符串、Profile 锁粒度优化

## v0.5.1 (2026-05-25)

- 🛡️ 修复 ProxyPool / DNSResolverPool `_try_revive` 竞态条件
- 🛡️ `PoolOrchestrator.combos()` 区分 PoolExhaustedError 与非预期异常，不再静默终止
- 🛡️ `PoolOrchestrator.__repr__` 加锁，保证线程安全一致性
- 🛡️ `UserAgentPool._init_defaults` 移除双重 `cast` hack
- 🛡️ DNSResolverPool 构造函数类型标注支持 `StrategyProtocol`
- 🛡️ `strategy` setter 添加类型校验，非法值抛 `TypeError`
- 📝 `user_agent_pool/exceptions.py` 补充模块文档字符串
- 📝 `AVAILABLE_PROFILES` 标记为导入时快照，引导使用 `get_available_profiles()`
- 📝 `ResourcePool` 基类添加 `__init_subclass__` 钩子和 `_lock` 初始化文档

## v0.5.0 (2026-05-25)

- 🎉 首次公开发布：User-Agent 池 + DNS 解析器池 + 代理池 + 编排器
- 完整的异常继承体系（统一捕获 + 精确捕获）
- 线程安全、故障隔离、可插拔策略、惰性导入

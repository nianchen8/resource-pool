# 更新日志

## v1.3.1 (2026-05-28)

文档审查与代码清理。

### 📝 文档
- 📝 **README**：版本徽章 1.2.4 → 1.3.1，补充 v1.3.0 / v1.3.1 更新日志条目
- 📝 **CHANGELOG**：补充 v1.3.0 模块重命名完整记录
- 📝 **PRODUCTION**：适用版本号 v1.2.3 → v1.3.1

### 🧹 清理
- 🧹 **ruff F401 修复**：`rename_module.py` 移除未使用导入 `os` / `sys`

## v1.3.0 (2026-05-28)

**BREAKING CHANGE** — 内部模块名 `resource_pool` 重命名为 `nurture_pool`，对齐 PyPI 包名 `nurture-pool`。

### 🚀 模块重命名
- 🚀 **目录重命名**：`resource_pool/` → `nurture_pool/`
- 🚀 **Python import**：所有 `from resource_pool.X` → `from nurture_pool.X`（14 处源码 import）
- 🚀 **运行时路径**：`dns_resolver_pool/servers.py` 的 `"..", "resource_pool", "data"` → `"..", "nurture_pool", "data"`
- 🚀 **配置文件**：`pyproject.toml` 中 `packages.find.include` 和 `package-data` 同步更新
- 🚀 **文档/示例/测试**：全部代码示例中 import/API 调用同步修改
- 🚀 **显示名**：文档中 `resource-pool` → `nurture-pool`（项目名引用）

### 影响范围
- 📊 **46 个文件**，**283 处替换**
- 🧪 **295 测试全部通过**（286 pytest + 6 live_demo + 3 example）
- ⚠️ **BREAKING CHANGE**：`import resource_pool` → `import nurture_pool`，现有代码必须更新导入语句

### 🔧 工具
- 🔧 **`rename_module.py`**：批量迁移脚本，支持 `--dry-run` 预览

## v1.2.3 (2026-05-28)

第三轮代码审查修复 —— PyPI 发布就绪。

### 🔧 修复
- 🔧 **`test_invalid_server_raises` 修复**：池内所有 DNS 被 `remove_server` 禁用后，系统 DNS 兜底成功导致 `PoolExhaustedException` 未抛出 → 添加 `fallback_to_system=False` 隔离系统 DNS 干扰
- 🔧 **`test_consecutive_fail_isolation` 修复**：第一次 resolve 失败后系统 DNS 兜底成功 → 结果被缓存 → 第二次 resolve 命中缓存 → 坏 DNS 未被第二次尝试 → `consecutive_fails` 仍为 1 → 未触发隔离 → 添加 `fallback_to_system=False` 确保每次都走池内失败计数
- 🔧 **`ServerState.last_health` 假复活修复**（同步+异步）：`last_health` 初始化为 `0.0` → `_try_revive` 中 `now - 0.0 > revive_after` 恒为真 → 被 `remove_server` / `mark_failed` 禁用的服务器会立即复活。已修复为 `last_health = time.time()`
- 🔒 **`auto_maintain` 竞态窗口缩小**：`load_from_url` 调用前重新获取锁读取最新 `alive`，避免锁释放后另一线程添加/移除代理导致 `alive` 判断偏旧
- 🚀 **`nurture_pool.import_proxy()` 新增 `auto_validate` 参数**：默认为 `True`，导入时自动探测代理连通性

### 🧹 冗余清理
- 🧹 **`user_agent_pool/pool.py`** 移除 `_load_unified_seeds()` 内冗余的 `import os as _os`（`os` 已在模块级导入），改用模块级 `os`
- 🧹 **`dns_resolver_pool/servers.py`** `_DOMESTIC`/`_OVERSEAS` 上方增加同步注释，提醒与 `dns_servers.json` 保持一致性

### 📝 发布就绪
- 📝 **README** 安装命令更新为 `pip install nurture-pool`（PyPI 发布后可用）
- 📝 **LICENSE** 添加 MIT 许可证文件

## v1.2.2 (2026-05-28)

第二轮全量代码审查修复版本 —— CI 修复 + 代理探测 + 冗余清理。

### 🔴 致命修复
- 🐛 **`DNSResolverPool._load_defaults` TypeError 修复**：本地开发时 `__init__` 向 `_load_defaults()` 多传了 `data_dir` / `load_builtin` / `load_fed` 三个参数（方法签名仅接受 `regions`），导致 `DNSResolverPool()` 实例化立即崩溃、CI 4 个 Python 版本矩阵全部测试失败。已恢复为 `_load_defaults(regions)`，`_data_dir` / `_load_builtin` / `_load_fed` 由方法内部通过 `self` 访问（与异步版一致）

### 🚀 新功能
- 🚀 **`nurture_pool.probe_proxy()` 代理探测**：单代理连通性检测（socket 连接 + HTTP 代理验证），支持 http/https/socks5
- 🚀 **`nurture_pool.validate_fed_proxies()` 养成代理批量验证**：三次失败测试 + 失败列表自动导出到 `proxy_failed_export.json`
- 两个新函数通过 `nurture_pool.__init__` 惰性导入对外暴露

### 🔧 修复
- 🔧 **CI lint 修复**：8 个 F401 未使用导入（`user_agent_pool` sync/async + `nurture_pool._feeding`）
- 🔧 **`.gitignore` 规则修复**：`data/` → `/data/`，仅忽略根目录 `data/`，避免误伤 `nurture_pool/data/` 关键数据文件
- 🔧 **`orchestrator_async.py` 尾部多余空行清理**

### 🧹 冗余与对齐
- 🧹 **`proxy_pool/pool.py`** 移除 `save_to_file()` 内冗余 `import os as _os`（`os` 已在模块级导入）
- 🧹 **`AsyncProxyState` 补齐 `score` 属性**：与同步版 `ProxyState.score` 评分逻辑一致，`AsyncProxyPool._calc_score()` 改为委托调用消除重复代码
- 🧹 **`ProxyPool` 支持字符串策略**：`ProxyStrategy(Enum)` → `ProxyStrategy(str, Enum)`，`__init__` / `strategy.setter` 均可接受 `"latency_weighted"` 字符串（与 async 版对齐）
- 🧹 **`orchestrator_async.py` 异常分级**：`next()` 区分 `PoolExhaustedError`（预期传播，不记 ERROR）与未预期异常（记 ERROR 后 raise），与同步版 `PoolOrchestrator.next()` 行为一致

- 🧪 全量 286 测试通过 + ruff All checks passed

## v1.2.1 (2026-05-28)

全量代码审查修复版本 —— 同步/异步双路径功能对齐。

### 🔴 同步/异步功能对齐
- 🐛 **AsyncDNSResolverPool `_probe_server` 返回类型修复**：返回类型从 `bool` 改为 `tuple[bool, float]`，与同步版一致。`health_check` 现在正确更新 `latency_ms`（EMA 加权），`LATENCY_WEIGHTED` 策略在异步版中实际生效
- 🐛 **AsyncDNSResolverPool 养成系参数补齐**：`__init__` 新增 `data_dir` / `load_builtin` / `load_fed` 参数，`_load_defaults` 实现三层加载（data_dir → JSON 数据文件 → 硬编码回退），`feed_dns()` 写入的养成数据对异步池可见
- 🐛 **AsyncUserAgentPool 养成系参数补齐**：`__init__` 新增 `data_dir` / `load_builtin` / `load_fed` / `raw_only` 参数，`_init_defaults` 实现三层加载（data_dir → ua_seeds.json → DEFAULT_AGENTS），支持按 source 过滤和 raw_only 模式
- 🐛 **AsyncProxyPool 养成系参数补齐**：`__init__` 新增 `data_dir` / `load_builtin` / `load_fed` 参数，新增 `_load_defaults` 实现两层加载（data_dir → JSON 数据文件），`feed_proxy()` 写入的代理对异步池可见
- 🐛 **AsyncProxyPool `ProxyStrategy` 改为 Enum**：从普通类改为 `class ProxyStrategy(str, Enum)`，与同步版 Enum 语义一致，同时保持字符串兼容性

### 🧹 冗余清理
- 🔧 删除根部冗余 `data/` 目录（`dns_servers.json` / `proxy_servers.json` / `header_profiles.json`），代码引用统一指向 `nurture_pool/data/`
- 🔧 删除无引用文件 `nurture_pool/data/header_profiles.json`（374 行无人引用）
- 🔧 移动杂散文件 `1.py` → `examples/quickstart.py`
- 🔧 修复测试文件名拼写错误 `test_stress_benchmark.py` → `test_stress_benchmark.py`

### 🔧 其他
- 🔧 版本号 1.2.0 → 1.2.1

## v1.2.0 (2026-05-27)

- 🚀 **养成系持久化 API**（`nurture_pool._feeding`）：让池子"越用越肥"——`feed_ua()` / `feed_dns()` / `feed_proxy()` 一道命令将新资源永久写入安装目录，`import_ua()` / `import_dns()` / `import_proxy()` 批量导入，`export_fed()` 备份养成数据，`reset()` 一键清除，`status()` 查看喂养统计。养成数据与原数据同文件共处（`source="fed"` + `batch` 批次号），支持去重、权重更新、自动分类。全部 API 通过 `nurture_pool.feed_ua()` 等惰性导入对外暴露
- 🚀 **数据格式标准化**：新增 `nurture_pool/data/schema/` 目录，含 `ua_format.json` / `dns_format.json` / `proxy_format.json` 三种标准格式定义，`import_*()` API 均按标准格式解析
- 🚀 **数据模板与 Profile**：`nurture_pool/data/` 纳入 `header_profiles.json`（Profile 组）和 `ua_templates.json`（UA 生成模板），便于深度定制
- 📝 **四层文档重构**：`docs/guides/` 拆分为开箱即用 / 初级定制 / 深度定制 / 底层源码 四层递进体系，每层含 5 种写法（单线程/多线程/多进程/异步/Scrapy），删除旧版 cookbook / deep-dive / quickstart
- 🐛 **`_parse_json` 补充 `host` 字段解析**：荷花代理等供应商 JSON 使用 `host`/`port` 字段而非 `IP`/`ip`，原解析链路未覆盖导致 `load_from_url` 失败
- 🛡️ **`_probe_proxy` 多目标三探验活**（同步+异步）：原逻辑仅随机选 1 个 URL 做单次探测，目标偶发抽风即冤杀代理。改为最多探测 3 个不同 URL，任一通过即判存活，误杀率从 70% 降到 0%
- 🔧 版本号 1.1.2 → 1.2.0

## v1.1.2 (2026-05-27)

- 🐛 **`create_resolver()` 返回类型修复**：`AsyncDNSResolverPool.create_resolver()` 此前返回裸 async 函数，aiohttp 的 `TCPConnector` 调用 `resolver.resolve()` 方法时报 `AttributeError`。已改为返回 `_Resolver` 类实例，`resolve()` 方法签名与 aiohttp 完全兼容，闭包持有 pool 引用实现池内 DNS 轮换。异步集成现在可以直接 `aiohttp.TCPConnector(resolver=pool.create_resolver())` 一行接入
- 🔧 版本号 1.1.1 → 1.1.2

## v1.1.1 (2026-05-27)

Bug 修复版本 —— 全量代码审查成果。

### 致命修复
- 🐛 **`ua_seeds.json` 未打包**：`pyproject.toml` 的 `[tool.setuptools.package-data]` 缺少 `ua_seeds.json`，导致 pip install 后 `UserAgentPool()` 无种子数据、UA 池为空。现已添加，pip 安装后池正常初始化 854 条 UA 种子

### 高风险修复
- 🐛 **短别名 `Proxy("ip:port:user:pass")` 解析错误**：`_shortcuts.py` `_add_one` 使用 `rsplit(":", 1)` 解析鉴权格式时 `port` 取到 `user` 字符串导致 `int()` 崩溃。已改为复用 `ProxyPool._parse_proxy_str` 完整解析链路，统一支持 `ip:port` / `ip:port:user:pass` / `http://ip:port` 等多种格式
- 🐛 **异步编排器 `isawaitable` 兜底**：`AsyncPoolOrchestrator._fetch_from_pool_async` 仅检查 `asyncio.iscoroutinefunction()`，若分派方法为非 async 但返回 coroutine 对象会导致未 await 的 coroutine 警告。已添加 `inspect.isawaitable()` 二级兜底检查

### 中风险修复
- 🐛 **`mark_failed` 未更新 `last_health`**（同步+异步）：`ProxyPool.mark_failed` / `AsyncProxyPool.mark_failed` 未设置 `s.last_health = time.time()`，`_try_revive` 复活逻辑依赖 `last_health` 判断时间差，隔离瞬间就可能被立即复活。已修复，两版均同步更新
- 🐛 **`DNSResolverPool.__repr__` / `AsyncDNSResolverPool.__repr__` None 守卫**：纯 callable 策略时 `self._strategy_enum` 为 None 会走 `else` 分支调用 `type(self._strategy_fn).__name__`，但 `_strategy_fn` 也可能为 None → `AttributeError`。已添加 `elif self._strategy_fn is not None` + `else: "unknown"` 三级守卫
- 🐛 **`_probe_proxy` 延迟更新注释**：`AsyncProxyPool._probe_proxy` 在锁外更新 `state.latency_ms`，虽 asyncio 单线程下原子安全，但与同步版锁内更新风格不一致。已添加注释说明 asyncio 单线程下写入原子的设计意图

### 低风险修复
- 🐛 **异常体系统一**：`InvalidAgentException` 原直接继承 `Exception`，与 `PoolExhaustedError` / `ResourceUnhealthyError` 并行。现已改为继承 `ResourceUnhealthyError`，纳入统一异常捕获体系

### 审查发现的历史缺陷
- 🐛 **异步 UA 池 `_build_headers` 调用错误**：`AsyncUserAgentPool._build_headers` 定义为 `@staticmethod` 但内部调用 `UserAgentPool._build_headers(entry)` —— 同步版的 `_build_headers` 是实例方法（含 `self` 引用），缺少 `self` 参数导致 8 个异步测试静默失败。已改为惰性创建同步单例 `AsyncUserAgentPool._sync_builder = UserAgentPool()` 并委托调用

### 清理
- 🔧 移除根目录 `headers_pool.jsonl` 搜索路径：仅在包内 `user_agent_pool/headers_pool.jsonl` 查找 bundled 版本
- 🔧 `.gitignore` 添加根目录 `headers_pool.jsonl`，不再纳入版本控制和发布
- 🔧 版本号 1.1.0 → 1.1.1
- 🧪 全量 286 测试通过（新增 8 个之前被静默跳过的异步测试）

## v1.1.0 (2026-05-27)

- 🚀 **DNS Socket 透明补丁**：`DNSResolverPool.patch_socket()` / `unpatch_socket()` monkey-patch `socket.getaddrinfo`，调用后 `requests` / `urllib3` / 标准库 socket 的 DNS 解析自动走池内 14 台 DNS 服务器轮询解析，池内全失败时回退到系统 DNS，无需在每处请求代码中显式调用 `resolve()`
  - 新增 `is_patched` 属性，运行时查询补丁状态
  - 新增 `__enter__` / `__exit__` 上下文管理器，`with dns:` 自动 patch/unpatch
  - IP 直通：`AI_NUMERICHOST` 标记的调用直接走原始 `getaddrinfo`，不触发池解析
  - 重复 patch 是 no-op，防止覆盖原始引用
- 🚀 **异步 aiohttp DNS 集成**：`AsyncDNSResolverPool.create_resolver()` 返回 aiohttp `TCPConnector` 兼容的异步 resolver 函数，直接传入 `aiohttp.TCPConnector(resolver=pool.create_resolver())` 即可让 aiohttp 的 DNS 走池
- 🚀 **短别名 DNS 增强**：`nurture_pool.DNS()` 新增 `patch_socket()` / `unpatch_socket()` 代理方法 + 上下文管理器，与完整版 API 一致
- 🔧 版本号 1.0.9 → 1.1.0

## v1.0.9 (2026-05-27)

- 🚀 **UA 零件池深度拆解 + 动态重组**：854 条 UA 拆解为 OS 串、完整版本令牌、WebKit 版本、Mobile Build 四个零件维度，跨零件随机 cross-pick，UA 数量从 3,160 暴增至 **31,496** 个独立 UA（×10 倍），完整请求头 **193,633** 种组合
  - 保留完整版号令牌（如 `Chrome/148.0.7727.56`），不再仅做主版本去重
  - Safai / WebKit 版本动态组合，移动端 `Mobile/` Build 随机选取
  - Chromium 派系 WebKit 硬固定 `537.36`，防止 Safari `605.1.15` 污染
- 🛡️ **DNS 系统 DNS 降级**：`resolve()` / `resolve_all()` 新增 `fallback_to_system=True`，14 台 DNS 全部失败后自动回退到操作系统 DNS，避免 `PoolExhaustedException` 中断业务
  - 同步版 `DNSResolverPool._system_resolve()` + 异步版 `AsyncDNSResolverPool._system_resolve()`
- 🔧 版本号 1.0.8 → 1.0.9

## v1.0.8 (2026-05-27)

- 🚀 **JSONL 完整 Header Profile 原子化利用**：`headers_pool.jsonl` 每行的完整请求头（Accept / Accept-Language / Cache-Control / Sec-Ch-Ua 等）作为原子单位直接存入 `entry["headers"]`，`_build_headers` 优先级 ① 直接命中，确保同一真实设备的字段组合不被拆散，杜绝拼凑 header 的不一致被反爬识别
- 🚀 **`add()` / `AsyncUserAgentPool.add()` 新增 `headers` 参数**：支持直接注入完整请求头字典，优先级最高
- 🚀 **`AsyncUserAgentPool.load_from_file()` 支持 JSONL**：异步版同步补齐 `.jsonl` 格式导入，与同步版 API 完全对齐
- 🔧 `_load_bundled_jsonl` / `_load_bundled_jsonl_sync` 自动传递 jsonl 内联 headers
- 🔧 `load_from_file` (同步/异步) 支持 jsonl 中保留的 headers 字段
- 🔧 版本号统一修复：`pyproject.toml` (1.0.6→1.0.8) + `README` badge (1.0.7→1.0.8)
- 📝 文档同步更新：deep-dive 数据流图反映 jsonl→优先级①、PRODUCTION/cookbook/quickstart 版本号和 API 说明更新

## v1.0.7 (2026-05-27)

- 🚀 **派系化 Header 组装引擎**：按浏览器引擎家族（Chromium/Chrome+Edge × Firefox × Safari × 6 平台：Windows/macOS/Linux/Android/iOS/ChromeOS）独立组装请求头，每次调用随机选取可变字段，实现指数级 header 组合爆炸（~850 基础 UA × 可变字段池 ≈ 12 万+ 种合法组合）
- 🚀 **headers_pool.jsonl 自动加载**：覆盖 4 引擎 × 7 平台，Chrome on Android(389)、Safari on iOS(200+)、Chrome on macOS(140)、Chrome on Windows(34)、Linux X11(19)、ChromeOS(12)、Firefox(24)、Edge(9)。池初始化时自动加载全部 830+ 条真实 UA
- 🚀 **ChromeOS / iPad GSA / CriOS 覆盖修复**：`_OS_PATTERNS` 新增 `CrOS` 检测，`_BROWSER_PATTERNS` 新增 `GSA/` 和 `CriOS/` 模式，确保 100% jsonl 条目可解析 browser/os/version 元数据并走派系组装路径
- 🚀 **双路径 header 组装**：在线路径（fake_useragent UA + 派系组装补充请求头）+ 本地降级路径（内置 UA + 派系模板即时生成），两条路径共享同一套派系引擎
- 🛡️ **`_build_headers` 4级优先级**：内联 headers > 派系即时组装 > Profile 匹配（向后兼容）> 仅 UA
- 🛡️ **派系约束自动保证**：UA 版本 == Sec-Ch-Ua 版本、UA 平台 == Sec-Ch-Ua-Platform、Accept-Language 段数匹配设备类型、Firefox 无 Sec-Ch-Ua/Cache-Control、Safari 无 Sec-Ch-Ua/Upgrade
- 🔧 `generate_ua()` 即时生成函数：从派系模板 + OS 参数池动态生成 UA 字符串
- 🔧 `_copy_agent_entry` 自动元数据检测：UA 字符串自动解析 browser/os/version，确保所有条目可走派系组装路径
- 🔧 `_OS_PLATFORM_META` 新增 `chromeos` 平台映射（`Sec-Ch-Ua-Platform: "Chrome OS"`）

## v1.0.6 (2026-05-26)

- 🚀 **本地 UA 数据集（headers_pool.jsonl）**：打包 830 条多浏览器/多平台 UA 到 `user_agent_pool/headers_pool.jsonl`，`load_from_fakeua()` 不可用时自动降级
- 🚀 **fake_useragent 降级策略**：`load_from_fakeua()` 远程优先：fake_useragent 可用时取其 UA + 架构 Profile 组装请求头；返回 < 5 条时自动回退到本地 jsonl 数据集
- 🚀 **JSONL 文件导入**：`load_from_file()` 新增 `.jsonl` 格式支持（每行一个 JSON 对象）
- 🛡️ **架构一致性**：jsonl 仅提取 UA 字符串，请求头统一走 Profile 匹配机制组装，不再使用预制 headers。`load_from_fakeua()` 和本地降级走同一套 pipeline
- 🔧 `AgentEntry` TypedDict 新增 `headers` 字段支持内联完整请求头（供高级用户自定义使用）
- 🔧 `_build_headers` 优先级：内联 headers > 显式 profile > 自动匹配 > 仅 UA

## v1.0.5 (2026-05-26)

- 🚀 **短别名封装层**：`import nurture_pool` 一行搞定日常使用
  - `nurture_pool.UA()` — `pick()`/`headers()`/`reserve()`，包装 UserAgentPool
  - `nurture_pool.Proxy("ip:port")` — 直传地址格式，`pick()`/`pick_dict()`
  - `nurture_pool.DNS()` — 自动 health_check，`resolve()`/`lookup()`
  - `nurture_pool.combo(ua=ua, proxy=proxy, dns=dns)` — 一行拿全套
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

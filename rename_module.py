#!/usr/bin/env python3
"""将内部模块名 resource_pool 重命名为 nurture_pool，对齐 PyPI 包名

全链路影响分析（详见脚本底部注释）：
  - 目录重命名: resource_pool/ → nurture_pool/
  - Python import: from resource_pool.X → from nurture_pool.X
  - 运行时路径: "resource_pool"/"data" → "nurture_pool"/"data"
  - 配置项: pyproject.toml 中 packages 声明
  - 文档/示例: 全部代码示例中的 import/API 调用
  - 显示名: "resource-pool" → "nurture-pool"（文档中的项目名称引用）

用法：
  cd D:\ProJects\PycharmProjects\resource_pool
  python rename_module.py          # 实际执行
  python rename_module.py --dry-run # 仅预览，不修改任何文件
"""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── 常量 ──────────────────────────────────────────────────────────────

OLD_MODULE = "resource_pool"       # Python 模块名（下划线）
NEW_MODULE = "nurture_pool"
OLD_DISPLAY = "resource-pool"      # 文档中的显示名（连字符）
NEW_DISPLAY = "nurture-pool"

# 需要扫描的文件扩展名
SCAN_EXTENSIONS = {".py", ".md", ".toml", ".cfg", ".yml", ".yaml", ".json", ".txt", ".ini"}

# 排除的目录（部分路径匹配）
EXCLUDE_DIRS = {
    ".git", "__pycache__", ".egg-info", ".pytest_cache",
    ".ruff_cache", ".codegraph", ".idea", "node_modules",
    "dist", "build",
}


def should_skip(path: Path) -> bool:
    """判断是否跳过该路径"""
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    # 跳过自身
    if path.name == "rename_module.py" and path.parent == ROOT:
        return True
    return False


def scan_files(root: Path) -> list[Path]:
    """收集所有需要扫描的文件"""
    files: list[Path] = []
    for ext in SCAN_EXTENSIONS:
        for file_path in root.rglob(f"*{ext}"):
            if not should_skip(file_path):
                files.append(file_path)
    return sorted(files)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将模块名 resource_pool → nurture_pool（对齐 PyPI 包名）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅预览变更，不实际修改任何文件"
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    # ══════════════════════════════════════════════════════════════════
    # Step 1: 重命名目录
    # ══════════════════════════════════════════════════════════════════
    old_dir = ROOT / OLD_MODULE
    new_dir = ROOT / NEW_MODULE

    print("=" * 60)
    print("  resource_pool → nurture_pool  模块重命名")
    print("=" * 60)

    if old_dir.is_dir():
        if dry_run:
            print(f"\n  [DRY-RUN] 将重命名目录: {old_dir.name}/ → {new_dir.name}/")
        else:
            shutil.move(str(old_dir), str(new_dir))
            print(f"\n  ✓ 目录重命名: {old_dir.name}/ → {new_dir.name}/")
    else:
        print(f"\n  ⚠ 目录 {OLD_MODULE}/ 不存在（可能已重命名），跳过")

    # ══════════════════════════════════════════════════════════════════
    # Step 2: 扫描并更新文件内容
    # ══════════════════════════════════════════════════════════════════
    files = scan_files(ROOT)
    print(f"\n  扫描到 {len(files)} 个文件，开始检查...\n")

    changed_count = 0
    total_replacements = 0

    for file_path in files:
        try:
            original = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError) as e:
            print(f"  ⚠ 跳过 {file_path.relative_to(ROOT)}: {e}")
            continue

        modified = original

        # ── 替换 1: 模块名 resource_pool → nurture_pool ──
        #   覆盖: Python import, 运行时路径, 文件注释, 文档代码示例
        count1 = modified.count(OLD_MODULE)
        modified = modified.replace(OLD_MODULE, NEW_MODULE)

        # ── 替换 2: 显示名 resource-pool → nurture-pool ──
        #   覆盖: 文档中的项目名称引用（如 "resource-pool 实战爬虫验证"）
        count2 = modified.count(OLD_DISPLAY)
        modified = modified.replace(OLD_DISPLAY, NEW_DISPLAY)

        if modified != original:
            rel = file_path.relative_to(ROOT)
            total = (count1 + count2)
            print(f"  ✓ {rel}  ({total} 处替换)")

            if not dry_run:
                file_path.write_text(modified, encoding="utf-8")

            changed_count += 1
            total_replacements += count1 + count2

    # ══════════════════════════════════════════════════════════════════
    # 汇总
    # ══════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 60}")
    if dry_run:
        print(f"  [DRY-RUN] 预览完成：{changed_count} 个文件，{total_replacements} 处替换")
    else:
        print(f"  迁移完成：{changed_count} 个文件，{total_replacements} 处替换")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════════════════════════════════
# 全链路影响分析（供审计）
# ═══════════════════════════════════════════════════════════════════════
#
# 1. 目录重命名
#    resource_pool/ → nurture_pool/
#
# 2. Python 源码 — import 语句（14 处）
#    resource_pool/__init__.py         # TYPE_CHECKING + _LAZY_IMPORTS 中 self-ref
#    resource_pool/orchestrator.py     # from resource_pool.base
#    resource_pool/orchestrator_async.py # from resource_pool.* (3 处)
#    resource_pool/_shortcuts.py       # combo() 中 from resource_pool.orchestrator
#    dns_resolver_pool/__init__.py     # from resource_pool.orchestrator
#    dns_resolver_pool/exceptions.py   # from resource_pool.exceptions
#    dns_resolver_pool/pool.py         # from resource_pool.base
#    dns_resolver_pool/pool_async.py   # from resource_pool.* (3 处)
#    proxy_pool/__init__.py            # from resource_pool.orchestrator
#    proxy_pool/exceptions.py          # from resource_pool.exceptions
#    user_agent_pool/__init__.py       # from resource_pool.orchestrator
#
# 3. Python 源码 — 运行时文件路径（1 处，关键）
#    dns_resolver_pool/servers.py L29  # "..", "resource_pool", "data"
#
# 4. 配置文件（1 个文件，2 行）
#    pyproject.toml L39, L42           # packages.find.include + package-data
#
# 5. 示例文件 examples/（5 个文件）
#    quickstart.py, async_integration.py, scrapy_integration.py,
#    simple_requests_demo.py, real_crawler_demo.py
#
# 6. 文档 .md（6 个文件）
#    README.md, PRODUCTION.md, 开箱即用.md, 初级定制.md
#    （底层源码.md / 深度定制.md 无引用）
#
# 7. 不受影响的文件
#    user_agent_pool/pool.py / pool_async.py  — 均无 resource_pool 引用
#    proxy_pool/pool.py / pool_async.py       — 均无 resource_pool 引用
#    tests/*.py                                — 全部 0 命中
#    .github/workflows/test.yml               — 0 命中
#    .pre-commit-config.yaml, .gitignore      — 0 命中

# Nurture Pool — GitHub 仓库配置参考

> 本地参考文档，不上传 Git。记录本仓库在 GitHub 上所有已配置的设置。
> 配置日期：2026-05-28

---

## 一、General 设置

**路径：** Settings → General

| 设置项 | 状态 | 说明 |
|--------|------|------|
| Release immutability | ✅ 已开启 | 发布后不允许修改 assets 和 tags |
| Always suggest updating PR branches | ✅ 已开启 | base 分支有新提交时提示更新 PR 分支 |
| Allow auto-merge | ✅ 已开启 | CI 通过后自动合并 |
| Automatically delete head branches | ✅ 已开启 | PR 合并后自动删除源分支 |
| Wikis | ✅ 开启（仅协作者可编辑） | |
| Issues | ✅ 开启 | |
| Discussions | ✅ 开启 | |
| Projects | ✅ 开启 | |
| Pull requests | ✅ 开启 | 所有人可创建 PR |
| Preserve this repository | ✅ 开启 | GitHub Archive Program |
| Auto-close issues with merged PRs | ✅ 开启 | |
| Merge strategies | 全部开启（commit/squash/rebase） | |

---

## 二、Branch 保护规则

**路径：** Settings → Branches → Branch protection rules

**保护分支：** `master`

| 规则 | 状态 |
|------|------|
| Require a pull request before merging | ✅ |
| ├─ Require approvals | ✅（至少 1 人审批） |
| Require conversation resolution before merging | ✅ |
| Do not allow bypassing the above settings | ✅（管理员也不能绕过） |
| Allow force pushes | ❌ |
| Allow deletions | ❌ |

---

## 三、Advanced Security

**路径：** Settings → Advanced Security

| 功能 | 状态 | 说明 |
|------|------|------|
| Private vulnerability reporting | ✅ | 允许私下报告安全漏洞 |
| Dependency graph | ✅ | 分析项目依赖 |
| Dependabot alerts | ✅ | 依赖漏洞告警 |
| Dependabot security updates | ✅ | 自动开 PR 修复安全漏洞 |
| Grouped security updates | ✅ | 多个安全更新合并为一个 PR |
| Dependabot version updates | ✅（通过 dependabot.yml） | 每周一自动更新依赖 |
| Secret Protection | ✅（默认开启） | 检测提交中的密钥 |
| Push protection | ✅（默认开启） | 阻止包含密钥的 push |

---

## 四、Actions 设置

**路径：** Settings → Actions → General

| 设置 | 值 |
|------|-----|
| Actions permissions | Allow all actions |
| Fork PR workflow approval | Require approval for first-time contributors |
| Workflow permissions | Read repository contents and packages |
| Artifact/log retention | 90 days |

---

## 五、Secrets

**路径：** Settings → Secrets and variables → Actions

| Secret 名称 | 用途 |
|-------------|------|
| `PYPI_API_TOKEN` | 自动发布到 PyPI（publish.yml 使用） |

---

## 六、代码级配置文件

### `.github/workflows/test.yml`
- 触发：push 到 master、PR 到 master
- 矩阵：Python 3.10 / 3.11 / 3.12 / 3.13
- 包含 lint（ruff）和 test（pytest）

### `.github/workflows/publish.yml`
- 触发：Release published
- 自动构建并发布到 PyPI（使用 `PYPI_API_TOKEN`）

### `.github/dependabot.yml`
- pip 依赖：每周一更新，最多 5 个 PR
- GitHub Actions：每周一更新，最多 3 个 PR

### `.github/PULL_REQUEST_TEMPLATE.md`
- PR 模板，包含变更类型、说明、影响范围、测试 checklist

### `.github/ISSUE_TEMPLATE/bug_report.md`
- Bug 报告模板

---

## 七、About 页面

**路径：** 仓库首页右侧 About 区域

| 字段 | 值 |
|------|-----|
| Website | https://pypi.org/project/nurture-pool/ |
| Topics | python, crawler, user-agent, dns, proxy, anti-detection, scrapy, web-scraping, requests |

---

## 八、日常开发流程

由于 master 已开启分支保护，日常开发建议：

```
1. 拉最新代码     git pull
2. 开 feature 分支  git checkout -b feature/xxx
3. 开发 + 提交     git add & git commit
4. 推送分支        git push origin feature/xxx
5. 在 GitHub 上创建 PR → 等待 CI 通过 → 合并
6. 本地切回 master  git checkout master && git pull
```

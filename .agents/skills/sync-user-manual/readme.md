# 使用说明同步 Skill

该 Skill 用于把项目根目录 `使用说明/` 中的 Markdown 文档和被引用图片同步到已部署的 issue-wiki 网站。

## 配置

在项目根目录执行：

```powershell
Copy-Item .agents/skills/sync-user-manual/.env.example .agents/skills/sync-user-manual/.env.local
```

编辑 `.env.local`，填写：

```dotenv
ISSUE_WIKI_API_BASE_URL=https://你的域名/api
ISSUE_WIKI_ADMIN_ACCOUNT=管理员邮箱或手机号
ISSUE_WIKI_ADMIN_PASSWORD=管理员密码
ISSUE_WIKI_DOCUMENT_AUTHOR=生产力Mark
```

`.env.local` 和同步状态文件已被 Git 忽略，不要提交真实账号、密码。

## 使用

可以在 Codex 中调用 `$sync-user-manual`，也可以手动执行脚本。

先预览同步计划，不会上传或修改网站内容：

```powershell
py -3 .agents/skills/sync-user-manual/scripts/sync_manual.py
```

检查预览结果并确认无误后，正式同步：

```powershell
py -3 .agents/skills/sync-user-manual/scripts/sync_manual.py --apply
```

同步会按本地文件夹和文件名创建或更新网站文档，只上传 Markdown 实际引用的图片，不会删除网站上的文件夹、文档或旧图片。

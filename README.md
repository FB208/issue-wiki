# issue-wiki

面向 GitHub 开源项目的任务管理、赞助、共创评论和说明文档综合平台。

## 技术栈

- 后端：FastAPI + SQLAlchemy + MySQL + Redis + Alembic
- 前端：React + Vite
- 文件存储：RustFS S3 兼容接口
- 部署：Docker + GitHub Actions

## 本地开发

先准备根目录 `.env`：

```bash
copy .env.example .env
```

然后配置 `.env` 中的 MySQL、Redis、爱发电、Gmail SMTP、阿里云短信和 RustFS。后端本地调试和 Docker Compose 都读取根目录 `.env`。

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

默认前端访问 `http://localhost:5173`，后端访问 `http://localhost:8000`。

## GitHub Issue 同步配置

GitHub 同步默认关闭。需要启用时，在 `.env` 中配置：

```bash
GITHUB_PROJECT_URL=https://github.com/owner/repo
GITHUB_SYNC_ENABLED=true
GITHUB_TOKEN=github_pat_xxx
GITHUB_WEBHOOK_SECRET=replace-with-random-secret
GITHUB_API_BASE_URL=https://api.github.com
```

`GITHUB_TOKEN` 建议使用 GitHub fine-grained personal access token，授权目标仓库：

- `Metadata`：Read-only
- `Issues`：Read and write

在 GitHub 仓库的 Webhooks 中新增 webhook：

- Payload URL：`https://你的域名/api/github/webhook`
- Content type：`application/json`
- Secret：填写与 `GITHUB_WEBHOOK_SECRET` 相同的值
- Events：选择 `Issues` 和 `Issue comments`

同步规则：

- 非 GitHub 来源任务从 `待审核` 改为其他状态后，如果尚未绑定 issue，会自动创建 GitHub issue。
- GitHub open issue 通过 webhook 或后台“同步历史任务”导入后，本地任务状态为 `待审核`；closed issue 导入为 `已完成`。
- 已绑定 GitHub issue 的任务状态变化会同步到 GitHub；`已完成` 会关闭 issue，其他状态保持 open。
- 赞助金额、启动资金、排序、隐藏状态和订单数据不会写入 GitHub。
- GitHub issue 新评论、编辑评论、删除评论会通过 webhook 同步到本地任务评论。

## 爱发电赞助配置

`.env` 中配置：

```bash
AFDIAN_SPONSOR_URL=https://afdian.com/a/your-name
AFDIAN_WEBHOOK_SECRET=replace-with-random-secret
AFDIAN_USER_ID=
AFDIAN_API_TOKEN=
AFDIAN_API_BASE_URL=https://afdian.net/api/open
```

在爱发电开发者后台配置 webhook：

- Webhook URL：`https://你的域名/api/payments/afdian/webhook?secret=AFDIAN_WEBHOOK_SECRET的值`
- 用户点击任务赞助时，系统会展示功能 ID，例如 `IW-TASK-12`。
- 用户在爱发电备注/留言中填写功能 ID 后，支付成功回调会自动计入对应任务。
- 未填写功能 ID 的订单会记录为“赞助作者”，不会增加到某一个具体任务上。

## VSCode 一键调试

已提供 `.vscode/launch.json` 和 `.vscode/tasks.json`。

使用方式：

1. 确认根目录 `.env` 已配置，并且 MySQL、Redis 可连接。
2. 在 VSCode 的“运行和调试”里选择 `Debug: 全栈一键启动`。
3. 点击启动后会先从 `DEV_BACKEND_PORT` 和 `DEV_FRONTEND_PORT` 开始自动递增寻找可用端口，并写入 `.vscode/.runtime.env`。
4. 然后并行启动 `Backend: FastAPI` 和 `Frontend: Vite`。Vite proxy 会自动使用实际后端端口。
5. Vite 输出本地地址后会自动用 Edge 打开前端调试窗口。
6. 数据库迁移不再阻塞后端启动。需要迁移数据库时，手动运行 VSCode 任务 `backend: migrate`，或在终端执行 `cd backend && alembic upgrade head`。
7. 如果前端提示 `ECONNREFUSED`，说明你输入的后端端口没有服务在监听，优先查看 `Backend: FastAPI` 终端里的 Uvicorn 报错。

如果只想调后端，选择 `Backend: FastAPI only`。如果想用 Chrome，在前端启动后单独选择 `Browser: Chrome`。

## 部署

复制 `.env.example` 为服务器部署目录下的 `.env`，配置 MySQL、Redis、爱发电、Gmail SMTP、阿里云短信和 RustFS。

提交符合 `vX.X.X` 的 tag 后，`.github/workflows/deploy.yml` 会构建单镜像并通过 SSH 执行 `docker compose` 部署。

# AGENTS.md

## 仓库速览
- 单仓全栈：`backend/` 是 FastAPI + SQLAlchemy + MySQL/Redis/Alembic，`frontend/` 是 React + Vite，根 `Dockerfile` 构建前端后把 `frontend/dist` 复制进后端镜像的 `static/`。
- 后端入口是 `backend/app/main.py`；所有 API router 通过 `settings.api_prefix` 挂载，默认前缀是 `/api`；只有存在 `backend/static` 时才由 FastAPI 托管 SPA 静态文件。
- 前端入口是 `frontend/src/main.jsx` -> `frontend/src/App.jsx`；API 封装在 `frontend/src/api.js`，默认请求 `/api`，并自动发送 `Authorization` 和 `X-Guest-Id`。

## 环境与命令
- 后端配置从根 `.env` 读取：`SettingsConfigDict(env_file=(".env", "../.env"))`。不要读取或提交真实 `.env`、`.env.secrets`；按 `.env.example` 和 `.env.secrets.example` 判断变量。
- 后端本地命令在 `backend/` 执行：`python -m venv .venv`，`.venv\Scripts\activate`，`pip install -r requirements.txt`，`alembic upgrade head`，`uvicorn app.main:app --reload`。
- 前端命令在 `frontend/` 执行：`npm install`，`npm run dev`，`npm run build`，`npm run preview`。锁文件是 `frontend/package-lock.json`，不要换成 pnpm/yarn 除非明确要求。
- VSCode 全栈调试使用根目录脚本：`python scripts/dev_ports.py` 写入 `.vscode/.runtime.env`，再跑 `python scripts/run_backend.py` 和 `node scripts/run_frontend.mjs`；这会自动避开被占用端口并设置 `VITE_API_PROXY_TARGET`。
- 当前没有发现 pytest、lint、typecheck、formatter 配置或脚本；不要把这些当作可用验证。前端改动优先用 `npm run build`，后端启动/迁移验证需要 `.env` 中的 MySQL 和 Redis 可连接。

## 数据库与迁移
- `backend/app/main.py` 启动时会先调用 `initialize_database()`，再调用 `ensure_admin_user()`；这会创建 MySQL 数据库、执行 Alembic `upgrade head`，并按环境变量创建/更新管理员账号和密码。
- Alembic 在 `backend/alembic/env.py` 中用 `settings.database_url`，并导入 `app.models` 作为 `Base.metadata`。改 SQLAlchemy 模型时，同步检查 `models.py`、`schemas.py`、相关 serializer/router，并新增 `backend/alembic/versions/` 迁移。

## 业务边界
- 路由集中在 `backend/app/api/`，共享分页和任务序列化在 `backend/app/api/utils.py`，Pydantic schema 在 `backend/app/schemas.py`。
- Redis 通过 `get_redis()` 用于验证码流程；上传接口要求登录用户并依赖 RustFS S3 兼容配置。
- GitHub 同步默认关闭；启用后 webhook 是 `/api/github/webhook`，状态标签前缀是 `issue-wiki/status:`。
- 支付渠道由 `PAYMENT_CHANNEL` 选择，只支持 `xorpay` 或 `afdian`；回调路由分别是 `/api/payments/xorpay/notify` 和 `/api/payments/afdian/webhook`。

## 前端注意点
- `frontend/src/App.jsx` 当前集中包含路由、页面、弹窗、后台和状态逻辑；后端字段变化通常也要同步 `schemas.py`、serializer、`api.js` 调用方和 `App.jsx` 展示。
- 任务列表同时有桌面表格和移动端卡片展示；改列、按钮或状态文案时要同时更新两套 UI。响应式断点在 `frontend/src/styles.css`。
- 仓库含大量中文文案和中文文档；新增 Windows 脚本保持 UTF-8 读写，参考 VSCode 任务里的 `PYTHONUTF8` 和 `PYTHONIOENCODING`。

## 部署
- 有效 GitHub Actions 是 `.github/workflows/deploy.yml`，tag `v*.*.*` 触发；它构建根 `Dockerfile`，推送 `$REGISTRY_REPO:$VERSION` 和 `latest`，再 SSH 到服务器执行 `docker compose pull/up`。
- 根 `docker-compose.yml` 不 build，只使用镜像 `${REGISTRY_REPO:-issue-wiki}:${VERSION:-latest}`，读取根 `.env`，并映射宿主机 `33089` 到容器 `8000`。
- 根目录 `deploy-backend.yml` 不在 `.github/workflows/` 下，且引用不存在的 `backend/docker/Dockerfile`；不要把它当作当前有效 CI 配置。
- Windows 上同步 GitHub Actions secrets：复制 `.env.secrets.example` 为被忽略的 `.env.secrets`，`gh auth login` 后运行 `.github\scripts\sync-secrets.ps1`。

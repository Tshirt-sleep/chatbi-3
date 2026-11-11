# P9 部署操作手册（草案）

本手册针对公开 Mock 演示。当前本地 `master` 分支尚无 commit/remote，且尚未创建云资源；部署前要建立 Git 托管远端并推送项目，让 Netlify/Render 可导入。源码仓库可以保持私有；公开的是演示网站。

## 1. Supabase：建立专用 Mock 数据库

1. 先查看“台词检索网站”所在 Supabase 组织的套餐。如果该组织是 Free，为了避免升级时连旧项目也计入 Pro 计算费，建议新建一个只放 ChatBI 的 Pro 组织；如果旧项目已在 Pro 组织内，可在同组织新建一个独立 ChatBI 项目，接受约 $10/月额外 Micro 计算费。然后在选定组织中新建专用 ChatBI Mock 项目，选择 Singapore；不要复用包含真实数据的项目。
2. 设置唯一数据库密码并保存到密码管理器，不发到聊天、不写入 `.env.example` 或代码。
3. 在项目的 Connect 页面复制 **Session pooler** 连接串（端口 5432）。调整 SQLAlchemy scheme 为 `postgresql+psycopg://`，保留查询参数中的 TLS 设置。该连接串只用于后端。
4. 在本机项目根目录使用 SecureString 提示初始化空库 schema。今后新增 Alembic migration 时，也要先在本机执行此命令成功，再部署应用版本：

   ```powershell
   $secureDbUrl = Read-Host 'Paste the Supabase owner Session Pooler URL' -AsSecureString
   $env:CHATBI_MIGRATION_DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureDbUrl).Password
   .\.venv\Scripts\python.exe -m alembic upgrade head
   Remove-Item Env:\CHATBI_MIGRATION_DATABASE_URL
   ```

5. 迁移完成后，在 Supabase SQL Editor 运行 [P9 Supabase 应用账号权限脚本](P9_SUPABASE_APP_ROLE.sql) 创建 `chatbi_app` 低权限账号。然后用 `psql` 连接该项目的 Session Pooler（命令中只填 host、用户名和端口，不含密码），交互执行 `\password chatbi_app` 并在隐藏提示中设置密码。Render 中只配置 app role URL 到 `CHATBI_DATABASE_URL`；owner URL 不进入 Render 环境。
6. 不要在前端配置数据库连接串、Supabase `service_role` 或数据库密码。

## 2. Render：部署 API

1. 从 Git 仓库导入本项目根目录的 `render.yaml`，选 Singapore 区域和 Starter 规格。
2. Render 环境变量设定：
   - `CHATBI_DATABASE_URL`：Supabase Session Pooler 的 `chatbi_app` 连接串，使用 Render Secret。
   - `CHATBI_CORS_ORIGINS`：Netlify 站点的精确 HTTPS origin，例如 `https://example-name.netlify.app`，不要带路径或尾部斜杠。
   - `CHATBI_PUBLIC_DEMO=true`、`CHATBI_DEBUG_ENABLED=false`、`CHATBI_LLM_PROVIDER=disabled` 按 Blueprint 设置保持。
3. API readiness 返回 ready 后，记录 Render 的 `https://<service>.onrender.com` 地址。
4. 不增加副本、不启用自动横向扩缩容；首版会话状态在单个进程的内存中。

## 3. Netlify：部署前端

1. 导入同一个 Git 仓库，Netlify 读取根目录 `netlify.toml`，在站点环境变量设置 `VITE_CHATBI_API_BASE_URL=https://<service>.onrender.com`（只填 origin，不加 `/api/v1`）。
2. `VITE_CHATBI_PUBLIC_DEMO=true` 由配置开启；没有 API URL 时生产构建会失败，避免生成指向访问者本机的错误前端。
3. 构建成功后先用 Netlify 子域名访问，暂不购买自定义域名。

## 4. 初始数据导入

在部署的代码版本中生成/携带版本化 `data/generated` 文件，然后从受控环境运行：

```powershell
$secureDbUrl = Read-Host 'Paste the Supabase owner Session Pooler URL' -AsSecureString
$env:CHATBI_CLOUD_SEED_DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureDbUrl).Password
.\.venv\Scripts\python.exe scripts\seed_cloud_mock.py --confirm-empty-mock-target
Remove-Item Env:\CHATBI_CLOUD_SEED_DATABASE_URL
```

连接串在本地隐藏输入，不会显示在命令历史中；不要把它发给助手、写入脚本或终端录屏。Seeder 只会连 PostgreSQL，并拒绝已有业务行的目标库；成功后 API readiness 才应变为 ready。Render 运行环境不会保存 owner URL。

## 5. 发布检查

- 创建会话、运行 P6 Golden 问题、对照本地 SQLite 结果。
- 公开模式的 `admin`/`analyst`/`viewer` 角色只作用于 Mock 展示范围；debug 和反馈汇总接口不可用。
- 检查页面 Network 面板，确认没有数据库连接串、服务密钥、SQL 或模型密钥。
- 从中国大陆不同运营商网络测试页面和 API；境外平台不保证大陆可达。
- 检查 Render、Supabase、Netlify 的账单与免费额度；首版 DeepSeek 保持关闭。

## 6. 当前尚需完成

- 建立/选定 Git 托管远端并让 Netlify、Render 可以读取。
- 用户在供应商控制台创建资源并配置秘密值。
- 执行迁移、导入、跨数据库黄金验收、权限验收和账单检查。

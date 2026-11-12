# P9 部署操作手册（草案）

本手册针对公开 Mock 演示。GitHub 私有仓库已创建；Supabase Free/Sydney 验收库已完成迁移、导入和 Golden/Smoke 对照。Render/Netlify 生产演示尚未部署。源码仓库保持私有；公开的是演示网站。

## 1. Supabase：建立专用 Mock 数据库

1. 当前已在 `Dialogue Finder` Free 组织创建独立 `chatbi-mock` 项目，项目状态为 Healthy，区域为 Oceania (Sydney)。项目方已选择公开演示继续使用此 Free 项目，并接受低活跃时可能暂停、没有自动备份。不要复用包含真实数据的项目。项目区创建后不能直接更换；若将来要迁区，需新建空项目并按恢复手册迁移。
2. 设置唯一数据库密码并保存到密码管理器，不发到聊天、不写入 `.env.example` 或代码。
3. 在项目的 Connect 页面复制 **Session pooler** 连接串（端口 5432）。调整 SQLAlchemy scheme 为 `postgresql+psycopg://`，保留查询参数中的 TLS 设置。该连接串只用于后端。
4. 在本机项目根目录使用 SecureString 提示初始化空库 schema。今后新增 Alembic migration 时，也要先在本机执行此命令成功，再部署应用版本：

   ```powershell
   $secureDbUrl = Read-Host 'Paste the Supabase owner Session Pooler URL' -AsSecureString
   $env:CHATBI_MIGRATION_DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureDbUrl).Password
   .\.venv\Scripts\python.exe -m alembic upgrade head
   Remove-Item Env:\CHATBI_MIGRATION_DATABASE_URL
   ```

5. 迁移完成后，在 Supabase SQL Editor 运行 [P9 Supabase 应用账号权限脚本](P9_SUPABASE_APP_ROLE.sql) 创建 `chatbi_app` 低权限账号。在本机运行 `.\.venv\Scripts\python.exe scripts\set_app_role_password.py`，按隐藏提示输入 owner Session Pooler URL 和两次新应用密码；脚本通过 psycopg 安全引用密码执行 `ALTER ROLE`，不回显或写入文件。Render 中只配置 app role URL 到 `CHATBI_DATABASE_URL`；owner URL 不进入 Render 环境。若之前曾将密码写进 SQL Editor 查询，部署前用该脚本轮换一次。
6. 不要在前端配置数据库连接串、Supabase `service_role` 或数据库密码。

## 2. Render：部署 API

1. 从 Git 仓库导入本项目根目录的 `render.yaml`，选 Singapore 区域和 Free 规格。Render Free Web Service 空闲 15 分钟会休眠，收到新请求后约需 1 分钟唤醒；内存 512 MB，每个 workspace 每月共用 750 小时额度，可能因超限暂停服务。适合免费作品集演示，但首次访问会慢，不能保证持续在线。见 [Render Free 服务说明](https://render.com/docs/free)。
2. Render 环境变量设定：
   - `CHATBI_DATABASE_URL`：Supabase Session Pooler 的 `chatbi_app` 连接串，使用 Render Secret。
   - `CHATBI_CORS_ORIGINS`：Netlify 站点的精确 HTTPS origin，例如 `https://example-name.netlify.app`，不要带路径或尾部斜杠。
   - `CHATBI_PUBLIC_DEMO=true`、`CHATBI_DEBUG_ENABLED=false`、`CHATBI_LLM_PROVIDER=disabled` 按 Blueprint 设置保持。
3. API readiness 返回 ready 后，记录 Render 的 `https://<service>.onrender.com` 地址。
4. 不增加副本、不启用自动横向扩缩容；首版会话状态在单个进程的内存中。Free 休眠/重启会清空会话及追问状态。

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

## 4.1 P9-4 SQLite/Supabase 数据对照

本地 SQLite Smoke 基线保存在 `data/local/p9-sqlite-smoke.json`。使用 `chatbi_app` 的 Session Pooler 连接串运行同一套只读校验，并比较报告：

```powershell
$secureDbUrl = Read-Host '输入 chatbi_app 的 Supabase Session Pooler 连接串' -AsSecureString
$env:CHATBI_DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureDbUrl).Password
try {
    .\.venv\Scripts\python.exe -m harness.run_smoke --output data/local/p9-supabase-smoke.json --compare data/local/p9-sqlite-smoke.json
}
finally {
    Remove-Item Env:\CHATBI_DATABASE_URL -ErrorAction SilentlyContinue
}
```

验收应显示 `report_comparison=identical`、`status=passed`、24/24 检查通过。检查覆盖三套 manifest 内容/版本/时区、各 CSV 对应表行数、UQ-01 参考汇总、空日夹具及跨数据库外键孤儿行。报告只保存在被 Git 忽略的 `data/local`。

## 5. 发布检查

- 创建会话、运行 P6 Golden 问题、对照本地 SQLite 结果。
- 公开模式的 `admin`/`analyst`/`viewer` 角色只作用于 Mock 展示范围；debug 和反馈汇总接口不可用。
- 检查页面 Network 面板，确认没有数据库连接串、服务密钥、SQL 或模型密钥。
- 从中国大陆不同运营商网络测试页面和 API；境外平台不保证大陆可达。
- 检查 Render、Supabase、Netlify 的账单与免费额度；首版 DeepSeek 保持关闭。

## 6. 当前尚需完成

- P9-6 数据库目标已确定：使用 Sydney Free `chatbi-mock`，接受可能自动暂停及无自动备份。Render API 按 Blueprint 使用 Singapore Free；同时接受 15 分钟空闲休眠、冷启动约 1 分钟、512 MB 内存和每 workspace 750 小时/月额度。先以 readiness、P6 Golden 和延迟观察验证跨区连接。不要将 owner URL 配入 Render。
- GitHub 私有仓库和 Supabase Free 验收库已建立；项目方已授权 Render/Netlify 获取部署所需的仓库访问权限，但控制台尚未完成连接和服务创建。当前 Windows 浏览器读取连续超时，需恢复控制台 UI 后继续。
- 用户在供应商控制台创建/授权服务并配置 secrets；首次部署前轮换 SQL Editor 中曾输入过的 `chatbi_app` 密码。
- 部署后执行公开 URL、CORS、限流、debug/OpenAPI 禁用、日志与浏览器 Network 核验，并查看实际账单。境外站点从中国大陆的连通性需要实测。
- P9-7 再执行空环境重建/恢复演练；恢复时旧 `turn_feedback` 按项目方确认清空。

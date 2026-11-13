# P9 部署操作手册（草案）

本手册针对公开 Mock 演示。GitHub 私有仓库已创建；Supabase Free/Sydney 验收库与独立 Seoul 恢复演练库已完成迁移、导入和 Golden/Smoke 对照；Render API 与 Netlify 前端已部署。P9-7 恢复与服务级回滚演练通过；P9 已完成。项目方在 P10-3 确认 `chatbi-api` 沿用 Workspace Email + Only failure notifications。源码仓库保持私有；公开的是演示网站。

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

5. 迁移完成后，在 Supabase SQL Editor 运行 [P9 Supabase 应用账号权限脚本](P9_SUPABASE_APP_ROLE.sql) 创建 `chatbi_app` 低权限账号。在本机运行 `.\.venv\Scripts\python.exe scripts\set_app_role_password.py`，按隐藏提示输入 owner Session Pooler URL 和两次新应用密码；原始 `postgresql://` URL 和 SQLAlchemy `postgresql+psycopg://` URL 均可输入。脚本通过 psycopg 安全引用密码执行 `ALTER ROLE`，不回显或写入文件。Render 中只配置 app role URL 到 `CHATBI_DATABASE_URL`；owner URL 不进入 Render 环境。若之前曾将密码写进 SQL Editor 查询，部署前用该脚本轮换一次。
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

## 4.2 现有 `chatbi-mock` 的退款数据增量更新（P11）

本操作只为已存在的 `ecommerce_mock_v1` 增加固定退款事件，不重建 schema，不重播空库 Seeder，也不删除或替换订单、明细、商品、SaaS 数据或反馈。脚本 `scripts/update_cloud_refunds.py` 默认只做 dry run；仅在明确加 `--apply` 后，才会在一个 PostgreSQL 事务中插入退款事件并将电商 manifest 从 `1.0.0` 更新到 `1.1.0`。

1. 在 Supabase Dashboard 选中原有 Sydney 项目 **`chatbi-mock`**，从浏览器地址 `/dashboard/project/<project-ref>` 读取 project ref。不要选 `chatbi-recovery-drill`。
2. 在项目根目录 PowerShell 中隐藏输入 owner Session Pooler URL，再运行 dry run。TLS 参数 `sslmode=require` 必须保留：

   ```powershell
   Set-Location C:\Users\HP\Desktop\chatBI-3
   $projectRef = Read-Host '输入原 chatbi-mock 项目的 Project ref'
   $secureDbUrl = Read-Host '输入原 chatbi-mock 项目的 owner Session Pooler URL' -AsSecureString
   $env:CHATBI_CLOUD_UPDATE_DATABASE_URL = [System.Net.NetworkCredential]::new('', $secureDbUrl).Password
   try {
       .\.venv\Scripts\python.exe .\scripts\update_cloud_refunds.py --expected-project-ref $projectRef
       if ($LASTEXITCODE -ne 0) { throw "退款数据 dry run 失败，退出码：$LASTEXITCODE" }
   }
   finally {
       Remove-Item Env:\CHATBI_CLOUD_UPDATE_DATABASE_URL -ErrorAction SilentlyContinue
       $secureDbUrl = $null
   }
   ```

3. 只有输出确认 project ref 正确、当前版本为 `1.0.0`、旧电商行数匹配且退款行数为 0，才重新运行上述隐藏输入步骤，并给脚本追加 `--apply`。若脚本拒绝或输出不同，停止；不要改用 `seed_cloud_mock.py`。
4. 成功后应显示仅追加 4,674 条退款事件并把版本改为 `1.1.0`。之后再推送已审阅的应用代码；Render/Netlify 部署完成后检查 readiness，并刷新网站创建新会话，查询“最近 30 天退款率最高的商品有哪些？”。

退款导入先提交，应用部署失败时旧 API 会忽略这张已存在的退款表，原有销售问数继续使用；按 P9-7 已演练的 Render/Netlify deploy history 回退代码即可，无需回删 Mock 退款行。脚本遇到库版本、既有退款记录、表行数、项目 ref 或 checksum 不匹配时会在写入前拒绝；退款数据和 manifest 在同一事务中提交。

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

- **已部署**：Render Free Singapore API `https://chatbi-api-avjp.onrender.com`；Netlify Free 前端 `https://for-chatbi.netlify.app/`。项目方提供的 readiness 响应为 `ready/database_and_mock_data`，线上截图成功返回昨日销售额与订单数。
- Supabase 继续使用 Sydney Free `chatbi-mock`，接受可能暂停及无自动备份；Render Free 接受空闲休眠、冷启动、512 MB 和 workspace 月额度限制。不要将 owner URL 配入 Render。
- P9-6 公开 URL 安全负例已由项目方检查；`chatbi_app` 密码已轮换，Render secret 已更新，轮换后 readiness 为 `ready/database_and_mock_data`。项目方提供的日志截图中服务启动、健康检查和预期安全负例状态正常；Network 截图显示 turns 请求 200、响应仅含问数结果和定义，可见范围未发现特权密钥。分享截图时应遮挡会话 ID。2026-11-13 平台快照：Render `$0.00` 预计费用、实例 0.53/750 小时；Supabase Free、Spend Cap 开启、余额 `$0.00`，数据库 39.6 MB/0.5 GB、egress/log ingestion/storage 显示 0、log query 0.006 GB；Netlify Free 已用 15.2/300 credits、剩余 284.8 credits，无付款方式。Render 日志显示进程关闭后约 10 分钟有新进程启动，但不能据此推算请求冷启动耗时；首次请求时延和跨区延迟尚待实测。P9-4 的云端 P6 Golden 与跨库 P5 Smoke 已有报告；线上成功问数作为独立部署链路证据。CORS 与 API origin 已由线上成功问数证明基本生效。
- **P9-7 已通过**：独立 Supabase Free 恢复演练库完成空库迁移、Mock 重建、P5/P6 Golden 对照；Render 临时切换到恢复库后 readiness 和 Netlify 问数成功，随后恢复原 Sydney 连接并再次验证 readiness 与线上问数正常。恢复时旧 `turn_feedback` 按项目方确认清空；演练库保留供后续核验。
- **P9-6 已完成**：项目方截图确认 Render Account Settings 邮箱已设置，Workspace → Notifications 的目的地为 Email，默认服务通知为 Only failure notifications；当前账户所有者负责接收/查看故障邮件并检查 Render Events/Logs。服务级通知覆盖状态将在 P10-3 复核。冷启动与跨区延迟实测由项目方选择跳过，作为已接受限制记录。

## 7. P10 运维值守与模型开关

- 告警：沿用 Render Workspace 的 Email + Only failure notifications；`chatbi-api` 由项目方确认沿用 Workspace 默认设置。账户所有者负责收到故障邮件后登录 Render，检查该服务的 Events 与 Logs。该流程是人工响应，没有自动修复或独立值班系统。
- 模型：DeepSeek 当前关闭。Render Blueprint 的 `CHATBI_LLM_PROVIDER=disabled`；公开演示模式还会在代码中无条件禁用模型 Provider。非公开环境只有同时将 `CHATBI_LLM_PROVIDER=deepseek` 且配置 `DEEPSEEK_API_KEY` 才会启用。恢复为关闭状态时将 Provider 设为 `disabled` 并重新部署；不要把密钥写入仓库或前端。
- 回退边界：Provider 超时/HTTP/响应格式错误在电商路径会回到确定性解析；不符合意图 schema 或白名单验证失败的草稿会被丢弃并回到确定性解析。SaaS Provider 异常同样回到确定性分支。Provider 正常返回但明确标注 unsupported/unknown term 时，系统会安全拒答/提示，不会冒险执行查询。恢复后先以固定问题验收，再决定是否启用。
- 数据重建：Supabase Free 当前没有自动备份。P9-7 已验证可以从版本化 Git Mock 数据在空库上迁移、重建并做 Smoke/Golden 对照；Seeder 会拒绝已有业务行的目标库。恢复重建不保留 `turn_feedback`；已确认该反馈表可从空状态重新开始。不要对线上非空数据库直接运行空库 Seeder。
- 回滚：P9-7 已演练 Render 临时切换到恢复库、验证 readiness/问数、再恢复原数据库连接并再次验证；代码部署回滚需在 Render/Netlify 各自的 deploy history 中选择已知通过版本，并在回滚后检查 readiness 与固定问题。

# P9-5 公开演示安全与恢复方案

- 状态：安全代码检查及定向测试已通过；公开 URL 负例已在 P9-6 检查；P9-7 独立 Supabase 空库重建、Golden 对照和 Render 服务级切换/回滚演练均已通过。恢复时可清空旧 `turn_feedback`。
- 目标环境：公开、匿名可访问的作品集演示；仅允许访问版本化合成 Mock 数据。
- Supabase 验收资源：Free 组织、Oceania/Sydney、Nano。该资源不是持续在线生产目标。

## 1. 公开访问安全边界

| 边界 | 规则与实现 | 当前证据/状态 |
|---|---|---|
| 数据范围 | API 只允许 `ecommerce_mock_v1` 和 `saas_subscription_mock_v1`；公开身份均由固定 Mock 身份表解析，viewer 只可访问电商主题。数据库 manifest 与版本化合成数据逐项核对。 | P9-4 Smoke 24/24，manifest 与记录数一致。 |
| 演示角色 | admin/analyst/viewer 只控制演示界面和固定 Mock 数据范围。公开模式会剥去 debug 与反馈汇总能力，admin 名称不代表真实授权。 | `resolve_mock_identity`；新增公开 admin 负例测试通过。 |
| SQL/接口文档 | 公开模式禁用 SQL debug、Swagger、ReDoc 和 OpenAPI JSON。普通回答不返回 SQL 或连接信息。 | 项目方于 2026-11-13 实测 `/docs`、`/redoc`、`/openapi.json`、debug URL 均返回 404；本地 debug 拒绝由测试覆盖。 |
| 模型外发 | Render Blueprint 将 `CHATBI_LLM_PROVIDER=disabled`；公开模式代码也不创建 DeepSeek provider。 | Blueprint 与代码配置一致；部署后核对 Render 环境值。 |
| 数据库账号 | Render 仅用 `chatbi_app` Session Pooler URL；角色不可超级管理、建库或建角色。业务 Mock 表只读，反馈表允许 select/insert/update。owner URL 仅在本机迁移/重建时输入。 | Supabase `pg_roles` 核对和 `has_table_privilege` 检查已通过；TLS 参数须保留。 |
| Supabase Data API | 应用通过后端 PostgreSQL 连接，不让浏览器直连；权限脚本撤销 `anon`/`authenticated` 对专用项目表和 sequence 的权限。 | SQL Editor 权限脚本已执行，订单查询权限负例通过。该脚本只用于专用 ChatBI Mock 项目。 |
| 跨域请求 | Render 的 `CHATBI_CORS_ORIGINS` 只填 Netlify 站点精确 HTTPS origin；不启用凭据跨域。CORS 是浏览器边界，不是身份认证。 | Render 截图显示配置为 `https://for-chatbi.netlify.app`；线上真实问数通过。 |
| 匿名请求负载 | 公开模式对会话创建、问数和反馈写入施加每进程每分钟 60 次总请求预算，超限返回 429/Retry-After；进程最多保留 2,000 个内存会话。预算跨所有访客共享，服务重启后清零。 | 新增限流/容量保护；安全定向测试 6/6 通过。它是基础保护，不等同于 WAF 或用户级限额。 |
| 数据库故障日志 | 公开模式只记录请求 ID、错误类型和 SQLSTATE，不记录数据库错误详情；请求日志不包含问题正文、SQL、参数或连接串。 | 代码已调整；项目方 2026-11-13 提供的 Render 日志截图中仅见启动信息、路径和 HTTP 状态，无凭据/问题正文/SQL；该截图只覆盖所示日志区间。Netlify Network 的 turns 响应截图可见指标数据和定义，无数据库连接串或特权 API 密钥；请求 URL 中的会话 ID 在后续分享时应遮挡。 |
| 身份与数据类型 | 不接入真实业务数据、个人信息、Supabase service role 或模型密钥。 | 固定数据集、公开模式设置与 P9-4 数据报告符合。 |

### 发布时必须核对

- `CHATBI_PUBLIC_DEMO=true`、`CHATBI_DEBUG_ENABLED=false`、`CHATBI_LLM_PROVIDER=disabled`（项目方截图核对通过）
- `CHATBI_DATABASE_URL` 使用 `chatbi_app`，不是 owner URL；连接串含 TLS 要求。项目方已轮换曾在截图中暴露的密码，并在 Render 更新 secret；轮换后 readiness 再次返回 `ready/database_and_mock_data`。连接串和密码均不写入文档。
- `CHATBI_CORS_ORIGINS=https://for-chatbi.netlify.app`（项目方截图核对通过）
- 前端 `VITE_CHATBI_PUBLIC_DEMO=true`，`VITE_CHATBI_API_BASE_URL` 指向 Render API
- `/docs`、`/redoc`、`/openapi.json` 均不可用；`/api/v1/debug/...` 返回 404（项目方已提供线上检查截图）
- 公开 admin Mock 身份不能查看反馈汇总（已实测 403）或 SQL debug（已实测 404）
- API 429 限流有效；页面、API readiness、真实浏览器查询可用
- Render 环境和日志中没有 owner URL、DB 密码、DeepSeek 密钥；Network 面板无数据库/API service-role 凭据

当前 API 不做真实用户认证，所有访客可使用固定 Mock 身份访问合成数据。每分钟 60 次是单实例总预算，不按访客公平分配；高并发时会让正常访问者收到 429。若公开流量增加，需在边缘层增加 WAF/按 IP 限流，再调整应用预算。

## 2. 备份策略

Supabase Free **不提供自动数据库备份**；Supabase 建议 Free 项目定期使用 CLI 导出并保存异地副本。Pro 提供 7 天每日备份且项目不会因低活跃自动暂停。当前数据库只有可从仓库重建的 Mock 数据，以及可能产生的 `turn_feedback` 评分/分类记录。见 [Supabase 备份说明](https://supabase.com/docs/guides/platform/backups) 和 [Free 备份说明](https://supabase.com/kb/faqs/platform/free-plan-backups)。

推荐按作品集 Demo 设定以下策略：

1. **可重建资产**：代码、Alembic migrations、三个版本化 manifest/CSV 和 P5/P6 验收基线由私有 GitHub 仓库保存；不把可重复生成的订单/订阅行当作唯一备份。
2. **反馈数据**：项目方已确认 `turn_feedback` 是可丢弃的演示遥测，灾难重建或恢复时允许清空旧记录。当前反馈不含原始问题或自由文本；备份不包含该表。恢复后从空表开始收集。
3. **正式持续在线**：建议 Supabase Pro 项目启用每日备份（当前 Pro 说明为 7 天保留），并在 Database > Backups 检查最近备份。PITR 是额外收费能力，首版不启用。升级费用需在最终选型时再次核价。
4. **密钥**：备份中不保存 `chatbi_app` 密码；重建/从 Supabase 备份恢复后在数据库中重新设置该角色密码，并更新 Render secret。本机脚本 `scripts/set_app_role_password.py` 使用隐藏输入和 psycopg SQL 引用设置角色密码；此前若密码通过 SQL Editor 输入，正式部署前用该脚本轮换。owner 凭据保存在密码管理器，不与代码/备份放在一起。
5. **当前 Free 验收阶段**：不承诺自动备份/RPO。可按需生成 CLI 逻辑备份并将文件加密保存到仓库以外的位置；不要把未加密数据库导出放进 Git。Free 项目低活跃自动暂停属于可恢复暂停，不等于可用的数据库备份。

## 3. 从空环境重建（当前可执行恢复路径）

该流程用于项目删除、损坏或需要换区时，在**新的空 Supabase Mock 项目**恢复服务；不在旧库执行清空或覆盖操作。

1. 从 GitHub 检出已验收的代码版本，核对生成数据 manifest 和本地 `p9-sqlite-smoke.json`、`p9-supabase-p6-golden.json` 基线。
2. 在新 Supabase 项目用 owner Session Pooler URL 在本机执行 `alembic upgrade head`。
3. 运行 `P9_SUPABASE_APP_ROLE.sql` 创建 `chatbi_app`，通过安全提示单独设密码。
4. 以 owner URL 在本机运行 `scripts/seed_cloud_mock.py --confirm-empty-mock-target`，导入版本化 Mock 数据。
5. 以 `chatbi_app` URL 验证 `/api/v1/health/ready`、`harness.run_smoke` 的 24/24 与 `harness.run_query_eval` 的 10/10、54/54。
6. 核对 `chatbi_app` 权限；在 Render 更新 `CHATBI_DATABASE_URL` secret 并部署。确认 API ready 后再将 Netlify API URL 指向该 API。
7. 验证公开安全清单，保留新的部署版本、数据 manifest、两个验收报告和恢复耗时记录。

Mock 业务数据的恢复点是 Git 中固定的数据快照（数据版本可重建）；反馈数据按上述推荐策略重置。P9-7 已完成恢复和服务回滚验证；本次未专门计时并承诺生产级 RTO。

### P9-7 本地隔离恢复演练（2026-11-13）

- 在 `data/local/` 下创建了唯一命名的临时 SQLite 目标库；没有连接或修改线上 Supabase `chatbi-mock`。
- 从仓库 Alembic 迁移执行 3 个 revision 至 `head`；按仓库版本化 CSV/manifest 重建 `ecommerce_mock_v1`、`ecommerce_empty_day_fixture_v1` 和 `saas_subscription_mock_v1` 三套 Mock 数据。
- P5 smoke 结果 `passed`，24/24；与 `data/local/p9-sqlite-smoke.json` 比较为 `report_comparison=identical`。UQ-01 恢复为 25,798,480 分/41 单；空日趋势夹具通过；外键孤儿行为 0。
- 本地报告和临时库位于 Git 忽略的 `data/local/`，本机路径为 `p9-recovery-drill-<随机 ID>-smoke.json` 和对应 SQLite 文件。它们不是云端备份。
- **阶段边界**：这项本地演练仅证明仓库能在隔离 SQLite 数据库重建 schema 和 Mock 数据；Supabase/PostgreSQL 与服务级切换在下方独立云端演练中验证。不得清空当前 `chatbi-mock`。

### P9-7 云端隔离目标已创建（2026-11-13）

- 项目方创建独立 Supabase Free 项目 `chatbi-recovery-drill`；控制台截图显示状态 Healthy、Nano、Northeast Asia (Seoul)，并显示 `No migrations`、`No backups`、`No repository connected`。
- 项目方随后在本机从私有代码仓库运行 `alembic upgrade head`；输出确认 PostgreSQL 上三项 migration 成功执行至 `c21f8d6a4e30`。连接 URL 仅通过 PowerShell 隐藏输入，未写入文档。
- 项目方随后通过本机隐藏输入脚本成功设置新项目 `chatbi_app` 密码，并以 owner 连接成功导入三套 Mock 数据；之后用新库 `chatbi_app` URL 执行 P5 Smoke，`report_comparison=identical`、24/24 passed，与 SQLite 基线一致；P6 HTTP Golden 也 `report_comparison=identical`，10 case、54/54 checks passed，与既有 Supabase 基线一致。Supabase SQL Editor 的只读权限核对显示 `rolsuper/rolcreatedb/rolcreaterole=false`、订单 SELECT 和 feedback SELECT/INSERT/UPDATE 均为 true，anon/authenticated 的订单 SELECT 均为 false。凭据未显示或写入文件。
- 这是独立的数据库恢复目标，不是新的 GitHub 仓库；现有 `chatBI-3` 源码仓库继续用于迁移和 seed。
- 该空项目已完成 `chatbi_app` 创建/设置密码及三套 Mock 数据导入；新库 app role P5 Smoke 与本地基线 identical，24/24 passed，P6 HTTP Golden 与既有 Supabase 基线 identical，10 case/54 checks passed；角色最小权限与 anon/authenticated 负例均符合预期。随后项目方将 Render `CHATBI_DATABASE_URL` 临时切到恢复库，readiness 返回 `ready/database_and_mock_data`，Netlify 问数成功返回销售额 `¥257,984.80`、订单数 41；之后将连接串恢复为原 `chatbi-mock`，readiness 再次为 ready，线上问数仍正常。服务级切换和回滚验证通过；未记录或分享任何连接串/密码，现有恢复演练项目保留。

## 4. P9-5 验收状态

- 代码边界与自动检查：通过（公开 admin 无 debug/反馈汇总；公开请求限流与会话容量上限；Ruff、mypy 和 access/feedback 定向 pytest 通过）。
- 云端低权限连接和匿名 role 权限：通过（P9-4 检查证据）。
- 备份/恢复策略与重建步骤：已定义。
- Render/Netlify 基本配置、公开 URL 负例、Render 日志和浏览器 Network 截图抽查：项目方提供证据，结果符合预期；Network 截图中会话 ID 属非认证标识，但分享时应遮挡。
- Render 环境截图曾暴露 `chatbi_app` 数据库密码；项目方已轮换并更新 Render secret，轮换后 readiness 复核通过。仍需确认日志没有敏感信息。
- 独立空库重建、P5/P6 对照及 Render 切换/回滚：P9-7 已通过；本演练未覆盖 Supabase 托管备份恢复，也未测量生产级 RTO。
- `turn_feedback` 恢复策略：项目方已确认可清空旧反馈；该表不纳入备份，恢复后从空表开始。

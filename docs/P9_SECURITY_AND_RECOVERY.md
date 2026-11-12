# P9-5 公开演示安全与恢复方案

- 状态：安全代码检查及定向测试已通过；备份/恢复策略已形成；项目方已确认恢复时可清空旧 `turn_feedback`。生产 URL 检查留 P9-6，实际恢复演练留 P9-7。
- 目标环境：公开、匿名可访问的作品集演示；仅允许访问版本化合成 Mock 数据。
- Supabase 验收资源：Free 组织、Oceania/Sydney、Nano。该资源不是持续在线生产目标。

## 1. 公开访问安全边界

| 边界 | 规则与实现 | 当前证据/状态 |
|---|---|---|
| 数据范围 | API 只允许 `ecommerce_mock_v1` 和 `saas_subscription_mock_v1`；公开身份均由固定 Mock 身份表解析，viewer 只可访问电商主题。数据库 manifest 与版本化合成数据逐项核对。 | P9-4 Smoke 24/24，manifest 与记录数一致。 |
| 演示角色 | admin/analyst/viewer 只控制演示界面和固定 Mock 数据范围。公开模式会剥去 debug 与反馈汇总能力，admin 名称不代表真实授权。 | `resolve_mock_identity`；新增公开 admin 负例测试通过。 |
| SQL/接口文档 | 公开模式禁用 SQL debug、Swagger、ReDoc 和 OpenAPI JSON。普通回答不返回 SQL 或连接信息。 | 启动时根据 `CHATBI_PUBLIC_DEMO=true` 关闭文档路由；debug 拒绝由测试覆盖。部署后仍须检查实际 URL。 |
| 模型外发 | Render Blueprint 将 `CHATBI_LLM_PROVIDER=disabled`；公开模式代码也不创建 DeepSeek provider。 | Blueprint 与代码配置一致；部署后核对 Render 环境值。 |
| 数据库账号 | Render 仅用 `chatbi_app` Session Pooler URL；角色不可超级管理、建库或建角色。业务 Mock 表只读，反馈表允许 select/insert/update。owner URL 仅在本机迁移/重建时输入。 | Supabase `pg_roles` 核对和 `has_table_privilege` 检查已通过；TLS 参数须保留。 |
| Supabase Data API | 应用通过后端 PostgreSQL 连接，不让浏览器直连；权限脚本撤销 `anon`/`authenticated` 对专用项目表和 sequence 的权限。 | SQL Editor 权限脚本已执行，订单查询权限负例通过。该脚本只用于专用 ChatBI Mock 项目。 |
| 跨域请求 | Render 的 `CHATBI_CORS_ORIGINS` 只填 Netlify 站点精确 HTTPS origin；不启用凭据跨域。CORS 是浏览器边界，不是身份认证。 | 蓝图和 CORS 配置已实现；需在部署时检查实际域名。 |
| 匿名请求负载 | 公开模式对会话创建、问数和反馈写入施加每进程每分钟 60 次总请求预算，超限返回 429/Retry-After；进程最多保留 2,000 个内存会话。预算跨所有访客共享，服务重启后清零。 | 新增限流/容量保护；安全定向测试 6/6 通过。它是基础保护，不等同于 WAF 或用户级限额。 |
| 数据库故障日志 | 公开模式只记录请求 ID、错误类型和 SQLSTATE，不记录数据库错误详情；请求日志不包含问题正文、SQL、参数或连接串。 | 代码已调整；需在 Render 日志抽查。 |
| 身份与数据类型 | 不接入真实业务数据、个人信息、Supabase service role 或模型密钥。 | 固定数据集、公开模式设置与 P9-4 数据报告符合。 |

### 发布时必须核对

- `CHATBI_PUBLIC_DEMO=true`
- `CHATBI_DEBUG_ENABLED=false`
- `CHATBI_LLM_PROVIDER=disabled`
- `CHATBI_DATABASE_URL` 使用 `chatbi_app`，不是 owner URL；连接串含 TLS 要求
- `CHATBI_CORS_ORIGINS` 是 Netlify 精确 origin
- 前端 `VITE_CHATBI_PUBLIC_DEMO=true`，`VITE_CHATBI_API_BASE_URL` 指向 Render API
- `/docs`、`/redoc`、`/openapi.json` 均不可用；`/api/v1/debug/...` 返回 404
- 公开 admin Mock 身份仍不能查看反馈汇总或 SQL debug
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

Mock 业务数据的恢复点是 Git 中固定的数据快照（数据版本可重建）；反馈数据按上述推荐策略重置。实际恢复耗时须在 P9-7 演练后记录，当前不宣称已演练。

## 4. P9-5 验收状态

- 代码边界与自动检查：通过（公开 admin 无 debug/反馈汇总；公开请求限流与会话容量上限；Ruff、mypy 和 access/feedback 定向 pytest 通过）。
- 云端低权限连接和匿名 role 权限：通过（P9-4 检查证据）。
- 备份/恢复策略与重建步骤：已定义。
- 实际 Render/Netlify 配置、公开 URL 负例检查、日志/Network 检查：部署前待执行。
- 实际备份恢复演练和实测 RTO：留 P9-7。
- `turn_feedback` 恢复策略：项目方已确认可清空旧反馈；该表不纳入备份，恢复后从空表开始。

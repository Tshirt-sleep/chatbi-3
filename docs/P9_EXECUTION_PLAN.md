# P9 云数据库迁移与云端 Mock 部署执行计划

- 状态：P9 验收项完成，准备进入 P10（P9-6 邮件故障告警已配置；P9-7 云端重建、Golden 对照和服务回滚已通过）
- 日期：2026-11-11
- 前置：P8 已正式签收；所有数据保持为合成 Mock 数据
- 部署边界：公开演示仅使用合成 Mock 数据；演示角色切换只影响预设 UI/Mock 能力，服务端不授予真实管理员权限
- 数据库类别：沿用 P4 已确认的 PostgreSQL 兼容数据库目标；P9-1 决定具体云厂商/产品，不重新讨论 SQLite 作为云目标

## 1. 目标

把本地 SQLite Mock ChatBI 部署到经项目方选定的云环境，保持黄金问数结果一致，并具备可重复迁移、健康检查、备份恢复和回滚方法。公开演示只使用合成 Mock 数据；发布前仍须通过 P9 安全验收。

## 2. 仓库架构盘点

| 领域 | 当前实现 | P9 影响 |
|---|---|---|
| 数据库地址 | `CHATBI_DATABASE_URL`，SQLAlchemy `Engine`，现已增加 psycopg 3 并归一化常见 Supabase URL | 云端实际连接/SSL 仍待 Supabase 项目验证 |
| Schema 变更 | Alembic，迁移脚本包含当前模型表 | Blueprint 预部署执行迁移；需在 Supabase 空库验证升级和重复升级 |
| 数据导入 | 本地 SQLite Seeder 保持路径限制；新增仅 PostgreSQL、拒绝非空表的显式云 Mock 导入脚本 | 首次导入和 manifest 核对待云数据库执行 |
| 健康检查 | readiness 已改为 SQLAlchemy Inspector 表检查 | 需在 PostgreSQL 验证缺迁移/缺数据/数据库断开响应 |
| 查询 SQL | SQLAlchemy `text()` 参数化；日期键使用 `substr()` | SQLite 和 PostgreSQL 均支持该字符串函数；仍需以云端 Golden 验证金额类型、排序和结果一致性 |
| API 状态 | 会话、追问、debug owner、turn owner 存进程内字典 | 重启丢失，多个副本状态不共享；部署拓扑需限制单副本或设计持久化/共享状态 |
| 身份与访问 | P8 可切换 `X-Mock-User` | 只能作为演示外观/Mock 行为；服务端固定为匿名公开演示权限，不得把该 header 当作授权凭据 |
| 配置与密钥 | `.env` 本地加载；模型密钥取自环境变量 | 云环境需使用平台密钥管理，不把 `.env` 打包进镜像或提交 |
| 网络绑定 | 本地开发仍绑定 `127.0.0.1`；CORS/API origin 已支持环境配置 | Render Blueprint 使用 `0.0.0.0:$PORT`、TLS health check；生产 CORS 需设置精确 Netlify origin |

## 3. 分阶段任务

### P9-1 选择目标云平台与运行边界（已确认）

项目方已确认 Supabase 作为数据库方向、网站可以部署在中国大陆以外、公开 Mock 演示可以保留角色切换但不能提供真实管理权限，先使用供应商子域名。源码托管使用 GitHub 私有仓库。项目方在 2026-11-12 明确选择：P9-6 公开演示继续使用现有 Supabase Free `chatbi-mock`，不增加 Supabase 费用，并接受低活跃可能暂停且无自动备份；Render API 也改用 Free，接受其空闲休眠、冷启动和使用额度。Supabase 项目为 Oceania (Sydney)、Nano；Render Blueprint 区域为 Singapore，部署后必须实测跨区连接延迟与稳定性。

**产物**：云平台决策记录、架构图、费用估算、私网/公网访问边界、责任人。

### P9-2 确认迁移和会话状态方案（决策已记录）

- 固定数据版本、manifest 校验和及数据库 schema revision。
- 定义空库迁移、Mock 导入、行数/外键/金额/时间范围校验、失败清理与重跑。
- 会话状态选定单副本内存存储，接受 Render 重启或重部署后会话/追问状态清空；不得启用多副本。
- 定义 Alembic 向前迁移和回滚策略；有数据表时不得假设 downgrade 可无损恢复数据。

**产物**：迁移设计、操作手册、回滚步骤和 Mock 数据重建方案。

### P9-3 建立数据库适配并兼容目标数据库（实现中）

- 增加 psycopg 3 驱动与 PostgreSQL URL 归一化；本地 SQLite 继续作为开发默认值。
- readiness 改用 SQLAlchemy Inspector 检查表，不依赖 SQLite 系统表。
- 前端 API origin 与 CORS origin 由部署环境变量配置。
- 增加公开演示服务端权限钳制和 Render/Netlify 部署蓝图。
- 审核/修订所有 SQL 方言、事务和连接池设置。
- 保持 Seeder 默认只能写入本地 SQLite；另建显式目标库导入入口，要求非生产环境和 Mock dataset allowlist。

**产物**：数据库兼容改动、迁移和导入工具、自动化跨数据库验收。

### P9-4 在云 Mock 数据库迁移并做黄金对照

先执行 Alembic，再导入固定 manifest 数据；核对 checksum、行数、外键、金额边界、关键汇总和 P6 HTTP Golden。失败时不得部分标记成功；保留可重跑日志和回滚步骤。

**产物**：迁移报告、P5 Smoke 报告、P6 HTTP Golden 报告及差异说明。

### P9-5 访问、安全与备份恢复

- 最小数据库账号权限、TLS、私网/白名单、密钥管理、访问日志。
- 公开演示允许匿名访问，但服务端强制固定的公开 Mock 权限；P8 Mock 身份只可影响演示外观/允许的 Mock 操作，不作为授权凭据。管理员汇总、SQL debug、真实数据连接必须在公开部署中关闭或不可达。
- 定义加密备份、保留期、恢复到干净环境的方法和恢复后黄金校验。

**产物**：安全配置清单、备份/恢复记录、访问验证和权限审查。

### P9-6 部署、监控、成本与运维

- 可重复部署/销毁；readiness、liveness、日志、告警和模型供应商失败降级。
- 记录资源规格、预算、实际/估算月成本、自动关停策略与责任人。
- 明确数据库迁移由谁、何时、以何种回滚条件执行。

**产物**：部署脚本/流水线、运维手册、成本记录和告警检查。

### P9-7 重建和回滚演练

从空环境重建数据库和应用，演练错误配置、迁移失败、备份恢复、版本回退及数据重置；每次检查恢复后的 P5/P6 黄金结果。

**产物**：演练报告、遗留问题清单和 P9 阶段门签收材料。

## 4. 验收标准

- AC-01：云平台、地区、访问边界及预算有项目方确认的决策记录。
- AC-02：新建空数据库可重复迁移；重复执行行为明确，不会静默覆盖数据。
- AC-03：Mock 数据导入的 manifest checksum、行数、外键和关键字段校验通过。
- AC-04：SQLite 与目标数据库的 P6 HTTP Golden 为 10/10 用例、54/54 检查一致；差异须解释并经核准。
- AC-05：readiness/liveness、数据库断开和迁移缺失可正确报告。
- AC-06：云端数据只有 Mock；凭据不进入源码、镜像、普通日志或评估报告。
- AC-07：网络/身份边界已验证；匿名公开演示只能访问合成 Mock 数据，切换演示角色不能获得服务端管理权限，SQL debug 和真实数据路径不可达。
- AC-08：备份恢复、部署重建和版本回滚演练均有记录且黄金检查通过。
- AC-09：成本上限、自动关停、告警与运维责任明确。

## 5. P9-1 决策与 P9-2 当前方案

项目方确认使用 Supabase，网站可以部署在中国大陆以外；公开访问仅承载 Mock 数据，角色切换不可取得真实管理员权限；使用 Netlify/Render 平台子域名，不购买域名。项目方在 P9-6 选择继续用现有 Free 组织及专用 `chatbi-mock`，不增加 Supabase 费用，并接受可能自动暂停、无自动备份。该项目区域为 Oceania (Sydney)、规格 Nano。Render Blueprint 运行在 Singapore，跨区数据库连接需部署后观察；大陆网络可达性也需实测，不作保证。

**当前进度（2026-11-13）**：Supabase Free 项目 `chatbi-mock`（Sydney/Nano）状态 Healthy。owner Session Pooler 已在本机用于 Alembic 三个迁移及三套 Mock 数据导入；seed 命令报告成功。`chatbi_app` 角色已在 SQL Editor 创建，查询 `pg_roles` 确认 `rolsuper=false`、`rolcreatedb=false`、`rolcreaterole=false`。用户本机以 `chatbi_app` Session Pooler URL 测试连接，`SELECT 1` 返回 1，订单行读取为 20,002；临时 `CHATBI_DATABASE_URL` 随后清除。完整本地 `scripts/check.ps1` 通过；云端 P5 Smoke 两库对照 identical 24/24，Supabase P6 HTTP Golden 10/10、54/54。

**P9-4 完成记录（2026-11-12）**：Supabase Free/Sydney 空库完成 3 个 Alembic migration 和 3 套 Mock 数据导入；`chatbi_app` 连接/readiness/权限通过。Supabase P6 HTTP Golden 10/10、54/54，且 JSON 与本地基线完全一致，报告见 [`p9-supabase-p6-golden.json`](../data/local/p9-supabase-p6-golden.json)。跨数据库 P5 Smoke 已对 SQLite 和 Supabase 分别运行并执行 `--compare`，结果 `report_comparison=identical`，两端均 24/24；覆盖 manifest 全文/版本/时区、CSV 对应行数、UQ-01 昨日汇总、空日夹具和外键孤儿行（0）。报告分别为 [`p9-sqlite-smoke.json`](../data/local/p9-sqlite-smoke.json) 与 [`p9-supabase-smoke.json`](../data/local/p9-supabase-smoke.json)。

**P9-5 安全与恢复方案（方案/代码交付完成）**：检查结果、公开部署核对项和重建流程见 [P9 安全与恢复方案](P9_SECURITY_AND_RECOVERY.md)。公开模式限制到固定 Mock 数据与角色；debug/OpenAPI/DeepSeek 关闭；应用数据库账号使用 `chatbi_app`；增加每进程每分钟 60 次 mutation 总请求预算和 2,000 个会话上限；公开日志隐藏数据库错误详情。Supabase Free 没有自动备份，项目以 Git 固定 CSV/manifest 和 Alembic 作为可重建备份。项目方已确认恢复时清空旧 `turn_feedback`；该表不纳入备份。定向安全测试 6/6、Ruff 和 mypy 通过。公开 URL 负例检查留 P9-6，恢复演练留 P9-7。

**P9-6 部署记录（2026-11-13）**：Render Free API 已部署，地址为 `https://chatbi-api-avjp.onrender.com`。用户打开 `/api/v1/health/ready` 并提供截图，响应为 `{"status":"ready","dependency":"database_and_mock_data"}`。Netlify Free 站点 `https://for-chatbi.netlify.app/` 已 Published；控制台截图显示 `master@2acfde3`。用户提供的线上页面截图显示电商主题成功查询昨日销售额 `¥257,984.80` 和订单数 `41`，并展示解析条件与 Mock 数据集版本。这证明公开前后端至少一条真实查询链路可用。此前 `Failed to fetch` 已消失，说明当前 API origin/CORS 配置已达到基本可用状态。此证据由项目方截图提供，尚未独立留存完整的云端 P6 Golden 报告。

**P9-6 安全检查记录（2026-11-13）**：项目方提供浏览器结果：`/docs`、`/redoc`、`/openapi.json` 与 SQL debug 路由均返回 `{"detail":"Not Found"}`；反馈汇总无 Mock 身份返回 401，带 `X-Mock-User: admin` 返回 403。Render 环境截图显示 `CHATBI_PUBLIC_DEMO=true`、`CHATBI_DEBUG_ENABLED=false`、`CHATBI_LLM_PROVIDER=disabled`，`CHATBI_CORS_ORIGINS` 与公开 Netlify origin 一致；数据库账号为 `chatbi_app`。该截图曾意外包含数据库凭据；项目方随后通过隐藏输入脚本轮换 `chatbi_app` 密码并更新 Render secret。轮换后 `/api/v1/health/ready` 返回 `{"status":"ready","dependency":"database_and_mock_data"}`，证明部署服务已用新凭据恢复数据库连接。不得将连接串或密码复制到本记录。

**P9-6 运维验收记录（2026-11-13）**：凭据轮换及 readiness 复核已完成。项目方提供的 Render Application Logs 截图显示 Uvicorn 正常启动；`/docs`、`/redoc`、`/openapi.json` 返回 404，未授权 debug 返回 401，feedback summary 返回 403，readiness GET 返回 200。可见日志只有访问路径、HTTP 状态及启动信息，没有凭据、问题正文或 SQL；抽查范围仅为截图所示时间窗口。Netlify Network 截图显示 turns 为 200，响应仅含问数结果、定义、状态和 request/turn ID；分享证据时应遮挡会话 ID。平台额度/用量已记录。项目方选择跳过冷启动与跨区延迟实测，并接受 Render Free 休眠及跨区时延的不确定性。随后项目方提供 Render Account Settings 截图确认账户邮箱已设置，Workspace → Notifications 截图显示目的地为 Email、Default Service Notifications 为 Only failure notifications；由当前账户所有者接收并查看故障通知。P9-4 云端 HTTP Golden 为 10/10、54/54，SQLite/Supabase P5 Smoke 为 24/24 identical；不将本地 ASGI harness 误作公网完整 Golden。

**P9-6 平台用量与费用快照（2026-11-13，项目方控制台读数）**：Render Hobby Free：本月实例 `0.53/750 小时`、带宽 `0 MB/5 GB`、流水线 `2/500 分钟`、服务 `1/25`；当前累计与预计费用均 `$0.00`，无历史发票、未绑定付款方式。Supabase Free：Spend Cap 开启，余额 `$0.00`，无发票、未绑定付款方式；项目 Usage 截图显示 Database Size `0.042 GB`，详情页显示当前最大数据库大小 `39.6 MB / 0.5 GB`（约 7.9%）；Log Ingestion `0 GB`、Log Query `0.006 GB`、Egress `0 GB`、Cached Egress `0 GB`、Storage `0 GB`、MAU/第三方 MAU/Realtime/Edge Function/Image Transformations 均为 0。项目概览 CPU 3%、磁盘 15%、内存 51%、连接数 8/60 属于运行指标，不代表账单金额。Netlify Free：本周期剩余 `284.8/300 credits`、已用 `15.2 credits`；生产部署 1 次/15 credits、Web 请求 390 次/约 0.1 credits、计算少于 1 credit、带宽约 0.1 credit；未保存付款方式。读数以截图时控制台为准，额度和用量会随周期变化。

**P9 阶段门结论**：部署、安全负例、数据库重建、P5/P6 Golden、服务切换/回滚、资源/成本快照及邮件故障告警均已记录。冷启动/跨区延迟实测按项目方选择跳过；Supabase Free 不提供可依赖的自动备份，本演练验证的是通过 Git 中 Mock 数据和迁移重建，而非托管备份恢复；未承诺生产级 RTO。该限制已明确记录，P9 可进入 P10 最终验收。

**P9-7 本地隔离恢复演练（2026-11-13）**：在全新、随机命名的本地 SQLite 库上执行 3 个 Alembic revision、从仓库重建三套 Mock 数据，P5 Smoke 24/24 通过并与 `p9-sqlite-smoke.json` 完全一致；当时未触碰线上 Supabase。随后另在独立 Supabase 恢复项目完成云端重建和服务回滚，详见下方云端记录与[安全与恢复方案](P9_SECURITY_AND_RECOVERY.md)。

**P9-7 云端隔离目标（2026-11-13）**：项目方已创建 Supabase Free 项目 `chatbi-recovery-drill`；截图显示 Healthy、Nano、Seoul、No migrations、No backups、未连接 GitHub。该项目用于恢复演练，源码继续使用现有私有 GitHub 仓库。项目方随后执行 `alembic upgrade head`，确认 PostgreSQL 上三个 revision 成功至 `c21f8d6a4e30`；URL 通过隐藏输入，没有保存。`chatbi_app` 密码也通过本机隐藏输入脚本成功设置，owner seeder 成功导入三套 Mock 数据。下一步用新库 app role 执行只读 Smoke 对照和权限核验；若控制台提示升级或付费则停止。

项目方用新库 app role 运行 P5 Smoke：`report_comparison=identical`，24/24 检查通过；结果与本地 SQLite 基线完全一致。随后运行 P6 HTTP Golden：`report_comparison=identical`，10 case/54 checks 全部通过，与既有 Supabase P6 基线一致。Supabase SQL Editor 只读核对确认 app role 不能超级管理/建库/建角色，业务订单只读，feedback 可读写；anon/authenticated 无订单读取权限。数据库层恢复验收通过；后续已完成 Render 服务级切换与回滚，见下一段。

项目方随后完成 Render 服务级切换和回滚：临时将 Render `CHATBI_DATABASE_URL` 改为 `chatbi-recovery-drill` 的 app-role URL，Render readiness 返回 `ready/database_and_mock_data`，Netlify 实际问数成功，结果为 `¥257,984.80` / 41 单；再恢复原 `chatbi-mock` 连接串并部署，readiness 再次 ready，Netlify 问数仍正常。未更改代码版本、未删除数据库。P9-7 云端恢复及服务回滚演练通过。

## 6. 阶段门

P9 完成条件：AC-01 至 AC-09 全部通过，完整迁移与恢复证据归档，云端仅含 Mock 数据。P9 完成后仍需独立评审 P10；不得将云端部署自动视为产品上线。

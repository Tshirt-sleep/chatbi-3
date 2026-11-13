# 开发与协作约定

本文件记录项目当前实际采用的开发方式。产品范围和阶段顺序以仓库根目录的 [`DEVELOPMENT_PLAN.md`](../DEVELOPMENT_PLAN.md) 为准。

## 当前仓库状态

- Git 已在项目根目录初始化，当前分支为 `master`。
- 当前仓库尚无 Git 提交。
- P0–P7（Mock 数据范围）已完成；P6 长图评审发现的问题已修正并复验（2026-11-07）；P7 DeepSeek API 适配、7 例黄金评估（7/7）和完整工程回归（61 项 pytest、类型/格式/前端构建）已通过；项目方接受耗时和费用基线，当前进入 P8。真实业务数据或公网开放前需另行审查数据留存、隐私告知和安全控制。
- 已锁定前端 React 19.3.1、TypeScript 7.0.2、Vite 8.3.6；后端 FastAPI 0.162.0、Pydantic 2.14.2、SQLAlchemy 2.1.8、Alembic 1.20.1、Uvicorn 0.54.0。
- 需要 Python 3.11、Node.js 20.19 或更新的兼容版本和 npm。项目当前工作环境 Python 3.11.9、Node.js 24.16.0。
- 本地数据库文件位于 `data/local/chatbi.sqlite`（已加入 Git 忽略）；生成源仍为 `data/generated/` 下的 CSV 与 manifest。

## 分支与提交

- 小型单人改动可以直接在当前分支进行；需要隔离实验或并行功能时，再创建短期功能分支。
- 每个达到可复核状态的节点做一次提交，提交信息包含阶段/任务 ID 和简述，例如：`P0-2 建立文档目录`。
- 提交前检查 `git status` 和 diff，确保不包含密钥、个人信息、真实业务数据或无关文件。
- 不要把未验证的改动标记为“已完成”；提交记录不等同于验收通过。

## 文档与任务状态

- 主路线和项目约束写在 `DEVELOPMENT_PLAN.md`。
- 阶段产物按类型放入 `docs/research/`、`docs/acceptance/`、`docs/decisions/` 等目录。
- 每项任务记录状态、完成证据、问题和下一步；涉及关键范围/技术/指标口径的决定追加到主计划的决策记录或单独 ADR。
- AI coding 每次只处理一个可验收任务；先读对应需求/设计，再改动，完成后运行该任务定义的检查并回写结果。

## 当前 Mock 数据边界

- 所有开发、演示、验收和部署环境只使用合成 Mock 数据。
- 早期本地存储和最终云数据库都存放 Mock 数据；禁止导入真实业务数据或个人数据。
- Mock 数据生成要可重复；规范见 [`MOCK_DATA_SPEC.md`](data/MOCK_DATA_SPEC.md)，数据版本/校验和见 `data/generated/*/manifest.json`。
- 数据库金额列以整数分存储；CSV 和 API 使用两位小数金额字符串，转换由后端完成。
- 本地开发服务只绑定 `127.0.0.1`；不得用 `0.0.0.0` 暴露到局域网/公网。公网部署前需先落实认证和访问控制。

## 启动与检查

### 首次安装或完整重建

从项目根目录打开 PowerShell：

```powershell
.\scripts\setup.ps1
```

该脚本安装锁定依赖、生成电商与 SaaS 固定 CSV、运行 Alembic 数据库迁移，并用 `--reset` 重建本地 SQLite 中的电商主数据、空日夹具和 SaaS 订阅主题。数据库只含 Mock 数据；每次重新导入会覆盖所有已登记 Mock 数据集。

### 启动/停止

```powershell
npm run dev
```

前端地址：<http://127.0.0.1:5173>；API 文档：<http://127.0.0.1:8000/docs>。在启动窗口按 `Ctrl+C` 停止前端和后端。两项服务都只监听本机。

### 单独执行数据操作

```powershell
& .\.venv\Scripts\python.exe scripts/generate_mock_data.py
& .\.venv\Scripts\python.exe scripts/generate_saas_mock_data.py
& .\.venv\Scripts\python.exe -m alembic upgrade head
& .\.venv\Scripts\python.exe -m backend.chatbi.seed --reset
```

若不希望替换已有本地 Mock 快照，运行 Seeder 时去掉 `--reset`；数据已存在时它会拒绝继续，以免误覆盖。

### 当前可用的基础检查

```powershell
.\scripts\check.ps1
& .\.venv\Scripts\python.exe -m harness.run_smoke --output data\local\p5-smoke-report.json
& .\.venv\Scripts\python.exe -m harness.run_smoke --compare data\local\p5-smoke-report.json
& .\.venv\Scripts\python.exe -m harness.run_query_eval --output data\local\p6-query-report.json
& .\.venv\Scripts\python.exe -m harness.run_query_eval --compare data\local\p6-query-report.json
```

标准检查脚本运行 Python 格式/lint/类型/pytest 和前端 typecheck/build。P5 Harness 核对数据 manifest、Seeder 行数/外键、UQ-01 以及独立空日夹具；P6 HTTP Harness 核对 10 个黄金问题（54 项检查），包括解析澄清、受控查询、图表类型、拒答/未知术语、结果与 Mock 证据。SQL 只在本地调试开关启用时由单独的 debug API 返回。

## P6 MVP 能力边界

- 首版采用确定性规则和受控 SQL 模板，不调用大模型；UQ-01–10 均走受控查询，其中 UQ-07 是商品退款订单率。
- 缺少时间或比较周期时先澄清；UQ-04/05/06/09 在澄清回答前不执行查询。首版有限追问只继承明确指标与时间范围并允许单维调整。
- 普通答案展示结果、指标口径、时间范围、筛选条件和 Mock 数据证据；SQL/参数位于本地验收调试视图。
- 会话状态暂存于 API 进程内存，重启后清空；当前是单机本地演示，不代表云端多实例部署能力。

## P6 长图评审修正

长图评审发现月度变化率卡片显示 `NaN`、无值指标显示为 ¥0.00、待补时间的问题会误吞后续独立问题、常见“最近一周/最近七天”写法无法解析，以及普通界面暴露内部字段标识。以上均已修复。复验：26 项 pytest、54 项 P6 HTTP Golden、前端 typecheck/build 全部通过。

## P7 启动状态

P7 模型方式和服务商已确认使用 DeepSeek 托管 API。项目方确认仅在确定性解析失败/需要消歧时调用，并只发送经业务词语白名单过滤的问题片段与相关指标/维度定义。规则能处理的问题不调用模型；订单明细、查询结果或身份信息不会进入模型正文。未知片段的具体文字不会发送，只附加“存在未识别文本”的通用标记。API Key 只用于认证头，不进入提示词、正文或日志。Provider 默认关闭，须显式配置且后端有密钥才生效。意图 Schema、语义/白名单校验器、条件回退与受控查询集成和最多 7 个问题的评估 Harness 已实现；2026-11-07 `deepseek-flash` v3 合成黄金集 7/7 通过，中位耗时 1163.8 ms、观测 P95 1665.6 ms；61 项 pytest、格式/静态类型和前端检查通过。项目方已接受耗时/费用基线，Mock 数据范围的 P7 阶段门通过。公开资料未承诺 API 请求固定留存时长；真实用户/业务数据或公网服务启用前，需复核账户适用条款并完成隐私告知和安全措施。评估命令见 [Harness 说明](../harness/README.md)，完整范围见 [P7 实现规格](P7_LLM_QUERY_SPEC.md)。

## P8 当前任务

P8-1 差距审查确认 P6 的有限澄清已覆盖 FR-010。P8-3 的 T1–T6 均已完成，SC-AC-01–11 阶段门通过。P8-2 排序/CSV、P8-4 SaaS 第二主题、P8-5 本地 Mock 权限和 P8-6 回答反馈/聚合均已实现并正式签收。最终验收：P6 HTTP Golden 10/10、54/54；pytest 98/98（query API 18/18）；ruff、mypy、前端 typecheck、表格 3/3 和生产 build 通过。P9/P10 尚未启动，P9 需项目方单独确认并启动。完整记录见 [P8 剩余迭代计划](../docs/P8_REMAINING_SCOPE.md) 和 [最终检查摘要](../data/local/p8-final-check-report.json)。

P9-1 云平台/成本与 P9-2 单实例会话、迁移策略已确认。方案为 Netlify Free + Render Singapore Starter + Supabase Pro Singapore，基础固定费约 $32/月（约 ¥215），DeepSeek API 费用另计；先用平台子域名。P9-3 正在适配 PostgreSQL URL、readiness 检查、公开演示权限和部署配置。公开匿名模式默认关闭 DeepSeek，以免未限额的公开请求造成模型费用。还需配置 Git 远端和由用户在供应商控制台创建专用 Mock 资源；大陆网络可达性待实测且不作保证。详见 [P9 执行计划](../docs/P9_EXECUTION_PLAN.md)、[架构决策](../docs/P9_ARCHITECTURE_DECISION.md) 和[部署操作手册](../docs/P9_DEPLOYMENT_RUNBOOK.md)。P10 尚未启动。

\n
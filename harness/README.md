# 问数 Harness

Harness 负责按固定数据、语义版本和黄金预期运行可重复的验收检查。它独立于前端 UI，包含数据/Seeder 核验和 P6 问数 API 的 HTTP 端到端检查。

## 当前覆盖

- 检查电商主数据、空日夹具和 SaaS 订阅主题 CSV 的 SHA-256、行数是否匹配 manifest。
- 检查 SQLite 三个数据集的导入行数和外键。
- 从 `GOLDEN_RESULTS.md` 读取 UQ-01 预期，并以只读参考查询核对 2026-07-31 销售额（整数分）和去重订单数。
- 核对独立空日夹具 8 月 9–11 日的订单数及金额。
- 输出 JSON 报告，记录数据集 ID/版本、语义目录 ID/版本、问题集 ID、检查准确率和失败分类；成功查询的 Evidence 必须与当前运行目录版本一致。
- 可与既有报告做结构化比较；报告不写生成时间，结果相同则内容稳定。
- P7 意图黄金集最多 7 个合成问题；只有显式启用 DeepSeek 且进程环境配置 API Key 时才发请求。报告只记用例 ID、意图字段是否匹配、模型/提示/数据版本、耗时和 Token 数，不记问题原文或模型输出。
- 报告结构有离线回归测试，确保不写入原始问题、提示词、模型文本或 API Key；P7 请求只会发送白名单保留片段和最小语义定义。

SQLite 参考查询只用于验证 Mock 数据、Seeder 与 P3 黄金结果的一致性。端到端结果通过 FastAPI ASGI HTTP 接口调用实际 P6 确定性查询服务；数据仍为本地 Mock。

## 运行

从项目根目录执行：

```powershell
& .\.venv\Scripts\python.exe -m harness.run_smoke --output data\local\p5-smoke-report.json
& .\.venv\Scripts\python.exe -m harness.run_smoke --compare data\local\p5-smoke-report.json
& .\.venv\Scripts\python.exe -m harness.run_query_eval --output data\local\p6-query-report.json
& .\.venv\Scripts\python.exe -m harness.run_query_eval --compare data\local\p6-query-report.json
& .\.venv\Scripts\python.exe -m harness.run_llm_eval --output data\local\p7-intent-report.json
& .\.venv\Scripts\python.exe -m harness.run_saas_eval --output data\local\p8-saas-eval.json
```

若修改了数据或语义定义，先按 `docs/DEVELOPMENT.md` 生成并导入固定数据，再运行 Harness。失败时根据 JSON 中首个 `passed=false` 的检查 ID 或 `error_category` 定位。

`run_smoke` 可通过 `CHATBI_DATABASE_URL` 对任意受支持的 SQLAlchemy 数据库执行同一只读校验。P9 使用 SQLite 和 Supabase 各生成一份报告，再以 `--compare` 对照；Smoke 会校验 CSV SHA-256 与行数、数据库 manifest 全文/版本/时区、每个数据表记录数、UQ-01、空日夹具和跨数据库外键孤儿行。

## P7 模型意图评估

首次配置时在项目根目录复制 `.env.example` 为 `.env`，把 `CHATBI_LLM_PROVIDER` 改为 `deepseek`，并把 `DEEPSEEK_API_KEY` 填入你的密钥。`.env` 已被 Git 忽略，后端启动和 Harness 都会读取它。不要把密钥提交到仓库或发在聊天中。以下命令最多调用 7 次 DeepSeek API，结果写入被 Git 忽略的本地目录；可用 `--limit 1` 先跑一个样例：

```powershell
& .\.venv\Scripts\python.exe -m harness.run_llm_eval --limit 1
& .\.venv\Scripts\python.exe -m harness.run_llm_eval
```

无密钥/Provider 未开启时，Harness 会停止且不发送请求。P7 报告包含语义目录版本、峰时与非峰时估算费用；单价快照日期和官方来源一并写入报告，价格变更后需重跑并核对最新 [DeepSeek 价格页](https://api-docs.deepseek.com/quick_start/pricing/)。评估集为演示意图能力的合成问法，不包含真实业务数据或个人信息。

## P6 端到端覆盖

HTTP Adapter 逐题加载 `golden_cases.json`，提交会话/问题/澄清回答，核对查询是否执行、状态、Mock 证据、数值和分组行；同时确认待澄清的问题没有提前执行查询。覆盖 UQ-01–10，包括 UQ-07 退款订单率的 Top 10 商品、退款订单数、有效订单数、百分比及 Mock 版本证据。报告不写生成时间，可比较重跑结果是否一致。SQL 与参数只由隔离的本地调试接口提供，普通响应不含 SQL。

P6 完成基线：UQ-01 至 UQ-10 的 HTTP Golden 全部通过（总检查数随每题精确结果检查变化），覆盖预期图表类型；UQ-04/05/06/09 澄清首轮均未查询，UQ-10 未查询；UQ-07 按 completed 退款订单去重查询；UQ-08、UQ-09 使用按分精度修正后的黄金值。

P8-4 SaaS 主题使用直接 FastAPI 路由契约 Harness，避免 Windows asyncio `socketpair` 环境卡点；模型解析另由注入的固定 Provider 检验活动语义目录上下文和受控计划校验。报告见 `data/local/p8-saas-eval.json`。

\n
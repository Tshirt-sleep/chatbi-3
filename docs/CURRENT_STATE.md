# 项目当前状态

- 更新日期：2026-11-17
- 依据：仓库代码、Git 提交记录、部署配置、项目方提供的阶段 6 本地验收报告，以及项目方于 2026-11-17 通过 PowerShell 对线上 API 的只读核验。
- 本文区分“已部署”“本地未提交”和“尚未实现”；阶段历史与验收细节仍以各阶段文档为准。

## 当前可用版本

公开演示站点：[https://for-chatbi.netlify.app](https://for-chatbi.netlify.app)。前端来自 GitHub `master`，部署配置见根目录 `netlify.toml`。API 地址为 `https://chatbi-api-avjp.onrender.com`，数据库为 Supabase 上的固定 Mock 数据。项目方于 2026-11-17 通过只读 PowerShell 请求确认 API readiness 为 `ready/database_and_mock_data`，活动电商目录版本为 `2.0.0`；这确认线上服务与数据依赖可用，不代表本地候选已部署。此前记录显示该 API 允许公开站点的精确 CORS origin。

最近相关提交：

- `0e70344`：Netlify 前端部署准备及近期 UI/会话体验变更。
- `9687faf`：公开语义目录 API 路由；该提交已推送并在 Render 生效。

## 已实现能力

### 前端

- React + TypeScript + Vite 单页应用；电商主题、演示角色切换、会话历史、问题输入、答案/图表/表格、导出与口径展示。
- 会话与消息保存在当前浏览器的 `localStorage`，不写入服务器数据库；不同浏览器/设备之间不共享。切换角色时，空会话复用当前会话，已有对话则创建对应角色的新会话并保留旧记录。
- 指标口径速查读取后端语义目录；服务不可用时呈现重试状态。
- 查询提交使用图标按钮；页面有滚动/进入动效。
- 公共构建使用 `VITE_CHATBI_PUBLIC_DEMO=true`，故公开演示不会调用 DeepSeek。

### 后端与算法

- FastAPI 提供会话问数、健康就绪检查、反馈及语义目录等 API；生产数据库访问仅限后端。
- 查询使用版本化语义目录、确定性规则、意图/schema/白名单校验以及已有受控查询模板。结果和指标口径由数据库查询与后端生成。
- DeepSeek Provider 和结构化意图处理已存在于代码与 P7 文档中；模型用于理解问题，不应生成 SQL 或答案数值。Render 公开部署显式设置 `CHATBI_LLM_PROVIDER=disabled`，不会对公开用户发起模型请求。
- 公开模式另有 Mock 身份/数据边界、调试接口关闭、限流及安全日志约束；演示角色切换不构成真实授权系统。

### 数据

- 仅使用合成电商与 SaaS Mock 数据；线上电商数据集标识为 `ecommerce_mock_v1`。语义目录包含指标、维度、别名、口径与目录版本，是问数能力和解释的权威来源。
- Supabase 云库迁移、固定 Mock 数据导入、SQLite/Supabase 对照和恢复演练记录见 [P9 执行计划](P9_EXECUTION_PLAN.md) 与 [数据规范](data/MOCK_DATA_SPEC.md)。
- Render Free 单实例内存中的 API 会话状态会在进程重启后清空；浏览器 localStorage 中的历史不会自动上传到服务器。反馈持久化与会话云端持久化不是同一能力。

## 当前部署开关与边界

| 位置 | 配置/行为 | 含义 |
|---|---|---|
| Netlify | `VITE_CHATBI_PUBLIC_DEMO=true` | 前端公共演示模式 |
| Netlify | `VITE_CHATBI_API_BASE_URL=https://chatbi-api-avjp.onrender.com` | API 目标地址 |
| Render | `CHATBI_PUBLIC_DEMO=true`、`CHATBI_DEBUG_ENABLED=false`、`CHATBI_LLM_PROVIDER=disabled` | 公开模式限制；不调用 DeepSeek |
| 浏览器 | `localStorage` | 用户侧会话历史，只保存在该浏览器 |
| Render API | 单进程内存会话 | 临时问答上下文，重启会清空 |

API Key 只能作为后端 secret 配置，不得放入 Netlify 前端变量、源码、提示词、日志或文档。公开站点保持模型关闭；若未来启用模型或接入真实数据，需先重新审查匿名调用成本、隐私告知、数据处理和安全策略。

## 本地未提交工作

截至本文更新，工作树另有 DeepSeek/意图解析及相关测试改动尚未提交，涉及 `llm_provider.py`、`query_service.py`、`query_capabilities.py`、电商语义目录和后端测试。本地活动语义目录已更新为 `4.0.0`，明确拒绝“退款金额”和“客户终身价值”等暂不支持指标，并为 UQ-12 使用独立的渠道销售额/订单数模板标识。2026-11-17 项目方提供的 P7-04 单例评估显示：意图字段匹配、后端校验通过、模板为 `uq12_channel_sales_orders`，本地 Mock 查询执行成功且返回 5 个渠道行；评估报告不包含查询结果值。最新报告包含工作区状态摘要和执行输入源码指纹；报告中的 28 个执行相关源码输入指纹与当前代码、Harness、测试用例及数据 manifest 一致，工作区状态摘要反映报告生成时的文件状态。阶段 6 Harness/Provider/意图集成测试 67 项通过，语义目录及版本测试 20 项通过；此前记录的 Ruff format/check、mypy、144 项非 API pytest、UQ-12 固定模板单测和前端 typecheck/表格测试/build 也通过。完整 `test_query_api.py` 在本机 Windows Python 3.11 初始化 asyncio 事件循环时阻塞于 `socketpair()`/`accept()`，因此完整 pytest 和 P6 HTTP Golden 尚不能记为通过，需在兼容环境（如 CI/Linux）补验。线上目录经项目方于 2026-11-17 核验为 `2.0.0`；本地 `4.0.0` 候选尚未部署。`.codex-logs/` 是本地运行日志，不属于产品文档或发布内容。

## 后续优先事项

1. 在兼容环境（如 Linux CI）补跑完整 `backend/tests/test_query_api.py` 和 P6 HTTP Golden Harness；Windows 本机的 asyncio/socketpair 挂起不可计为通过。
2. 核对报告的 Git revision、工作区状态和源码指纹；评估报告不能包含密钥、模型原文、用户原文或查询结果。
3. 若准备发布，先单独审核候选文件清单、目录 4.0.0 与线上目录 2.0.0 的迁移/兼容，以及 Render/Netlify 回滚点；线上 API readiness 和目录版本已于 2026-11-17 由项目方核验。得到明确授权后再执行提交或部署，并记录 commit/build ID。
4. 保持当前公开演示的 LLM 关闭，除非另行批准面向匿名访问启用模型的限额、滥用防护和成本责任。
4. 会话云端持久化、真实登录/RBAC、真实业务数据和生产级备份/SLA 尚不属于当前公开 Mock MVP。

## 相关文档

- 项目阶段与下一任务：[开发计划](../DEVELOPMENT_PLAN.md)
- 日常运行与开发约定：[开发手册](DEVELOPMENT.md)
- 产品需求：[PRD](PRD.md)；总体技术设计：[SDD](SDD.md)
- 模型问数：[P7 实现规格](P7_LLM_QUERY_SPEC.md)
- 语义目录：[P8 语义目录规格](P8_SEMANTIC_CATALOG_SPEC.md)
- 部署/恢复：[P9 部署手册](P9_DEPLOYMENT_RUNBOOK.md)、[安全与恢复方案](P9_SECURITY_AND_RECOVERY.md)

# P8 剩余迭代范围与验收计划

- 状态：P8 正式签收完成（2026-11-11）；P9/P10 未启动
- 日期：2026-11-11
- 边界：Mock 数据与本地开发范围；P9/P10 不在本计划内

## 已确认的范围

| 子阶段 | 确认内容 | 明确不包含 |
|---|---|---|
| P8-2 结果交互 | 结果表按名称/指标列排序；导出当前表格为 CSV | 新的交互筛选、查询口径/API 变更 |
| P8-4 第二业务主题 | SaaS 订阅经营 Mock 主题，验证主题和数据集可扩展 | 接入真实 SaaS 数据；未定义指标不得猜算 |
| P8-5 权限 | 本地 Mock 身份、角色和数据范围权限验收 | 真实登录、身份提供商、生产密钥/公网认证 |
| P8-6 反馈与观察 | 对答案评分并选择问题类别；本地保存，关联 turn；不保留原问题或自由文本 | 云端监控、用户画像、自由文本反馈 |

P8-5 角色先以管理员、分析者、只读者为建议基线；具体可执行操作必须由 SDD 和验收案例限定。P8-6 反馈类别至少覆盖理解/指标口径/筛选条件/结果/图表/其他；如实现发现已有数据模型不能安全关联，应先更新本规格和迁移再做功能。

## 阶段执行顺序

### P8-2 结果表排序与 CSV（已完成）

**需求**：当前表格支持每列升降序排序；排序稳定且可访问。CSV 中文表头、原始数值、行列与当前表格顺序一致；正确引用特殊字符并防止文本公式注入；导出不重新查询。

**验收证据**：排序/CSV 单元验收 3/3（数字排序、重复值稳定、名称自然排序、null 排序、CSV BOM/原始金额/特殊字符/公式保护）；前端 typecheck/build 通过；P6 HTTP Golden 在 P8-2 实现后 10/10、54/54。详细记录见 [P8-2 结果交互规格](P8_2_RESULT_INTERACTION_SPEC.md)。

### P8-4 SaaS 订阅经营主题（已完成）

**需求**：新增与电商独立的数据集 manifest、语义目录、确定性 Mock 数据和仅基于已明确定义能力的问数链路。主题切换/会话必须绑定数据集与目录版本；模型解析必须只得到活动主题所需的语义；主题外字段及指标拒绝或澄清。开发前先写数据/指标口径与验收问题，不直接复用或误套电商口径。

**验收证据**：P5 数据 Smoke 21/21；SaaS 路由契约 14/14，覆盖 CSV 独立计算的活跃数/MRR/套餐汇总/趋势、未定义和歧义不查询、跨主题元数据、未知 dataset 拒绝、模型只用活动 SaaS 目录且非法过滤条件不执行；相关 Provider/目录/意图测试 39/39；P6 HTTP Golden 的既有 10/10、54/54 基线通过，SaaS 引入后 e-commerce UQ-01 路由回归与标准值一致。ASGI 端到端重跑受本机 `socketpair` 自动审批超时影响，使用直接路由契约覆盖，未将其表述为 HTTP 网络验证。实现规格和指标口径见 [P8-4 SaaS 主题规格](P8_4_SAAS_TOPIC_SPEC.md)。

### P8-5 本地 Mock 权限（已实现）

**需求**：增加仅用于本地演示和自动验收的固定身份映射；后端对会话、数据集和查询执行强制执行角色/数据范围，前端隐藏操作仅作体验，不作为授权边界。身份缺失/无效默认拒绝；跨用户会话访问和越权数据范围不得返回内容。请求体不能自报 user ID、role 或 scope。演示身份可在 UI 公开切换，因此不是生产认证。

**验收证据**：固定身份映射、dataset scope、会话 owner、debug owner 和前端身份切换已实现；本地直接路由及 SaaS/目录回归 12/12 通过，包含无身份、viewer SaaS 越权、跨用户会话/debug 和 viewer debug 拒绝。身份选择是公开测试开关，不是生产登录。ASGI HTTP 层未重跑，受已知 Windows `socketpair` 限制影响。实现详见 [P8-5 权限 SDD](P8_5_ACCESS_CONTROL_SDD.md)。

### P8-6 反馈与本地观察（已实现）

**需求**：查询完成后可选择正/负评分和问题类别；只保存会话/turn 的随机标识、评分、类别、时间和非敏感版本元数据，不存原始问题、自由文本、查询结果或 SQL。重复提交策略需幂等或明确覆盖；日志和 API 响应不得泄露问题文本。

**验收证据**：完成回答反馈、负向分类、重复覆盖、admin 聚合和权限拒绝已实现；迁移 `c21f8d6a4e30` 已应用；反馈 schema 不含原问题、答案、SQL、结果值或自由文本；直接路由验收 12/12。数据库异常隔离于问数请求，因为反馈使用单独 API。完整字段/行为见 [P8-6 反馈规格](P8_6_FEEDBACK_SPEC.md)。

## 完成门

四个子阶段规格、实现和验收均通过。项目方确认 P6 HTTP Golden 及完整 `scripts/check.ps1` 通过，P8 正式签收；P9 云迁移与 P10 上线验收仍须分别启动。

## P8 阶段评审记录

- 评审日期：2026-11-11
- 结论：**正式通过并签收**。实现与获批的 Mock 功能范围一致，阶段验收项通过。
- 复核证据：P6 HTTP Golden 10/10 用例、54/54 检查；pytest 98/98（含 `test_query_api.py` 18/18）；ruff 格式/代码检查、mypy、前端 typecheck、结果表用例 3/3、前端 build 均通过。
- 完整检查摘要：[`p8-final-check-report.json`](../data/local/p8-final-check-report.json)。P6 HTTP 明细：[`p8-p6-http-final.json`](../data/local/p8-p6-http-final.json)。
- 签收范围：P8-1 至 P8-6。下一阶段 P9 仍未启动，需项目方单独确认范围并启动。

### 2026-11-11 HTTP 验收执行记录（已由最终通过结果取代）

- P6 HTTP Golden 结果已确认：FastAPI ASGI HTTP 10/10 用例、54/54 检查通过。报告为 [`p8-p6-http-final.json`](../data/local/p8-p6-http-final.json)。
- 早期工具执行曾遇到 pytest 停滞和 `socketpair()` 阻塞；该状态已被随后项目方确认的完整成功 PowerShell 输出取代，不再作为当前验收结论。
- 最终结果：P6 HTTP Golden 10/10、54/54；pytest 98/98，`test_query_api.py` 18/18；ruff format/check、mypy、前端 typecheck、表格 3/3、生产 build 全部通过。
- 不经 asyncio HTTP 的检查已完成：P5 Smoke 21/21，SaaS 路由契约 14/14。报告分别为 [`p8-p5-smoke-final.json`](../data/local/p8-p5-smoke-final.json) 与 [`p8-saas-final.json`](../data/local/p8-saas-final.json)。
- 旧阻塞记录 [`p8-http-acceptance-blocked.json`](../data/local/p8-http-acceptance-blocked.json) 仅保留历史尝试；当前状态以 [`p8-final-check-report.json`](../data/local/p8-final-check-report.json) 为准。P8 已签收；P9/P10 未启动。

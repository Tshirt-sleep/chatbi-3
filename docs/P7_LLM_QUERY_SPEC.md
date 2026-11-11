# P7 大模型辅助问数：实现规格与验收计划

- 状态：P7 Mock 数据范围通过（2026-11-07）；DeepSeek `deepseek-flash` v3 合成黄金集 7/7，项目方接受耗时/费用基线。真实用户/业务数据和公网服务仍需另行核验 API 数据处理/留存要求。
- 日期：2026-11-07
- 依据：已批准 PRD v0.3、P3 语义目录、P6 确定性问数实现

## 1. 目标与边界

P7 让用户可以用更多自然说法询问当前 MVP 支持的电商指标，同时保持答案仍由确定性后端查询得出。大模型只帮助理解问题并提出结构化意图；它不连接数据库、不写 SQL、不生成数值答案，也不改变已确认指标口径。

本阶段只扩大当前 UQ-01–06、UQ-08–10 的语言理解覆盖，不增加退款率、复杂归因、自动决策、多行业配置或真实业务数据。UQ-07 仍然拒答。数据仍为固定 Mock。

## 2. 已确认约束与待决定事项

### 已确认

- 所有数据仍为 Mock；数据库查询仅由后端受控路径执行。
- 语义目录是指标、维度、时间和口径的唯一来源。
- 模型输出需要结构化；每轮查询仍须重新校验。
- 保留 P6 确定性链路作为无模型或模型不可用时的可用路径。
- 普通界面不展示 SQL；调试信息继续独立隔离。
- 项目方确认：只有确定性规则不能解析或无法消歧时才调用 DeepSeek；发送经业务词语白名单脱敏/过滤后的用户问题和理解该问题所需的相关指标/维度定义，不发送订单明细、查询结果或身份信息；API Key 只放在服务商要求的认证头中，不进入提示词、问题正文或日志。未识别文本的具体内容会被丢弃，只传递“存在未识别文本”的通用标记。

### 已确认

- 接入方式采用托管模型 API。

### 待项目方决定

- 具体账户层的数据留存与处理策略，真实用户/业务数据或公网服务启用前需由项目方核实。

用户已选择 DeepSeek 并确认上述外发边界。Provider 通过项目根目录被 Git 忽略的 `.env` 或进程环境变量显式启用；默认仍关闭，P6 确定性链路仍为默认行为。当前环境没有 API Key，未发真实模型请求。

## 2.1 托管 API 候选比较（官方资料核验于 2026-11-07）

| 服务商 | 对当前 ChatBI 的适配 | 计费/区域要点 | 需留意 |
|---|---|---|---|
| 阿里云百炼 Qwen3.8-Flash（推荐候选） | 官方列出该系列支持 JSON Schema 结构化输出，并提供 OpenAI 兼容 API；可用本项目 Pydantic schema 直接约束模型返回 | 北京区标准价为输入 ¥0.8 / 百万 Token、输出 ¥2.7 / 百万 Token；当前标注 100 万 Token 免费额度，有效 90 天；按量计费 API 可用于自定义应用 | API Key 与 Base URL 按地域配置；官方说明会依法存储模型/API 调用数据，但不用于模型训练。Token Plan/Coding Plan 的订阅 Key 不用于自定义应用 API 调用，需用普通 API 按量计费 |
| 火山方舟 Doubao（备选） | OpenAI 兼容；支持 JSON Schema 结构化输出，但该能力目前标为 Beta，需逐模型确认是否支持 | 可按 Token 后付费；模型价格和低优/常规服务档位不同，选定模型后再按官方价格页核算 | JSON Schema Beta 的可用性需在目标模型上验证；用生产 Endpoint ID 有助于管理限流和版本 |
| DeepSeek API（项目方已选） | 官方 Chat Completions 支持 `deepseek-flash` 和 JSON Output；JSON mode 保证合法 JSON，不保证匹配本地严格 Schema，因此 Pydantic 与语义白名单校验不可绕过 | 官方价格页显示按输入/输出 Token 计费，并区分峰谷时段；以该页实时价格为准。Base URL 为 `https://api.deepseek.com` | 当前适配器使用 JSON mode，不让模型选工具或输出 SQL；空白内容、无效 JSON、请求失败均安全失败。托管地域/调用数据处理条款及项目预算仍需核实 |

用户已选择 DeepSeek。原候选调研保留为比较资料，不再作为服务商建议。当前适配配置为 `deepseek-flash`、OpenAI 兼容 Chat Completions、官方 Base URL。项目方允许仅在规则解析失败时发送经过业务词语白名单过滤的问题片段和相关最小语义条目；未知文本的具体内容不发送，只附加通用存在标记；所有 Mock 订单/商品明细和查询结果留在本地。DeepSeek JSON mode 不代表语义正确，后端强制 Pydantic 与白名单模板校验。项目方已接受 7/7 基线及耗时/费用；公开条款未说明适用于 API 的固定请求留存时长，真实用户/业务数据和公网服务启用前仍需核实账户适用条款，并履行用户告知与安全要求。

DeepSeek 官方面向开发者的 Open Platform 条款说明开发者需建立用户管理、数据安全、监测、告警与应急措施；公开隐私政策提示输入内容会被处理，但该隐私政策明确不覆盖开发者基于开放平台构建的下游应用。当前公开 API 文档没有足够信息让本项目承诺 API 请求的固定保留时长或训练用途，因此规格不作此类承诺；需项目方在启用前按 API 账户/条款核实。参见 [DeepSeek Open Platform Terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) 与 [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)。

官方依据（核验于 2026-11-07）：[DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)、[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)、[DeepSeek 数据模型列表 API](https://api-docs.deepseek.com/api/list-models/)。历史候选比较来源：[百炼结构化输出与支持模型](https://help.aliyun.com/zh/model-studio/qwen-structured-output)、[百炼模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)、[方舟结构化输出 Beta](https://docs.volcengine.com/docs/ark/structured-output-beta?lang=zh)。

## 3. 查询流程

1. 接收问题及当前会话中明确确认的有限上下文。
2. 只提供完成解析所需的语义目录信息；不得把订单、顾客或商品行明细发送给模型。
3. 模型返回一个符合严格 Schema 的意图草稿，或提出澄清/拒答状态。
4. Pydantic 校验结构；后端语义校验器检查意图 ID、指标、维度、字段关系、粒度、时间边界、排序、限制及 UQ 支持范围。
5. 不合法、缺字段、越界、矛盾或未知的输出不执行；转为澄清、拒答或 P6 确定性回退。
6. 只有通过所有校验，后端才映射到现有受控查询模板；模型不能指定模板外 SQL。
7. 结果、口径和解释由后端根据查询结果生成，模型不得改写或补造数值。
8. 按 request_id 记录模型/提示/目录版本、校验状态、耗时与结果分类；普通日志不记录问题原文、密钥、SQL 参数或结果行。

## 4. Provider-neutral 意图草稿

计划 Schema 建议采用严格对象并禁止额外字段：

```json
{
  "status": "ready",
  "question_kind": "uq04",
  "metric_ids": ["sales_amount"],
  "dimension_ids": ["product"],
  "time_range": {
    "start_inclusive": "2026-07-02",
    "end_exclusive": "2026-08-01",
    "timezone": "Asia/Shanghai"
  },
  "comparison_range": null,
  "filter_ids": ["valid_paid_orders"],
  "sort": [{"field_id": "sales_amount", "direction": "desc"}],
  "limit": 10,
  "clarification_prompt": null
}
```

`status` 仅允许 `ready`、`clarification_required`、`unsupported`、`unknown_term`。时间区间为半开区间。澄清状态不得同时带可执行查询计划。模型不得输出 SQL、数据库字段任意表达式、数字答案、置信度阈值或未登记的 ID。

## 5. 校验与失败行为

- **Schema 无效/多余字段**：不执行查询；记录错误类别；可使用确定性回退。
- **未知指标/维度/过滤器**：拒绝或提示可用术语；不执行。
- **超出 Mock 日期范围、时间区间矛盾或周期重叠**：澄清或拒绝；不裁剪后静默执行。
- **指标与维度粒度不兼容、跨主题或 UQ-07**：拒绝或澄清；不尝试生成新查询。
- **提示注入、要求泄露提示/密钥或执行 SQL**：忽略注入指令，只按允许的意图解析；无法安全解析则拒绝。
- **模型超时、限流或不可用**：P6 已识别的问题不会请求模型，仍由确定性路径回答；回退调用失败或输出无效时不执行查询，按当前支持范围安全拒答或澄清。
- **校验器或数据库错误**：安全失败；不给模型提供内部堆栈或密钥。

## 6. 验收清单

| ID | 验收标准 | 验证方式 |
|---|---|---|
| P7-AC-01 | 常见改写/口语问题能映射到当前受支持的标准意图 | 黄金集意图字段逐项匹配 |
| P7-AC-02 | 输出只包含严格 Schema 允许的字段和值 | 有效、缺字段、额外字段、错误类型测试 |
| P7-AC-03 | 模型只提出计划；所有实际查询使用后端白名单模板 | 检查模板 ID；尝试模型输出 SQL 并确认不执行 |
| P7-AC-04 | 澄清前不执行查询，补充答案后重新解析和校验 | UQ-04/05/06/09 多种问法回归 |
| P7-AC-05 | UQ-07、未知术语、超范围时间、危险/注入问题均拒答或澄清 | 安全负例；确认查询执行数为 0 |
| P7-AC-06 | P6 明确支持问题不调用模型；模型失败/无效输出时不执行猜测计划并安全澄清或拒答 | 规则命中不调用、模拟超时/限流/无效 JSON/结构错误 |
| P7-AC-07 | 结果数值和口径完全来自后端，模型不能更改 | 与 P6 Golden Results 精确对照 |
| P7-AC-08 | 同版本黄金评估可重复，记录模型/提示/目录/代码版本 | 连续运行 Harness 并比较报告 |
| P7-AC-09 | 外部请求正文不含 Mock 数据行或密钥；API Key 仅在认证头，普通日志无问题原文/SQL 参数 | 捕获请求与日志字段审计 |

准确率、延迟、费用的目标值不由实现者推定；先用实际所选服务跑出基线，再由项目方确认门槛。2026-11-07 项目方接受 v3 评估的准确率、耗时及费用，7/7 黄金集通过，P7 Mock 数据范围阶段门通过。关键安全负例必须全部拦截，方可通过 P7 阶段门。公网或真实用户/业务数据的处理不属于本次阶段门，启用前须复核 API 账户条款、用户告知和安全措施。

## 7. 实施任务

| ID | 工作项 | 依赖 | 完成证据 |
|---|---|---|---|
| P7-T01 | 确认服务商/模型/区域、预算和调用数据边界 | 项目方决定（托管方式、DeepSeek 和外发范围已确认） | 服务商/调用边界已记录；预算及账号层留存条款在真实验收前核实 |
| P7-T02 | 建立严格 Pydantic 意图 Schema 和 Provider 接口 | 服务商无关，可与 P7-T01 并行；真实调用依赖 P7-T01 | 已完成；Schema 额外字段拒绝、Protocol 定义；测试通过 |
| P7-T03 | 建立基于语义目录的计划校验器，并限制映射到 P6 查询模板 | P7-T02 | 已完成；指标/维度/过滤/时间/周期/排序/数量校验，模板仅由服务端白名单映射；负例测试通过 |
| P7-T04 | 实现所选 Provider 与无模型/故障回退 | P7-T01–03 | Provider 默认关闭；规则失败才回退调用；脱敏、模拟响应、结构错误、超时及模板白名单集成测试通过 |
| P7-T05 | 建立黄金集及受控 API 评估报告 | P7-T02–04 | 已创建 7 个合成用例的 Harness，单次最多 7 个请求；v3 基线 7/7；中位耗时 1163.8 ms，观测 P95 1665.6 ms；峰时费用估算 $0.00116762/7 例；报告不写问题/模型原文 |
| P7-T06 | 与项目方逐项核验 PRD 门槛和关键负例 | P7-T05 | 2026-11-07 项目方接受准确率、响应时间与费用基线；Mock 数据范围阶段门通过；公网/真实数据另设发布前条件 |

## 8. 当前接口与实现约束

P6 现有集成点为 `backend/chatbi/query_service.py` 的问题解析/服务入口、`backend/chatbi/query_schemas.py` 的 Pydantic DTO、`backend/chatbi/main.py` 的会话 API、`docs/semantic/SEMANTIC_CATALOG.md` 的业务定义及 `harness/` 的黄金验收。P7 应把“模型解析”作为可替换组件接入，在现有确定性服务之前输出意图草稿；受控 SQL 模板和结果生成逻辑保持在服务端。

DeepSeek Provider 只解析到 Pydantic 意图草稿，调用方必须再执行 `validate_intent_draft`；验证通过后才调用既有受控查询函数。API 默认不启用模型；在 Git 忽略的根目录 `.env` 中显式设置 `CHATBI_LLM_PROVIDER=deepseek` 并设置 `DEEPSEEK_API_KEY` 后，未识别问题才会发起外部请求。P7 黄金评估单次最多发送 7 条合成问法，报告不记录问题或模型原文。

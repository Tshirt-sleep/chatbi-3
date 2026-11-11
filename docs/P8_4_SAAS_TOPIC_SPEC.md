# P8-4 SaaS 订阅经营主题规格

- 状态：已实现并通过子阶段验收
- 版本：v1.0（2026-11-10）
- 目标：用第二套独立 Mock 业务主题验证数据集、语义目录和问数路由扩展能力

## 1. 边界

- 仅生成可复现的合成数据，固定参考日 2026-08-01，覆盖 2025-08-01 至 2026-07-31，时区 `Asia/Shanghai`。
- 与电商使用不同 dataset ID、业务表和语义目录；会话创建时选择主题并固定目录版本。
- 首期不支持复杂分析链、收入确认、续费预测、退款、折扣、试用转化或流失率。
- 未定义的“收入”“流失”“续费”等术语必须澄清/拒答，不映射到 MRR。

## 2. 建议数据模型

| 实体 | 字段 | 说明 |
|---|---|---|
| accounts | account_id, account_name, region, created_at | 合成企业客户 |
| plans | plan_id, plan_name, monthly_fee_cents, status | 只包含月付标准价；费用按整数分 |
| subscriptions | subscription_id, account_id, plan_id, started_at, canceled_at, status | 一条订阅在本 Mock 中固定套餐、固定月价，无升降级历史 |
| acquisition_channels | channel_id, channel_name | 获客渠道 |

订阅外键必须同 dataset_id 隔离；生成器固定种子，清单包含文件行数与 SHA-256。所有日期按完整自然日解释。

## 3. 指标口径

| 指标 ID | 展示名 | 定义 | 时间语义 |
|---|---|---|---|
| active_subscriptions | 活跃订阅数 | 在参考日 2026-08-01 00:00（含）处于有效期且状态为 active 的去重 subscription_id 数；`started_at <= 参考时点` 且 `canceled_at` 为空或大于参考时点 | 固定快照，不随提问周期变化 |
| mrr | 月度经常性收入（MRR） | 上述活跃订阅的 `monthly_fee_cents` 求和；只包含标准月付价，不代表会计收入/现金回款 | 固定快照，不做日内按比例摊销 |
| new_subscriptions | 新增订阅数 | `started_at` 落在所问半开时间范围内的去重 subscription_id 数 | 按订阅开始日期归属 |

金额 API 使用十进制元展示，数据库以整数分保存。MRR 只按 plan 标准月价相加；本模型没有折扣、税费、年付或变更历史。

## 4. 首版确定性问法

1. “截至现在有多少活跃订阅？”→ 固定参考日快照，指标卡。
2. “当前 MRR 是多少？”→ 固定参考日快照，指标卡，并展示 MRR 口径。
3. “最近 7 天新增订阅数？”→ 需要明确时间范围；如果解析完整自然日窗口，按日折线图与表格。
4. “按套餐看当前活跃订阅数”→ 表格/柱图；只允许 `plan` 维度与 `active_subscriptions`/`mrr` 的白名单组合。

首期实现以上问题及必要的时间澄清。不能把“销售额/订单/商品/渠道”当作 SaaS 同义词；未识别的 SaaS 指标应说明当前支持范围。确定性规则无法解析时才调用配置的 Provider；模型只收到当前 SaaS 目录和脱敏/白名单保留的问题片段，计划还须通过 SaaS 代码白名单校验。

## 5. API 与交互

- `/api/v1/sessions` 可显式创建 `ecommerce_mock_v1` 或 `saas_subscription_mock_v1` 会话，默认行为维持电商以兼容现有调用。
- response/evidence/trace/debug 均使用会话固定的数据集和目录 ID/版本。
- 前端提供受限的主题选择器；创建新主题会话，不把已有会话切换成另一个数据集。
- 服务端对主题到目录、模板和表的映射使用代码白名单；用户和模型都不能指定任意 SQL、表名或 dataset_id 查询参数。

## 6. 验收标准

| ID | 通过条件 |
|---|---|
| P84-AC-01 | SaaS 生成数据重复运行 SHA-256/行数一致，manifest 与目录兼容；SQLite seed 可重建 |
| P84-AC-02 | 创建 SaaS 会话返回 SaaS dataset/catalog 元数据；默认电商会话行为不变 |
| P84-AC-03 | 活跃订阅数、MRR、套餐分组及新增订阅时间窗和独立 SQL 黄金结果逐分/逐行一致 |
| P84-AC-04 | 未定义收入/流失率、越界维度、跨主题或伪造 dataset 参数不执行查询 |
| P84-AC-05 | P6 电商 10/10、54/54 黄金回归通过；P7 电商受限解析回归通过 |
| P84-AC-06 | 前端可切主题并新建会话；普通答案展示主题、口径、时间/筛选和 Mock 证据 |

## 7. 实施顺序

1. 增加独立确定性数据生成器、manifest、语义目录及严格启动校验。
2. 增加模型/迁移/seed 和可重建数据库检查。
3. 设计并实现会话级 dataset/catalog 绑定、SaaS allowlisted query service 与最小 API 合约。
4. 增加前端主题选择和支持范围提示。
5. 加入 SaaS Golden 及电商/P7 回归；复核 SQL、Evidence 和安全负例。

## 8. 实施与验收记录

- 新增 `saas_subscription_mock_v1` 固定种子数据：2,400 个账户、4 个套餐、4 个获客渠道、6,000 条订阅；manifest 含行数、SHA-256、固定参考日和时区。
- 新增严格 SaaS 语义目录、独立 SQLAlchemy 表和 Alembic 迁移；会话、Evidence、调试查询按会话固定的数据集/目录路由。
- 前端增加电商/SaaS 主题选择器。首期问法由确定性规则执行；模型仅在规则未识别时收到活动 SaaS 目录上下文，输出经精确 capability/字段/时间窗校验后映射固定 SQL。
- 验收：数据 Smoke 21/21；SaaS 路由/数据黄金 14/14（活跃订阅 4,669、MRR ¥3,819,131.00、套餐和 7 日趋势逐项匹配独立 CSV 算值）；相关 pytest 39/39；ruff/mypy、前端 typecheck/build 通过。
- 电商回归：P8-2 后 HTTP Golden 10/10、54/54；SaaS 加入后直接路由 UQ-01 仍精确返回销售额 ¥257,984.80 和 41 单。当前 Windows `socketpair` 运行限制及自动审批复核超时使本轮 ASGI HTTP Harness 未重跑；直接路由验收不等同网络层验证。

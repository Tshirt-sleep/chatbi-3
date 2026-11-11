# P8-3 语义目录配置化：技术设计与实施顺序

- 状态：T1–T6 全部验收通过；P8-3 阶段完成
- 版本：草案 v0.1
- 日期：2026-11-10
- 关联需求：[P8-3 需求与验收](P8_SEMANTIC_CATALOG_SPEC.md)

## 1. 设计目标

把目前分散在 Markdown 与 Python 常量中的电商业务语义迁移到单一版本化 JSON 配置，并让确定性解析、意图校验、DeepSeek 上下文、结果口径和 API 证据读取同一个启动时加载的目录快照。SQL 模板和计算逻辑保留在后端白名单实现中。

## 2. 当前实现与约束

目前主要重复定义位于：

- `backend/chatbi/query_service.py`：目录 ID/版本、时间常量、指标定义、问题识别和模型上下文构造。
- `backend/chatbi/intent_validation.py`：意图可用指标/维度集合、时间范围和查询模板映射。
- `backend/chatbi/llm_provider.py`：脱敏词表；模型意图上下文的数据类型与提示。
- `backend/chatbi/main.py`：会话创建响应中的目录 ID/版本。
- `docs/semantic/SEMANTIC_CATALOG.md`：业务可读口径、别名、适用维度及时间/策略规则。

当前只有一个数据集 `ecommerce_mock_v1`。其 `manifest.json` 是参考日期和数据窗口的唯一来源。SQL 只通过 `query_service.py` 中的固定模板执行。

## 3. 组件设计

### 3.1 配置文件

新增 `backend/chatbi/catalogs/ecommerce_mock_semantics.json`，包含：

- `catalog_id`、`version`、`status`、`dataset_id`、`timezone`。
- `metrics`：稳定 ID、名称、定义、单位、别名、可用维度和后端实现 ID。
- `dimensions`：稳定 ID、名称、定义、别名、字段/关系说明、适用指标和后端实现 ID。
- `terms`：稳定术语 ID、原词、目标 ID 或 `ambiguous`/`unsupported` 状态。
- `policies`：有效订单、销售额/订单粒度、时间区间和澄清规则引用。
- `capabilities`：已审核的 UQ 类型说明、允许指标/维度及固定 `template_id` 引用。
- `change_note`：本次目录版本变更摘要。

配置不包含 SQL、任意公式脚本、数据库连接信息、密钥或数据行。指标公式由配置中的定义文字说明；数值计算仍由代码中的实现 ID 完成。

### 3.2 Pydantic 目录模型与加载器

新增 `backend/chatbi/semantic_catalog.py`：

1. 使用严格 Pydantic 模型解析 JSON，拒绝额外字段和错误类型。
2. 校验 ID、引用、别名、版本、状态、manifest 数据集兼容和实现 ID。
3. 生成不可变的 `SemanticCatalog` 快照，供业务模块注入或读取。
4. 目录载入/校验失败时应用启动失败；不回退到散落的 Python 默认定义。
5. 提供只读的 `load_catalog()` 与 `validate_catalog()`，不提供运行期写入或热更新。

后端可执行能力仍由代码侧的 `SUPPORTED_QUERY_TEMPLATES`/实现注册表限制。加载器要求配置中的 capability/template 引用同时出现在代码白名单中；反向也检查当前首版应支持的 UQ 模板都由活动目录声明。

### 3.3 运行时读取

- `query_service.py` 从加载快照取得目录 ID/版本、时区、指标定义、别名、维度与 capability 信息；数据参考日/起止日仍从 manifest 取得。
- `intent_validation.py` 用目录定义校验 intent 的指标/维度组合和 capability，再将已允许的 `template_id` 交给现有受控查询执行器。
- 确定性解析器保留现有 UQ 问题结构识别规则，但指标、维度、业务术语别名从目录读取；新增词汇不要求同步改多个硬编码词表。
- `_intent_context()` 从目录生成最小相关指标/维度/术语/能力描述；P7 脱敏器从同一目录生成允许转发词表，并继续只发送识别到的词语和必要上下文。
- `main.py` 创建会话和结果 `Evidence` 从同一个快照读取 `catalog_id/version`。
- 会话记录创建时的目录版本；版本不匹配时停止继承旧意图，提示新建会话/重述。

### 3.4 版本与发布

- 初次迁移版本为 `0.1.0`；T4 增加能力说明、周期要求及口语查询示例，提升补丁版本至 `0.1.4`，不改变已接受口径和黄金结果。
- 纯文案修订只提升补丁；兼容新增别名/实体提升次版本；ID 删除/重定义、口径或数据集兼容性变化提升主版本。
- 发布前运行目录校验、P6 HTTP Golden、P7 意图 Golden 及全量工程检查。
- 通过 `releases/` 归档或 Git 还原前一版 JSON 配置并重新部署即可回滚；不需要数据库迁移。当前工作树尚无 Git 提交，首次受控提交前使用归档文件恢复。

## 4. 数据结构草图

```json
{
  "catalog_id": "ecommerce_mock_semantics",
  "version": "0.1.4",
  "status": "active",
  "dataset_id": "ecommerce_mock_v1",
  "timezone": "Asia/Shanghai",
  "metrics": [],
  "dimensions": [],
  "terms": [],
  "policies": {},
  "capabilities": [],
  "change_note": "首次机器可读配置迁移，口径不变"
}
```

真实配置需用 Pydantic contract 校验；本例仅展示顶层形状。

## 5. 错误处理

| 情况 | 行为 |
|---|---|
| JSON 格式/字段结构错误 | 启动失败，错误只指出字段路径和错误类型 |
| 重复 ID、别名冲突、悬空引用 | 加载/校验失败，不启动问数服务 |
| manifest 缺失或数据集不兼容 | 加载失败，不以默认日期或旧常量继续 |
| 配置引用未审核查询模板 | 校验失败；不会创建动态 SQL 或放宽白名单 |
| 用户问题命中歧义或已停用术语 | 澄清/拒绝，执行查询次数为 0 |
| 老会话目录版本与当前快照不一致 | 不继承旧计划，要求新会话或重述 |

## 6. 分步实施任务

| 任务 | 工作内容 | 涉及区域 | 验收证据/回归 |
|---|---|---|---|
| [x] P8-3-T1 配置契约与加载器 | 创建符合严格 Schema 的首版目录 JSON；应用启动时加载一次并生成不可变快照；验证目录内部引用、manifest 数据集兼容性及代码白名单映射。有效配置成功加载；任一无效配置给出字段定位并阻止服务启动；配置语义与 P3 一致 | `semantic_catalog.py`、`catalogs/ecommerce_mock_semantics.json`、能力白名单注册、加载器测试及 `query_service` 启动挂载 | `pytest backend/tests/test_semantic_catalog.py -q`：8 passed；目录 CLI 校验成功；ruff format/check 与 mypy 通过。健康检查测试已改为不依赖 socketpair 并通过；全量 pytest 仍在 `test_query_api.py` 的 Windows asyncio loop 初始化处受环境限制，未将完整回归记为通过 |
| [x] P8-3-T2 统一目录元数据 | 移除散落的目录 ID/版本、指标定义、时间口径常量引用；会话/答案/trace 使用快照元数据，日期边界来自 manifest | `query_service.py`、`main.py`、`trace.py`、`intent_validation.py`、`time_periods.py` | `scripts/check.ps1`：ruff、mypy、pytest 73/73、前端 typecheck/build 全通过；`harness.run_query_eval`：10/10 黄金问题、54/54 检查通过；元数据快照与日历周期测试通过 |
| [x] P8-3-T3 接入确定性语义解析 | 将指标、维度和术语别名/歧义改为目录驱动；保持已有解析结构、查询模板与安全限制 | `query_service.py`、目录解析帮助函数及测试 | 新增目录驱动匹配与歧义/不支持/停用维度测试；`scripts/check.ps1`：76 pytest、ruff、mypy、前端 typecheck/build 全通过；P6 HTTP Golden：10/10 用例、54/54 检查通过 |
| [x] P8-3-T4 接入意图校验与模型上下文 | capability 指标/维度/模板引用从目录读取，仍须通过代码 allowlist；LLM 相关定义和脱敏词表读取目录；目录提供能力说明、必需时间/比较周期及口语示例 | `intent_validation.py`、`llm_provider.py`、`query_service.py`、集成测试 | `scripts/check.ps1`：79 pytest、ruff、mypy、前端 typecheck/build 全通过；P6 HTTP Golden：10/10 用例、54/54 检查；P7 DeepSeek 意图 Golden：7/7，提示 v6、目录 0.1.4 |
| [x] P8-3-T5 版本隔离与回滚流程 | 会话固定目录 ID/版本；跨版请求返回 409、要求新建会话并重述；加入变更类型与 semver 校验器和已发布快照还原步骤 | `main.py`、`query_service.py`、`catalog_versioning.py`、目录版本归档、会话/版本测试、文档 | 版本策略单测覆盖 patch/minor/major、不升版和无内容变更；旧会话在 provider/query 前被拒绝；归档 0.1.3 加载通过，临时恢复该版本运行 P6 Golden 10/10、54/54；活动文件在 `finally` 后与归档 0.1.4 SHA256 一致 |
| [x] P8-3-T6 端到端基线与文档收口 | 补充目录维护说明/变更模板，记录首个机器可读版本；P6 报告校验目录元数据；覆盖 Harness 脱敏输出与无效目录启动失败；对当前及回滚版本执行 P6/P7 与工程回归 | `docs/semantic/`、`docs/DEVELOPMENT.md`、`harness/`、隐私/启动校验测试 | SC-AC-08–11；P5 Smoke 17/17、重复报告一致；P6 当前 10/10/54/54、回滚至 0.1.3 后 10/10/54/54 且 Evidence/报告标出 0.1.3；P7 v6 7/7；`scripts/check.ps1` 90 pytest、ruff/mypy、前端 typecheck/build 全通过 |

每项任务结束后更新 `DEVELOPMENT_PLAN.md`，记录状态、命令和证据；只有任务验收通过后才开始依赖它的下一项。若当前任务引入口径变化或改变 API 行为，先暂停并同步需求/验收稿。

## 7. 实施阶段门

- **设计通过**：目录 JSON 契约、后端能力白名单、版本/回滚行为已被接受。
- **迁移通过**：初始配置与原 P3 目录一致；已有 P6/P7 行为和黄金结果不变。
- **安全通过**：仅代码 allowlist 中的 capability 可执行；坏配置、歧义术语、停用能力不查询。
- **P8-3 完成**：SC-AC-01–11 全部通过；完整工程检查通过；变更模板、版本快照及回滚步骤已记录。

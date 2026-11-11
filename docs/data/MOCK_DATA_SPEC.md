# 电商 Mock 数据规范（P3 评审稿）

- 版本：0.1
- 状态：P3 阶段门已核验通过；核心业务口径和类目树已确认，可复现主数据、独立空日夹具及黄金预期已生成
- 日期：2026-11-07
- 数据边界：仅使用虚构生成数据；本规范中的数量和业务口径是供首版评审的明确建议。

## 1. 数据集目标与固定参数

| 项目 | 建议值 | 说明 |
|---|---|---|
| 数据集 ID | `ecommerce_mock_v1` | schema、语义目录及黄金集通过版本号关联 |
| 固定参考日期 | 2026-08-01（Asia/Shanghai） | 相对日期解析锚点；“昨天”指 2026-07-31，不随机器当前日期漂移 |
| 覆盖区间 | `[2025-08-01 00:00, 2026-08-01 00:00)` 上海时间 | 365 个完整自然日，最近数据日为 2026-07-31 |
| 订单量 | 20,000 笔 | 足够支撑趋势、排行与分组，控制本地运行规模 |
| 商品量 | 500 个 | 商品稳定归属一个叶子类目 |
| 类目量 | 30 个 | 3 个一级类目、每个 9 个二级类目（共 27 个叶子类目）；问题按叶子类目统计 |
| 渠道量 | 5 个 | `web`、`app`、`mini_program`、`marketplace_a`、`marketplace_b` |
| 虚构客户量 | 8,000 个 | 仅随机 ID，不生成真实姓名、电话、地址、邮箱 |
| 随机种子 | `20260801` | 使用指定伪随机算法/版本；生成器实现时锁定运行时及算法版本 |

CSV 按实体稳定 ID/行序输出，不保证按事件时间排序；查询须显式按 `paid_at` 过滤及排序。主数据集在 365 天内每日均有有效订单，并以固定哈希和轮转规则分配日期、渠道和类目，不依赖真实节假日销售数据。主数据集包含未支付、取消、关闭订单、跨类目和多商品订单；独立验收夹具目前只覆盖空日补零。部分/全额退款及非法跨渠道记录尚无夹具，留待对应需求进入实施时再补。

生成器采用跨运行时稳定的伪随机方案：`H(parts...)` 将各参数转成字符串后以 `|` 拼接，UTF-8 编码并计算 SHA-256，将摘要前 8 个字节按大端序解释为无符号整数，再按目标范围取模。所有 `row_index` 从 1 开始；生成器不得依赖语言默认随机数实现。生成依赖顺序为类目、渠道、客户、商品、订单、明细；输出文件内分别按稳定 ID/行序排列。对要求覆盖的维度值使用轮转分配，再用上述 hash 派生其余字段，避免随机抽样造成某个类目/渠道缺失。

订单日期确定算法：主数据集窗口共 365 日，按从 `2025-08-01` 起的日序号编号。365 天各先分配 1 笔有效订单；剩余 17,635 笔有效订单及 2,000 笔非有效订单分别按 `SHA256(seed|order|row_index|date)` 前 8 字节大端整数对 365 取模分配，因此每天至少有 1 笔有效订单。此处 `date` 是固定字段标签；`row_index` 是订单序号。对有效订单，分配日期是 `paid_at` 的上海日期，`created_at` 设为支付前 1–48 小时；对非有效订单，分配日期是 `created_at` 日期，`paid_at` 为空。订单时间由对应哈希派生，确保同一数据种子/行号永远生成相同值。渠道和商品用轮转保证覆盖，其余属性按字段独立哈希派生。

订单状态固定配额：17,000 笔 `paid`、1,000 笔 `completed`、1,000 笔 `created`、600 笔 `cancelled`、400 笔 `closed`；按 1 起始的 `order_id` 序号区间分配。前 18,000 笔为有效订单，必须有 `paid_at`；其余状态没有 `paid_at` 且 `paid_amount=0`。每单 1–4 条明细；前 3,600 笔有效订单（占有效订单 20%）至少两条明细且覆盖不同叶子类目；其他字段由固定哈希确定。商品价在 500–200,000 分间按哈希生成；有效商品标记为 90%；每个渠道按订单序号轮转。明细折扣在折前金额的 0–20% 间按哈希生成。所有金额先按整数分计算，明细折扣合计与订单折扣一致，防止浮点误差。主数据集的 `refunds.csv` 仅含表头、不生成退款记录；退款率 UQ-07 延后，避免未确认的退款率口径影响首版数据。

## 2. 数据实体与关系

### 已确认类目树（30 个节点）

项目方已确认保留以下类目提案，每个商品只能归属一个主要叶子类目；每个父类下列 9 个叶子类目：

| 一级类目 | 叶子类目（各 1 个节点） |
|---|---|
| 家居生活 | 家纺床品、厨具餐饮、收纳整理、清洁用品、家具家装、灯具照明、卫浴用品、园艺户外、宠物用品 |
| 服饰鞋包 | 女装、男装、童装、内衣、鞋靴、箱包、运动服饰、户外服饰、服饰配件 |
| 数码家电 | 手机通讯、电脑办公、数码配件、摄影摄像、影音娱乐、智能设备、大家电、小家电、游戏设备 |

| 实体 | 粒度 / 主键 | 主要字段 | 关系与规则 |
|---|---|---|---|
| `orders` 订单 | 一笔订单 / `order_id` | `customer_id`, `channel_id`, `order_status`, `created_at`, `paid_at`, `currency`, `gross_amount`, `discount_amount`, `paid_amount` | `gross_amount`/`discount_amount` 汇总明细；有效支付订单 `paid_amount = gross_amount - discount_amount`，未支付/取消/关闭订单 `paid_amount=0` 且 `paid_at` 为空 |
| `order_items` 订单明细 | 一笔订单中的一个商品行 / `order_item_id` | `order_id`, `product_id`, `quantity`, `unit_price`, `line_discount`, `line_amount_after_discount` | 多对一关联订单和商品；`line_amount_after_discount = quantity × unit_price - line_discount`；有效支付订单的明细金额合计等于订单 `paid_amount` |
| `products` 商品 | 一个商品 / `product_id` | `product_name`, `primary_leaf_category_id`, `list_price`, `is_active` | 每个商品只能归属一个主要叶子类目，且必须引用唯一叶子节点；不允许商品多类目归属或直接归属父类目；名称为合成文本 |
| `categories` 类目 | 一个类目 / `category_id` | `category_name`, `parent_category_id`, `level` | 父子树最多两层；本期按叶子类目查询 |
| `channels` 渠道 | 一个销售渠道 / `channel_id` | `channel_name`, `channel_code` | 一个订单只有一个归属渠道 |
| `customers` 客户 | 一个虚构客户 / `customer_id` | `created_at`, `region_code` | 不包含可识别个人身份的字段；地区只到省级虚构/通用代码 |
| `refunds` 退款事件 | 一次退款 / `refund_id` | `order_item_id`, `refunded_amount`, `requested_at`, `completed_at`, `refund_status` | 支持部分退款及多次退款；仅为后续 UQ-07 的数据预留，首版销售额/订单数/AOV 均不扣减退款 |

关联基数：`customers 1—N orders`、`channels 1—N orders`、`orders 1—N order_items`、`products 1—N order_items`、`categories 1—N products`、`order_items 1—N refunds`。所有外键必须能关联；`products.primary_leaf_category_id` 必须指向 `level=2` 的叶子类目；每个商品只有一个此字段值；退款累计额不得超过对应明细支付额。

## 3. 数据字段、类型与隐私规则

实现使用本地关系型数据库时映射为 `TEXT/INTEGER/DECIMAL/TIMESTAMP`；金额使用定点 `DECIMAL(12,2)`，不得使用浮点存储。ID 使用稳定字符串（如 `ord_000001`）。数量为正整数。枚举字段只允许本规范列出的值。

| 字段组 | 类型/单位 | 空值与生成规则 | 示例 |
|---|---|---|---|
| 主键/外键 | `TEXT` | 非空、稳定、可复现 | `ord_000001` |
| 时间 | ISO-8601 `TEXT` 或带时区 timestamp | 订单创建时间必填；支付/退款事件按状态可空；统一上海时区语义 | `2026-07-31T13:24:00+08:00` |
| 金额 | `DECIMAL(12,2)`，人民币元 | 非负；明细合计与订单金额一致 | `128.50` |
| `order_status` | 枚举 | `created`, `paid`, `completed`, `cancelled`, `closed` | `paid` |
| `refund_status` | 枚举 | `requested`, `completed`, `rejected`, `cancelled` | `completed` |
| `quantity` | `INTEGER`，件 | 大于 0 | `2` |
| `region_code` | 虚构省级代码 | 可空；不得包含真实地址文本 | `R-07` |
| 名称 | 合成中文文本 | 使用合成商品/类目/渠道词表，不复制真实品牌或个人内容 | `轻量收纳盒-021` |

### 字段级数据字典（建议 schema）

`NOT NULL` 为必填；默认生成逻辑应由固定种子与字段名决定。时间字段均为上海本地带 `+08:00` 的 ISO-8601 值；金额 `DECIMAL(12,2)`；ID 为稳定文本键。

| 表.字段 | 类型 / 可空 | 含义、单位 / 枚举 | 合成示例与生成规则 |
|---|---|---|---|
| `orders.order_id` | TEXT / NOT NULL | 订单主键 | `ord_000001`，按行序生成 |
| `orders.customer_id` | TEXT / NOT NULL, FK | 虚构客户 | 由客户 ID 稳定轮转/hash 选择 |
| `orders.channel_id` | TEXT / NOT NULL, FK | 订单唯一渠道 | 5 个渠道轮转保证覆盖 |
| `orders.order_status` | TEXT / NOT NULL, enum | `created/paid/completed/cancelled/closed` | 按固定 hash 分布；固定边界样例覆盖全部状态 |
| `orders.created_at` | TIMESTAMP / NOT NULL | 下单时间 | `2026-07-31T12:00:00+08:00`；由日期与 hash 时间生成 |
| `orders.paid_at` | TIMESTAMP / NULL | 支付时间 | 有效支付状态必填且不早于创建；未支付/取消/关闭为空 |
| `orders.currency` | CHAR(3) / NOT NULL | 币种 | 固定 `CNY` |
| `orders.gross_amount` | DECIMAL(12,2) / NOT NULL | 折扣前订单金额，元 | 明细单价×数量合计 |
| `orders.discount_amount` | DECIMAL(12,2) / NOT NULL | 折扣额，元 | 非负且不超过折前金额 |
| `orders.paid_amount` | DECIMAL(12,2) / NOT NULL | 折扣后实付，元 | 有效支付订单为 `gross_amount-discount_amount` 且等于明细折后金额合计；未支付/关闭/取消订单为 0 |
| `order_items.order_item_id` | TEXT / NOT NULL | 明细主键 | `item_000001`，按行序生成 |
| `order_items.order_id` | TEXT / NOT NULL, FK | 所属订单 | 指向唯一订单 |
| `order_items.product_id` | TEXT / NOT NULL, FK | 商品 | hash 选择；每订单至少一行 |
| `order_items.quantity` | INTEGER / NOT NULL | 购买件数，件 | 正整数 1–5 |
| `order_items.unit_price` | DECIMAL(12,2) / NOT NULL | 成交前单价，元 | 从商品价格表取值 |
| `order_items.line_discount` | DECIMAL(12,2) / NOT NULL | 明细折扣，元 | 非负且不超过行折前金额 |
| `order_items.line_amount_after_discount` | DECIMAL(12,2) / NOT NULL | 明细折后应付金额，元 | `quantity×unit_price-line_discount`；只有有效支付订单计入销售额 |
| `products.product_id` | TEXT / NOT NULL | 商品主键 | `prd_000001` |
| `products.product_name` | TEXT / NOT NULL | 合成商品名 | 合成词表+稳定编号，不含真实品牌 |
| `products.primary_leaf_category_id` | TEXT / NOT NULL, FK | 商品唯一主要叶子类目 | 轮转分配，保证 27 个叶子类目均覆盖；必须指向 `level=2` 的叶子节点 |
| `products.list_price` | DECIMAL(12,2) / NOT NULL | 标价，元 | 由品类档位与 hash 生成 |
| `products.is_active` | BOOLEAN / NOT NULL | 是否在售 | 固定比例生成；历史订单可关联下架商品 |
| `categories.category_id` | TEXT / NOT NULL | 类目主键 | `cat_001`…`cat_030`；其中 3 个父类目、27 个叶子类目 |
| `categories.category_name` | TEXT / NOT NULL | 合成类目名 | 合成类目词表；全局唯一 |
| `categories.parent_category_id` | TEXT / NULL, FK | 父类目 | 一级类目为空；二级指向一级 |
| `categories.level` | INTEGER / NOT NULL, enum | 层级 1/2 | 与父子关系一致 |
| `channels.channel_id` | TEXT / NOT NULL | 渠道主键 | `chn_01`…`chn_05` |
| `channels.channel_name` | TEXT / NOT NULL | 展示名 | 合成固定值，如“自营网页” |
| `channels.channel_code` | TEXT / NOT NULL | 机器码 | `web/app/mini_program/marketplace_a/marketplace_b` |
| `customers.customer_id` | TEXT / NOT NULL | 虚构客户主键 | `cus_000001`，不含个人信息 |
| `customers.created_at` | TIMESTAMP / NOT NULL | 虚构注册时间 | 生成在数据窗口内或之前 |
| `customers.region_code` | TEXT / NULL | 合成省级地区码 | `R-07` 等，不映射真实地址 |
| `refunds.refund_id` | TEXT / NOT NULL | 退款事件主键 | `ref_000001` |
| `refunds.order_item_id` | TEXT / NOT NULL, FK | 对应订单明细 | 仅有效支付明细 |
| `refunds.refunded_amount` | DECIMAL(12,2) / NOT NULL | 本次退款/申请金额，元 | 大于 0；同明细累计不超实付 |
| `refunds.requested_at` | TIMESTAMP / NOT NULL | 退款申请时间 | 不早于支付时间 |
| `refunds.completed_at` | TIMESTAMP / NULL | 退款完成时间 | `completed` 时必填，其他状态可空 |
| `refunds.refund_status` | TEXT / NOT NULL, enum | `requested/completed/rejected/cancelled` | 固定 hash 分布并包含边界样例 |

不得生成或导入姓名、手机号、身份证号、精确住址、真实账号、生产订单号或任何生产数据快照。数据集目录包含版本、参考日期、行数、生成种子和文件校验和；重置须能完整删除并重建同一数据集。

## 4. 查询资格和分组归属

- 首版有效订单：`order_status IN ('paid','completed')` 且 `paid_at` 非空。
- 销售额与订单数均按 `paid_at` 所属上海自然日归属；订单数按去重 `order_id` 计数。
- 商品销售额按有效订单明细 `line_amount_after_discount` 汇总；类目销售额按商品所属叶子类目汇总。
- 按类目统计订单数时，订单只要包含该类目商品就计入该类目一次；一个订单含多个类目时会分别出现在多个类目组，因此分组订单数相加可能大于总体去重订单数。界面/答案需说明类目订单数按“订单是否涉及该类目”分别计数，可重复覆盖同一订单。例如订单 A 同时购买服饰和鞋靴、订单 B 只购买服饰，则服饰 2 单、鞋靴 1 单、总体去重 2 单。
- 按渠道统计时，订单按唯一 `channel_id` 归属。
- 退款在首版从指标中排除；不得以退款发生日期回写或改变原销售额。
- 无记录日期在趋势查询中补 0；无匹配维度值不伪造行。

## 5. 边界与异常样例

主数据集保证每天都有有效订单。空日独立放在验收夹具 `ecommerce_empty_day_fixture_v1` 中，不混入 `ecommerce_mock_v1`，也不参与其汇总。该夹具使用相同 schema 和语义版本，2025-08-09、2025-08-10、2025-08-11 三日销售额分别为 100、0、200 CNY，各邻日有效订单数均为 1，目标日有效订单数为 0，供三日趋势补零验收。Harness 必须显式选择此夹具，不能将它并入主数据集或主指标汇总。主数据集已覆盖折扣后金额、单/多商品订单、跨类目订单和未支付/取消/关闭状态；非法跨渠道记录和退款事件属于后续独立安全/退款夹具，不写入有效数据集。项目方已确认不生成 0 元有效订单。

有效订单金额必须大于 0；未支付、取消、关闭等非有效订单可有关联商品明细，但其订单 `paid_amount=0`，不参与首版指标。

## 6. 固定时间解析示例

统一按半开区间 `[start, end)` 过滤上海时间，数据库 timestamp 不得因服务器时区变化而改变结果。

| 表达 | 本规范建议解析 | 说明 |
|---|---|---|
| 昨天 | `[2026-07-31 00:00, 2026-08-01 00:00)` | 参考日期前一完整自然日 |
| 最近 7 天 | `[2026-07-25 00:00, 2026-08-01 00:00)` | 含最近 7 个完整自然日，不含参考日 |
| 本月 | `[2026-07-01 00:00, 2026-08-01 00:00)` | 参考日是数据窗口的排他结束边界；按最近完整数据日所在月份，即 2026 年 7 月 |
| 上月 | `[2026-06-01 00:00, 2026-07-01 00:00)` | 与最近完整数据月比较；两期均为完整自然月 |
| 本周 | 2026-07-27 至 2026-07-31 | 周一开始；截至参考日前最后一个完整自然日 |
| 上周同期 | 2026-07-20 至 2026-07-24 | 与本周已完成的周一至周五对齐 |

`最近 N 天` 不含参考日期当天；本周按周一开始并截至参考日前最后一个完整自然日，“本周比上周”按已完成天数对齐。固定参考日为数据窗口的排他结束边界，`本月`解释为最近一个完整数据日所在月份，因此 2026-08-01 的“本月”是 2026 年 7 月，“上月”是 2026 年 6 月。一般进行中的月份按当月月初至最近完整日，与上月相同日数范围比较；若上月天数较少，则截到月末。若比较期为零，增长率标为不可计算，不除以零。

## 7. 已确认事项与落实规则

1. **销售额**按支付时间归属，统计有效订单折后实付金额合计，首版不扣退款；**订单数**统计支付成功/已完成状态的去重订单。例：实付 180 元后退款 30 元，仍计 180 元。
2. 类目订单数按订单是否涉及该类目分别计数；一个订单可以出现在多个类目，结果需解释其与总体去重订单数的区别。
3. 固定参考日为 2026-08-01，数据窗口为 2025-08-01 至 2026-07-31，时区 Asia/Shanghai；最近 7 天为 2026-07-25 至 2026-07-31。
4. 数据规模为 20,000 笔订单、500 个商品、30 个类目、5 个渠道；不生成 0 元有效订单，可保留未支付、取消等非有效订单。
5. UQ-09 先澄清比较周期，再分解订单数和客单价的数值变化，不推断因果。
6. “收入”不自动等同销售额；解释销售额口径并澄清收入具体含义，澄清前不执行查询。

时间比较规则落实：固定快照参考日 2026-08-01 是数据窗口排他结束日，“本月”按最近完整数据日所在月（2026 年 7 月），与上一个完整自然月（2026 年 6 月）比较。一般进行中月份按当月月初至最近完整日，与上月相同日数范围比较；上月天数不足时截到月末。周一为周起始日；本周截至参考日前最后一个完整日，参考日 2026-08-01 时为 2026-07-27 至 2026-07-31，对比上周同期 2026-07-20 至 2026-07-24。

时间条件规则：UQ-04 商品 Top 10、UQ-05 类目汇总、UQ-06 渠道客单价未指定时间范围时，必须先向用户追问时间范围，用户补充后再执行；首版不默认使用完整 Mock 数据窗口。

类目归属规则：类目树采用上方 3 个一级类目和 27 个叶子类目。每个商品严格只有一个主要叶子类目；一个订单仍可购买多个商品，因此可能涉及多个叶子类目。按类目统计订单数时，订单只要涉及该类目便在该类目计 1 次。

数据连续性规则：主数据集每天至少有 1 笔有效订单。空日仅存在于独立验收夹具 `ecommerce_empty_day_fixture_v1`，不混入 `ecommerce_mock_v1` 或其汇总结果。

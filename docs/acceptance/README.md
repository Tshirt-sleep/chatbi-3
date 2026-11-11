# 验收资料

验收用例和标准问题集放在此目录。每个用例应能追溯到需求 ID，并记录角色、问题、预期语义/指标口径、预期结果、允许误差、验证方式和状态。

- `GOLDEN_QUESTIONS.md`：P2/P3 建立并持续维护的问数标准集。
- `GOLDEN_RESULTS.md`：由固定 Mock 数据生成的精确预期值。

## P3 固定数据

- 主数据：`data/generated/ecommerce_mock_v1/`，覆盖 2025-08-01 至 2026-07-31，每天至少一笔有效订单；每日销售趋势没有空日。
- 空日夹具：`data/generated/ecommerce_empty_day_fixture_v1/`，2025-08-09 与 2025-08-11 各一笔有效订单，2025-08-10 为零，用来核对趋势补零；它不并入主数据集。
- 每个商品只关联一个 `primary_leaf_category_id`。订单可以有多个商品，因此仍可包含多个叶子类目。
- 两个数据集都提供 `manifest.json`，包含行数和 CSV SHA-256。按仓库根目录运行 `python scripts/generate_mock_data.py` 可重建数据及黄金结果。

黄金验收应显式选择数据集 ID；普通问数使用主数据，只有空日补零用例选择独立夹具。不得将夹具数据追加到主数据后再核对黄金数值。

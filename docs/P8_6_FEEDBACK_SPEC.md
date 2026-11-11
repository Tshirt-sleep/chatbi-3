# P8-6 回答反馈与本地汇总规格

- 状态：已实现；待阶段整体评审
- 范围：本地合成数据、公开 Mock 身份、回答反馈与聚合观察

## 用户流程

仅在回答状态为 `completed` 时显示反馈。管理员和分析者可选择“有帮助”或“需改进”；正向评分分类固定为 `looks_good`。负向评分必须选择一种原因：问题理解、指标口径、筛选条件、结果、图表、其他。只读身份不允许提交。

重复提交按同一 dataset/session/turn/mock user 覆盖已有反馈，避免重复计数。未完成澄清、拒答、失败回答不接受反馈。

## 数据最小化

`turn_feedback` 仅保存随机反馈 ID、dataset/session/turn ID、Mock user ID、评分、分类、UTC 时间、数据集版本与语义目录 ID/版本。表结构不含问题文本、答案、查询结果、SQL、模型提示或自由文本。身份与 turn/session 关联只服务本地验收；此模拟身份不是匿名化或生产级身份系统。

## API 与权限

- `POST /api/v1/sessions/{session_id}/turns/{turn_id}/feedback`：仅会话 owner 且具备 feedback 权限者；校验 turn 属于该会话并已完成；分类须与评分匹配。
- `GET /api/v1/feedback/summary`：仅 admin，返回总量和评分/分类计数，不返回用户、turn、session 或内容字段；前端管理员可展开汇总面板查看。
- 未知请求字段由严格请求 Schema 拒绝；请求体不能自赋 user/role/dataset。
- 反馈数据库错误不进入问数请求路径；答案先返回，用户反馈是独立请求。

## 验收清单

- [x] 仅 completed 回答可提交；viewer、跨 owner、无效分类和未完成 turn 均拒绝。
- [x] 同一 user 重复提交更新为单条当前反馈。
- [x] 数据表只包含允许的元数据字段，不存问题/答案/SQL/结果/自由文本。
- [x] admin 汇总只返回评分/分类计数；analyst 无权读汇总。
- [x] `backend/tests/test_access_and_feedback.py`、目录/SaaS 直接路由用例 12/12 通过。
- [x] Alembic migration `c21f8d6a4e30` 已在本地数据库应用。
- [ ] 受限环境中的全量 ASGI HTTP Harness 待 `socketpair` 初始化条件解决后重跑。

## 运维边界

本地 SQLite 数据会随本地文件保留，不含清理/保留期策略；P9 云数据库阶段须再定义保留期限、删除能力、真实身份引用与聚合访问审计。当前汇总接口不支持任意日期筛选。

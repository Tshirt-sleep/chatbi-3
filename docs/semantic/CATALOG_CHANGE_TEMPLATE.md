# 语义目录变更模板

复制本模板，为每次修改活动语义目录填写一份记录，并与 JSON 变更一起评审。

## 变更信息

- 日期：YYYY-MM-DD
- 负责人：
- 变更类型：补丁文案 / 兼容扩展 / 语义破坏性变更
- 目录版本：旧版本 → 新版本
- 变更说明（与 JSON `change_note` 保持一致）：

## 变更内容

- 涉及 ID（指标、维度、术语或 capability）：
- 变更前：
- 变更后：
- 对已有问题、指标口径、时间规则或澄清行为的影响：
- 是否新增查询能力：否（新增能力需另行修改代码白名单并经评审）

## 兼容性与安全

- 是否兼容现有会话和数据集：
- 旧版本会话如何处理：
- 是否涉及模型发送词汇或上下文：
- 是否包含订单行、结果、身份信息或 API 密钥：否

## 验收与发布

- [ ] `python -m backend.chatbi.semantic_catalog` 通过
- [ ] `python -m backend.chatbi.catalog_versioning <previous.json> <active.json>` 通过
- [ ] `scripts/check.ps1` 通过
- [ ] P6 HTTP Golden 通过；检查报告中的目录 ID/版本符合预期
- [ ] P7 意图 Golden 通过（若模型上下文、目录提示或脱敏词表有变化）
- [ ] 已保存不可变的已接受 JSON 快照到 `backend/chatbi/catalogs/releases/`
- [ ] 已记录回滚目标版本及恢复步骤

## 回滚

- 目标版本：
- 恢复文件：
- 已验证的目录/数据集兼容性：
- 回滚后的 P6/P7 结果：

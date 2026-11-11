# P8-5 本地 Mock 身份与访问控制设计

- 状态：已实现；本地直接路由验收通过
- 数据边界：本地合成 Mock 数据；本机制用于演示和验收，不构成真实认证

## 固定身份

客户端通过 `X-Mock-User` 选择固定演示身份；服务端只接受代码内映射，不接受请求体中的 user ID、role 或 scope。

| 身份 ID | 角色 | 数据范围 | 允许操作 |
|---|---|---|---|
| `admin` | admin | 电商、SaaS | 创建会话、问数、查看本人 SQL 调试、查看反馈汇总 |
| `analyst` | analyst | 电商、SaaS | 创建会话、问数、查看本人 SQL 调试、提交本人答案反馈 |
| `viewer` | viewer | 电商 | 创建会话、问数；不可查看 SQL 调试或提交反馈 |

三种身份会在本地界面公开切换，以便验收不同允许/拒绝路径；任何客户端都可选择这些演示身份，因此不能把此机制视作登录或生产授权。未知/缺失身份不允许调用受保护 API。

## 后端约束

1. `/sessions` 从请求头解析身份；校验 dataset 在身份 scope 中后才建会话，并把 user ID、dataset ID、目录 ID/版本固定在会话记录。
2. `/sessions/{session_id}/turns` 要求请求身份与会话 owner 一致；不匹配时返回 404，避免泄露会话是否存在。
3. Debug 查询 ID 绑定 owner；只有 owner 的 admin/analyst 可读取自己的 SQL/参数，viewer 与其他 owner 均拒绝。
4. 反馈写入和汇总另执行角色、owner 与数据集 scope 检查。请求体中的 `user_id`、`role`、`dataset_id` 不能覆盖会话身份和范围。
5. 每个查询仍绑定会话 dataset；身份有多数据集范围不表示一次查询可以跨主题 join。
6. CORS 只允许本地来源并仅开放 `X-Mock-User` 作为演示身份头。部署到公网前必须替换真实认证、服务端会话、授权模型和审计。

## API 行为与验收

- 无身份头/未知身份：受保护路由返回 401，不创建会话或执行查询。
- viewer 创建 SaaS 会话：返回 403，无查询。
- user A 读取 user B 会话或 debug：返回 404；debug 权限不足：403/404，无 SQL 返回。
- 固定身份无法通过请求字段自赋 `admin` 或扩大 dataset scope；body 中的多余字段由 Pydantic 拒绝。
- 会话切换身份后必须新建；旧会话不会转交。
- Health/readiness 不包含业务数据且继续匿名可读。

## 开发和测试约定

- 前端通过 `X-Mock-User` 发送当前演示身份；身份或主题切换会清空当前会话并重新创建。
- API Harness 显式使用 `analyst` 身份；权限 Harness 覆盖固定角色矩阵、无效身份、跨用户会话、主题越权和 debug 越权。
- 所有本地角色 ID 都是公开测试夹具；不得在 UI 中声称已完成生产认证。

## 实现记录（2026-11-11）

- 新增固定身份映射和 `X-Mock-User` 解析；缺失/无效身份返回 401。
- 会话固定 owner；越权 dataset 返回 403，跨身份访问会话/debug 返回 404；每个 API 查询仍按会话 dataset 分支执行。
- 前端可切换管理员、分析者、只读者；切换身份或主题会重新建会话；只读者界面隐藏调试和反馈操作。
- 本地浏览器身份选择是公开的模拟开关，不能防止终端用户伪造身份，不能用于生产认证。
- 验收：`backend/tests/test_access_and_feedback.py` 与目录/SaaS 直接路由回归共 12 项通过；ASGI HTTP 网络层尚未重新验收，沿用 Windows `socketpair` 限制说明。

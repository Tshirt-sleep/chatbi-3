# P9 云平台初步比较

- 日期：2026-11-11
- 用途：帮助项目方选择持续运行的公开作品集演示环境；应用和数据库可部署在中国大陆以外
- 数据范围：只部署合成 Mock 数据
- 价格口径：官方公开页面；实际购买页、账户优惠、地域和税费会变化，正式选型前必须重新报价

## 建议与项目方选择

项目方已选择 **Supabase 作为数据库方向**。该项目还有独立的 React/Vite 前端和 FastAPI 后端，Supabase 不负责托管这两个现有应用。因此估算完整站点时需分别计入静态前端、持续运行的 API 和数据库。尚未创建项目或付费资源。

**推荐的最低持续运行组合**：Netlify Free 托管 Vite 静态站点（$0）+ Render Singapore Starter 托管 FastAPI（$7/月）+ Supabase Pro Singapore PostgreSQL（$25/月），基础固定月费约 **$32/月**。按 2026-11-06 中国外汇交易中心 USD/CNY 中间价 6.7168 粗算约 **¥215/月**。平台免费子域名可用，无需先买域名。DeepSeek API 用量、超额带宽/存储、税费和以后购买自定义域名另计；公开演示流量较低时预计不会触发超额，但需要部署后看账单。

Render 免费 Web Service 会在 15 分钟无请求后休眠，首次访问需冷启动，且免费方案面向测试/爱好项目；所以若用户要求持续在线，应按 $7 Starter 估算。Supabase Pro 为 $25/月，包含 $10 compute credit，价格页给出的 Micro compute 正好由额度覆盖。Supabase 的 IPv4-only 后端可以使用共享 Session Pooler 5432 连接，无需先加购 IPv4 地址。

**访问限制**：用户同意应用无需部署在中国大陆，但其原先的“不想让访问者搭梯子”目标仍需端到端实测。Netlify/Render/Supabase 均不保证从中国大陆任一运营商网络始终可达；如实测失败，届时需改用大陆托管方案并重新评估域名、备案和总价。

## 方案比较

| 方案 | 组合形态 | 大陆访问匹配度 | 成本信息（当前公开资料） | 对本项目的优缺点 |
|---|---|---|---|---|
| Supabase + Render + Netlify | Supabase Singapore PG + Render Singapore FastAPI + Netlify 静态站点 | **待中国大陆端到端实测**。所有服务位于境外；平台不保证大陆可达性 | **约 $32/月（约 ¥215）基础固定费**：Supabase Pro $25 + Render Starter $7 + Netlify Free $0；AI 用量、超额资源、税费/汇率另计 | 保留当前 Python API；Render 与数据库可选同一区域；静态前端走 CDN。平台地址可免费使用；大陆用户连通性不是供应商保证 |
| Supabase 单独使用 | Supabase 数据库 | 不适用完整托管 | Pro $25/月；但不托管已有 Vite/FastAPI 应用 | 不构成可运行整站，仍需独立 Web/API 托管 |
| Supabase | Supabase Postgres + 腾讯/阿里大陆应用主机 | **低到中，需实测**。数据库无大陆项目区域；应用访问境外 PG 会依赖跨境网络。网站本身若部署大陆仍会涉及备案要求 | 数据库 Pro 起价 $25/月；应用服务器和跨境流量另计 | 可保留国内应用入口，但跨境数据库链路增加不稳定因素；报价也需把国内主机补齐 |
| 腾讯云 | Lighthouse/CVM + 云数据库 PostgreSQL，同地域同 VPC | **高，候选优先**。大陆计算和 DB 可同地域私网连接；可从大陆用户网络直接访问网站。大陆域名上线前要完成 ICP 备案 | Lighthouse 官方月价示例：2核2GB、40GB SSD 套餐约 **¥45/月**；2核2GB、50GB 套餐约 **¥50/月**。托管 PostgreSQL 另计，购买页按地域、规格、存储和架构报价；备份有免费额度，超出另计 | 同厂商私网链路、备案和运维资料相对直接；需另买托管 PG，应用和 DB 分开计费；DB 准确总价需要账号购买页报价 |
| 阿里云 | 轻量/ECS + ApsaraDB RDS PostgreSQL，同地域同 VPC | **高，候选优先**。大陆资源可同地域私网连接；网站使用大陆资源需备案 | RDS PG Serverless 公开公式：RCU **¥0.333/RCU·小时**，存储 **¥0.0021/GB·小时**，另看实例下限、存储起配、备份和地域；轻量/ECS 与数据库分开计费，需购买页配置报价 | Serverless 可按活动负载弹性计费，且有传统规格可选；需确认目标地域可售、最低 RCU/存储与持续运行费用。配置项较多，初学者的云网络和部署学习成本略高 |

上述腾讯轻量价为官方标准套餐价示例，不代表活动价；通用 2核2GB套餐公开价约 ¥52/月，套餐规格、流量限制和可购地域以购买页为准。价格页面在 2026-06 更新。

## 成本估算边界

估算假设：一个低流量公开演示、一个 Singapore 数据库项目、Render 最小付费常驻实例、Netlify Free 全球静态站点、不购买自定义域名/IPv4 附加项、不启用高可用。**$32/月成立的条件是 ChatBI 使用单独的 Supabase Pro 组织，并且该组织只有这一个 Micro 数据库项目**：Pro $25/月含 $10 计算额度覆盖一个 Micro；Render Starter $7；Netlify Free $0。该估算不是含税或模型用量的账单保证。

项目方已有另一个 Supabase 项目，因此创建前要确认旧项目所属组织的计划：

- 若旧项目在 Free 组织，建议为 ChatBI 建立独立 Pro 组织和专用 Singapore 项目，旧项目保持 Free；ChatBI 基础月费仍约 $32。
- 若把 ChatBI 加到已有 Pro 组织，第二个 Micro 项目约增加 $10 计算费；Supabase 组织总费可能为 $35/月，连同 Render 后完整平台费用约 $42/月。
- 若升级包含旧项目的 Free 组织为 Pro，旧项目也可能开始产生计算费用；应以 Supabase 创建/升级前的组织账单估算器为准。

因此，用户已接受的是“独立 Pro 组织单项目”的 $32 方案；是否符合账户实际边际账单，待核对旧项目所在组织计划后再创建资源。Supabase 官方说明每个项目有独立数据库计算实例，Pro 组织的 $10/月计算额度覆盖一个 Micro，额外项目约从 $10/月起。

如果需要先压成本，可评估在单台大陆 VM 上自管 PostgreSQL；这会取消托管数据库费，但增加备份、升级、监控和恢复责任，且不符合 P9 已确定的“PostgreSQL 兼容云数据库类别”目标中的托管服务假设，需项目方另行确认后才改变。

## 公网访问与合规前置

1. 工信部现行《非经营性互联网信息服务备案管理办法》规定，在中国境内提供非经营性互联网信息服务应依法履行备案，未备案不得提供服务。大陆云厂商的备案说明要求网站解析到其大陆资源前完成备案。备案的主体资格、域名要求和材料需按项目方所在地及所选接入商核实。
2. 采用大陆云资源、域名公开访问时，需要项目方准备实名认证云账号、可用于备案的域名与备案主体材料；如尚无域名，需在备案前购买/完成实名认证。
3. P8 的 `X-Mock-User` 是客户端可公开选择的演示身份，不是公网授权。保留角色切换时，角色仅呈现不同的 Mock 能力说明/界面；服务端不信任客户端角色、不提供真实管理权限、不触及真实数据。SQL debug、真实管理接口均从公开部署关闭；模型调用、写操作和访问频率须设限。
4. 真实认证不一定要阻止匿名访问演示页：可以开放不含管理/调试功能的匿名 Mock 演示，并把管理员功能留在受控环境。但此公开匿名策略需要在 P9 安全设计中明确并验收。

## 决策建议

基于“持续运行、作品集公开展示、Supabase 已有使用经验、先压低月费”，建议把短名单缩为：

1. **Netlify Free + Render Starter + Supabase Pro**：约 $32/月，平台域名即可启动；先做公开 Mock 演示和大陆网络实测。
2. **腾讯云备选**：如果大陆访问实测不满足，再比较 Lighthouse/CVM + 同地域云数据库 PostgreSQL 的完整续费价与备案要求。
3. **阿里云备选**：轻量应用服务器或 ECS + 同地域 RDS PostgreSQL；按购买页补齐完整续费报价。

推荐先从腾讯云和阿里云账号购买页各取一份同配置报价，再选择。暂不建议为了省下数据库托管费把 PostgreSQL 与应用塞进同一主机，因为本项目需要学习和演练云数据库迁移、备份和恢复。

## 官方资料

- [Supabase 可用区域](https://supabase.com/docs/guides/platform/regions)：当前列出 Singapore、Tokyo、Seoul 等 APAC 区域，未列中国大陆；每个项目选择一个主区域。
- [Supabase 官方价格](https://supabase.com/pricing)：Free/Pro 规格、暂停策略、备份保留及计算价格。
- [Supabase PostgreSQL 连接方式](https://supabase.com/docs/guides/database/connecting-to-postgres)：IPv4-only 的长期运行后端可用共享 Session Pooler，Pro 包含 Micro compute credit。
- [Render 官方价格](https://render.com/pricing)：静态站点免费、最小付费实例 $7/月。
- [Render Regions](https://render.com/docs/regions)：Singapore 可用；静态站点由全球 CDN 服务。
- [Render Free plan 限制](https://render.com/docs/free)：免费 Web Service 15 分钟无请求后休眠，免费方案有资源限制。
- [Netlify credit-based plans](https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/credit-based-pricing-plans/)：Free $0/月、300 credits/月并设硬上限，支持自定义域名/TLS。
- [中国外汇交易中心汇率](https://www.chinamoney.org.cn/english/bmkcpr/index.html?tab=2)：2026-11-06 USD/CNY 中间价 6.7168，仅用于人民币粗算。
- [腾讯云 Lighthouse 大陆价格总览](https://cloud.tencent.com/document/product/1207/73452)：公开标准月价、套餐资源和流量限制。
- [腾讯云 PostgreSQL 计费说明](https://cloud.tencent.com/document/product/409/49577)：规格、存储、备份、流量的计价构成；准确价格需登录购买页/计算器。
- [腾讯云备案云资源要求](https://cloud.tencent.com/document/product/243/18908)：大陆云资源公网建站前须完成 ICP 备案，备案所需资源条件。
- [阿里云 RDS PostgreSQL 计费](https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/billing-1)：规格和存储构成、购买页报价方法。
- [阿里云 RDS PostgreSQL Serverless 单价与公式](https://help.aliyun.com/en/rds/apsaradb-rds-for-postgresql/serverless-apsaradb-rds-for-postgresql-instances-are-supported-1)：RCU 与存储按小时计费的公开单价；需再核目标地域起配条件。
- [工信部非经营性互联网信息服务备案管理办法](https://hunca.miit.gov.cn/zwgk/zcwj/flfg/art/2024/art_0f195e060e174cd68c5170893f390f49.html)：境内非经营性互联网服务备案要求及办理原则。
- [腾讯云备案场景说明](https://cloud.tencent.com/document/product/243/18910)：大陆服务器对外提供服务前备案要求，含 IP 访问说明。

## 决策状态

项目方已接受独立 Supabase Pro 组织单项目约 $32/月（约 ¥215/月）的持续运行基础固定费；DeepSeek API 按实际调用另计。因为项目方已有 Supabase 网站，创建前需查看旧项目所在组织计划；同一 Pro 组织再加一个 Micro 项目会改变总账单，具体见上文。项目方确认先使用平台子域名，不购买自定义域名；公开角色切换仅展示 Mock 身份，服务端不授予真实管理员权限、不开放 SQL debug、不连接真实数据。境外托管从中国大陆网络是否可达，需部署后用多个运营商实测；此项仍是技术验收条件，不是当前选型前提。

正式创建 Supabase/Render 资源前，项目方需在 Supabase 控制台核对旧项目组织计划，并确认新建独立 Pro 组织还是使用已有付费组织；再在相应控制台确认所选资源及账单。真实密钥由项目方在供应商控制台或本机安全提示中配置，不在聊天中提供。

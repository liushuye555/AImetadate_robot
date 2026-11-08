# QQ 官方方案与 DSH 插件调研

核对日期：2026-10-28。本次只读调研，没有安装插件、扫码、登录、修改 DSH 配置或启动 QQ 服务。

## 找到的官方插件

腾讯已发布 [tencent-connect/dsh-qqbot](https://github.com/tencent-connect/dsh-qqbot)，包名为 `@tencent-connect/dsh-qqbot`。发布组织 [tencent-connect](https://github.com/tencent-connect) 已通过 GitHub 对 `bot.q.qq.com` 域名的验证；它不是仅在第三方插件市场自称“官方”的条目。

本次读取源码 commit `d998f72fb4ab5492eaab3c5e1cc9de1d7901e8a9`，package.json 版本为 0.5.3。插件通过腾讯 QQ Bot SDK、AppID/AppSecret 和官方 WebSocket 网关连接 QQ，将收到的消息交给 DSH Agent。它不依赖 NapCat，也不通过普通 QQ 客户端登录账号。

官方 README 的桌面安装流程：DSH 左侧“插件”→“添加插件”→输入 `@tencent-connect/dsh-qqbot@latest`；安装后在“设置→QQ 机器人”用手机 QQ 扫码连接。扫码用于绑定机器人凭据，不是接管原普通 QQ 账号及其群关系。也支持手工配置机器人 AppID/AppSecret。实际安装版本以 npm 发布状态为准，本次没有执行安装。

## 官方机器人能否进原群

[QQ 官方接入指南](https://bot.q.qq.com/wiki/)明确支持群聊、频道和单聊；服务范围取决于主体认证状态：未认证创建者仅可添加自己是群主或管理员的群，个人认证暂不支持公开使用、进群上限为 500 个，企业认证可设置公开服务范围。

因此可以评估把新机器人添加到原来的群，但不能自动继承旧 QQ 账号已加入的群，也不能在未检查群权限和机器人服务范围前保证所有原群都可加入。此前“继续使用普通 QQ 账号身份”的要求与这条官方机器人路线不同。

官方 WebSocket 模式不要求公网回调服务器，适合本机长期连接；Webhook 模式则把事件推送到配置的 HTTPS 服务。两种方式均见上述官方接入指南。

## 已确认全量群消息能力

[官方 GROUP_MESSAGE_CREATE 文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html)明确：开启“接收所有消息”后，会推送群里的消息，不限于 @机器人。事件包含文本、群 OpenID、成员 OpenID、昵称、附件和消息元素等信息。能收到哪些事件仍以目标机器人和目标群实际开启的能力为准。

读取的 [腾讯 Node.js SDK](https://github.com/tencent-connect/qqbot-nodejs) 版本为 1.0.5；其 `src/protocol/gateway/event-dispatcher.ts` 同时分发 GROUP_AT_MESSAGE_CREATE 和 GROUP_MESSAGE_CREATE。DSH 插件在 @门控之前维护收到的群消息缓存，因此 `requireMention` 控制回复触发，并不等于从平台取得全量消息权限。

DSH 插件使用 MemoryHistoryStore 保存近期上下文，并在回复后清理；README 的 `historyLimit` 是上下文缓冲条数，不能视作“从 QQ 服务器拉取历史记录”或项目数据库长期归档。

## 对当前项目的适配判断

| 需求 | 本次核实结果 | 项目后续工作 |
| --- | --- | --- |
| QQ 群/单聊 AI 对话 | 官方插件已有 | 可作为官方通道的验证入口 |
| 收集新群消息、文字和消息附件 | 官方事件具备相关字段 | 接入数据库、下载、分类和去重流程；验证目标群实际推送 |
| 图库和已有报告 | 当前项目数据已在本地 | 保留本地查询与生成，不需要依附 DSH 会话 |
| 定时日报发送 | 官方提供主动消息接口 | 另做发送适配、权限判断和频控，不沿用 OneBot RPC |
| 历史补拉、完整群文件目录扫描 | 本次未确认等价能力 | 标为未验证，不能承诺功能无损替换 |
| 沿用旧群号与 QQ 号的白名单 | 官方接口使用 OpenID | 需新增身份映射与来源命名空间，不能直接把 OpenID 转成数字群号 |

[官方群消息发送接口](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)支持文本、Markdown 和富媒体，明确区分被动回复与主动发送，并列出群消息频控。[消息收发概述](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html)还说明，用户可以关闭主动接收开关；因此定时报告不能只验证接口连接成功，还要验证目标群的实际发送授权。

调研后的实现进展：本项目已新增 QQ 官方适配器、扫码绑定入口、实时采集和报告发送支持，详见 [QQ 官方通道接入](QQ官方通道接入.md)。腾讯官方接口的鉴权、事件和 REST 发送协议不同，不能只换一个 ws_url，也不能仅安装 DSH 插件便宣称本项目已支持官方通道。

## 采用建议与验证边界

若目标是优先使用官方接入，可先用腾讯 DSH 插件验证机器人能否进入指定原群、能否收到未 @ 的新消息及附件，再决定是否把官方 SDK 接入当前项目的数据管线。长期实现建议将官方接入做成独立适配器，沿用本项目数据库、图库和报告，而不是把归档工作寄托在 DSH 的短期聊天上下文中。

仅检查本机 DSH 的 desktop/web profile 包清单与插件目录，未找到该腾讯插件的安装记录；这不等同于对所有运行时或所有 profile 的完整安装审计。本次没有验证真实机器人凭据、目标群权限、收发闭环或长期运行稳定性。

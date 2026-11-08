# QQ 官方通道接入

本项目已增加 QQ 开放平台 API v2 接入，不依赖 NapCat 或 DSH 常驻。采用与腾讯 DSH 插件相同的官方协议；扫码绑定组件使用腾讯 `@tencent-connect/qqbot-connector@1.2.0`，归档与报告仍由本项目处理。

## 连接方式

打开管理器“设置→通用→连接 QQ 官方机器人（扫码）”，用手机 QQ 完成腾讯页面中的选择与授权。二维码有效期以腾讯提示为准；到期后重新点击连接。成功后 AppID 写入 config.yaml，AppSecret 只写入项目 .env，自动选择 qqofficial 接入并关闭 NapCat 进程管理。已有多个机器人但没有指定 AppID 时，不会替用户猜选。

也可在“设置→运行配置”选择 qqofficial，填写 AppID 和遮罩显示的 AppSecret 后保存；密钥栏留空会保留已有密钥。保存通过标准输入传递密钥，不放在命令行参数中，不回显到保存结果。

绑定完成后重新打开管理器或重新进入设置页刷新配置。机器人不会因扫码成功而自行启动。原 QQ 号/群号白名单不自动转为官方 OpenID；先在目标群添加官方机器人并启用需要的事件/接收所有消息，再从本项目观察到的群列表中取得官方群标识。群列表只包含已收到消息的群，不能视作平台完整群列表。

先启动通道接收消息，可在“群采集”页查看已观察到的群；随后按需要配置官方回复白名单和日报接收者。未配置官方命令白名单时，旧的数字 QQ 白名单不会授予新 OpenID 权限；原有群管理员回复策略仍按原设置生效。

```yaml
onebot:
  provider: qqofficial
  protocol: qqofficial
  manage_process: false
  webui_url: https://q.qq.com/
qq_official:
  app_id: '机器人 AppID'
  allowed_users: []
  allowed_groups: []
  report_users: []
  report_groups: []
```

上述列表填写原始 OpenID 或同一应用的完整 `qqofficial:AppID:OpenID` 标识。平台身份在数据库中按应用隔离，官方群范围为 `group:qqofficial:AppID:OpenID`，不会与旧数字群号合并。AppID/AppSecret 只证明机器人凭据，不会继承普通 QQ 账号的群关系。

## 已实现与边界

- 官方 Access Token 获取和到期刷新；官方 WebSocket HELLO、IDENTIFY、心跳、ACK 检查、断线重连和进程内 RESUME。
- 群 @、群全量和单聊新消息转换到现有采集管线；文本、分享链接、图片与文件消息附件进入现有处理流程。群全量消息是否推送取决于平台及目标群的设置。
- 收到消息先存入 SQLite 的 official_inbox，再推进恢复序号；成功消费后标记 processed，处理失败保留为 failed。进程中断后可继续处理 pending 消息，不依赖内存队列。
- 引用消息通过引用索引保留关联，不把旧图和旧正文归给引用者。已收到的合并记录可从本地缓存读取节点并保留原作者；这不是向平台补拉任意历史记录。
- 文本回复、官方 OpenID 用户/群的主动日报；支持远程图片 URL 经官方富媒体接口上传发送。发送确认会检查平台错误和消息 ID，失败不标记日报成功。本地文件上传、语音、视频出站尚未实现。
- 旧数据库、图库、报告预览继续使用；切换通道无需清空数据。需要下载的附件仍遵守既有开关、大小、目录及保留策略，过期的官方附件 URL 不会回退请求 NapCat。
- 历史消息补拉、完整群文件目录遍历、基于旧协议的文件链接续取不支持；官方模式不启动这些后台功能，也不将官方附件加入旧协议群文件同步队列。
- 群/单聊发送仍受官方权限和频控约束；多条分片可能部分发送后失败，不承诺平台没有提供的事务性发送。

平台返回停用/封禁终止码 4914/4915 时，停止该通道收发，保留待处理消息，不自动重试官方网络请求。修复开放平台状态后，可执行下列命令解除本地阻断，再手动启动：

```powershell
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control official-reset
```

只读诊断：

```powershell
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control gateway-info
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control gateway-check
```

gateway-check 可以验证凭据和获取网关地址，不会发送测试消息；只有真实 READY/心跳和活着的本项目进程才会被状态面板确认为在线。未配置凭据时，会显示“尚未绑定”，不会尝试启动 NapCat。

扫码依赖安装（新机器）：安装 Node.js 20+，在项目根目录执行 `npm.cmd ci --prefix scripts/qq-official --ignore-scripts`。业务接入由 Python 运行，只有扫码时需要 Node.js；直接填写 AppID/AppSecret 不依赖扫码组件。

## 验证记录

已使用本地 HTTP/WebSocket 模拟服务验证鉴权、握手、心跳、消息入库去重、文本/图片发送、权限错误、256/257 条消息积压与新连接恢复、引用作者归属、终止态禁止发送、密钥保存和绑定配置。Qt 已验证真实设置保存将密钥写入临时项目 .env，而不进入 YAML、argv 或返回结果。

真实 QQ 凭据、目标群权限、群全量推送、平台发送结果和长期稳定性仍需扫码绑定后实测。本地测试不等同于真实平台验收。

参考：[腾讯 DSH 插件](https://github.com/tencent-connect/dsh-qqbot)、[QQ 官方全量群事件](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html)、[官方消息收发规则](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html)。

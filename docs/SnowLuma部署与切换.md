# SnowLuma 部署与切换

本文说明在 Windows 上安装 SnowLuma，并把本项目的 OneBot v11 接入切换到 SnowLuma。项目集成负责下载解包、启动/停止 SnowLuma，以及在切换时检查连接；首次协议确认、QQ 登录仍由用户在 SnowLuma WebUI 和桌面 QQ 中完成。

## 版本与下载

本文按 SnowLuma v2.4.2 编写。上游发布页：<https://github.com/SnowLuma/SnowLuma/releases/tag/v2.4.2>。

| Windows x64 发行包 | 适用情况 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| [完整版 ZIP](https://github.com/SnowLuma/SnowLuma/releases/download/v2.4.2/SnowLuma-v2.4.2-win-x64.zip) | 推荐；自带 Node.js 运行时 | 43,361,462 字节 | `0912926c5e73260f35b000278a8658493fc9452f36782c32fa86f0e825bad81a` |
| [Lite ZIP](https://github.com/SnowLuma/SnowLuma/releases/download/v2.4.2/SnowLuma-v2.4.2-win-x64-lite.zip) | 仅适合已安装兼容 Node.js 的环境 | 7,196,866 字节 | `14c6f137196d5f556e6c601a880ee8aa238ffaf4227696848a146209f96d0f31` |

本项目自动安装使用 Windows x64 完整版，解包到项目根目录下的 `runtime/snowluma`。实际目录包含 `node.exe`、`index.mjs`、`client/` 等文件；SnowLuma 配置与账号数据也保存在此运行目录中。完整版避免依赖系统 Node.js。Lite 包不含 Node.js；v2.4.2 发布说明标注需 Node.js 24.22.1 或 26.12.1 起。SnowLuma 本身要求 Windows 桌面版 NTQQ（QQ.exe），本项目不会代装 QQ。

安装时可在管理器设置页使用 SnowLuma 安装按钮，或从项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control snowluma-install
```

安装只下载并解包发行包，不会启动 SnowLuma，也不会替用户接受 EULA/隐私政策或登录 QQ。SnowLuma 的启动、停止依赖管理器的后台任务，应使用管理器设置页的启动/停止按钮；不要在管理器外单独运行这些命令，因为管理器外调用目前不支持该任务上下文。SnowLuma 运行时随管理器启动和退出。

为避免 SnowLuma 的 `#sl` 自动状态回复干扰群聊，项目会在安装、启动和切换时关闭其 OneBot 状态命令；其他 SnowLuma 设置保持不变。

随后访问 <http://127.0.0.1:5099>，按 SnowLuma 页面提示阅读并接受 EULA 与隐私政策，再按页面引导登录 QQ。SnowLuma 的首次管理员登录名为 `admin`，初始密码由启动日志给出。初始 `hookAutoLoad` 为关闭状态；在 WebUI 中手动选择 QQ 进程并加载 hook。确认手动流程正常后，可在 SnowLuma WebUI 中按需启用自动加载。登录需要桌面 QQ 扫码；SnowLuma 与 QQ 应由同一 Windows 用户、相同权限级别运行。QQ 客户端版本需与 SnowLuma 的 native hook 兼容；遇到注入失败时请先查看上游兼容说明。

## 切换本项目

管理器首页“概览”的“框架切换”区域可直接操作：普通 OneBot 框架选择目标并填写连接地址与 Token 变量名，然后点击“检查并切换”。已安装的 SnowLuma 可在同一区域启动、打开管理页，登录后点击“自动识别并切换 SnowLuma”，由项目读取其本地连接配置和 Token。首页的“恢复上次框架”恢复最近一次切换前的接入配置。操作结果显示在首页；成功后点击首页服务控制区的“启动”。设置页原有入口继续可用。

在 SnowLuma WebUI 中启用 OneBot v11 正向 WebSocket 服务，确认 WebSocket 监听在本机，默认地址为 `ws://127.0.0.1:3001`。按需在 SnowLuma 的账号配置中设置访问 Token。不要将 WebUI 或 OneBot 端口暴露到公网。

确认 SnowLuma 已登录后，在本项目管理器设置中选择 SnowLuma，并点击切换/检查按钮。也可以运行：

```powershell
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control snowluma-switch
```

切换会自动停止本项目业务机器人，并检查本机 OneBot WebSocket 端点和登录状态。检查通过后保存配置为 `provider: snowluma`、`protocol: onebot11`、`manage_process: false`，并设置 `onebot.start_installed_runtime: true`，使下次管理器启动时启动已安装的 SnowLuma。SnowLuma 账号 Token 写入专用 `.env` 变量 `SNOWLUMA_ONEBOT_TOKEN`，原有 `ONEBOT_ACCESS_TOKEN` 不会被覆盖。切换不会迁移或删除本项目数据库、图库、白名单和报告。

无论切换检查成功还是失败，业务机器人都会保持停止；失败时原接入配置保持不变。管理器主窗口保持开启，不需要事先停止整个管理器。切换成功后，在管理器“总览”页点击“启动”以启动业务机器人并应用新接入。

如需停止 SnowLuma，使用管理器设置页的停止按钮。若业务机器人仍在运行，SnowLuma 停止操作会被拒绝；先通过恢复按钮切回原接入（会停止业务机器人），或退出管理器（会同时停止其托管的 SnowLuma）。

安装/启动按钮会显示操作结果，也可使用命令查看安装和运行状态：

```powershell
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control snowluma-status
```

## 回到其他 OneBot 接入

使用设置页恢复按钮，或运行以下命令恢复切换前保存的接入：

```powershell
.\.venv\Scripts\python.exe -m qq_onebot_whitelist.control snowluma-restore
```

恢复同样会先停止业务机器人；完成后到管理器“总览”页点击“启动”。如果不再需要 SnowLuma，请先确认运行目录中没有需要保留的配置、登录资料或其他数据，再考虑自行清理 `runtime/snowluma`。该目录包含 SnowLuma 的运行配置和账号数据，不要将其当作临时缓存直接删除。本项目数据库、图库、白名单和报告均保留在原处。

## 上游资料

- [v2.4.2 发布说明及资产](https://github.com/SnowLuma/SnowLuma/releases/tag/v2.4.2)
- [Windows 手动部署指南](https://snowluma.github.io/zh/docs/guide/deploy/windows)
- [SnowLuma 发行包结构与服务说明](https://snowluma.github.io/en/docs/guide/introduction)

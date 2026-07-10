# QQ OneBot 白名单资源机器人

基于 NapCat / OneBot v11 正向 WebSocket 的本地 QQ 群消息、AI 图片与资源归档机器人。

> 项目采用非官方 QQ 客户端接入方式，不使用 QQ 官方机器人开放平台。

## 主要功能

- 白名单私聊与群聊 `@机器人` 回复；群管理员/群主可按配置触发。
- 自动记录非黑名单群消息、链接、模型/压缩包/工作流文件信息。
- 图片元数据识别：ComfyUI、NovelAI 等 AI 生成信息。
- 图片分级归档：AI 元数据、群友好评、AI 上下文、候选待观察。
- DeepSeek V4 Flash 自动增量分析群聊 AI 上下文。
- 高价值链接与文件去重、按群名分类生成本地 HTML 页面。
- 每日资源增量精选；只统计上次日报后的新增内容。
- 启动时后台补拉历史消息，不阻塞实时命令回复。

## 项目入口

- 完整使用说明：[`docs/使用说明.md`](docs/使用说明.md)
- 维护与交接文档：[`docs/交接文档.md`](docs/交接文档.md)
- 图片和资源总入口：`data/view/index.html`
- 高价值链接：`data/view/resources.html`
- 高价值文件/工作流：`data/view/files.html`

从项目根目录可直接打开：

```powershell
Start-Process ".\data\view\index.html"
```

## 快速启动（Windows 托盘）

首次安装桌面和开始菜单快捷方式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-tray-shortcut.ps1"
```

之后打开“QQ OneBot Bot”快捷方式。机器人会在后台启动，并在系统托盘提供：打开本地页面、查看日志、停止服务和退出托盘。

NapCat 默认位于项目内 `runtime/NapCat.Shell.Windows.Node`，该运行目录不进入 Git。`scripts/windows/launcher.config.ps1` 只用于可选路径覆盖。

命令行后台启动：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\start-qq-onebot-whitelist-hidden.ps1"
```

命令行停止 bot 和 NapCat：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\stop-qq-onebot-whitelist-hidden.ps1"
```

前台运行 bot：

```powershell
uv run python -m qq_onebot_whitelist.onebot --config config.yaml
```

## 测试

```bash
uv run --extra dev pytest -q
```

当前项目要求 Python 3.11+，依赖由 `uv` 管理。

## 重要数据

```text
data/bot.db                 SQLite 主数据库
data/images/ai/             长期图片归档，不按缓存预算删除
data/images/candidates/     临时候选图片，可按 TTL 清理
data/view/                  自动生成的本地浏览页面
logs/                       bot 与 NapCat 日志
run/                        PID 文件
```

不要手动删除 `data/images/ai/` 或 `data/bot.db`。`data/view/` 是可重建视图，不是唯一数据源。

## 分析时段

默认全天允许分析。可通过托盘“Set analysis windows”、直接编辑 `config.yaml`，或白名单用户私聊机器人发送：

```text
分析时段 查看
分析时段 设置 00:30-08:30,12:00-13:00
分析时段 全天
```

多个时间段和跨午夜时间段均受支持，修改后无需重启。

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

## 控制面板（Qt 原生）

`qq-onebot-manager-qt/` 是 Qt 6 Widgets 原生控制面板（C++），替代旧的 Rust 管理器，提供：

- **概览**：NapCat / OneBot / 机器人 / QQ 登录状态卡片，启动/停止/重启，日志、报告、配置目录快捷入口，图片/链接数据概况。
- **设置**：分区配置表单（数据来自 `config_bridge.py` schema）、语言、主题（浅色/深色）、开机自启、登录通知开关、自动重启开关。
- **日志**：bot.log / napcat.log 实时增量查看，搜索、只看错误、暂停。
- **报告**：报告页入口、日报预览、手动发送测试日报。
- 托盘常驻、关闭进托盘、QQ 登录/掉线与服务异常的原生系统通知、面板侧自动重启。

构建（命令行；也可直接用 Qt Creator 打开 `qq-onebot-manager-qt/CMakeLists.txt`）：

```powershell
& "C:\Qt\Tools\CMake_64\bin\cmake.exe" -S qq-onebot-manager-qt -B qq-onebot-manager-qt/build -G "MinGW Makefiles" -DCMAKE_PREFIX_PATH="C:\Qt\6.11.1\mingw_64" -DCMAKE_CXX_COMPILER="C:\Qt\Tools\mingw1310_64\bin\g++.exe"
& "C:\Qt\Tools\CMake_64\bin\cmake.exe" --build qq-onebot-manager-qt/build
```

构建后运行部署脚本把 Qt DLL 复制到 exe 旁边，之后可直接双击运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\qq-onebot-manager-qt\deploy.ps1"
.\qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe
```

控制面板通过 `python -m qq_onebot_whitelist.control`（`control.py`）完成启动/停止/统计/报告等操作；机器人在 `run/status.json` 写入实时状态，面板进程内读取，高频刷新不产生子进程。

## 测试

```bash
uv run --extra dev pytest -q
```

Qt 单元测试：

```powershell
& "C:\Qt\Tools\CMake_64\bin\ctest.exe" --test-dir qq-onebot-manager-qt/build
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

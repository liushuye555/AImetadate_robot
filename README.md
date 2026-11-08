# QQ OneBot 白名单资源机器人

支持 OneBot v11 与 QQ 官方开放平台的本地 QQ 群消息、AI 图片与资源归档机器人，接入层不绑定 NapCat。

QQ 官方通道可在管理器中扫码绑定；OneBot 通道继续支持外部框架。配置与功能边界见 [QQ 官方通道接入](docs/QQ官方通道接入.md)。

## 主要功能

- 白名单私聊与群聊 `@机器人` 回复；群管理员/群主可按配置触发。
- 自动记录非黑名单群消息、链接、模型/压缩包/工作流文件信息。
- 图片元数据识别：ComfyUI、NovelAI 等 AI 生成信息。
- 图片分级归档：AI 元数据、群友好评、AI 上下文、候选待观察。
- DeepSeek V4 Flash 自动增量分析群聊 AI 上下文。
- 高价值链接与文件去重、按群名分类生成本地 HTML 页面。
- 每日资源增量精选；只统计上次日报后的新增内容。
- 启动时后台补拉历史消息，不阻塞实时命令回复。
- 需要向前补齐所有可获取的群历史时，可运行独立的[全量历史补抓任务](docs/全量历史补抓.md)：无固定页数上限、逐页保存断点、按原始日期归档，保留接口无法返回更早消息的状态。
- 可选的按群总结、知识提取、术语学习和文件归档（全局默认关闭；需逐群、逐功能主动开启）。

## 项目入口

- 完整使用说明：[`docs/使用说明.md`](docs/使用说明.md)
- 维护与交接文档：[`docs/交接文档.md`](docs/交接文档.md)
- 框架选择、检查并切换、恢复及 Token 配置：[`docs/框架接入兼容性.md`](docs/框架接入兼容性.md)
- SnowLuma 内置安装、启停、迁移与恢复：[`docs/SnowLuma部署与切换.md`](docs/SnowLuma部署与切换.md)（管理器 → 设置 → 通用 → SnowLuma）
- 图片和资源总入口：`data/view/index.html`
- 数据库图库：机器人运行时访问 `http://127.0.0.1:3017/view/gallery.html`（端口可配置）。分页、搜索和分类直接查询 SQLite，浏览不再生成分类图片硬链接。
- 高价值链接：`data/view/resources.html`
- 高价值文件/工作流：`data/view/files.html`
- 群知识功能说明：[`docs/群知识功能使用说明.md`](docs/群知识功能使用说明.md)

群知识结果默认保存在本地 `data/view/knowledge.html`，索引使用独立的 `knowledge.db`。首次开启实时功能从当前最新消息水位开始，不会自动回填旧消息。启用方式、历史回放和文件保留命令见使用说明。

从项目根目录可直接打开：

```powershell
Start-Process ".\data\view\index.html"
```

## 快速启动（Windows 管理器）

首次安装桌面和开始菜单快捷方式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-tray-shortcut.ps1"
```

之后打开“QQ OneBot Bot”快捷方式启动 Qt 管理器。关闭窗口右上角的 X 会把管理器收进系统托盘并继续托管机器人。选择“停止”或“退出”会关闭管理器并结束它托管的机器人后台；外部接入框架继续独立运行。

NapCat 默认位于项目内 `runtime/NapCat.Shell.Windows.Node`，该运行目录不进入 Git。`scripts/windows/launcher.config.ps1` 只用于可选路径覆盖。

命令行启动同样转交给 Qt 管理器：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\start-qq-onebot-whitelist-hidden.ps1"
```

请求 Qt 管理器停止并退出：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\stop-qq-onebot-whitelist-hidden.ps1"
```

机器人后台由 Qt 管理器的 Windows Job 托管。管理器崩溃或被强制结束时，Windows 会一并结束机器人后台；NapCat 被独立启动，不随管理器退出。重新启动机器人时，请重新打开 Qt 管理器。

## 控制面板（Qt 原生）

`qq-onebot-manager-qt/` 是 Qt 6 Widgets 原生控制面板（C++），替代旧的 Rust 管理器，提供：

- **概览**：所选接入框架 / OneBot / 机器人 / QQ 登录状态卡片，启动/停止/重启，日志、报告、配置目录快捷入口，图片/链接数据概况。
- **设置**：分区配置表单（数据来自 `config_bridge.py` schema）、语言、主题（浅色/深色）、开机自启和登录通知开关。
- **日志**：bot.log / gateway.log 及历史 napcat.log 实时增量查看，搜索、只看错误、暂停。外部框架日志由其自身管理。
- **报告**：报告页入口、日报预览、手动发送测试日报。
- 托盘常驻、关闭进托盘、QQ 登录/掉线与服务异常的原生系统通知。

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

不要手动删除 `data/images/ai/` 或 `data/bot.db`。`data/view/` 保存报告和图库入口，不是唯一数据源。图片原文件保留在磁盘，分类关系保存在数据库；缩略图按需缓存到 `data/cache/gallery-thumbnails/`。旧分类目录暂保留供历史报告链接使用，后台不再自动生成分类或画风工具的硬链接；需要独立文件目录时手动导出。

## 分析时段

默认全天允许分析。可通过托盘“Set analysis windows”、直接编辑 `config.yaml`，或白名单用户私聊机器人发送：

```text
分析时段 查看
分析时段 设置 00:30-08:30,12:00-13:00
分析时段 全天
```

多个时间段和跨午夜时间段均受支持，修改后无需重启。

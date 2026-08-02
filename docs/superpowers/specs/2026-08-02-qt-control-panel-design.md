# Qt 控制面板设计

日期：2026-08-02

## 1. 背景与目标

现有 Rust/Slint 原生管理器存在渲染缺陷（窗口从托盘重新打开后内容空白，Slint 1.17.1 软件渲染器在 Windows 上未触发重绘，当前无官方修复），且界面样式与功能都未达预期。本子项目用成熟、流畅、低占用的方案替换它。

目标：

- 流畅：界面操作零卡顿，状态刷新不阻塞主线程。
- 占用低：常驻内存控制在几十 MB 级别；高频操作不产生子进程。
- 维护方便：业务逻辑收敛到 Python 单语言，C++ 只做界面。
- 可扩展：为后续功能（聊天能力、复读机、多群采集、负载感知调度）预留接口；主题与图标可替换。

## 2. 核心决策

| 决策点 | 结论 | 理由 |
| --- | --- | --- |
| 界面技术 | Qt 6.11.1 Widgets + CMake + MinGW，Qt Creator 工程 | 原生渲染流畅；本地已装 6.11.1 / MinGW 13.1 / CMake 3.30 |
| 状态刷新 | 面板进程内读取 `run/status.json`（机器人写入）；文件过期时用端口探测兜底 | 零子进程、零额外内存；机器人自身连接 OneBot，登录态最准 |
| 启动/停止/配置 | Python 控制桥 `python -m qq_onebot_whitelist.control ...` | 低频操作，偶发子进程可接受；业务逻辑留在 Python，pytest 可测 |
| PowerShell | 降级为兼容入口，面板不依赖 | 去掉第三套语言，降低维护负担 |
| 通知 | QSystemTrayIcon 原生托盘通知（Windows 10/11 系统样式） | 无需额外依赖，成熟可靠 |
| WebView | 不使用 | 一个 WebView 会吃掉数百 MB，违背低占用 |

## 3. 总体架构

```
┌──────────────────────┐        ┌──────────────────────────┐
│  Qt 面板（C++）       │  QProcess│  Python 控制层           │
│  core/ ui/ theme/    │ ──────▶ │  qq_onebot_whitelist/    │
│  ── 状态：读文件（端口兜底）│     │  control.py              │
│  ── 控制：调 control  │ ◀────── │  config_bridge.py（复用） │
│  ── 日志：尾部增量读  │        │  机器人进程内状态写入器    │
└──────────────────────┘        └──────────────────────────┘
          │ ▲
          │ 读 run/status.json（机器人写入，3~5s 轮询）
          ▼ │
   run/status.json
```

工程结构：

```
qq-onebot-manager-qt/
├── CMakeLists.txt
├── src/
│   ├── main.cpp                 # 入口、单实例
│   ├── app/                     # 应用级逻辑（启动自检、托盘）
│   ├── core/                    # 桥接层，与界面无关
│   │   ├── StatusMonitor.h/.cpp # 读 status.json + 端口检测
│   │   ├── ServiceControl.h/.cpp# QProcess 调 control.py
│   │   ├── ConfigBridge.h/.cpp  # QProcess 调 config_bridge.py
│   │   ├── LogReader.h/.cpp     # 日志尾部增量读取
│   │   ├── ReportBridge.h/.cpp  # 报告入口、日报预览/测试发送
│   │   └── Notifier.h/.cpp      # 状态变化 → 原生通知
│   ├── ui/
│   │   ├── MainWindow.h/.cpp    # 侧边导航 + 页面容器
│   │   ├── pages/               # Overview/Settings/Logs/Reports
│   │   ├── widgets/             # StatusCard、CollapsibleSection 等
│   │   └── theme/ThemeManager.h/.cpp
│   └── resources/
│       ├── icons.qrc            # 全部图标
│       └── themes/              # light.qss / dark.qss
```

桥接层与界面层严格分离：桥接层只负责数据与命令，界面层只负责显示与交互；新增功能 = 新增一个桥接模块 + 一个页面，主框架不动。

## 4. 状态协议

机器人（Python）在其进程内维护 `run/status.json`，内容：

```json
{
  "napcat": true,
  "onebot": true,
  "bot": true,
  "qqLoggedIn": true,
  "qqNumber": "1736617425",
  "qqNickname": "柳树叶",
  "autoRestartedAt": "2026-08-02T08:30:00+08:00",
  "updatedAt": "2026-08-02T09:00:00+08:00"
}
```

- 面板每 3~5 秒读一次文件（QFile + QJsonDocument，进程内）。
- `updatedAt` 超过 15 秒视为状态过期，卡片显示"未知"，避免误报。
- 文件过期时面板用进程内 TCP 探测 6099/3001 端口作为兜底显示。
- 机器人写入时机：OneBot 连接建立/断开、QQ 登录/掉线事件（生命周期事件）、以及 30 秒定时兜底写入。
- NapCat 字段：机器人用本地 TCP 探测 6099 端口；自动重启发生时写入 `autoRestartedAt`。
- 该文件同时被托盘菜单和外部脚本复用，成为统一状态源。

## 5. 界面：四个页面

### 5.1 概览（Overview）

- 4 张状态卡：NapCat / OneBot / 机器人 / QQ 账号（含昵称与号）。
- 服务控制：启动、停止、重启、刷新。
- 手动停止状态提示：用户停止后明确显示"已手动停止，自动重启已暂停"。
- 自动重启状态可视化：开关状态 + 最近一次自动重启时间（来自 `autoRestartedAt`）。
- 数据概况：归档图片数、资源链接数、报告更新时间（进页时通过 `control stats` 查询一次）。
- 快捷入口：打开日志目录 / 打开报告 / 打开配置目录 / 立即读取历史。

### 5.2 设置（Settings）

- 分区折叠：运行环境 / 机器人 / AI / 日报 / 访问控制 / 高级 / 功能开关。
- 语言：跟随系统 / 中文 / 英文。
- 开机自启开关：添加/移除 Windows 启动文件夹快捷方式（指向面板 exe，面板启动时自动拉起机器人）。
- 自动重启开关（将现有隐藏配置显性化）。
- 通知开关（登录提醒等）。
- API Key 等敏感字段：只写入、不回显明文。
- 输入校验：非法数字/越界标红；切换页面或关闭时有未保存提醒。
- 表单由 config_bridge 的 schema 数据驱动生成，机器人配置新增字段后面板自动跟上。

### 5.3 日志（Logs）

- bot.log / napcat.log 切换；尾部增量读取（QTimer 轮询文件大小），不整文件加载。
- 自动滚动、暂停、搜索过滤、错误行高亮 + "只看错误"。
- 打开日志目录按钮。

### 5.4 报告（Reports）

- 报告入口：`data/view/index.html`、`files.html`、`resources.html` 用系统浏览器打开。
- 最近日报预览：`control report-preview` 调用现有 `build_daily_resource_report` 生成文本，原生卡片展示。
- 手动发送测试日报：`control report-send`（控制层独立建立 OneBot WebSocket 连接发送）。
- 下次日报发送时间提示。

## 6. 通知（Windows 原生）

使用 `QSystemTrayIcon::showMessage`（Windows 10/11 下显示为系统原生通知）。

触发事件：

- QQ 登录成功。
- QQ 掉线。
- 服务从正常变为异常（NapCat / OneBot / 机器人任一）。
- 服务自动重启成功（`autoRestartedAt` 变化）/ 全部恢复健康。

由面板的 `Notifier` 比较相邻两次状态快照检测变化，去重（同一事件 10 分钟内不重复提醒）。设置页可关闭。

## 7. Python 控制层（control.py）

新增 `qq_onebot_whitelist/control.py`，CLI 子命令：

| 命令 | 行为 |
| --- | --- |
| `status` | 输出 status.json（CLI/测试用途） |
| `start` | 迁移现有 start 脚本逻辑：启动 NapCat（napcat.bat）、等待 3001 端口、启动机器人 |
| `stop` | 迁移现有 stop 脚本逻辑：按 PID 文件与进程特征终止 |
| `restart` | stop + start |
| `config-get` / `config-patch` | 复用 config_bridge.py 语义 |
| `stats` | 查询 Store 数据库：图片数、资源数、最近报告时间 |
| `report-preview` | 生成日报文本（复用 daily_report.py） |
| `report-send` | 独立 WebSocket 连接，按日报配置的目标群发送日报 |

机器人进程内新增状态写入器（`status_writer` 任务），与现有 `daily_report_loop`、`ai_context_loop`、`keepalive_loop` 并列。

未来负载感知调度（子项目 ⑤）在 control.py 内预留 `scheduler` 与资源检测接口（psutil），本期只留接口不实现。

## 8. 扩展性预留

1. **主题引擎**：ThemeManager 从 QSS 文件加载，内置浅色/深色，用户可添加自定义主题文件（美化无需改代码）。
2. **图标系统**：统一 .qrc 资源，替换图标集只换资源文件。
3. **页面注册制**：导航项按注册表添加，新页面不碰主框架。
4. **schema 驱动表单**：设置页由 config_bridge schema 自动生成。
5. **消息处理器框架**（子项目 ② 的前置接口）：control.py 与机器人侧预留"处理器注册"概念，聊天、复读机、采集器作为独立处理器挂载。

## 9. 流畅与占用保障

- 状态刷新：纯文件读取 + 进程内端口探测，无子进程。
- 所有 QProcess 调用（控制/配置/报告）异步执行，不进主线程。
- 日志尾部增量读取，不整文件加载。
- 无 WebView、无浏览器内核。
- 预计常驻内存 40~60 MB。

## 10. 托盘

- 关闭窗口 → 隐藏到托盘（行为与现状一致）。
- 托盘菜单：状态摘要 + 打开面板 / 启动 / 停止 / 重启 / 打开日志 / 打开报告 / 退出。
- 托盘图标来自 .qrc 资源，窗口图标同源。

## 11. 测试与维护

- Qt Test：StatusMonitor 解析、ConfigBridge/ServiceControl 命令构造、Notifier 状态变化判定。
- pytest：control.py 各命令与状态写入器。
- 手动验收清单：托盘开/关窗、状态刷新、通知触发、开机自启开关、配置保存与校验、日志滚动。
- CMake 工程由 Qt Creator 直接打开；构建命令：`cmake --build` 或 Qt Creator 内构建。

## 12. 范围界定

本期只实现子项目 ①（Qt 面板 + Python 控制层 + 状态写入器）。以下为后续子项目，本期仅预留接口：

- ② 消息处理器框架（聊天能力地基）
- ③ 复读机
- ④ 多群多类型采集与分类
- ⑤ 负载感知调度
- ⑥ HTML 报告美化

## 13. 风险与对策

| 风险 | 对策 |
| --- | --- |
| NapCat 启动/停止逻辑迁移到 Python 可能有行为差异 | 对照现有脚本逐条移植，并用现有 pytest 与手动验收覆盖 |
| 状态文件写入与面板读取竞态 | JSON 原子写入（临时文件 + rename）；面板容忍解析失败 |
| 通知过度打扰 | 事件去重 + 设置页开关 |
| Qt 模块缺失（如 WebSockets） | 状态不依赖 Qt WebSockets（机器人直接写状态）；报告发送在 Python 侧完成 |

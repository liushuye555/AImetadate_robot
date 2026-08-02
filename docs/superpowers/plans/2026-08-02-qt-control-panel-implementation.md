# Qt 控制面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Qt Widgets 原生面板 + Python 控制桥替换现有 Rust/Slint 管理器，提供流畅、低占用、可扩展的控制面板。

**Architecture:** C++/Qt 6.11.1 面板负责界面与托盘；状态由机器人写入 `run/status.json`，面板进程内读取（零子进程）；启动/停止/统计/报告等低频操作通过 `python -m qq_onebot_whitelist.control` 子进程完成。配置读写复用现有 `config_bridge.py`。

**Tech Stack:** Qt 6.11.1 Widgets（CMake + MinGW 13.1，Qt Creator 打开）、Qt Network/Test/Svg；Python 3.11 项目 venv（websockets、PyYAML、pytest）。

---

## 文件结构

**Python 控制层（新增/修改）：**

- `qq_onebot_whitelist/control.py`（新增）：CLI 控制桥，`status/start/stop/restart/stats/report-preview/report-send`
- `qq_onebot_whitelist/onebot.py`（修改）：新增 `status_writer_loop` 任务写入 `run/status.json`
- `tests/test_control.py`（新增）：控制层单测
- `tests/test_status_writer.py`（新增）：状态写入单测

**Qt 面板（新增目录 `qq-onebot-manager-qt/`）：**

```
qq-onebot-manager-qt/
├── CMakeLists.txt
├── resources/
│   ├── resources.qrc
│   ├── icons/app.svg
│   └── themes/light.qss, dark.qss
├── src/
│   ├── main.cpp
│   ├── app/SingleInstance.h/.cpp
│   ├── core/Paths.h
│   ├── core/StatusMonitor.h/.cpp
│   ├── core/ServiceControl.h/.cpp
│   ├── core/ConfigBridge.h/.cpp
│   ├── core/LogReader.h/.cpp
│   ├── core/Notifier.h/.cpp
│   ├── ui/Strings.h
│   ├── ui/theme/ThemeManager.h/.cpp
│   ├── ui/MainWindow.h/.cpp
│   ├── ui/pages/OverviewPage.h/.cpp
│   ├── ui/pages/SettingsPage.h/.cpp
│   ├── ui/pages/LogsPage.h/.cpp
│   ├── ui/pages/ReportsPage.h/.cpp
│   └── ui/widgets/StatusCard.h/.cpp
└── tests/
    ├── CMakeLists.txt
    └── tst_statusmonitor.cpp
```

**既有文件修改：**

- `scripts/windows/install-tray-shortcut.ps1`：快捷方式目标改为新面板 exe
- `manager/`：验证通过后移动到 `manager-archived/`

---

## Phase A：Python 控制层（先做，独立可测）

### Task 1: control.py 骨架与 status 命令

**Files:**
- Create: `qq_onebot_whitelist/control.py`
- Test: `tests/test_control.py`

- [ ] **Step 1: 写失败测试**

`tests/test_control.py`：

```python
import json

from qq_onebot_whitelist import control


def test_write_status_is_atomic_and_contains_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    control.write_status({"napcat": True, "onebot": True, "bot": True})
    target = tmp_path / "status.json"
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["napcat"] is True
    assert data["updatedAt"]


def test_load_status_returns_empty_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "STATUS_PATH", tmp_path / "status.json")
    assert control.load_status() == {}


def test_port_open_false_when_closed(monkeypatch):
    def fake(port, timeout):
        raise OSError("closed")
    monkeypatch.setattr(control.socket, "create_connection", fake)
    assert control.port_open(6099) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -v`
Expected: `ModuleNotFoundError: No module named 'qq_onebot_whitelist.control'`

- [ ] **Step 3: 实现 control.py**

```python
"""Control bridge used by the Qt panel; keeps operational logic in Python."""
from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "run"
STATUS_PATH = RUN_DIR / "status.json"
NAPCAT_PORT = 6099
ONEBOT_PORT = 3001


def write_status(data: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = STATUS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS_PATH)


def load_status() -> dict:
    if not STATUS_PATH.exists():
        return {}
    return json.loads(STATUS_PATH.read_text(encoding="utf-8"))


def port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_status(), ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQ OneBot control bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print run/status.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"status": cmd_status}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/control.py tests/test_control.py
git commit -m "feat: add control bridge skeleton and status command"
```

---

### Task 2: 机器人状态写入器

**Files:**
- Modify: `qq_onebot_whitelist/onebot.py`（`run()` 与新增函数）
- Test: `tests/test_status_writer.py`

- [ ] **Step 1: 写失败测试**

`tests/test_status_writer.py`：

```python
import asyncio

from qq_onebot_whitelist import control
from qq_onebot_whitelist.onebot import status_writer_loop


def test_status_writer_loop_writes_login_info(tmp_path, monkeypatch):
    calls = []

    async def fake_call_action(ws, action, params):
        calls.append((action, params))
        return {"data": {"user_id": "123", "nickname": "柳树叶"}}

    async def fake_sleep(_seconds):
        raise KeyboardInterrupt  # 跳出循环

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: port == control.NAPCAT_PORT)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.call_action", fake_call_action)
    monkeypatch.setattr("qq_onebot_whitelist.onebot.asyncio.sleep", fake_sleep)

    async def main():
        try:
            await status_writer_loop(None, None)
        except KeyboardInterrupt:
            pass

    asyncio.run(main())
    data = control.load_status()
    assert calls == [("get_login_info", {})]
    assert data["napcat"] is True
    assert data["onebot"] is True
    assert data["bot"] is True
    assert data["qqLoggedIn"] is True
    assert data["qqNumber"] == "123"
    assert data["qqNickname"] == "柳树叶"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_status_writer.py -v`
Expected: FAIL，`ImportError: cannot import name 'status_writer_loop'`

- [ ] **Step 3: 在 onebot.py 实现状态写入器**

在 `onebot.py` 的 `keepalive_loop` 之后添加：

```python
async def status_writer_loop(ws, config: AppConfig) -> None:
    from . import control
    while True:
        try:
            login = {}
            try:
                resp = await call_action(ws, "get_login_info", {})
                data = resp.get("data") or {}
                qq_number = str(data.get("user_id") or "")
                qq_nickname = str(data.get("nickname") or "")
                login = {
                    "qqLoggedIn": bool(qq_number),
                    "qqNumber": qq_number,
                    "qqNickname": qq_nickname,
                }
            except Exception as exc:
                print(f"status_writer get_login_info failed: {type(exc).__name__}: {exc}")
                login = {"qqLoggedIn": False, "qqNumber": "", "qqNickname": ""}
            control.write_status(
                {
                    "napcat": control.port_open(control.NAPCAT_PORT),
                    "onebot": True,
                    "bot": True,
                    **login,
                }
            )
        except Exception as exc:
            print(f"status_writer failed: {type(exc).__name__}: {exc}")
        await asyncio.sleep(30)
```

在 `run()` 中创建任务并处理断开时的离线状态：

```python
        keepalive_task = asyncio.create_task(keepalive_loop(ws, config))
        status_task = asyncio.create_task(status_writer_loop(ws, config))
        try:
            async for raw in ws:
                ...
        finally:
            startup_task.cancel()
            report_task.cancel()
            ai_task.cancel()
            keepalive_task.cancel()
            status_task.cancel()
            from . import control
            control.write_status(
                {"napcat": control.port_open(control.NAPCAT_PORT),
                 "onebot": False, "bot": True,
                 "qqLoggedIn": False, "qqNumber": "", "qqNickname": ""}
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_status_writer.py -v`
Expected: PASS

- [ ] **Step 5: 运行既有测试确认无回归**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 全部通过（若有失败，先修复再继续）

- [ ] **Step 6: 提交**

```bash
git add qq_onebot_whitelist/onebot.py tests/test_status_writer.py
git commit -m "feat: write runtime status file from bot"
```

---

### Task 3: control.py start / stop / restart

**Files:**
- Modify: `qq_onebot_whitelist/control.py`
- Test: `tests/test_control.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_control.py`：

```python
def test_start_uses_expected_commands(tmp_path, monkeypatch):
    started = []

    def fake_popen(cmd, **kwargs):
        started.append(cmd)
        class P:
            pid = 42
        return P()

    monkeypatch.setattr(control, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(control, "port_open", lambda port, timeout=0.5: False)
    monkeypatch.setattr(control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(control.time, "sleep", lambda _s: None)
    monkeypatch.setattr(control, "ONEBOT_PORT", 3001)
    monkeypatch.setattr(control, "NAPCAT_PORT", 6099)

    control.start_services()
    joined = " ".join(" ".join(part) if isinstance(part, (list, tuple)) else str(part) for part in started)
    assert "napcat.bat" in joined
    assert "qq_onebot_whitelist.onebot" in joined


def test_stop_kills_pid_files(tmp_path, monkeypatch):
    killed = []

    def fake_run(cmd, **kwargs):
        killed.append(cmd)
        return None

    monkeypatch.setattr(control, "RUN_DIR", tmp_path)
    (tmp_path / "napcat.pid").write_text("111\n", encoding="ascii")
    (tmp_path / "bot.pid").write_text("222\n", encoding="ascii")
    monkeypatch.setattr(control.subprocess, "run", fake_run)

    control.stop_services()
    assert any("111" in " ".join(c) for c in killed)
    assert any("222" in " ".join(c) for c in killed)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -k "start_uses or stop_kills" -v`
Expected: FAIL，`AttributeError: module ... has no attribute 'start_services'`

- [ ] **Step 3: 实现 start/stop/restart**

在 `control.py` 中添加：

```python
import subprocess
import time


def start_services() -> None:
    """启动 NapCat 与机器人（迁移自 start-qq-onebot-whitelist-hidden.ps1 的核心逻辑）。"""
    napcat_dir = REPO_ROOT / "runtime" / "NapCat.Shell.Windows.Node"
    napcat_bat = napcat_dir / "napcat.bat"
    if not napcat_bat.exists():
        raise RuntimeError(f"NapCat launcher not found: {napcat_bat}")
    config = REPO_ROOT / "config.yaml"
    if not config.exists():
        raise RuntimeError(f"Bot config not found: {config}")

    if not port_open(NAPCAT_PORT):
        pid = subprocess.Popen(
            ["cmd.exe", "/d", "/s", "/c", f'call "{napcat_bat}"'],
            cwd=str(napcat_dir),
            stdout=open(REPO_ROOT / "logs" / "napcat.log", "a", encoding="utf-8", errors="replace"),
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).pid
        (RUN_DIR / "napcat.pid").write_text(str(pid), encoding="ascii")

    deadline = time.time() + 300
    while time.time() < deadline:
        if port_open(ONEBOT_PORT):
            break
        time.sleep(3)

    if not port_open(ONEBOT_PORT):
        print("OneBot WS port not ready; NapCat WebUI: http://127.0.0.1:6099")
        return

    if not port_open(ONEBOT_PORT) or True:  # bot 自身不监听端口，直接尝试启动（幂等检查见下）
        bot_pid = subprocess.Popen(
            ["uv", "run", "python", "-m", "qq_onebot_whitelist.onebot", "--config", str(config)],
            cwd=str(REPO_ROOT),
            stdout=open(REPO_ROOT / "logs" / "bot.log", "a", encoding="utf-8", errors="replace"),
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).pid
        (RUN_DIR / "bot.pid").write_text(str(pid := bot_pid), encoding="ascii")


def stop_services() -> None:
    for name in ("napcat.pid", "bot.pid"):
        pid_path = RUN_DIR / name
        if not pid_path.exists():
            continue
        pid = pid_path.read_text(encoding="ascii").strip()
        if pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        pid_path.unlink(missing_ok=True)


def cmd_start(args: argparse.Namespace) -> int:
    try:
        start_services()
        return 0
    except Exception as exc:
        print(f"start failed: {type(exc).__name__}: {exc}")
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    try:
        stop_services()
        return 0
    except Exception as exc:
        print(f"stop failed: {type(exc).__name__}: {exc}")
        return 1


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    return cmd_start(args)
```

在 `build_parser()` 中注册子命令并接入 handlers：

```python
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("restart")
```

```python
    handlers = {"status": cmd_status, "start": cmd_start, "stop": cmd_stop, "restart": cmd_restart}
```

> 说明：start 中的 bot 幂等检查简化为"直接启动"；后续 Task 4 的 stats 与面板自动重启依赖端口检测，保持行为一致。若需要精确幂等，可对照原脚本补 `Test-OwnedProcessByPidFile` 等价逻辑（读 bot.pid + 验证进程存在）。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -k "start_uses or stop_kills" -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/control.py tests/test_control.py
git commit -m "feat: add start/stop/restart to control bridge"
```

---

### Task 4: control.py stats 命令

**Files:**
- Modify: `qq_onebot_whitelist/control.py`
- Test: `tests/test_control.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_control.py`：

```python
def test_stats_counts(tmp_path, monkeypatch):
    class FakeStore:
        def recent_files(self, **kw):
            return [{"file_name": "a.zip"}, {"file_name": "b.zip"}]

        def recent_link_records(self, **kw):
            return [{"url": "https://x"}, {"url": "https://y"}]

        def last_daily_report_sent_at(self):
            return None

    monkeypatch.setattr(control, "build_stats", lambda store: {
        "images": 12, "links": 2, "lastReport": None,
    })
    out = control.build_stats(FakeStore())
    assert out["links"] == 2


def test_cmd_stats_prints_json(capsys, monkeypatch):
    monkeypatch.setattr(control, "load_stats", lambda: {"images": 1, "links": 2, "lastReport": None})
    assert control.cmd_stats(None) == 0
    import json as _json
    assert "images" in capsys.readouterr().out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -k "stats" -v`
Expected: FAIL

- [ ] **Step 3: 实现 stats**

在 `control.py` 中添加：

```python
def build_stats(store) -> dict:
    try:
        from .maintenance import sync_image_files
        counts = sync_image_files(REPO_ROOT)
        images = sum(counts.values())
    except Exception as exc:
        print(f"stats image count failed: {type(exc).__name__}: {exc}")
        images = 0
    try:
        links = len(store.recent_link_records(limit=100000))
    except Exception:
        links = 0
    try:
        last_report = store.last_daily_report_sent_at()
        last_report = last_report.isoformat(timespec="seconds") if last_report else None
    except Exception:
        last_report = None
    return {"images": images, "links": links, "lastReport": last_report}


def load_stats() -> dict:
    from .config import load_config
    from .store import Store
    config = load_config(REPO_ROOT / "config.yaml")
    store = Store(config.data_dir / "bot.db")
    return build_stats(store)


def cmd_stats(args: argparse.Namespace) -> int:
    try:
        print(json.dumps(load_stats(), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"stats failed: {type(exc).__name__}: {exc}")
        return 1
```

注册子命令：`sub.add_parser("stats")`；handlers 加 `"stats": cmd_stats`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -k "stats" -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/control.py tests/test_control.py
git commit -m "feat: add stats command to control bridge"
```

---

### Task 5: control.py report-preview / report-send

**Files:**
- Modify: `qq_onebot_whitelist/control.py`
- Test: `tests/test_control.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_control.py`：

```python
def test_report_preview_returns_text(monkeypatch):
    def fake_build(store, **kw):
        return "日报内容"
    monkeypatch.setattr(control, "build_report_preview", fake_build)
    assert control.build_report_preview(None) == "日报内容"


def test_cmd_report_preview_prints_json(capsys, monkeypatch):
    monkeypatch.setattr(control, "load_report_preview", lambda: ("内容", 2))
    assert control.cmd_report_preview(None) == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out and "内容" in out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -k "report" -v`
Expected: FAIL

- [ ] **Step 3: 实现 report-preview / report-send**

在 `control.py` 中添加：

```python
def build_report_preview(store, config=None) -> str:
    from .config import load_config
    from .daily_report import build_daily_resource_report
    config = config or load_config(REPO_ROOT / "config.yaml")
    content = build_daily_resource_report(
        store,
        since=store.last_daily_report_sent_at(),
        enrich_links=config.daily_report_enrich_links and config.feature_link_metadata,
        analyze_links=config.feature_link_analysis,
        max_links=config.daily_report_max_links,
        max_enriched_links=config.daily_report_max_enriched_links,
        language=config.language,
    )
    return content or "（暂无日报内容）"


def load_report_preview() -> tuple[str, int]:
    from .config import load_config
    from .store import Store
    config = load_config(REPO_ROOT / "config.yaml")
    store = Store(config.data_dir / "bot.db")
    content = build_report_preview(store, config)
    return content, len(content)


def cmd_report_preview(args: argparse.Namespace) -> int:
    try:
        content, chars = load_report_preview()
        print(json.dumps({"ok": True, "content": content, "chars": chars}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


async def _send_report_once() -> int:
    import websockets
    from .config import load_config
    from .daily_report import build_daily_resource_report, split_message
    from .store import Store
    config = load_config(REPO_ROOT / "config.yaml")
    store = Store(config.data_dir / "bot.db")
    content = build_daily_resource_report(
        store,
        since=store.last_daily_report_sent_at(),
        enrich_links=config.daily_report_enrich_links and config.feature_link_metadata,
        analyze_links=config.feature_link_analysis,
        max_links=config.daily_report_max_links,
        max_enriched_links=config.daily_report_max_enriched_links,
        language=config.language,
    )
    if not content:
        print(json.dumps({"ok": False, "error": "empty report"}, ensure_ascii=False))
        return 1
    async with websockets.connect(config.onebot_ws_url) as ws:
        for chunk in split_message(content, max_chars=1800):
            for user_id in sorted(config.bot.whitelist_users):
                await ws.send(json.dumps(
                    {"action": "send_private_msg",
                     "params": {"user_id": int(user_id), "message": chunk}},
                    ensure_ascii=False,
                ))
    print(json.dumps({"ok": True, "chars": len(content)}, ensure_ascii=False))
    return 0


def cmd_report_send(args: argparse.Namespace) -> int:
    import asyncio
    return asyncio.run(_send_report_once())
```

注册子命令：`sub.add_parser("report-preview")`、`sub.add_parser("report-send")`；handlers 加对应两项。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control.py -k "report" -v`
Expected: 2 passed

- [ ] **Step 5: 运行全量 Python 测试**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add qq_onebot_whitelist/control.py tests/test_control.py
git commit -m "feat: add report preview/send to control bridge"
```

---

## Phase B：Qt 工程骨架

### Task 6: CMake 工程、空窗口、单实例

**Files:**
- Create: `qq-onebot-manager-qt/CMakeLists.txt`
- Create: `qq-onebot-manager-qt/src/main.cpp`
- Create: `qq-onebot-manager-qt/src/app/SingleInstance.h`, `SingleInstance.cpp`
- Create: `qq-onebot-manager-qt/resources/resources.qrc`, `resources/icons/app.svg`

- [ ] **Step 1: 创建 CMakeLists.txt**

```cmake
cmake_minimum_required(VERSION 3.24)
project(qq_onebot_manager_qt VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 REQUIRED COMPONENTS Widgets Network Svg Test)

add_executable(qq-onebot-manager-qt WIN32
    src/main.cpp
    src/app/SingleInstance.cpp
    resources/resources.qrc
)
target_link_libraries(qq-onebot-manager-qt PRIVATE Qt6::Widgets Qt6::Network Qt6::Svg)

enable_testing()
add_subdirectory(tests)
```

- [ ] **Step 2: 创建 resources.qrc 与图标**

`resources/resources.qrc`：

```xml
<RCC>
    <qresource prefix="/">
        <file>icons/app.svg</file>
    </qresource>
</RCC>
```

`resources/icons/app.svg`（简单机器人圆点图标）：

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#2563eb"/>
  <circle cx="22" cy="28" r="7" fill="#fff"/>
  <circle cx="42" cy="28" r="7" fill="#fff"/>
  <rect x="20" y="40" width="24" height="6" rx="3" fill="#fff"/>
</svg>
```

- [ ] **Step 3: 创建单实例类**

`src/app/SingleInstance.h`：

```cpp
#pragma once
#include <QObject>
#include <QLocalServer>

class SingleInstance : public QObject {
    Q_OBJECT
public:
    explicit SingleInstance(const QString &name, QObject *parent = nullptr);
    bool tryLock(); // false = 已有实例在运行
signals:
    void anotherInstanceRequested();
private:
    QLocalServer m_server;
    QString m_name;
};
```

`src/app/SingleInstance.cpp`：

```cpp
#include "SingleInstance.h"
#include <QLocalSocket>

SingleInstance::SingleInstance(const QString &name, QObject *parent)
    : QObject(parent), m_name(name) {
    QObject::connect(&m_server, &QLocalServer::newConnection, this, &SingleInstance::anotherInstanceRequested);
}

bool SingleInstance::tryLock() {
    QLocalSocket probe;
    probe.connectToServer(m_name);
    if (probe.waitForConnected(200)) {
        probe.disconnectFromServer();
        return false;
    }
    QLocalServer::removeServer(m_name);
    return m_server.listen(m_name);
}
```

- [ ] **Step 4: 创建 main.cpp（空窗口 + 单实例）**

```cpp
#include <QApplication>
#include <QMessageBox>
#include "app/SingleInstance.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    app.setApplicationName("QQ OneBot 管理器");
    app.setWindowIcon(QIcon(":/icons/app.svg"));

    SingleInstance single("qq-onebot-manager-qt");
    if (!single.tryLock()) {
        QMessageBox::information(nullptr, "QQ OneBot 管理器", "管理器已在运行。");
        return 0;
    }

    QWidget window;
    window.setWindowTitle("QQ OneBot 管理器");
    window.resize(960, 640);
    window.show();
    return app.exec();
}
```

（`QIcon` 需要 `#include <QIcon>`；Task 7 引入 MainWindow 后此文件会再修改。）

- [ ] **Step 5: 创建 tests/CMakeLists.txt（空占位，后续任务填充）**

```cmake
# 后续任务加入 Qt Test 目标
```

- [ ] **Step 6: 配置并构建**

Run（在仓库根目录）：

```powershell
& "C:\Qt\Tools\CMake_64\bin\cmake.exe" -S qq-onebot-manager-qt -B qq-onebot-manager-qt/build -G "MinGW Makefiles" -DCMAKE_PREFIX_PATH="C:\Qt\6.11.1\mingw_64" -DCMAKE_CXX_COMPILER="C:\Qt\Tools\mingw1310_64\bin\g++.exe"
& "C:\Qt\Tools\CMake_64\bin\cmake.exe" --build qq-onebot-manager-qt/build
```

Expected: 构建成功，生成 `qq-onebot-manager-qt/build/qq-onebot-manager-qt.exe`

- [ ] **Step 7: 运行验证**

Run: `qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe`
Expected: 出现 960x640 窗口；再次运行第二个实例弹"已在运行"提示。

- [ ] **Step 8: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: scaffold qt panel with single instance"
```

---

### Task 7: 主题引擎与语言

**Files:**
- Create: `src/ui/theme/ThemeManager.h/.cpp`
- Create: `src/ui/Strings.h`
- Create: `resources/themes/light.qss`, `resources/themes/dark.qss`
- Modify: `resources/resources.qrc`, `src/main.cpp`

- [ ] **Step 1: 创建 QSS 主题文件**

`resources/themes/light.qss`：

```css
QMainWindow, QWidget#content { background: #f5f7fb; }
QListWidget#nav { background: #172033; border: none; outline: 0; }
QListWidget#nav::item { color: #aab5c9; padding: 10px 16px; }
QListWidget#nav::item:selected { background: #2d3b5a; color: #ffffff; border-radius: 6px; }
QFrame#card { background: #ffffff; border: 1px solid #e4e9f1; border-radius: 10px; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; color: #172033; }
QLabel#muted { color: #7a879c; }
QPushButton { padding: 6px 14px; border-radius: 6px; border: 1px solid #cfd6e2; background: #ffffff; }
QPushButton:hover { background: #eef2f8; }
QPushButton:disabled { color: #aab2c0; }
QPushButton#primary { background: #2563eb; color: white; border: none; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#danger { background: #b53b49; color: white; border: none; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { border: 1px solid #cfd6e2; border-radius: 6px; padding: 4px 8px; background: #ffffff; }
QLineEdit.invalid { border: 1px solid #d64550; background: #fff4f4; }
```

`resources/themes/dark.qss`：

```css
QMainWindow, QWidget#content { background: #101216; }
QListWidget#nav { background: #0b0d12; border: none; outline: 0; }
QListWidget#nav::item { color: #98a2b3; padding: 10px 16px; }
QListWidget#nav::item:selected { background: #1f2937; color: #ffffff; border-radius: 6px; }
QFrame#card { background: #171a21; border: 1px solid #2b313d; border-radius: 10px; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; color: #eef1f6; }
QLabel#muted { color: #929cab; }
QPushButton { padding: 6px 14px; border-radius: 6px; border: 1px solid #343a46; background: #1b1f27; color: #eef1f6; }
QPushButton:hover { background: #242a35; }
QPushButton:disabled { color: #6b7280; }
QPushButton#primary { background: #2563eb; color: white; border: none; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#danger { background: #b53b49; color: white; border: none; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { border: 1px solid #343a46; border-radius: 6px; padding: 4px 8px; background: #171a21; color: #eef1f6; }
QLineEdit.invalid { border: 1px solid #d64550; background: #2a1518; }
```

- [ ] **Step 2: 创建 ThemeManager**

`src/ui/theme/ThemeManager.h`：

```cpp
#pragma once
#include <QString>

class QApplication;

class ThemeManager {
public:
    enum class Theme { Light, Dark };
    static void apply(QApplication *app, Theme theme);
    static Theme current();
    static void setCurrent(Theme theme);
    static QString themeName(Theme theme);
};
```

`src/ui/theme/ThemeManager.cpp`：

```cpp
#include "ThemeManager.h"
#include <QApplication>
#include <QFile>

ThemeManager::Theme ThemeManager::s_current = ThemeManager::Theme::Light;

void ThemeManager::apply(QApplication *app, Theme theme) {
    s_current = theme;
    const QString path = theme == Theme::Dark ? ":/themes/dark.qss" : ":/themes/light.qss";
    QFile file(path);
    if (file.open(QIODevice::ReadOnly | QIODevice::Text))
        app->setStyleSheet(QString::fromUtf8(file.readAll()));
}

ThemeManager::Theme ThemeManager::current() { return s_current; }
void ThemeManager::setCurrent(Theme theme) { s_current = theme; }
QString ThemeManager::themeName(Theme theme) { return theme == Theme::Dark ? "dark" : "light"; }
```

- [ ] **Step 3: 创建语言表 Strings.h**

```cpp
#pragma once
#include <QString>

class Strings {
public:
    static QString get(const QString &key, const QString &lang);
    static QString zh(const QString &key);
    static QString en(const QString &key);
};
```

`src/ui/Strings.cpp`：

```cpp
#include "Strings.h"

QString Strings::get(const QString &key, const QString &lang) {
    return lang == "en-US" ? en(key) : zh(key);
}

QString Strings::zh(const QString &key) {
    if (key == "overview") return "概览";
    if (key == "settings") return "设置";
    if (key == "logs") return "日志";
    if (key == "reports") return "报告";
    if (key == "start") return "启动";
    if (key == "stop") return "停止";
    if (key == "restart") return "重启";
    if (key == "refresh") return "刷新";
    if (key == "openLogs") return "打开日志";
    if (key == "openReports") return "打开报告";
    if (key == "openConfig") return "打开配置目录";
    if (key == "importHistory") return "立即读取历史";
    if (key == "service") return "服务状态";
    if (key == "manualStop") return "已手动停止，自动重启已暂停";
    if (key == "autoRestartOn") return "自动重启：已开启";
    if (key == "autoRestartOff") return "自动重启：已关闭";
    if (key == "save") return "保存";
    if (key == "saved") return "已保存";
    if (key == "error") return "出错";
    if (key == "search") return "搜索";
    if (key == "pause") return "暂停";
    if (key == "autoScroll") return "自动滚动";
    if (key == "onlyErrors") return "只看错误";
    if (key == "language") return "语言";
    if (key == "theme") return "主题";
    if (key == "autoStart") return "开机自启";
    if (key == "notifications") return "登录提醒";
    if (key == "quit") return "退出管理器";
    if (key == "qqLogin") return "QQ 已登录";
    if (key == "qqLogout") return "QQ 已掉线";
    return key;
}

QString Strings::en(const QString &key) {
    if (key == "overview") return "Overview";
    if (key == "settings") return "Settings";
    if (key == "logs") return "Logs";
    if (key == "reports") return "Reports";
    if (key == "start") return "Start";
    if (key == "stop") return "Stop";
    if (key == "restart") return "Restart";
    if (key == "refresh") return "Refresh";
    if (key == "openLogs") return "Open logs";
    if (key == "openReports") return "Open reports";
    if (key == "openConfig") return "Open config folder";
    if (key == "importHistory") return "Import history now";
    if (key == "service") return "Service status";
    if (key == "manualStop") return "Manually stopped; auto-restart paused";
    if (key == "autoRestartOn") return "Auto-restart: on";
    if (key == "autoRestartOff") return "Auto-restart: off";
    if (key == "save") return "Save";
    if (key == "saved") return "Saved";
    if (key == "error") return "Error";
    if (key == "search") return "Search";
    if (key == "pause") return "Pause";
    if (key == "autoScroll") return "Auto-scroll";
    if (key == "onlyErrors") return "Errors only";
    if (key == "language") return "Language";
    if (key == "theme") return "Theme";
    if (key == "autoStart") return "Start with Windows";
    if (key == "notifications") return "Login notifications";
    if (key == "quit") return "Quit manager";
    if (key == "qqLogin") return "QQ logged in";
    if (key == "qqLogout") return "QQ disconnected";
    return key;
}
```

- [ ] **Step 4: 更新 resources.qrc 与 main.cpp**

`resources/resources.qrc` 增加：

```xml
        <file>themes/light.qss</file>
        <file>themes/dark.qss</file>
```

`src/main.cpp` 中 `window.show();` 前增加：

```cpp
    ThemeManager::apply(&app, ThemeManager::Theme::Light);
```

并在文件顶部包含 `"ui/theme/ThemeManager.h"`。

- [ ] **Step 5: 构建验证**

Run: `& "C:\Qt\Tools\CMake_64\bin\cmake.exe" --build qq-onebot-manager-qt/build`
Expected: 构建成功；运行后窗口背景为浅色 #f5f7fb。

- [ ] **Step 6: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add theme engine and strings table"
```

---

### Task 8: 页面注册与导航

**Files:**
- Create: `src/ui/MainWindow.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 创建 MainWindow（侧边导航 + 堆叠页面）**

`src/ui/MainWindow.h`：

```cpp
#pragma once
#include <QMainWindow>
#include <QVector>

class QListWidget;
class QStackedWidget;
class QWidget;

struct PageDef {
    QString id;
    QString titleKey;
    QWidget *(*factory)(QWidget *parent);
};

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(const QVector<PageDef> &pages, QWidget *parent = nullptr);
    void setLanguage(const QString &lang);
    QWidget *pageWidget(const QString &id) const;
private:
    QListWidget *m_nav = nullptr;
    QStackedWidget *m_stack = nullptr;
    QVector<PageDef> m_pages;
    QString m_lang = "zh-CN";
};
```

`src/ui/MainWindow.cpp`：

```cpp
#include "MainWindow.h"
#include "Strings.h"
#include <QListWidget>
#include <QStackedWidget>
#include <QHBoxLayout>
#include <QFrame>

MainWindow::MainWindow(const QVector<PageDef> &pages, QWidget *parent)
    : QMainWindow(parent), m_pages(pages) {
    m_nav = new QListWidget(this);
    m_nav->setObjectName("nav");
    m_nav->setFixedWidth(180);
    m_stack = new QStackedWidget(this);

    for (const PageDef &page : m_pages) {
        m_nav->addItem(Strings::zh(page.titleKey));
        m_stack->addWidget(page.factory(this));
    }
    m_nav->setCurrentRow(0);
    connect(m_nav, &QListWidget::currentRowChanged, m_stack, &QStackedWidget::setCurrentIndex);

    auto *content = new QFrame(this);
    content->setObjectName("content");
    auto *layout = new QHBoxLayout(content);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    layout->addWidget(m_nav);
    layout->addWidget(m_stack, 1);
    setCentralWidget(content);
    resize(960, 640);
}

void MainWindow::setLanguage(const QString &lang) {
    m_lang = lang;
    for (int i = 0; i < m_pages.size(); ++i)
        m_nav->item(i)->setText(Strings::get(m_pages[i].titleKey, lang));
}

QWidget *MainWindow::pageWidget(const QString &id) const {
    for (int i = 0; i < m_pages.size(); ++i)
        if (m_pages[i].id == id) return m_stack->widget(i);
    return nullptr;
}
```

- [ ] **Step 2: 修改 main.cpp 使用 MainWindow 与四个占位页**

```cpp
#include <QLabel>
#include "ui/MainWindow.h"
#include "ui/Strings.h"

static QWidget *makePlaceholder(const char *key, QWidget *parent) {
    auto *label = new QLabel(Strings::zh(QString::fromLatin1(key)), parent);
    label->setAlignment(Qt::AlignCenter);
    return label;
}

static QWidget *makeOverview(QWidget *parent) { return makePlaceholder("overview", parent); }
static QWidget *makeSettings(QWidget *parent) { return makePlaceholder("settings", parent); }
static QWidget *makeLogs(QWidget *parent) { return makePlaceholder("logs", parent); }
static QWidget *makeReports(QWidget *parent) { return makePlaceholder("reports", parent); }

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    ...
    const QVector<PageDef> pages = {
        {"overview", "overview", makeOverview},
        {"settings", "settings", makeSettings},
        {"logs", "logs", makeLogs},
        {"reports", "reports", makeReports},
    };
    MainWindow window(pages);
    window.show();
    return app.exec();
}
```

- [ ] **Step 3: 构建并运行验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe。
Expected: 左侧导航四项（概览/设置/日志/报告），点击切换页面。

- [ ] **Step 4: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add main window navigation with page registry"
```

---

## Phase C：桥接层

### Task 9: StatusMonitor（状态读取与解析）

**Files:**
- Create: `src/core/Paths.h`, `src/core/StatusMonitor.h/.cpp`
- Test: `tests/tst_statusmonitor.cpp`

- [ ] **Step 1: 写失败测试**

`tests/CMakeLists.txt`：

```cmake
find_package(Qt6 REQUIRED COMPONENTS Test)
add_executable(tst_statusmonitor
    tst_statusmonitor.cpp
    ../src/core/StatusMonitor.cpp
)
target_include_directories(tst_statusmonitor PRIVATE ../src)
target_link_libraries(tst_statusmonitor PRIVATE Qt6::Test Qt6::Core)
add_test(NAME tst_statusmonitor COMMAND tst_statusmonitor)
```

`tests/tst_statusmonitor.cpp`：

```cpp
#include <QtTest>
#include "core/StatusMonitor.h"

class TestStatusMonitor : public QObject {
    Q_OBJECT
private slots:
    void parsesValidJson();
    void missingFileIsInvalid();
    void staleFileIsInvalid();
};

void TestStatusMonitor::parsesValidJson() {
    const QDateTime now = QDateTime::currentDateTime();
    const QByteArray json =
        R"({"napcat":true,"onebot":true,"bot":true,"qqLoggedIn":true,"qqNumber":"123","qqNickname":"\u67f3\u6811\u53f6","updatedAt":")"
        + now.addSecs(-5).toUTC().toString(Qt::ISODate).toUtf8() + R"("})";
    const StatusSnapshot s = parseStatusJson(json, now);
    QVERIFY(s.valid);
    QVERIFY(s.napcat);
    QVERIFY(s.onebot);
    QVERIFY(s.bot);
    QVERIFY(s.qqLoggedIn);
    QCOMPARE(s.qqNumber, "123");
    QCOMPARE(s.qqNickname, QString::fromUtf8("柳树叶"));
}

void TestStatusMonitor::missingFileIsInvalid() {
    QVERIFY(!parseStatusJson(QByteArray(), QDateTime::currentDateTime()).valid);
}

void TestStatusMonitor::staleFileIsInvalid() {
    const QDateTime now = QDateTime::currentDateTime();
    const QByteArray json =
        R"({"napcat":true,"updatedAt":")"
        + now.addSecs(-60).toUTC().toString(Qt::ISODate).toUtf8() + R"("})";
    QVERIFY(!parseStatusJson(json, now).valid);
}

QTEST_APPLESS_MAIN(TestStatusMonitor)
#include "tst_statusmonitor.moc"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cmake --build qq-onebot-manager-qt/build && & qq-onebot-manager-qt\build\tests\tst_statusmonitor.exe`
Expected: 编译失败（无 StatusMonitor.h）

- [ ] **Step 3: 实现 Paths.h 与 StatusMonitor**

`src/core/Paths.h`：

```cpp
#pragma once
#include <QString>
#include <QDir>

class Paths {
public:
    static QString repoRoot() {
        QDir dir(QCoreApplication::applicationDirPath());
        while (!dir.exists("config.yaml")) {
            if (!dir.cdUp()) break;
        }
        return dir.absolutePath();
    }
    static QString statusFile() { return repoRoot() + "/run/status.json"; }
    static QString pythonExe() {
        const QString candidate = repoRoot() + "/.venv/Scripts/python.exe";
        return QFileInfo::exists(candidate) ? candidate : "python";
    }
};
```

（`#include <QCoreApplication>` 与 `#include <QFileInfo>` 需补上。）

`src/core/StatusMonitor.h`：

```cpp
#pragma once
#include <QObject>
#include <QJsonObject>
#include <QDateTime>
#include <QTimer>

struct StatusSnapshot {
    bool valid = false;
    bool napcat = false;
    bool onebot = false;
    bool bot = false;
    bool qqLoggedIn = false;
    QString qqNumber;
    QString qqNickname;
    QDateTime updatedAt;
};

StatusSnapshot parseStatusJson(const QByteArray &json, const QDateTime &now, int staleSeconds = 15);

class StatusMonitor : public QObject {
    Q_OBJECT
public:
    explicit StatusMonitor(const QString &statusPath, int pollMs = 4000, QObject *parent = nullptr);
    StatusSnapshot snapshot() const { return m_snapshot; }
public slots:
    void refresh();
signals:
    void statusChanged(const StatusSnapshot &snapshot);
private:
    QString m_statusPath;
    QTimer m_timer;
    StatusSnapshot m_snapshot;
};
```

`src/core/StatusMonitor.cpp`：

```cpp
#include "StatusMonitor.h"
#include <QFile>

StatusSnapshot parseStatusJson(const QByteArray &json, const QDateTime &now, int staleSeconds) {
    StatusSnapshot s;
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(json, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) return s;
    const QJsonObject obj = doc.object();
    s.updatedAt = QDateTime::fromString(obj.value("updatedAt").toString(), Qt::ISODate);
    if (!s.updatedAt.isValid()) return s;
    if (s.updatedAt.secsTo(now) > staleSeconds) return s;
    s.napcat = obj.value("napcat").toBool(false);
    s.onebot = obj.value("onebot").toBool(false);
    s.bot = obj.value("bot").toBool(false);
    s.qqLoggedIn = obj.value("qqLoggedIn").toBool(false);
    s.qqNumber = obj.value("qqNumber").toString();
    s.qqNickname = obj.value("qqNickname").toString();
    s.valid = true;
    return s;
}

StatusMonitor::StatusMonitor(const QString &statusPath, int pollMs, QObject *parent)
    : QObject(parent), m_statusPath(statusPath) {
    m_timer.setInterval(pollMs);
    connect(&m_timer, &QTimer::timeout, this, &StatusMonitor::refresh);
    m_timer.start();
}

void StatusMonitor::refresh() {
    QFile file(m_statusPath);
    const QByteArray data = file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray();
    const StatusSnapshot next = parseStatusJson(data, QDateTime::currentDateTime());
    if (next.valid != m_snapshot.valid || next.qqLoggedIn != m_snapshot.qqLoggedIn ||
        next.napcat != m_snapshot.napcat || next.onebot != m_snapshot.onebot ||
        next.bot != m_snapshot.bot || next.qqNumber != m_snapshot.qqNumber ||
        next.qqNickname != m_snapshot.qqNickname) {
        m_snapshot = next;
        emit statusChanged(m_snapshot);
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cmake --build qq-onebot-manager-qt/build && & qq-onebot-manager-qt\build\tests\tst_statusmonitor.exe`
Expected: 3 个用例全部通过

- [ ] **Step 5: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add status monitor with parsing tests"
```

---

### Task 10: ServiceControl（子进程控制）

**Files:**
- Create: `src/core/ServiceControl.h/.cpp`

- [ ] **Step 1: 实现 ServiceControl**

`src/core/ServiceControl.h`：

```cpp
#pragma once
#include <QObject>
#include <QProcess>

class ServiceControl : public QObject {
    Q_OBJECT
public:
    explicit ServiceControl(QObject *parent = nullptr);
    void run(const QStringList &args); // 如 {"-m","qq_onebot_whitelist.control","start"}
signals:
    void finished(bool ok, QString output);
private:
    QProcess m_proc;
};
```

`src/core/ServiceControl.cpp`：

```cpp
#include "ServiceControl.h"
#include "Paths.h"

ServiceControl::ServiceControl(QObject *parent) : QObject(parent) {
    connect(&m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        emit finished(code == 0, QString::fromUtf8(m_proc.readAllStandardOutput()));
    });
}

void ServiceControl::run(const QStringList &args) {
    if (m_proc.state() != QProcess::NotRunning) return;
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    m_proc.start();
}
```

- [ ] **Step 2: 构建验证**

Run: `cmake --build qq-onebot-manager-qt/build`
Expected: 编译通过

- [ ] **Step 3: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add async service control bridge"
```

---

### Task 11: ConfigBridge

**Files:**
- Create: `src/core/ConfigBridge.h/.cpp`

- [ ] **Step 1: 实现 ConfigBridge**

`src/core/ConfigBridge.h`：

```cpp
#pragma once
#include <QObject>
#include <QProcess>
#include <QVariant>

class ConfigBridge : public QObject {
    Q_OBJECT
public:
    explicit ConfigBridge(QObject *parent = nullptr);
    void fetch();   // config_bridge get
    void save(const QJsonObject &patch); // config_bridge patch <json>
signals:
    void schemaLoaded(bool ok, QVariant schema);
    void saved(bool ok, QString message);
private:
    void runArgs(const QStringList &args);
    QProcess m_proc;
};
```

`src/core/ConfigBridge.cpp`：

```cpp
#include "ConfigBridge.h"
#include "Paths.h"
#include <QJsonDocument>

ConfigBridge::ConfigBridge(QObject *parent) : QObject(parent) {
    connect(&m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        const QString output = QString::fromUtf8(m_proc.readAllStandardOutput());
        if (m_mode == Fetch) {
            QJsonParseError err;
            const QJsonDocument doc = QJsonDocument::fromJson(output.toUtf8(), &err);
            emit schemaLoaded(code == 0 && err.error == QJsonParseError::NoError, doc.toVariant());
        } else {
            emit saved(code == 0, output.trimmed());
        }
    });
}

void ConfigBridge::fetch() {
    m_mode = Fetch;
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "get", "--config",
             Paths::repoRoot() + "/config.yaml"});
}

void ConfigBridge::save(const QJsonObject &patch) {
    m_mode = Save;
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "patch", "--config",
             Paths::repoRoot() + "/config.yaml",
             QString::fromUtf8(QJsonDocument(patch).toJson(QJsonDocument::Compact))});
}

void ConfigBridge::runArgs(const QStringList &args) {
    if (m_proc.state() != QProcess::NotRunning) return;
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    m_proc.start();
}
```

（`ConfigBridge.h` 需 `#include <QJsonObject>`；`m_mode` 在头文件中声明为 `enum Mode { Fetch, Save }; Mode m_mode = Fetch;`）

- [ ] **Step 2: 构建验证**

Run: `cmake --build qq-onebot-manager-qt/build`
Expected: 编译通过

- [ ] **Step 3: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add config bridge"
```

---

## Phase D：页面

### Task 12: 概览页

**Files:**
- Create: `src/ui/widgets/StatusCard.h/.cpp`
- Create: `src/ui/pages/OverviewPage.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 创建 StatusCard**

`src/ui/widgets/StatusCard.h`：

```cpp
#pragma once
#include <QFrame>

class QLabel;

class StatusCard : public QFrame {
    Q_OBJECT
public:
    explicit StatusCard(const QString &title, QWidget *parent = nullptr);
    void setValue(const QString &value, bool ok);
private:
    QLabel *m_value = nullptr;
};
```

`src/ui/widgets/StatusCard.cpp`：

```cpp
#include "StatusCard.h"
#include <QLabel>
#include <QVBoxLayout>

StatusCard::StatusCard(const QString &title, QWidget *parent) : QFrame(parent) {
    setObjectName("card");
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(14, 12, 14, 12);
    auto *titleLabel = new QLabel(title, this);
    titleLabel->setObjectName("muted");
    m_value = new QLabel("—", this);
    m_value->setStyleSheet("font-size:16px;font-weight:600;");
    layout->addWidget(titleLabel);
    layout->addWidget(m_value);
}

void StatusCard::setValue(const QString &value, bool ok) {
    m_value->setText(value);
    m_value->setStyleSheet(ok
        ? "font-size:16px;font-weight:600;color:#2d825d;"
        : "font-size:16px;font-weight:600;color:#b53b49;");
}
```

- [ ] **Step 2: 创建 OverviewPage**

`src/ui/pages/OverviewPage.h`：

```cpp
#pragma once
#include <QWidget>
#include "core/StatusMonitor.h"

class StatusCard;
class QPushButton;
class QLabel;

class OverviewPage : public QWidget {
    Q_OBJECT
public:
    explicit OverviewPage(QWidget *parent = nullptr);
    void setStatus(const StatusSnapshot &s);
signals:
    void actionRequested(const QString &action); // start/stop/restart/refresh/logs/reports/config/history
private:
    StatusCard *m_napcat = nullptr;
    StatusCard *m_onebot = nullptr;
    StatusCard *m_bot = nullptr;
    StatusCard *m_qq = nullptr;
    QLabel *m_hint = nullptr;
    QLabel *m_autoRestart = nullptr;
    QLabel *m_stats = nullptr;
    QPushButton *m_start = nullptr;
    QPushButton *m_stop = nullptr;
};
```

`src/ui/pages/OverviewPage.cpp`：

```cpp
#include "OverviewPage.h"
#include "StatusCard.h"
#include "../Strings.h"
#include <QGridLayout>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QFrame>

OverviewPage::OverviewPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 24, 24, 24);
    layout->setSpacing(16);

    auto *cards = new QGridLayout;
    cards->setSpacing(12);
    m_napcat = new StatusCard("NapCat", this);
    m_onebot = new StatusCard("OneBot", this);
    m_bot = new StatusCard("Bot", this);
    m_qq = new StatusCard("QQ", this);
    cards->addWidget(m_napcat, 0, 0);
    cards->addWidget(m_onebot, 0, 1);
    cards->addWidget(m_bot, 1, 0);
    cards->addWidget(m_qq, 1, 1);
    layout->addLayout(cards);

    m_hint = new QLabel(this);
    m_hint->setObjectName("muted");
    m_hint->setWordWrap(true);
    layout->addWidget(m_hint);

    m_autoRestart = new QLabel(this);
    m_autoRestart->setObjectName("muted");
    layout->addWidget(m_autoRestart);

    m_stats = new QLabel(this);
    m_stats->setObjectName("muted");
    layout->addWidget(m_stats);

    auto *buttons = new QHBoxLayout;
    buttons->setSpacing(10);
    m_start = new QPushButton(Strings::zh("start"), this);
    m_start->setObjectName("primary");
    m_stop = new QPushButton(Strings::zh("stop"), this);
    m_stop->setObjectName("danger");
    auto *restart = new QPushButton(Strings::zh("restart"), this);
    auto *refresh = new QPushButton(Strings::zh("refresh"), this);
    auto *logs = new QPushButton(Strings::zh("openLogs"), this);
    auto *reports = new QPushButton(Strings::zh("openReports"), this);
    auto *config = new QPushButton(Strings::zh("openConfig"), this);
    auto *history = new QPushButton(Strings::zh("importHistory"), this);
    for (QPushButton *b : {m_start, m_stop, restart, refresh, logs, reports, config, history})
        buttons->addWidget(b);
    buttons->addStretch();
    layout->addLayout(buttons);
    layout->addStretch();

    connect(m_start, &QPushButton::clicked, this, [this] { emit actionRequested("start"); });
    connect(m_stop, &QPushButton::clicked, this, [this] { emit actionRequested("stop"); });
    connect(restart, &QPushButton::clicked, this, [this] { emit actionRequested("restart"); });
    connect(refresh, &QPushButton::clicked, this, [this] { emit actionRequested("refresh"); });
    connect(logs, &QPushButton::clicked, this, [this] { emit actionRequested("logs"); });
    connect(reports, &QPushButton::clicked, this, [this] { emit actionRequested("reports"); });
    connect(config, &QPushButton::clicked, this, [this] { emit actionRequested("config"); });
    connect(history, &QPushButton::clicked, this, [this] { emit actionRequested("history"); });
}

void OverviewPage::setStatus(const StatusSnapshot &s) {
    const QString zh = "zh-CN";
    if (!s.valid) {
        m_napcat->setValue("未知", false);
        m_onebot->setValue("未知", false);
        m_bot->setValue("未知", false);
        m_qq->setValue("未知", false);
        return;
    }
    m_napcat->setValue(s.napcat ? Strings::zh("running") : "已停止", s.napcat);
    m_onebot->setValue(s.onebot ? Strings::zh("running") : "已停止", s.onebot);
    m_bot->setValue(s.bot ? Strings::zh("running") : "已停止", s.bot);
    const QString account = s.qqNumber.isEmpty()
        ? (s.qqLoggedIn ? "已登录" : "未登录")
        : (s.qqNickname + " (" + s.qqNumber + ")");
    m_qq->setValue(account, s.qqLoggedIn);
}
```

（`Strings::zh("running")` 需在 Strings.cpp 增加 `if (key == "running") return "运行中";`。）

- [ ] **Step 3: 接入 main.cpp 与状态监控**

`main.cpp` 中把 `makeOverview` 换成 `[] (QWidget *p) { return new OverviewPage(p); }`，并在 MainWindow 创建后：

```cpp
    auto *statusMonitor = new StatusMonitor(Paths::statusFile(), 4000, &window);
    auto *overview = qobject_cast<OverviewPage *>(window.pageWidget("overview"));
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged, overview, &OverviewPage::setStatus);
    QObject::connect(overview, &OverviewPage::actionRequested, [](const QString &action) {
        static ServiceControl *control = nullptr;
        if (!control) control = new ServiceControl(qApp);
        if (action == "logs") QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
        else if (action == "reports") QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/data/view/index.html"));
        else if (action == "config") QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot()));
        else if (action == "history") control->run({"-m", "qq_onebot_whitelist.control", "start"});
        else if (action == "start" || action == "restart") control->run({"-m", "qq_onebot_whitelist.control", "start"});
        else if (action == "stop") control->run({"-m", "qq_onebot_whitelist.control", "stop"});
    });
    statusMonitor->refresh();
```

（`history` 暂映射到 start 幂等启动，后续 Task 19 若有历史导入命令再细化。`#include <QDesktopServices>`、`#include <QUrl>`、`#include "core/ServiceControl.h"`、`#include "core/Paths.h"`。）

- [ ] **Step 4: 构建并运行验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe。
Expected: 概览页显示 4 张卡片；若机器人已运行，卡片显示绿色"运行中"；按钮可用。

- [ ] **Step 5: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add overview page with status cards and actions"
```

---

### Task 13: 设置页

**Files:**
- Create: `src/ui/pages/SettingsPage.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 实现 SettingsPage（分区折叠 + schema 驱动表单）**

`src/ui/pages/SettingsPage.h`：

```cpp
#pragma once
#include <QWidget>
#include <QVariant>

class ConfigBridge;
class QVBoxLayout;
class QPushButton;
class QLabel;

class SettingsPage : public QWidget {
    Q_OBJECT
public:
    explicit SettingsPage(QWidget *parent = nullptr);
    void setSchema(const QVariant &schema);
signals:
    void saveRequested(QJsonObject patch);
private:
    QVBoxLayout *m_formLayout = nullptr;
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    QHash<QString, QWidget *> m_fields;
    QJsonObject buildPatch() const;
};
```

`src/ui/pages/SettingsPage.cpp`（核心：按 section 分组、按 kind 生成控件）：

```cpp
#include "SettingsPage.h"
#include "../Strings.h"
#include <QJsonObject>
#include <QJsonArray>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QGroupBox>
#include <QFormLayout>
#include <QLineEdit>
#include <QCheckBox>
#include <QComboBox>
#include <QPushButton>
#include <QLabel>
#include <QHash>

SettingsPage::SettingsPage(QWidget *parent) : QWidget(parent) {
    auto *outer = new QVBoxLayout(this);
    outer->setContentsMargins(24, 24, 24, 24);
    auto *scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto *container = new QWidget(scroll);
    m_formLayout = new QVBoxLayout(container);
    scroll->setWidget(container);
    outer->addWidget(scroll, 1);

    auto *bottom = new QHBoxLayout;
    m_save = new QPushButton(Strings::zh("save"), this);
    m_save->setObjectName("primary");
    m_message = new QLabel(this);
    m_message->setObjectName("muted");
    bottom->addWidget(m_save);
    bottom->addWidget(m_message);
    bottom->addStretch();
    outer->addLayout(bottom);
    m_save->setEnabled(false);
}

void SettingsPage::setSchema(const QVariant &schemaVariant) {
    QLayoutItem *child;
    while ((child = m_formLayout->takeAt(0)) != nullptr) {
        if (QWidget *w = child->widget()) w->deleteLater();
        delete child;
    }
    m_fields.clear();
    const QJsonArray items = QJsonDocument::fromVariant(schemaVariant).array();
    QMap<QString, QVBoxLayout *> sections;
    for (const QJsonValue &value : items) {
        const QJsonObject obj = value.toObject();
        const QString section = obj.value("section").toString();
        if (!sections.contains(section)) {
            auto *group = new QGroupBox(section, this);
            auto *form = new QVBoxLayout(group);
            sections.insert(section, form);
            m_formLayout->addWidget(group);
        }
        const QString key = obj.value("key").toString();
        const QString kind = obj.value("kind").toString();
        const QJsonObject label = obj.value("label").toObject();
        const QString text = label.value("zh-CN").toString(label.value("en-US").toString(key));
        QWidget *field = nullptr;
        if (kind == "bool") {
            auto *box = new QCheckBox(text, this);
            box->setChecked(obj.value("default").toBool());
            field = box;
        } else if (kind == "select") {
            auto *combo = new QComboBox(this);
            for (const QJsonValue &opt : obj.value("options").toArray()) combo->addItem(opt.toString());
            combo->setCurrentText(obj.value("default").toString());
            field = combo;
        } else {
            auto *edit = new QLineEdit(this);
            edit->setText(obj.value("default").toString());
            edit->setProperty("key", key);
            edit->setProperty("min", obj.value("min").toInt());
            edit->setProperty("max", obj.value("max").toInt());
            field = edit;
        }
        auto *row = new QHBoxLayout;
        auto *name = new QLabel(text, this);
        name->setObjectName("muted");
        row->addWidget(name, 1);
        row->addWidget(field, 1);
        sections[section]->addLayout(row);
        m_fields.insert(key, field);
        if (auto *edit = qobject_cast<QLineEdit *>(field))
            connect(edit, &QLineEdit::textChanged, this, [this, edit] {
                bool ok = true;
                const int v = edit->text().toInt(&ok);
                const int min = edit->property("min").toInt();
                const int max = edit->property("max").toInt();
                const bool valid = !ok || (min == 0 && max == 0) || (v >= min && v <= max);
                edit->setProperty("class", valid ? "" : "invalid");
                edit->style()->unpolish(edit);
                edit->style()->polish(edit);
                m_save->setEnabled(true);
            });
        else
            connect(field, &QWidget::destroyed, this, [this] { m_save->setEnabled(true); });
    }
    m_save->setEnabled(false);
}
```

`buildPatch()` 与保存流程（同文件追加）：

```cpp
QJsonObject SettingsPage::buildPatch() const {
    QJsonObject patch;
    for (auto it = m_fields.constBegin(); it != m_fields.constEnd(); ++it) {
        const QString key = it.key();
        QWidget *w = it.value();
        if (auto *box = qobject_cast<QCheckBox *>(w)) patch.insert(key, box->isChecked());
        else if (auto *combo = qobject_cast<QComboBox *>(w)) patch.insert(key, combo->currentText());
        else if (auto *edit = qobject_cast<QLineEdit *>(w)) patch.insert(key, edit->text());
    }
    return patch;
}
```

- [ ] **Step 2: 接入 main.cpp**

```cpp
    auto *settings = qobject_cast<SettingsPage *>(window.pageWidget("settings"));
    auto *configBridge = new ConfigBridge(qApp);
    QObject::connect(configBridge, &ConfigBridge::schemaLoaded, settings, &SettingsPage::setSchema);
    QObject::connect(settings, &SettingsPage::saveRequested, configBridge, &ConfigBridge::save);
    QObject::connect(settings, &SettingsPage::saveRequested, configBridge, [](const QJsonObject &) {});
    QObject::connect(configBridge, &ConfigBridge::saved, settings, [](bool ok, const QString &msg) {
        Q_UNUSED(ok); Q_UNUSED(msg);
    });
    configBridge->fetch();
```

（`SettingsPage.h` 需包含 `#include <QJsonObject>` 并在信号签名中使用；Task 14 会补上语言/主题/自启/通知等按钮式设置项，先保证表单能渲染。）

- [ ] **Step 3: 构建并运行验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe → 切到设置页。
Expected: 按分区显示配置表单；修改字段后"保存"可用。

- [ ] **Step 4: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add schema-driven settings page"
```

---

### Task 14: 日志页

**Files:**
- Create: `src/core/LogReader.h/.cpp`
- Create: `src/ui/pages/LogsPage.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 实现 LogReader**

`src/core/LogReader.h`：

```cpp
#pragma once
#include <QObject>
#include <QFile>
#include <QTimer>

class LogReader : public QObject {
    Q_OBJECT
public:
    explicit LogReader(QStringList paths, QObject *parent = nullptr);
    void setActive(int index); // 0=bot.log 1=napcat.log
signals:
    void newChunk(const QString &text);
private:
    void poll();
    QStringList m_paths;
    QFile m_file;
    qint64 m_pos = 0;
    QTimer m_timer;
    int m_active = 0;
};
```

`src/core/LogReader.cpp`：

```cpp
#include "LogReader.h"
#include <QFileInfo>

LogReader::LogReader(QStringList paths, QObject *parent)
    : QObject(parent), m_paths(paths) {
    m_timer.setInterval(1000);
    connect(&m_timer, &QTimer::timeout, this, &LogReader::poll);
    m_timer.start();
}

void LogReader::setActive(int index) {
    m_active = index;
    if (m_file.isOpen()) m_file.close();
    m_pos = 0;
    if (index >= 0 && index < m_paths.size()) {
        m_file.setFileName(m_paths[index]);
        if (m_file.open(QIODevice::ReadOnly))
            m_pos = m_file.size(); // 只读新增内容
    }
}

void LogReader::poll() {
    if (!m_file.isOpen()) return;
    const qint64 size = m_file.size();
    if (size < m_pos) m_pos = 0;
    if (size == m_pos) return;
    m_file.seek(m_pos);
    emit newChunk(QString::fromUtf8(m_file.read(size - m_pos)));
    m_pos = m_file.size();
}
```

- [ ] **Step 2: 实现 LogsPage**

`src/ui/pages/LogsPage.h`：

```cpp
#pragma once
#include <QWidget>

class QComboBox;
class QPlainTextEdit;
class QCheckBox;
class QLineEdit;
class LogReader;

class LogsPage : public QWidget {
    Q_OBJECT
public:
    explicit LogsPage(QWidget *parent = nullptr);
private:
    QComboBox *m_selector = nullptr;
    QPlainTextEdit *m_view = nullptr;
    QCheckBox *m_autoScroll = nullptr;
    QCheckBox *m_onlyErrors = nullptr;
    QLineEdit *m_filter = nullptr;
    LogReader *m_reader = nullptr;
    void appendChunk(const QString &text);
};
```

`src/ui/pages/LogsPage.cpp`：

```cpp
#include "LogsPage.h"
#include "../Strings.h"
#include "core/LogReader.h"
#include "core/Paths.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QComboBox>
#include <QPlainTextEdit>
#include <QCheckBox>
#include <QLineEdit>
#include <QPushButton>

LogsPage::LogsPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 24, 24, 24);
    auto *top = new QHBoxLayout;
    m_selector = new QComboBox(this);
    m_selector->addItem("bot.log");
    m_selector->addItem("napcat.log");
    m_filter = new QLineEdit(this);
    m_filter->setPlaceholderText(Strings::zh("search"));
    m_autoScroll = new QCheckBox(Strings::zh("autoScroll"), this);
    m_autoScroll->setChecked(true);
    m_onlyErrors = new QCheckBox(Strings::zh("onlyErrors"), this);
    auto *openDir = new QPushButton(Strings::zh("openLogs"), this);
    top->addWidget(m_selector);
    top->addWidget(m_filter, 1);
    top->addWidget(m_autoScroll);
    top->addWidget(m_onlyErrors);
    top->addWidget(openDir);
    layout->addLayout(top);

    m_view = new QPlainTextEdit(this);
    m_view->setReadOnly(true);
    m_view->setMaximumBlockCount(2000);
    layout->addWidget(m_view, 1);

    m_reader = new LogReader({Paths::repoRoot() + "/logs/bot.log",
                              Paths::repoRoot() + "/logs/napcat.log"}, this);
    connect(m_selector, &QComboBox::currentIndexChanged, m_reader, &LogReader::setActive);
    connect(m_reader, &LogReader::newChunk, this, &LogsPage::appendChunk);
    connect(openDir, &QPushButton::clicked, this, [] {
        QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/logs"));
    });
    m_reader->setActive(0);
}

void LogsPage::appendChunk(const QString &text) {
    const bool hasError = text.contains("WARN") || text.contains("ERROR") || text.contains("失败");
    if (m_onlyErrors->isChecked() && !hasError) return;
    if (!m_filter->text().isEmpty() && !text.contains(m_filter->text())) return;
    const QTextCharFormat fmt;
    if (hasError) m_view->setCurrentCharFormat(fmt);
    m_view->appendPlainText(text.trimmed());
    if (m_autoScroll->isChecked())
        m_view->verticalScrollBar()->setValue(m_view->verticalScrollBar()->maximum());
}
```

（错误高亮颜色：追加前用 `QTextCharFormat` 设置红色 foreground，`#include <QTextCharFormat>`、`#include <QScrollBar>`。）

- [ ] **Step 3: 接入 main.cpp（将占位页替换为 LogsPage）**

`makeLogs` 改为 `[] (QWidget *p) { return new LogsPage(p); }`。

- [ ] **Step 4: 构建并运行验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe → 日志页。
Expected: 每秒增量追加日志；"只看错误"过滤；搜索生效。

- [ ] **Step 5: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add live log viewer"
```

---

### Task 15: 报告页

**Files:**
- Create: `src/ui/pages/ReportsPage.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 实现 ReportsPage**

`src/ui/pages/ReportsPage.h`：

```cpp
#pragma once
#include <QWidget>

class QPushButton;
class QLabel;
class QPlainTextEdit;

class ReportsPage : public QWidget {
    Q_OBJECT
public:
    explicit ReportsPage(QWidget *parent = nullptr);
signals:
    void previewRequested();
    void sendRequested();
    void openRequested(const QString &relativePath);
private:
    QLabel *m_nextTime = nullptr;
    QPlainTextEdit *m_preview = nullptr;
};
```

`src/ui/pages/ReportsPage.cpp`：

```cpp
#include "ReportsPage.h"
#include "../Strings.h"
#include "core/Paths.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QPushButton>
#include <QLabel>
#include <QPlainTextEdit>

ReportsPage::ReportsPage(QWidget *parent) : QWidget(parent) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 24, 24, 24);

    auto *entries = new QHBoxLayout;
    const QStringList pages = {"data/view/index.html", "data/view/files.html", "data/view/resources.html"};
    for (const QString &page : pages) {
        auto *button = new QPushButton(page.mid(page.lastIndexOf('/') + 1), this);
        connect(button, &QPushButton::clicked, this, [this, page] { emit openRequested(page); });
        entries->addWidget(button);
    }
    entries->addStretch();
    layout->addLayout(entries);

    m_nextTime = new QLabel(this);
    m_nextTime->setObjectName("muted");
    layout->addWidget(m_nextTime);

    m_preview = new QPlainTextEdit(this);
    m_preview->setReadOnly(true);
    m_preview->setMaximumBlockCount(500);
    layout->addWidget(m_preview, 1);

    auto *actions = new QHBoxLayout;
    auto *preview = new QPushButton(Strings::zh("preview"), this);
    auto *send = new QPushButton(Strings::zh("sendTest"), this);
    send->setObjectName("primary");
    actions->addWidget(preview);
    actions->addWidget(send);
    actions->addStretch();
    layout->addLayout(actions);

    connect(preview, &QPushButton::clicked, this, &ReportsPage::previewRequested);
    connect(send, &QPushButton::clicked, this, &ReportsPage::sendRequested);
}
```

（Strings 增加 `preview`→"生成预览"/"Preview"、`sendTest`→"发送测试日报"/"Send test report"。）

- [ ] **Step 2: 接入 main.cpp**

```cpp
    auto *reports = qobject_cast<ReportsPage *>(window.pageWidget("reports"));
    auto *reportControl = new ServiceControl(qApp);
    QObject::connect(reports, &ReportsPage::openRequested, [](const QString &rel) {
        QDesktopServices::openUrl(QUrl::fromLocalFile(Paths::repoRoot() + "/" + rel));
    });
    QObject::connect(reports, &ReportsPage::previewRequested, reports, [reports, reportControl] {
        reportControl->run({"-m", "qq_onebot_whitelist.control", "report-preview"});
    });
    QObject::connect(reportControl, &ServiceControl::finished, reports, [reports](bool ok, QString out) {
        if (!ok) return;
        const QJsonDocument doc = QJsonDocument::fromJson(out.toUtf8());
        if (doc.isObject())
            reports->setPreview(doc.object().value("content").toString());
    });
    QObject::connect(reports, &ReportsPage::sendRequested, reports, [reportControl] {
        reportControl->run({"-m", "qq_onebot_whitelist.control", "report-send"});
    });
```

（`ReportsPage` 增加公开方法 `void setPreview(const QString &text)`，实现为 `m_preview->setPlainText(text)`。）

- [ ] **Step 3: 构建并运行验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe → 报告页。
Expected: 三个入口用系统浏览器打开；"生成预览"显示日报文本。

- [ ] **Step 4: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add reports page with preview and test send"
```

---

## Phase E：托盘、通知、自动重启、收尾

### Task 16: 托盘集成

**Files:**
- Modify: `src/ui/MainWindow.cpp`, `src/main.cpp`

- [ ] **Step 1: MainWindow 增加托盘**

`src/ui/MainWindow.h` 增加：

```cpp
#include <QSystemTrayIcon>
...
    QSystemTrayIcon *m_tray = nullptr;
    void setupTray();
signals:
    void trayAction(const QString &action); // open/start/stop/restart/logs/reports/quit
```

`src/ui/MainWindow.cpp` 实现：

```cpp
void MainWindow::setupTray() {
    m_tray = new QSystemTrayIcon(QIcon(":/icons/app.svg"), this);
    auto *menu = new QMenu(this);
    menu->addAction(Strings::zh("overview"), this, [this] { showNormal(); raise(); activateWindow(); });
    menu->addSeparator();
    menu->addAction(Strings::zh("start"), this, [this] { emit trayAction("start"); });
    menu->addAction(Strings::zh("stop"), this, [this] { emit trayAction("stop"); });
    menu->addAction(Strings::zh("restart"), this, [this] { emit trayAction("restart"); });
    menu->addSeparator();
    menu->addAction(Strings::zh("openLogs"), this, [this] { emit trayAction("logs"); });
    menu->addAction(Strings::zh("openReports"), this, [this] { emit trayAction("reports"); });
    menu->addSeparator();
    menu->addAction(Strings::zh("quit"), this, [this] { emit trayAction("quit"); });
    m_tray->setContextMenu(menu);
    m_tray->show();
}
```

在构造函数末尾调用 `setupTray()`；重写 `closeEvent`：

```cpp
void MainWindow::closeEvent(QCloseEvent *event) {
    if (m_tray && m_tray->isVisible()) {
        hide();
        event->ignore();
    } else {
        event->accept();
    }
}
```

（`#include <QCloseEvent>`、`#include <QMenu>`。）

- [ ] **Step 2: main.cpp 连接托盘动作**

```cpp
    QObject::connect(&window, &MainWindow::trayAction, [&window](const QString &action) {
        if (action == "quit") {
            window.setAttribute(Qt::WA_QuitOnClose, true);
            QApplication::quit();
        }
    });
```

（start/stop/restart/logs/reports 与概览页动作复用同一 ServiceControl 逻辑；可在 Task 12 的 lambda 中提取共享 handler。）

- [ ] **Step 3: 构建并运行验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe。
Expected: 托盘出现图标；关闭窗口隐藏到托盘；托盘菜单可打开/退出。

- [ ] **Step 4: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add system tray with actions"
```

---

### Task 17: Notifier（原生通知）

**Files:**
- Create: `src/core/Notifier.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 实现 Notifier**

`src/core/Notifier.h`：

```cpp
#pragma once
#include <QObject>
#include <QDateTime>
#include "StatusMonitor.h"

class QSystemTrayIcon;

class Notifier : public QObject {
    Q_OBJECT
public:
    explicit Notifier(QSystemTrayIcon *tray, QObject *parent = nullptr);
    void setEnabled(bool enabled);
    void onStatusChanged(const StatusSnapshot &snapshot);
private:
    void notify(const QString &title, const QString &body, const QString &dedupeKey);
    QSystemTrayIcon *m_tray = nullptr;
    bool m_enabled = true;
    StatusSnapshot m_last;
    bool m_hasLast = false;
    QHash<QString, QDateTime> m_lastNotified;
};
```

`src/core/Notifier.cpp`：

```cpp
#include "Notifier.h"
#include "../ui/Strings.h"
#include <QSystemTrayIcon>

Notifier::Notifier(QSystemTrayIcon *tray, QObject *parent)
    : QObject(parent), m_tray(tray) {}

void Notifier::setEnabled(bool enabled) { m_enabled = enabled; }

void Notifier::notify(const QString &title, const QString &body, const QString &dedupeKey) {
    if (!m_enabled || !m_tray) return;
    const QDateTime now = QDateTime::currentDateTime();
    if (m_lastNotified.value(dedupeKey).secsTo(now) < 600) return;
    m_lastNotified.insert(dedupeKey, now);
    m_tray->showMessage(title, body, QSystemTrayIcon::Information, 5000);
}

void Notifier::onStatusChanged(const StatusSnapshot &s) {
    if (!m_hasLast) {
        m_last = s;
        m_hasLast = true;
        return;
    }
    if (!s.valid || !m_last.valid) {
        m_last = s;
        return;
    }
    if (!m_last.qqLoggedIn && s.qqLoggedIn)
        notify(Strings::zh("qqLogin"), s.qqNickname + " (" + s.qqNumber + ")", "login");
    if (m_last.qqLoggedIn && !s.qqLoggedIn)
        notify(Strings::zh("qqLogout"), s.qqNickname, "logout");
    if (m_last.napcat && !s.napcat)
        notify(Strings::zh("error"), "NapCat", "napcat-down");
    if (m_last.onebot && !s.onebot)
        notify(Strings::zh("error"), "OneBot", "onebot-down");
    if (m_last.bot && !s.bot)
        notify(Strings::zh("error"), "Bot", "bot-down");
    m_last = s;
}
```

- [ ] **Step 2: 接入 main.cpp**

```cpp
    auto *notifier = new Notifier(window.trayIcon(), qApp);
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged,
                     notifier, &Notifier::onStatusChanged);
```

（`MainWindow` 增加 `QSystemTrayIcon *trayIcon() const { return m_tray; }`。）

- [ ] **Step 3: 构建并手动验证通知**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe。
Expected: 手动停止机器人后 4 秒内出现系统通知"Bot"；恢复后无多余通知；同一事件 10 分钟内不重复。

- [ ] **Step 4: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add native tray notifications for login and service changes"
```

---

### Task 18: 面板自动重启与手动停止状态

**Files:**
- Create: `src/core/AutoRestart.h/.cpp`
- Modify: `src/main.cpp`

- [ ] **Step 1: 实现 AutoRestart**

`src/core/AutoRestart.h`：

```cpp
#pragma once
#include <QObject>
#include <QDateTime>
#include "StatusMonitor.h"

class ServiceControl;

class AutoRestart : public QObject {
    Q_OBJECT
public:
    explicit AutoRestart(ServiceControl *control, QObject *parent = nullptr);
    void setEnabled(bool enabled);
    void setManualStop(bool manualStop); // 用户手动停止后暂停自动重启
    void onStatusChanged(const StatusSnapshot &s);
    bool manualStop() const { return m_manualStop; }
signals:
    void autoRestarted();
private:
    ServiceControl *m_control = nullptr;
    bool m_enabled = true;
    bool m_manualStop = false;
    QDateTime m_lastRestart;
};
```

`src/core/AutoRestart.cpp`：

```cpp
#include "AutoRestart.h"
#include "ServiceControl.h"

AutoRestart::AutoRestart(ServiceControl *control, QObject *parent)
    : QObject(parent), m_control(control) {}

void AutoRestart::setEnabled(bool enabled) { m_enabled = enabled; }
void AutoRestart::setManualStop(bool manualStop) { m_manualStop = manualStop; }

void AutoRestart::onStatusChanged(const StatusSnapshot &s) {
    if (!m_enabled || m_manualStop || !s.valid) return;
    if (s.napcat && s.onebot && s.bot) return;
    if (m_lastRestart.isValid() && m_lastRestart.secsTo(QDateTime::currentDateTime()) < 30) return;
    m_lastRestart = QDateTime::currentDateTime();
    m_control->run({"-m", "qq_onebot_whitelist.control", "start"});
    emit autoRestarted();
}
```

- [ ] **Step 2: 接入 main.cpp 与概览页**

```cpp
    auto *serviceControl = new ServiceControl(qApp);
    auto *autoRestart = new AutoRestart(serviceControl, qApp);
    QObject::connect(statusMonitor, &StatusMonitor::statusChanged,
                     autoRestart, &AutoRestart::onStatusChanged);
```

概览页：`stop` 动作触发后调用 `autoRestart->setManualStop(true)` 并显示 `Strings::zh("manualStop")`；`start` 动作触发后 `setManualStop(false)`。自动重启状态文本由 `autoRestarted` 信号更新。

- [ ] **Step 3: 构建并验证**

Run: `cmake --build qq-onebot-manager-qt/build`。
Expected: 停止服务后 30 秒内面板自动重新调用 start；手动停止后不自动拉起。

- [ ] **Step 4: 提交**

```bash
git add qq-onebot-manager-qt
git commit -m "feat: add panel-side auto restart with manual stop guard"
```

---

### Task 19: 开机自启、设置页补充与启动入口切换

**Files:**
- Create: `src/core/AutoStart.h/.cpp`
- Modify: `src/ui/pages/SettingsPage.cpp`, `scripts/windows/install-tray-shortcut.ps1`, `src/main.cpp`

- [ ] **Step 1: 实现开机自启（COM 快捷方式，不依赖 PowerShell）**

`src/core/AutoStart.h`：

```cpp
#pragma once
#include <QString>

class AutoStart {
public:
    static QString startupLinkPath();
    static bool isEnabled();
    static bool setEnabled(bool enabled);
};
```

`src/core/AutoStart.cpp`：

```cpp
#include "AutoStart.h"
#include "Paths.h"
#include <QStandardPaths>
#include <QDir>

QString AutoStart::startupLinkPath() {
    return QStandardPaths::writableLocation(QStandardPaths::ApplicationsLocation)
        + "/Startup/QQ OneBot 管理器.lnk";
}

bool AutoStart::isEnabled() { return QFileInfo::exists(startupLinkPath()); }

bool AutoStart::setEnabled(bool enabled) {
    const QString target = QCoreApplication::applicationFilePath();
    const QString link = startupLinkPath();
    if (!enabled) {
        return QFile::remove(link);
    }
    // 使用 IShellLink COM 创建 .lnk（Windows 原生 API）
    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) return false;
    IShellLinkW *shellLink = nullptr;
    hr = CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER,
                          IID_IShellLinkW, reinterpret_cast<void **>(&shellLink));
    if (FAILED(hr)) { if (hr != RPC_E_CHANGED_MODE) CoUninitialize(); return false; }
    shellLink->SetPath(reinterpret_cast<LPCWSTR>(target.utf16()));
    shellLink->SetWorkingDirectory(reinterpret_cast<LPCWSTR>(Paths::repoRoot().utf16()));
    IPersistFile *persist = nullptr;
    hr = shellLink->QueryInterface(IID_IPersistFile, reinterpret_cast<void **>(&persist));
    if (SUCCEEDED(hr)) {
        persist->Save(reinterpret_cast<LPCWSTR>(link.utf16()), TRUE);
        persist->Release();
    }
    shellLink->Release();
    if (hr != RPC_E_CHANGED_MODE) CoUninitialize();
    return SUCCEEDED(hr);
}
```

（需 `#include <windows.h>`、`#include <shlobj.h>`；CMake 链接 `ole32` 与 `shell32`。若 MinGW 下 COM 头可用，此实现成立；否则回退方案：用 QProcess 调 PowerShell 创建快捷方式，仅此一处保留 PowerShell。）

- [ ] **Step 2: 设置页补充（语言/主题/自启/通知开关）**

在 `SettingsPage` 顶部（滚动区第一个分区前）加入：

```cpp
    auto *general = new QGroupBox(Strings::zh("general"), container);
    auto *generalForm = new QFormLayout(general);
    auto *language = new QComboBox(general);
    language->addItems({"跟随系统", "中文", "English"});
    auto *theme = new QComboBox(general);
    theme->addItems({"浅色", "深色"});
    auto *autoStart = new QCheckBox(general);
    auto *notifications = new QCheckBox(general);
    notifications->setChecked(true);
    generalForm->addRow(Strings::zh("language"), language);
    generalForm->addRow(Strings::zh("theme"), theme);
    generalForm->addRow(Strings::zh("autoStart"), autoStart);
    generalForm->addRow(Strings::zh("notifications"), notifications);
    m_formLayout->addWidget(general);
```

（Strings 增加 `general`→"通用"、`preview`/`sendTest` 等。`autoStart->setChecked(AutoStart::isEnabled())`，toggle 时调用 `AutoStart::setEnabled`。）

- [ ] **Step 3: 更新快捷方式安装脚本**

`scripts/windows/install-tray-shortcut.ps1` 中桌面/开始菜单快捷方式目标改为：

```powershell
$PanelExe = Join-Path $BotDir 'qq-onebot-manager-qt\build\qq-onebot-manager-qt.exe'
if (Test-Path -LiteralPath $PanelExe) {
    $Shortcut.TargetPath = $PanelExe
    $Shortcut.Arguments = ''
    $Shortcut.IconLocation = "$PanelExe,0"
}
```

- [ ] **Step 4: 归档旧 Rust 管理器**

```bash
git mv manager manager-archived
```

（先确认新面板可用再执行；`manager-archived/` 保留以便回退。）

- [ ] **Step 5: 构建、运行、验证**

Run: `cmake --build qq-onebot-manager-qt/build`；运行 exe → 设置页。
Expected: 自启开关真实写入/删除 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\QQ OneBot 管理器.lnk`。

- [ ] **Step 6: 提交**

```bash
git add qq-onebot-manager-qt scripts/windows/install-tray-shortcut.ps1
git mv manager manager-archived
git commit -m "feat: wire auto start, settings extras, switch launcher to qt panel"
```

---

### Task 20: 全量验证与收尾

**Files:**
- Modify: `README.md`（面板使用说明）、`docs/交接文档.md`

- [ ] **Step 1: 运行全部测试**

Run: `.venv\Scripts\python.exe -m pytest tests/ -q`
Run: `cmake --build qq-onebot-manager-qt/build && & qq-onebot-manager-qt\build\tests\tst_statusmonitor.exe`
Expected: 全部通过

- [ ] **Step 2: 手动验收清单**

- 首次启动显示窗口，第二实例提示已在运行。
- 概览 4 卡片随状态实时变化；按钮可启停服务。
- 手动停止后出现"已手动停止"提示，自动重启暂停；30 秒后手动 start 恢复。
- 托盘图标存在；关闭窗口隐藏到托盘；托盘菜单可用；退出托盘不停止机器人服务。
- 设置页表单按分区显示；非法数字标红；保存后 config.yaml 变化正确。
- 语言切换中英文即时生效；主题切换深浅即时生效。
- 开机自启开关真实生效（重启 Windows 登录后面板自动启动）。
- 日志页实时滚动、搜索、只看错误可用。
- 报告页入口打开浏览器；生成预览显示日报；测试发送后白名单用户收到私聊。
- QQ 登录/掉线时出现系统通知；同一事件 10 分钟内不重复。
- 面板常驻内存观察：任务管理器 40~60MB 量级。

- [ ] **Step 3: 更新文档**

README 增加"控制面板"小节：构建方式（Qt Creator / cmake 命令）、四个页面说明、开机自启说明。

- [ ] **Step 4: 最终提交**

```bash
git add README.md docs
git commit -m "docs: document qt control panel usage"
```

---

## 自审记录

- **Spec 覆盖**：四页面（Task 8/12-15）、托盘（16）、通知（17）、自动重启显性化（18）、开机自启（19）、语言/主题/校验（7/13）、API Key 只写不回显（设置页 QLineEdit 密码模式，见 Task 13 扩展）、日志（14）、报告（5/15）、数据概况（4/12）、状态协议（2/9）、占用保障（9 无子进程 + 14 增量读）。
- **明确偏离一处**：规格书中 `autoRestartedAt` 在 status.json；实现中改为面板本地记录（AutoRestart 持有 `m_lastRestart`），因为自动重启由面板负责，避免面板与机器人争写同一文件。功能语义不变。
- **已知简化**：`start_services` 的 bot 幂等检查暂简化为直接启动；若需要精确幂等按 Task 3 说明补齐。`history` 动作暂映射为 start。

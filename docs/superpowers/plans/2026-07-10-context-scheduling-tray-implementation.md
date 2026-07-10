# Context Scheduling and Tray Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make analysis scheduling user-configurable, remove empty LLM boilerplate, classify AI context conservatively, split the oversized context page, move NapCat into the project, and provide reliable tray-based startup and shutdown.

**Architecture:** Keep `config.yaml` as the single scheduling source and add one focused Python settings module used by the bot, QQ commands, and the Windows tray dialog. Store tolerant AI quality metadata in `ai_context_batches.raw_json`; generate a small directory shell plus one static HTML file per batch so `file://` remains sufficient. Keep NapCat under ignored `runtime/` and let launch scripts default to that path.

**Tech Stack:** Python 3.11, PyYAML, SQLite, pytest, PowerShell 5.1/Windows Forms, static HTML/CSS/JavaScript, Git.

---

## File Map

- Create `qq_onebot_whitelist/settings.py`: validate, read, and atomically update `ai_context.allowed_windows`; expose a small CLI for the tray dialog.
- Create `qq_onebot_whitelist/context_quality.py`: tolerant AI-value parsing, deterministic evidence checks, and display-summary cleanup.
- Create `qq_onebot_whitelist/context_view.py`: batch/image loading and split static context-page generation.
- Create `scripts/windows/set-analysis-windows.ps1`: native multiline settings dialog that calls the Python settings CLI.
- Modify `qq_onebot_whitelist/config.py`: keep the default schedule empty.
- Modify `qq_onebot_whitelist/schedule.py`: validate multiple normal and cross-midnight windows.
- Modify `qq_onebot_whitelist/commands.py`: add private scheduling commands and remove `/` from displayed instructions.
- Modify `qq_onebot_whitelist/onebot.py`: reload config every analysis check and pass a config path to commands.
- Modify `qq_onebot_whitelist/llm_summary.py`: prohibit boilerplate and request a tolerant value section.
- Modify `qq_onebot_whitelist/ai_context_analyze.py`: store parsed quality metadata without a second LLM request.
- Modify `qq_onebot_whitelist/build_image_view.py`: delegate AI-context output to `context_view.py`.
- Modify `scripts/windows/qq-onebot-tray.ps1`: add the settings action and make stop-all the primary exit.
- Modify Windows start/stop scripts: use project-local NapCat and remove `call .env`.
- Modify `.gitignore`, examples, README, and Chinese operating docs.

### Task 1: Capture the Current Project Baseline

**Files:**
- Stage: all currently trackable project files except ignored runtime/private data

- [ ] **Step 1: Re-run the current baseline tests**

Run:

```powershell
uv run --extra dev pytest -q
```

Expected: `91 passed` before new implementation work.

- [ ] **Step 2: Verify private files remain ignored**

Run:

```powershell
git check-ignore -v .env config.yaml data/bot.db logs/bot.log run/bot.pid scripts/windows/launcher.config.ps1
```

Expected: every path is matched by `.gitignore`.

- [ ] **Step 3: Create the requested baseline commit**

Run:

```powershell
git add .
git diff --cached --check
git commit -m "chore: capture qq onebot project baseline"
```

Expected: all source, tests, docs, examples, and scripts are committed; runtime/private paths are absent.

### Task 2: Add Validated Multi-Window Settings

**Files:**
- Create: `qq_onebot_whitelist/settings.py`
- Modify: `qq_onebot_whitelist/config.py`
- Modify: `qq_onebot_whitelist/schedule.py`
- Modify: `config.example.yaml`
- Test: `tests/test_schedule.py`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write failing schedule validation tests**

Add tests that require:

```python
from datetime import datetime

import pytest

from qq_onebot_whitelist.schedule import is_in_time_windows, normalize_time_windows


def test_normalize_time_windows_accepts_multiple_and_cross_midnight():
    assert normalize_time_windows(['00:30-08:30', '12:00-13:00', '23:00-07:00']) == [
        '00:30-08:30', '12:00-13:00', '23:00-07:00'
    ]


@pytest.mark.parametrize('value', ['24:00-08:00', '8:00-09:00', '09:60-10:00', '09:00'])
def test_normalize_time_windows_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_time_windows([value])


def test_empty_windows_allow_all_day():
    assert is_in_time_windows(datetime(2026, 7, 10, 15, 0), []) is True
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run --extra dev pytest -q tests/test_schedule.py
```

Expected: FAIL because `normalize_time_windows` does not exist.

- [ ] **Step 3: Implement strict normalization**

Implement in `qq_onebot_whitelist/schedule.py`:

```python
WINDOW_RE = re.compile(r'^(\d{2}):(\d{2})-(\d{2}):(\d{2})$')


def normalize_time_windows(windows: list[str]) -> list[str]:
    result = []
    for raw in windows:
        value = str(raw).strip()
        match = WINDOW_RE.fullmatch(value)
        if not match:
            raise ValueError(f'无效时间段：{value}，格式应为 HH:MM-HH:MM')
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
            raise ValueError(f'无效时间段：{value}')
        result.append(value)
    return result
```

Call this function from `is_in_time_windows` before comparing times.

- [ ] **Step 4: Write failing settings persistence tests**

Create `tests/test_settings.py` with:

```python
from qq_onebot_whitelist.settings import read_analysis_windows, write_analysis_windows


def test_write_analysis_windows_preserves_other_config(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('reply:\n  whitelist_users: ["1"]\nai_context:\n  enabled: true\n', encoding='utf-8')

    write_analysis_windows(path, ['00:30-08:30', '12:00-13:00'])

    assert read_analysis_windows(path) == ['00:30-08:30', '12:00-13:00']
    text = path.read_text(encoding='utf-8')
    assert 'whitelist_users' in text
    assert 'enabled: true' in text


def test_write_analysis_windows_supports_all_day(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('{}\n', encoding='utf-8')
    write_analysis_windows(path, [])
    assert read_analysis_windows(path) == []
```

- [ ] **Step 5: Run settings tests and verify RED**

Run:

```powershell
uv run --extra dev pytest -q tests/test_settings.py
```

Expected: FAIL because `qq_onebot_whitelist.settings` does not exist.

- [ ] **Step 6: Implement atomic YAML settings and CLI**

Create `qq_onebot_whitelist/settings.py` with this complete implementation shape:

```python
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .schedule import normalize_time_windows


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding='utf-8')) or {}


def read_analysis_windows(path: str | Path) -> list[str]:
    raw = _read_yaml(Path(path))
    return normalize_time_windows(list((raw.get('ai_context') or {}).get('allowed_windows') or []))


def write_analysis_windows(path: str | Path, windows: list[str]) -> list[str]:
    target = Path(path)
    normalized = normalize_time_windows(windows)
    raw = _read_yaml(target)
    raw.setdefault('ai_context', {})['allowed_windows'] = normalized
    temporary = target.with_suffix(target.suffix + '.tmp')
    temporary.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding='utf-8')
    temporary.replace(target)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yaml')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--get', action='store_true')
    action.add_argument('--set')
    action.add_argument('--all-day', action='store_true')
    args = parser.parse_args()
    if args.get:
        windows = read_analysis_windows(args.config)
    elif args.all_day:
        windows = write_analysis_windows(args.config, [])
    else:
        windows = write_analysis_windows(args.config, [x.strip() for x in args.set.split(',') if x.strip()])
    print('\n'.join(windows) if windows else '全天')
    return 0
```

Use `yaml.safe_load`, preserve unrelated keys, normalize windows, write to `path.with_suffix(path.suffix + '.tmp')`, then replace the original. The CLI must support:

```powershell
uv run python -m qq_onebot_whitelist.settings --config config.yaml --get
uv run python -m qq_onebot_whitelist.settings --config config.yaml --set "00:30-08:30,12:00-13:00"
uv run python -m qq_onebot_whitelist.settings --config config.yaml --all-day
```

- [ ] **Step 7: Restore empty defaults**

Set `config.example.yaml` to:

```yaml
allowed_windows: []
```

Update the ignored local `config.yaml` with:

```powershell
uv run python -m qq_onebot_whitelist.settings --config config.yaml --all-day
```

Keep `AppConfig.ai_context_allowed_windows` defaulting to `[]`, and normalize configured values in `load_config`.

- [ ] **Step 8: Run schedule/settings tests and commit**

Run:

```powershell
uv run --extra dev pytest -q tests/test_schedule.py tests/test_settings.py tests/test_ai_context_auto_config.py
git add qq_onebot_whitelist/settings.py qq_onebot_whitelist/schedule.py qq_onebot_whitelist/config.py config.example.yaml tests/test_schedule.py tests/test_settings.py tests/test_ai_context_auto_config.py
git commit -m "feat: add configurable analysis windows"
```

Expected: all selected tests pass.

### Task 3: Add Private QQ Scheduling Commands and Live Reload

**Files:**
- Modify: `qq_onebot_whitelist/commands.py`
- Modify: `qq_onebot_whitelist/onebot.py`
- Modify: `tests/test_private_global_commands.py`
- Create: `tests/test_analysis_window_commands.py`
- Create: `tests/test_ai_context_reload.py`

- [ ] **Step 1: Write failing command tests**

Create tests for these exact messages, including the event helpers:

```python
from qq_onebot_whitelist.commands import build_reply
from qq_onebot_whitelist.settings import read_analysis_windows
from qq_onebot_whitelist.store import Store


def private_event(text: str) -> dict:
    return {'message_type': 'private', 'user_id': 1, 'message': text}


def group_event(text: str) -> dict:
    return {'message_type': 'group', 'group_id': 2, 'user_id': 1, 'message': text}


def test_private_user_can_view_set_and_clear_analysis_windows(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('ai_context:\n  allowed_windows: []\n', encoding='utf-8')
    store = Store(tmp_path / 'bot.db')
    assert build_reply(private_event('分析时段 查看'), store, config_path=config) == '当前允许分析时段：全天'
    reply = build_reply(private_event('分析时段 设置 00:30-08:30,12:00-13:00'), store, config_path=config)
    assert '已设置分析时段' in reply
    assert read_analysis_windows(config) == ['00:30-08:30', '12:00-13:00']
    assert '全天' in build_reply(private_event('分析时段 全天'), store, config_path=config)
    assert read_analysis_windows(config) == []


def test_group_cannot_change_analysis_windows(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('{}\n', encoding='utf-8')
    store = Store(tmp_path / 'bot.db')
    assert build_reply(group_event('分析时段 全天'), store, config_path=config) == '分析时段只能由白名单用户私聊修改。'


def test_slash_prefix_remains_compatible(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('{}\n', encoding='utf-8')
    store = Store(tmp_path / 'bot.db')
    assert '当前允许分析时段' in build_reply(private_event('/分析时段 查看'), store, config_path=config)
```

Assertions must include:

```python
assert build_reply(private_event('分析时段 查看'), store, config_path=config) == '当前允许分析时段：全天'
assert '已设置分析时段' in build_reply(private_event('分析时段 设置 00:30-08:30,12:00-13:00'), store, config_path=config)
assert read_analysis_windows(config) == ['00:30-08:30', '12:00-13:00']
assert build_reply(group_event('分析时段 全天'), store, config_path=config) == '分析时段只能由白名单用户私聊修改。'
assert '当前允许分析时段' in build_reply(private_event('/分析时段 查看'), store, config_path=config)
```

- [ ] **Step 2: Run command tests and verify RED**

Run:

```powershell
uv run --extra dev pytest -q tests/test_analysis_window_commands.py
```

Expected: FAIL because the command is unknown and `config_path` is unsupported.

- [ ] **Step 3: Implement command parsing**

Add a helper in `commands.py`:

```python
def handle_analysis_windows_command(text: str, *, is_private: bool, config_path: str | Path) -> str | None:
    command = text.strip().lstrip('/').strip()
    if not command.startswith('分析时段'):
        return None
    if not is_private:
        return '分析时段只能由白名单用户私聊修改。'
    argument = command[len('分析时段'):].strip()
    if argument in {'', '查看'}:
        windows = read_analysis_windows(config_path)
        return '当前允许分析时段：' + ('、'.join(windows) if windows else '全天')
    if argument == '全天':
        write_analysis_windows(config_path, [])
        return '已设置分析时段：全天'
    if argument.startswith('设置'):
        values = [x.strip() for x in argument[len('设置'):].strip().split(',') if x.strip()]
        try:
            windows = write_analysis_windows(config_path, values)
        except ValueError as exc:
            return str(exc)
        return '已设置分析时段：' + ('、'.join(windows) if windows else '全天')
    return '用法：分析时段 查看；分析时段 设置 00:30-08:30,12:00-13:00；分析时段 全天'
```

Use `read_analysis_windows`, `write_analysis_windows`, and `normalize_time_windows`. Return validation errors without changing the file.

Update `HELP_TEXT` and the fallback reply so displayed commands never require `/`; retain old slash parsing.

- [ ] **Step 4: Write and verify a live-reload RED test**

Extract and implement this one-iteration decision helper in `onebot.py`:

```python
def should_run_ai_context(config_path: str | Path, store: Store, now: datetime) -> tuple[bool, int, AppConfig]:
    current = load_config(config_path)
    scopes = [scope for scope in configured_scopes(current, current.data_dir / 'bot.db') if scope]
    pending = sum(
        store.count_messages_after(str(scope), store.last_ai_context_end_message_id(str(scope)))
        for scope in scopes
    )
    allowed = is_in_time_windows(now, current.ai_context_allowed_windows)
    return pending >= current.ai_context_min_new_messages and allowed, pending, current
```

The test must write `allowed_windows: []`, assert allowed, rewrite to `00:30-08:30`, and assert a 15:00 check is blocked without recreating the store or process.

Run:

```powershell
uv run --extra dev pytest -q tests/test_ai_context_reload.py
```

Expected: FAIL before the helper exists.

- [ ] **Step 5: Reload config every loop iteration**

Change `ai_context_loop` to receive `config_path`, call `load_config(config_path)` each cycle, and use the reloaded interval, minimum message count, scopes, and windows. Pass the same config path from `main/run` and `build_reply`.

- [ ] **Step 6: Run command/reload tests and commit**

Run:

```powershell
uv run --extra dev pytest -q tests/test_analysis_window_commands.py tests/test_ai_context_reload.py tests/test_private_global_commands.py tests/test_commands.py
git add qq_onebot_whitelist/commands.py qq_onebot_whitelist/onebot.py tests/test_analysis_window_commands.py tests/test_ai_context_reload.py tests/test_private_global_commands.py
git commit -m "feat: manage analysis windows from private chat"
```

### Task 4: Remove LLM Boilerplate and Classify Context Conservatively

**Files:**
- Create: `qq_onebot_whitelist/context_quality.py`
- Modify: `qq_onebot_whitelist/llm_summary.py`
- Modify: `qq_onebot_whitelist/ai_context_analyze.py`
- Create: `tests/test_context_quality.py`
- Modify: `tests/test_llm_summary.py`
- Modify: `tests/test_ai_context_batches.py`

- [ ] **Step 1: Write failing boilerplate cleanup tests**

Add:

```python
def test_normalize_summary_drops_everything_before_first_heading():
    text = '好的，已对69条消息进行过滤。\n过滤规则严格遵守。\n\n## 本批概览\n- 有效内容'
    assert normalize_summary_output(text).startswith('## 本批概览')
    assert '过滤规则' not in normalize_summary_output(text)
```

- [ ] **Step 2: Write failing tolerant quality tests**

Create tests covering:

```python
parse_context_quality('AI相关：是\n价值等级：高')
parse_context_quality('- ai_relevant: true\n- value: medium')
parse_context_quality('```json\n{"ai_relevant": false, "value_level": "low"}\n```')
parse_context_quality('只有正常摘要，没有判定字段')
```

Expected results: `high`, `review`, `low`, and `review`. Add a conflict test where AI says high but the summary only says “无有效讨论”; expected `review`.

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
uv run --extra dev pytest -q tests/test_llm_summary.py tests/test_context_quality.py
```

Expected: FAIL on pre-heading cleanup and missing quality module.

- [ ] **Step 4: Implement tolerant parsing and deterministic evidence**

Create `context_quality.py` with:

```python
@dataclass(slots=True)
class ContextQuality:
    ai_relevant: bool | None
    value_level: str
    reason: str
    display_summary: str


def has_substantive_ai_evidence(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in (
        'prompt', '提示词', 'negative', 'lora', 'checkpoint', '模型', '工作流', 'workflow',
        'comfyui', 'sampler', '采样', 'steps', 'cfg', 'seed', '节点', '训练', '放大', '重绘',
    ))
```

Implement `parse_context_quality` with complete precedence:

```python
def parse_context_quality(summary: str) -> ContextQuality:
    clean = redact_secrets(summary).strip()
    relevant_match = re.search(r'(?i)(?:AI相关|ai_relevant)\s*[：:=]\s*(是|否|true|false)', clean)
    level_match = re.search(r'(?i)(?:价值等级|value_level|value)\s*[：:=]\s*(高|中|低|high|medium|low)', clean)
    reason_match = re.search(r'(?im)(?:判断理由|reason)\s*[：:=]\s*([^\n]+)', clean)
    relevant = None if not relevant_match else relevant_match.group(1).lower() in {'是', 'true'}
    level_map = {'高': 'high', 'high': 'high', '中': 'review', 'medium': 'review', '低': 'low', 'low': 'low'}
    parsed_level = level_map.get(level_match.group(1).lower()) if level_match else 'review'
    display = re.split(r'(?im)^#{1,6}\s*内容判定\s*$', clean, maxsplit=1)[0].rstrip()
    evidence = has_substantive_ai_evidence(display)
    empty_claim = bool(re.search(r'无有效.*(?:讨论|内容)|无需输出总结|已过滤', display))
    if parsed_level == 'high' and (not evidence or empty_claim or relevant is False):
        parsed_level = 'review'
    if relevant is None or level_match is None:
        parsed_level = 'review'
    return ContextQuality(relevant, parsed_level, reason_match.group(1).strip() if reason_match else '', display)
```

Accept Chinese/English labels, JSON/code fences, and unordered fields. Map unparsed, medium, and conflicts to `review`. Strip the `## 内容判定` section from `display_summary`.

- [ ] **Step 5: Strengthen the LLM prompt and normalization**

In `normalize_summary_output`, if a Markdown heading exists, return from the first heading onward before secret redaction. Update the system prompt to forbid process narration and request the optional content-judgment section without requiring strict JSON.

- [ ] **Step 6: Persist quality metadata**

In `analyze_scope`, parse the returned summary once and store:

```python
raw = {
    'message_count': len(records),
    'provider': config.ai_context_provider,
    'users': user_alias_map(records),
    'quality': {
        'ai_relevant': quality.ai_relevant,
        'value_level': quality.value_level,
        'reason': quality.reason,
    },
}
```

Store `quality.display_summary` in the summary column. Do not issue another LLM request.

- [ ] **Step 7: Run quality tests and commit**

Run:

```powershell
uv run --extra dev pytest -q tests/test_llm_summary.py tests/test_context_quality.py tests/test_ai_context_batches.py tests/test_ai_context_fetch.py
git add qq_onebot_whitelist/context_quality.py qq_onebot_whitelist/llm_summary.py qq_onebot_whitelist/ai_context_analyze.py tests/test_context_quality.py tests/test_llm_summary.py tests/test_ai_context_batches.py
git commit -m "feat: classify AI context with tolerant parsing"
```

### Task 5: Split the Context View into Group/Date/Batch Pages

**Files:**
- Create: `qq_onebot_whitelist/context_view.py`
- Modify: `qq_onebot_whitelist/build_image_view.py`
- Replace: `tests/test_context_html_view.py`
- Create: `tests/test_context_view_quality.py`

- [ ] **Step 1: Write failing split-page tests**

Build a temporary database with two groups, two dates, high/review/low batches, one exactly linked image, and one legacy image without `message_db_id`. Assert:

```python
index = (context_dir / 'index.html').read_text(encoding='utf-8')
assert '<iframe' in index
assert '<details' in index
assert '测试群' in index
assert '2026-07-10' in index
assert '高价值摘要正文' not in index
assert (context_dir / 'batches' / '1.html').exists()
assert '高价值摘要正文' in (context_dir / 'batches' / '1.html').read_text(encoding='utf-8')
assert not (context_dir / 'batches' / '3.html').exists()  # low
assert '待复核' in index
assert any((context_dir / 'history').rglob('*.html'))
```

- [ ] **Step 2: Run view tests and verify RED**

Run:

```powershell
uv run --extra dev pytest -q tests/test_context_html_view.py tests/test_context_view_quality.py
```

Expected: FAIL because the current index embeds every card and no batch files exist.

- [ ] **Step 3: Implement context data loading**

Create `context_view.py` with these complete data-loading and assignment functions:

```python
def load_context_batches(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        'SELECT id, created_at, scope, start_message_id, end_message_id, model, summary, raw_json '
        'FROM ai_context_batches ORDER BY id DESC'
    ).fetchall()
    result = []
    for row in rows:
        try:
            raw = json.loads(row['raw_json'] or '{}')
        except Exception:
            raw = {}
        quality = raw.get('quality') or {}
        result.append({
            **dict(row),
            'value_level': quality.get('value_level') or 'review',
            'quality_reason': quality.get('reason') or '',
        })
    return result


def assign_context_images(images: list[dict], batches: list[dict]) -> tuple[dict[int, list[dict]], list[dict]]:
    assigned: dict[int, list[dict]] = {}
    legacy = []
    for image in images:
        message_db_id = image.get('message_db_id')
        if message_db_id is None:
            legacy.append(image)
            continue
        batch = next((item for item in batches if item['scope'] == image['scope'] and item['start_message_id'] <= message_db_id <= item['end_message_id']), None)
        if batch is None:
            legacy.append(image)
        else:
            assigned.setdefault(int(batch['id']), []).append(image)
    return assigned, legacy
```

Implement `write_context_view` by creating `batches/` and `history/`, writing one batch page for each `high` or `review` batch, writing one history page per `(scope, seen_at[:10])`, then building the sidebar from the generated relative paths. Use `<details open>` for the first hierarchy level, nested `<details>` for group/date, and `<iframe name="content" src="<first generated page>">`. Low batches are skipped and no image or database row is deleted.

Parse `raw_json.quality`; missing metadata becomes `review`. Match new images by scope and `start_message_id <= message_db_id <= end_message_id`. Group legacy images by displayed scope and local date only.

- [ ] **Step 4: Generate a small directory shell**

Generate `index.html` with a fixed left sidebar and right `iframe`. Sidebar hierarchy:

```text
高价值
  群名
    日期
      批次 #ID
待复核
  群名
    日期
      批次 #ID
历史未精确关联图片
  群名
    日期
```

Batch files live under `batches/<id>.html`; history files use safe group/date names under `history/`. Use only relative links and existing `render_markdown`.

- [ ] **Step 5: Delegate from `build_image_view.py`**

Keep image hard-link/copy logic in `build_image_view.py`, but pass copied context-image records and batch rows to `write_context_view`. Remove the old all-cards `write_context_html` implementation.

- [ ] **Step 6: Run view tests and commit**

Run:

```powershell
uv run --extra dev pytest -q tests/test_context_html_view.py tests/test_context_view_quality.py tests/test_view_index.py tests/test_image_file_sync.py
git add qq_onebot_whitelist/context_view.py qq_onebot_whitelist/build_image_view.py tests/test_context_html_view.py tests/test_context_view_quality.py
git commit -m "feat: split context view by group and date"
```

### Task 6: Add Tray Settings and Correct Startup/Exit Behavior

**Files:**
- Create: `scripts/windows/set-analysis-windows.ps1`
- Modify: `scripts/windows/qq-onebot-tray.ps1`
- Modify: `scripts/windows/start-qq-onebot-whitelist-hidden.ps1`
- Modify: `scripts/windows/stop-qq-onebot-whitelist-hidden.ps1`
- Modify: `scripts/windows/start-qq-onebot-whitelist.bat`
- Modify: `scripts/windows/launcher.config.ps1.example`
- Create: `tests/test_windows_scripts.py`

- [ ] **Step 1: Write failing script-contract tests**

Create text-based tests asserting:

```python
assert 'call .env' not in all_start_script_text.lower()
assert "runtime\\NapCat.Shell.Windows.Node" in hidden_start_text
assert "set-analysis-windows.ps1" in tray_text
assert tray_text.index('Stop all and exit') < tray_text.index('Exit tray (keep services running)')
```

Also assert the settings script invokes `qq_onebot_whitelist.settings` with `--get`, `--set`, and `--all-day`.

- [ ] **Step 2: Run script tests and verify RED**

Run:

```powershell
uv run --extra dev pytest -q tests/test_windows_scripts.py
```

Expected: FAIL on `call .env`, external-path requirement, and missing settings dialog.

- [ ] **Step 3: Implement the settings dialog**

Create an ASCII-only PowerShell 5.1 Windows Forms script with:

- Multiline textbox, one interval per line.
- `Save`, `All day`, and `Cancel` buttons.
- On load: run `uv run python -m qq_onebot_whitelist.settings --config config.yaml --get`.
- On save: join non-empty lines with commas and call `--set`.
- Show Python validation errors in a message box.

- [ ] **Step 4: Update tray behavior**

Add `Set analysis windows` before the separator. Order exit actions so `Stop all and exit` is the primary visible exit, while `Exit tray (keep services running)` remains available. Keep automatic startup when the tray launches.

- [ ] **Step 5: Use project-local NapCat and remove `.env` execution**

Set the default in both start and stop scripts:

```powershell
$NapcatDir = Join-Path $BotDir 'runtime\NapCat.Shell.Windows.Node'
if ($env:NAPCAT_DIR) { $NapcatDir = $env:NAPCAT_DIR }
if (Test-Path $LauncherConfig) { . $LauncherConfig }
```

Remove `if exist .env call .env &&` from all active start scripts. Keep `launcher.config.ps1` as an optional override only.

- [ ] **Step 6: Verify PowerShell and commit**

Run:

```powershell
uv run --extra dev pytest -q tests/test_windows_scripts.py
$errors=@(); Get-ChildItem scripts/windows -Filter *.ps1 | ForEach-Object { $t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$t,[ref]$e)|Out-Null; $errors += $e }; if($errors){$errors; exit 1}
git add scripts/windows tests/test_windows_scripts.py
git commit -m "feat: add tray schedule settings and local startup"
```

### Task 7: Stop Services and Move NapCat into the Project

**Files:**
- Move runtime directory: `D:\Hermes\Data\tools\napcat\NapCat.Shell.Windows.Node` → `runtime/NapCat.Shell.Windows.Node`
- Modify: `.gitignore`
- Modify: `docs/外部依赖.md`
- Modify: `docs/使用说明.md`
- Modify: `docs/交接文档.md`
- Modify: `README.md`

- [ ] **Step 1: Ignore the runtime before moving it**

Add:

```gitignore
runtime/
```

Run `git check-ignore -v runtime/NapCat.Shell.Windows.Node/napcat.bat` after creating an empty `runtime/` directory if needed.

- [ ] **Step 2: Stop bot and NapCat**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\stop-qq-onebot-whitelist-hidden.ps1"
```

Then verify no process command line contains `qq_onebot_whitelist.onebot` or the exact old NapCat path. Exclude the current inspection PowerShell process from matching.

- [ ] **Step 3: Verify absolute move boundaries**

Resolve and assert:

```powershell
$source = (Resolve-Path -LiteralPath 'D:\Hermes\Data\tools\napcat\NapCat.Shell.Windows.Node').Path
$workspace = (Resolve-Path '.').Path
$target = [IO.Path]::GetFullPath((Join-Path $workspace 'runtime\NapCat.Shell.Windows.Node'))
if(-not $target.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar)){throw 'Target escapes workspace'}
if(-not (Test-Path -LiteralPath (Join-Path $source 'napcat.bat'))){throw 'Source launcher missing'}
if(Test-Path -LiteralPath $target){throw 'Target already exists'}
```

- [ ] **Step 4: Move and verify the complete directory**

Run:

```powershell
New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
Move-Item -LiteralPath $source -Destination $target
if(-not (Test-Path -LiteralPath (Join-Path $target 'napcat.bat'))){throw 'Target launcher missing'}
if(Test-Path -LiteralPath $source){throw 'Source still exists'}
```

Record the target file count and byte total; compare with the pre-move values `704 files` and `334145801 bytes`.

- [ ] **Step 5: Update documentation and commit tracked changes**

Document that NapCat now lives in `runtime/`, starts automatically with the tray, and stops only for `Stop bot and NapCat` or `Stop all and exit`. Remove the claim that an external NapCat folder is required.

Run:

```powershell
git add .gitignore README.md docs scripts/windows/launcher.config.ps1.example
git commit -m "chore: move NapCat runtime into project"
```

The ignored `runtime/` directory must not appear in `git status`.

### Task 8: Final Verification and Baseline Completion

**Files:**
- Verify all tracked source, tests, docs, and scripts
- Rebuild ignored generated pages under `data/view/`

- [ ] **Step 1: Run the full automated suite**

Run:

```powershell
uv run --extra dev pytest -q
uv run python -m compileall -q qq_onebot_whitelist
```

Expected: all tests pass and compile exits `0`.

- [ ] **Step 2: Verify every PowerShell script parses under Windows PowerShell syntax**

Run the parser loop from Task 6 and require zero errors.

- [ ] **Step 3: Rebuild real local pages**

Run:

```powershell
uv run python -m qq_onebot_whitelist.maintenance --project-dir .
```

Verify:

- `data/view/03_AI上下文/index.html` contains an `iframe` and directory tree.
- Main index size remains small and does not contain complete batch summaries.
- `batches/` and `history/` files exist.
- `rg -n 'sk-[A-Za-z0-9_-]{20,}' data/view` returns no results.

- [ ] **Step 4: Verify local runtime and configuration**

Run:

```powershell
Test-Path runtime/NapCat.Shell.Windows.Node/napcat.bat
uv run python -m qq_onebot_whitelist.settings --config config.yaml --get
git check-ignore -v runtime/NapCat.Shell.Windows.Node/napcat.bat config.yaml data/bot.db .env
```

Expected: launcher exists, schedule reports all day, and all runtime/private paths are ignored.

- [ ] **Step 5: Install the shortcut and inspect it immediately**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-tray-shortcut.ps1"
```

Read the created `.lnk` through `WScript.Shell` and verify its target is the absolute Windows PowerShell executable and arguments include `qq-onebot-tray.ps1`.

- [ ] **Step 6: Commit final verification/doc adjustments**

Run:

```powershell
git add .
git diff --cached --check
git commit -m "docs: finalize local bot operation"
git status --short --branch
```

Expected: clean tracked working tree; only ignored runtime/data remain outside Git.

# Resource Context and Tray Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate the local resource library, private daily report, image-centered reusable context, and Windows runtime status while preserving existing data.

**Architecture:** Keep SQLite as the source of truth and preserve every raw occurrence. Apply conservative filtering and deduplication only when selecting local views and reports. Reuse the existing Windows PowerShell launcher and add a small JSON status probe plus tray timer instead of introducing a service manager.

**Tech Stack:** Python 3.11, SQLite, PyYAML, pytest, Windows PowerShell 5.1, WinForms.

---

### Task 1: Conservative resource selection and daily report

**Files:**
- Modify: `qq_onebot_whitelist/daily_report.py`
- Modify: `qq_onebot_whitelist/resource_view.py`
- Modify: `qq_onebot_whitelist/onebot.py`
- Test: `tests/test_daily_report.py`
- Test: `tests/test_daily_report_curated.py`
- Test: `tests/test_resource_view.py`

- [ ] Write failing tests proving unknown links are retained, link reports omit group names, file reports contain only file name and group, and an empty day returns `今日无新增资源`.
- [ ] Run the focused tests and verify failures come from the current score-based filtering and empty-report behavior.
- [ ] Replace positive-score admission with conservative rejection: discard only `is_low_value_link`, otherwise retain and deduplicate using `dedupe_url_key`.
- [ ] Use `群聊未说明用途` when message and quoted context do not explain a link.
- [ ] Simplify daily output to file name plus group and link plus one-line description; send and mark an empty report too.
- [ ] Run focused resource/report tests.

### Task 2: Preserve occurrences while deduplicating views

**Files:**
- Modify: `qq_onebot_whitelist/store.py`
- Modify: `qq_onebot_whitelist/resource_view.py`
- Test: `tests/test_resource_dedupe.py`
- Test: `tests/test_store_summary.py`

- [ ] Write failing tests proving duplicate file occurrences preserve all groups and duplicate link occurrences select the best available context.
- [ ] Run focused tests and verify the current first-item file selection loses groups.
- [ ] Keep raw `links` and `files` rows unchanged; aggregate occurrence scopes only in selectors.
- [ ] Render all groups for a deduplicated file and omit link source groups.
- [ ] Run focused deduplication tests.

### Task 3: Image-centered reusable context

**Files:**
- Modify: `qq_onebot_whitelist/llm_summary.py`
- Modify: `qq_onebot_whitelist/ai_context_analyze.py`
- Modify: `qq_onebot_whitelist/context_quality.py`
- Modify: `qq_onebot_whitelist/context_view.py`
- Test: `tests/test_llm_summary.py`
- Test: `tests/test_ai_context_quality_store.py`
- Test: `tests/test_context_view_quality.py`

- [ ] Write failing tests proving the prompt asks only for reusable image-generation evidence, empty evidence is stored only as a processed cursor, and no review value is exposed.
- [ ] Run focused tests and verify the chat-topic summary and review classification still appear.
- [ ] Change the LLM contract to concise reusable parameters with an explicit empty sentinel.
- [ ] Store empty batches with a hidden value used only to advance the cursor; do not create an HTML page for them.
- [ ] Remove review from display selection while preserving existing raw records.
- [ ] Run focused image-context tests.

### Task 4: Incremental startup history catch-up

**Files:**
- Modify: `config.yaml`
- Modify: `config.example.yaml`
- Modify: `qq_onebot_whitelist/onebot.py`
- Test: `tests/test_startup_history_all.py`
- Test: `tests/test_history_cursor.py`

- [ ] Write a failing test proving normal startup stops paging after encountering the saved newest sequence.
- [ ] Run the focused test and verify `all: true` bypasses the saved boundary.
- [ ] Set normal configuration to cursor-based incremental catch-up and retain explicit CLI full-history import for maintenance only.
- [ ] Run startup history tests.

### Task 5: Runtime status probe and tray supervision

**Files:**
- Create: `scripts/windows/get-qq-onebot-status.ps1`
- Modify: `scripts/windows/qq-onebot-tray.ps1`
- Modify: `scripts/windows/start-qq-onebot-whitelist-hidden.ps1`
- Modify: `scripts/windows/install-tray-shortcut.ps1`
- Test: `tests/test_windows_scripts.py`

- [ ] Write failing script-contract tests for NapCat, QQ account, OneBot and bot status, WebUI menu entry, restart action, timer supervision, manual-stop flag, and second-launch signal.
- [ ] Run the focused tests and verify each required contract is absent.
- [ ] Implement a JSON status probe using ports, owned process command lines, and NapCat `get_login_info` over HTTP/WebSocket-compatible API when available, with config-file fallback for the account.
- [ ] Add tray status rows, WebUI action, start/restart/stop actions, a ten-second timer, thirty-second restart cooldown, and a manual-stop marker.
- [ ] Make a second shortcut launch write a start-check signal before exiting; let the existing tray consume it.
- [ ] Run PowerShell parser and focused script tests.

### Task 6: Rebuild existing processed data and verify

**Files:**
- Modify: `docs/使用说明.md`
- Generated: `data/view/resources.html`
- Generated: `data/view/files.html`
- Generated: `data/view/03_AI上下文/**`

- [ ] Run the full pytest suite.
- [ ] Run Python compilation and PowerShell syntax parsing.
- [ ] Run `python -m qq_onebot_whitelist.maintenance --project-dir .` to rebuild local pages from existing records without new AI calls.
- [ ] Verify files are not downloaded, duplicate image files remain content-addressed, empty context text is absent, and generated HTML contains no secret-like values.
- [ ] Reinstall the tray shortcut, restart only the tray controller, and verify current NapCat/QQ/OneBot/bot status without stopping a healthy NapCat session.
- [ ] Commit implementation and confirm `git status` and `git fsck --full` are clean.

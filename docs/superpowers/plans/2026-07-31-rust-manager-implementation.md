# Rust Native Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build a native Rust manager with bilingual configuration, status/process controls, and a shortcut migration while preserving the existing Python/NapCat runtime.

**Architecture:** `manager/` contains a small `eframe/egui` desktop application. It invokes `scripts/windows/*.ps1` for process orchestration and `qq_onebot_whitelist/config_bridge.py` for YAML reads/writes. Python localization is shared by command replies and report-facing labels.

**Tech Stack:** Rust 2021, `eframe`, `serde`, `serde_json`; Python 3.11, PyYAML, pytest; Windows PowerShell scripts.

---

### Task 1: Add locale and configuration bridge

**Files:**
- Create: `qq_onebot_whitelist/i18n.py`
- Create: `qq_onebot_whitelist/config_bridge.py`
- Modify: `qq_onebot_whitelist/config.py`
- Modify: `config.example.yaml`
- Test: `tests/test_i18n.py`

- [ ] Add `ui.language` parsing with `en-US` and `zh-CN` validation and Windows locale fallback.
- [ ] Add a JSON bridge with `get` and `patch` subcommands; preserve unknown YAML keys and write atomically.
- [ ] Add focused tests for locale fallback and patch round-tripping.

### Task 2: Localize command responses

**Files:**
- Modify: `qq_onebot_whitelist/commands.py`
- Modify: `qq_onebot_whitelist/onebot.py`
- Test: `tests/test_commands.py`

- [ ] Replace single-language literals used by the command workflow with locale lookups while preserving Chinese aliases.
- [ ] Pass the configured locale into reply building and keep `help`/`帮助` behavior unchanged.
- [ ] Cover English default, Chinese override, aliases, and analysis-window errors.

### Task 3: Create the Rust manager

**Files:**
- Create: `manager/Cargo.toml`
- Create: `manager/src/main.rs`
- Create: `manager/src/i18n.rs`
- Create: `manager/src/process.rs`
- Create: `manager/src/config.rs`

- [ ] Add the app shell, bilingual labels, status cards, action buttons, configuration sections, and error banner.
- [ ] Implement bounded PowerShell command execution for status/start/stop/restart and opening logs/pages.
- [ ] Implement JSON bridge calls and basic form validation before writing.
- [ ] Add unit tests for locale selection, command construction, and invalid numeric fields.

### Task 4: Upgrade the Windows entry point

**Files:**
- Modify: `scripts/windows/install-tray-shortcut.ps1`
- Create: `scripts/windows/start-qq-onebot-manager.ps1`
- Modify: `scripts/windows/qq-onebot-tray.ps1`

- [ ] Make shortcuts target the Rust manager when `manager/target/release/qq-onebot-manager.exe` exists.
- [ ] Keep the current PowerShell tray as an explicit fallback.
- [ ] Use the same mutex and status script so only one entry point controls the services.

### Task 5: Verify and measure

**Files:**
- No source changes unless verification finds a defect.

- [ ] Run `cargo test` and `cargo build --release` in `manager/`.
- [ ] Run `uv run pytest -q` and `git diff --check`.
- [ ] Record release binary size and a short startup/idle observation in the completion note.

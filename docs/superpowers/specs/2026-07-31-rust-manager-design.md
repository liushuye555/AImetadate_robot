# Rust Native Manager Design

## Goal

Provide a lightweight native Windows manager for the QQ OneBot bot without a Web UI, WebView, Electron, Tauri, or a local HTTP server. The manager owns the operator workflow while NapCat and the existing Python bot remain the runtime backend.

## Decisions

- The manager is a Rust `eframe/egui` executable in `manager/`.
- The desktop shortcut starts the Rust executable and falls back to the existing PowerShell tray when the release binary is absent.
- Process control continues to call the existing PowerShell start/stop/status scripts. Rust does not duplicate NapCat or OneBot startup rules.
- Configuration is edited through a small Python helper that loads and writes YAML with the backend's existing semantics. Unknown YAML keys are preserved.
- The manager exposes a compact status view, start/stop/restart actions, log/data shortcuts, language selection, and an advanced configuration form.

## Language

The effective locale is selected in this order:

1. `ui.language` when set to `en-US` or `zh-CN`.
2. Windows user locale (`zh-*` selects Chinese; every other locale selects English).
3. English fallback.

The manager, tray labels, command replies, and daily report labels use the same locale. Chinese command aliases remain accepted in every locale. English is the fallback for missing translations.

## Configuration Contract

The helper returns a JSON snapshot for the manager and accepts a JSON patch. Current fields include OneBot URL, reply whitelist and group policy, summary limits, image retention, startup history, AI context, and `ui.language`. The helper writes only fields represented by the patch and leaves unrelated YAML content intact.

## Failure Handling

Start, stop, status, and config operations are bounded subprocess calls. Failures are shown in the manager with the command output and log directory. A failed start is not retried by the Rust process; the existing tray/start scripts keep their current retry and ownership checks.

## Acceptance Criteria

- No embedded browser or HTTP listener.
- English by default on non-Chinese Windows installations; Chinese on `zh-*` Windows installations.
- Existing Chinese commands continue to work.
- `cargo test`, `cargo build --release`, and the existing Python test suite pass.
- The release binary and idle behavior are measured before claiming NapCat-like resource usage.

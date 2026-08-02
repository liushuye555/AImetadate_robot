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


def status_path() -> Path:
    return RUN_DIR / "status.json"


def write_status(data: dict) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = status_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(status_path())


def load_status() -> dict:
    if not status_path().exists():
        return {}
    return json.loads(status_path().read_text(encoding="utf-8"))


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

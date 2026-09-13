from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

import yaml

from .schedule import normalize_time_windows, normalize_weekdays


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    for attempt in range(20):
        try:
            return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01)


def _atomic_write_yaml(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent, prefix=target.name + '.', suffix='.tmp', delete=False) as file:
        temporary = Path(file.name)
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
        file.flush()
        os.fsync(file.fileno())
    try:
        for attempt in range(20):
            try:
                temporary.replace(target)  # 写好的临时文件原子替换 config
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


def read_analysis_windows(path: str | Path) -> list[str]:
    raw = _read_yaml(Path(path))
    return normalize_time_windows(list((raw.get('ai_context') or {}).get('allowed_windows') or []))


def write_analysis_windows(path: str | Path, windows: list[str]) -> list[str]:
    target = Path(path)
    normalized = normalize_time_windows(windows)
    raw = _read_yaml(target)
    raw.setdefault('ai_context', {})['allowed_windows'] = normalized
    _atomic_write_yaml(target, raw)
    return normalized


def read_all_day_weekdays(path: str | Path) -> list[str]:
    raw = _read_yaml(Path(path))
    return normalize_weekdays((raw.get('ai_context') or {}).get('all_day_weekdays') or [])


def write_all_day_weekdays(path: str | Path, weekdays: list[str]) -> list[str]:
    target = Path(path)
    normalized = normalize_weekdays(weekdays)
    raw = _read_yaml(target)
    raw.setdefault('ai_context', {})['all_day_weekdays'] = normalized
    _atomic_write_yaml(target, raw)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--json', action='store_true')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--get', action='store_true')
    action.add_argument('--set')
    action.add_argument('--all-day', action='store_true')
    action.add_argument('--all-day-weekdays')
    args = parser.parse_args()
    if args.get:
        windows = read_analysis_windows(args.config)
        if args.json:
            print(json.dumps(windows))  # 托盘脚本契约：纯数组
        else:
            weekdays = read_all_day_weekdays(args.config)
            suffix = f"（全天开放：{'、'.join(weekdays)}）" if weekdays else ''
            print(('\n'.join(windows) if windows else '全天') + suffix)
        return 0
    if args.all_day_weekdays is not None:
        weekdays = write_all_day_weekdays(
            args.config, [item.strip() for item in args.all_day_weekdays.split(',') if item.strip()]
        )
    elif args.all_day:
        windows = write_analysis_windows(args.config, [])
        weekdays = read_all_day_weekdays(args.config)
    else:
        weekdays = read_all_day_weekdays(args.config)
        windows = write_analysis_windows(
            args.config, [item.strip() for item in args.set.split(',') if item.strip()]
        )
    print(json.dumps({'windows': windows, 'all_day_weekdays': weekdays}) if args.json
          else ('\n'.join(windows) if windows else '全天'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

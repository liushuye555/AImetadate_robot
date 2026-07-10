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
        windows = write_analysis_windows(args.config, [item.strip() for item in args.set.split(',') if item.strip()])
    print('\n'.join(windows) if windows else '全天')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

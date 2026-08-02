from __future__ import annotations

import argparse
from pathlib import Path

from .build_image_view import build_view
from .resource_view import write_resource_pages
from .store import Store


def deduplicate_image_storage(project_dir: str | Path, store: Store) -> int:
    project_dir = Path(project_dir)
    archive_root = project_dir / 'data' / 'images' / 'ai'
    candidate_root = project_dir / 'data' / 'images' / 'candidates'
    archive = {path.stem: path for path in archive_root.rglob('*') if path.is_file()}
    candidates = {path.stem: path for path in candidate_root.rglob('*') if path.is_file()}
    removed = 0
    for digest, candidate in candidates.items():
        target = archive.get(digest)
        if target is None:
            continue
        candidate.unlink(missing_ok=True)
        removed += 1
    for digest, path in {**candidates, **archive}.items():
        target = archive.get(digest) or path
        store.set_image_path_for_sha(digest, target)
    return removed


def prune_empty_dirs(root: str | Path) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    removed = 0
    dirs = sorted([p for p in root.rglob('*') if p.is_dir()], key=lambda p: len(p.parts), reverse=True)
    for path in dirs:
        try:
            path.rmdir()
            removed += 1
        except OSError:
            pass
    return removed


def sync_image_files(project_dir: str | Path) -> dict[str, int]:
    project_dir = Path(project_dir)
    store = Store(project_dir / 'data' / 'bot.db')
    image_duplicates_removed = deduplicate_image_storage(project_dir, store)
    missing_cleared = store.clear_missing_image_paths(project_dir)
    empty_candidate_dirs = prune_empty_dirs(project_dir / 'data' / 'images' / 'candidates')
    counts = build_view(project_dir)
    resource_counts = write_resource_pages(project_dir / 'data' / 'view', store)
    return {'image_duplicates_removed': image_duplicates_removed, 'missing_cleared': missing_cleared, 'empty_candidate_dirs': empty_candidate_dirs, **counts, **resource_counts}


def main() -> int:
    parser = argparse.ArgumentParser(description='Synchronize image DB paths with disk and rebuild view')
    parser.add_argument('--project-dir', default='.')
    args = parser.parse_args()
    result = sync_image_files(Path(args.project_dir).resolve())
    for key, value in sorted(result.items()):
        print(f'{key}: {value}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

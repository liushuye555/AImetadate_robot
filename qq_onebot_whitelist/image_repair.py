from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .image_meta import extract_prompt_signature, parse_image_metadata
from .images import download_image, sha256_file, verify_image_file


def _filename_hint(record: dict[str, Any]) -> str | None:
    image = record.get('raw', {}).get('image') or {}
    return str(image.get('file') or image.get('filename') or '') or None


def _archive_download(path: Path, url: str, archive_root: Path) -> dict[str, Any]:
    digest = sha256_file(path)
    meta = parse_image_metadata(path)
    destination = archive_root / digest[:2] / f'{digest}{path.suffix or ".img"}'
    destination.parent.mkdir(parents=True, exist_ok=True)
    if verify_image_file(destination) is not None:
        staged = destination.with_name(destination.name + '.repair')
        staged.unlink(missing_ok=True)
        try:
            os.replace(path, staged)
        except OSError:
            shutil.move(str(path), str(staged))
        os.replace(staged, destination)
    else:
        path.unlink(missing_ok=True)
    return {
        'url': url, 'sha256': digest, 'size': destination.stat().st_size,
        'format': meta.format, 'width': meta.width, 'height': meta.height,
        'metadata_keys': meta.metadata_keys, 'has_ai_metadata': meta.has_ai_metadata,
        'ai_source': meta.ai_source, 'text_excerpt': meta.text_excerpt,
        'prompt_key': extract_prompt_signature(destination) if meta.has_ai_metadata else None,
        'kept_path': str(destination),
    }


def _same_batch_replacement(store, record: dict[str, Any]) -> dict[str, Any] | None:
    """优先找同批已完整归档的图片，避免再次请求已经失效的 QQ 链接。"""
    for candidate in store.same_batch_image_records(int(record['id'])):
        path = Path(str(candidate.get('kept_path') or ''))
        if path.exists() and verify_image_file(path) is None:
            return candidate
    return None


def _replacement_result(source: dict[str, Any]) -> dict[str, Any]:
    return {key: source.get(key) for key in (
        'url', 'sha256', 'size', 'format', 'width', 'height', 'metadata_keys',
        'has_ai_metadata', 'ai_source', 'text_excerpt', 'prompt_key', 'kept_path',
    )}


def repair_image(store, image_id: int, *, tmp_dir: str | Path, archive_root: str | Path) -> dict[str, Any]:
    """用同批正常图替换，否则才重新下载；只接受完整可解码图片。"""
    record = store.get_image_record(int(image_id))
    if record is None:
        return {'status': 'missing', 'id': int(image_id), 'reason': 'image record not found'}
    local_replacement = _same_batch_replacement(store, record)
    if local_replacement is not None:
        store.update_repaired_image(int(image_id), _replacement_result(local_replacement))
        return {
            'status': 'repaired', 'id': int(image_id),
            'source_id': int(local_replacement['id']),
            'path': str(local_replacement['kept_path']),
        }
    url = str(record.get('url') or '')
    old_path = Path(str(record.get('kept_path') or ''))
    if not url:
        return {'status': 'failed', 'id': int(image_id), 'reason': 'original URL is unavailable'}
    try:
        downloaded = download_image(url, Path(tmp_dir), filename_hint=_filename_hint(record))
        validation_error = verify_image_file(downloaded)
        if validation_error:
            downloaded.unlink(missing_ok=True)
            return {'status': 'failed', 'id': int(image_id), 'reason': validation_error}
        result = _archive_download(downloaded, url, Path(archive_root))
        store.update_repaired_image(int(image_id), result)
        new_path = Path(result['kept_path'])
        if old_path and old_path.resolve() != new_path.resolve():
            old_path.unlink(missing_ok=True)
        return {'status': 'repaired', 'id': int(image_id), 'path': result['kept_path']}
    except Exception as exc:
        return {'status': 'failed', 'id': int(image_id), 'reason': f'{type(exc).__name__}: {exc}'}


def repair_damaged_images(store, *, tmp_dir: str | Path, archive_root: str | Path) -> dict[str, int]:
    summary = {'scanned': 0, 'damaged': 0, 'repaired': 0, 'failed': 0}
    for record in store.image_records_with_paths():
        summary['scanned'] += 1
        if verify_image_file(record['kept_path']) is None:
            continue
        summary['damaged'] += 1
        result = repair_image(store, int(record['id']), tmp_dir=tmp_dir, archive_root=archive_root)
        if result['status'] == 'repaired':
            summary['repaired'] += 1
        else:
            summary['failed'] += 1
    return summary
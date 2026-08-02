from __future__ import annotations

from pathlib import Path
import hashlib
import shutil
import urllib.request
from urllib.parse import urlparse

from .image_meta import ImageMetadata, parse_image_metadata
from .image_policy import should_keep_image


def is_sticker_image_segment(data: dict) -> bool:
    summary = str(data.get('summary') or '')
    sub_type = str(data.get('sub_type') or '')
    if '表情' in summary or '动画表情' in summary:
        return True
    if sub_type == '1' and summary and '图片' not in summary:
        return True
    # NapCat animated stickers are often jpg with small file_size and explicit sticker-like summary.
    return False


def extract_image_segments(event: dict) -> list[dict]:
    segments = []
    message = event.get('message')
    if isinstance(message, list):
        for seg in message:
            if seg.get('type') == 'image':
                data = seg.get('data') or {}
                if is_sticker_image_segment(data):
                    continue
                url = data.get('url') or data.get('file_url')
                if url:
                    segments.append(data | {'url': url})
    return segments


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download_image(url: str, tmp_dir: Path, filename_hint: str | None = None, timeout: int = 30) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename_hint or urlparse(url).path).suffix or '.img'
    out = tmp_dir / (hashlib.sha1(url.encode('utf-8')).hexdigest() + suffix)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp, out.open('wb') as f:
        shutil.copyfileobj(resp, f)
    return out


def archive_image(tmp: Path, archive_root: Path, digest: str) -> Path:
    ext = tmp.suffix or '.img'
    dest = archive_root / digest[:2] / f'{digest}{ext}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.move(str(tmp), str(dest))
    else:
        tmp.unlink(missing_ok=True)
    return dest


def existing_content_path(digest: str, archive_root: Path, candidate_root: Path | None) -> Path | None:
    roots = [archive_root]
    if candidate_root is not None:
        roots.append(candidate_root)
    for root in roots:
        matches = list((root / digest[:2]).glob(digest + '.*'))
        if matches:
            return matches[0]
    return None


def is_probable_sticker_result(result: dict) -> bool:
    if result.get('has_ai_metadata'):
        return False
    fmt = str(result.get('format') or '').upper()
    size = int(result.get('size') or 0)
    width = result.get('width')
    height = result.get('height')
    if fmt == 'GIF':
        return True
    if width is None or height is None:
        return size and size < 600_000 and fmt in {'JPEG', 'JPG', 'PNG', 'WEBP'}
    if width <= 360 and height <= 360 and size < 600_000:
        return True
    if width <= 700 and height <= 700 and abs(width - height) <= 80 and size < 150_000:
        return True
    if height and width / max(height, 1) >= 4 and size < 200_000:
        return True
    return False


def process_image_url(
    url: str,
    *,
    tmp_dir: Path,
    archive_root: Path,
    candidate_root: Path | None = None,
    filename_hint: str | None = None,
    nearby_text: str = '',
) -> dict:
    tmp = download_image(url, tmp_dir, filename_hint=filename_hint)
    size = tmp.stat().st_size
    digest = sha256_file(tmp)
    meta = parse_image_metadata(tmp)
    keep, reason = should_keep_image(meta, nearby_text=nearby_text)
    kept_path = None
    existing = existing_content_path(digest, archive_root, candidate_root)
    if existing is not None:
        tmp.unlink(missing_ok=True)
        if keep and candidate_root is not None and str(existing).startswith(str(candidate_root)):
            kept_path = archive_root / digest[:2] / existing.name
            kept_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(existing), str(kept_path))
        elif str(existing).startswith(str(archive_root)):
            kept_path = existing
            reason = reason if keep else 'candidate'
        else:
            kept_path = existing
            reason = 'candidate'
    elif keep:
        kept_path = archive_image(tmp, archive_root, digest)
    elif candidate_root is not None:
        kept_path = archive_image(tmp, candidate_root, digest)
        reason = 'candidate'
    else:
        tmp.unlink(missing_ok=True)
    return {
        'url': url,
        'sha256': digest,
        'size': size,
        'format': meta.format,
        'width': meta.width,
        'height': meta.height,
        'metadata_keys': meta.metadata_keys,
        'has_ai_metadata': meta.has_ai_metadata,
        'ai_source': meta.ai_source,
        'text_excerpt': meta.text_excerpt,
        'kept_path': str(kept_path) if kept_path else None,
        'retention_reason': reason,
    }

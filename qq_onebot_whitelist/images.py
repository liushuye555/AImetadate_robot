from __future__ import annotations

from pathlib import Path
import hashlib
import shutil
import tempfile
import urllib.request
from urllib.parse import urlparse

from .image_meta import ImageMetadata, extract_prompt_signature, parse_image_metadata
from .image_policy import should_keep_image
from .obfuscation import image_phash, jpeg_blockiness


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


def verify_image_file(path: str | Path) -> str | None:
    """Return an error for an image Pillow cannot fully decode, else ``None``."""
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except Exception as exc:
        return f'invalid or truncated image: {exc or type(exc).__name__}'
    return None


def download_image(url: str, tmp_dir: Path, filename_hint: str | None = None, timeout: int = 30) -> Path:
    """下载到每次独占的临时文件，避免相同 QQ 链接并发写入互相覆盖。"""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename_hint or urlparse(url).path).suffix or '.img'
    handle = tempfile.NamedTemporaryFile(
        mode='wb', prefix='.download-', suffix=suffix, dir=tmp_dir, delete=False,
    )
    out = Path(handle.name)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with handle, urllib.request.urlopen(req, timeout=timeout) as resp:
            shutil.copyfileobj(resp, handle)
        return out
    except Exception:
        out.unlink(missing_ok=True)
        raise


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
    return is_sticker_format(result)


def is_sticker_format(result: dict) -> bool:
    """表情包格式特征：低分辨率/小体积/GIF。"""
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


def is_junk_image(result: dict) -> bool:
    """明显非 AI 内容：GIF / 表情包 / 超宽超高条状（截图条、长条 banner）。"""
    if result.get('has_ai_metadata'):
        return False
    if str(result.get('format') or '').upper() == 'GIF':
        return True
    if is_sticker_format(result):
        return True
    width = result.get('width')
    height = result.get('height')
    if width and height:
        ratio = max(width, height) / max(1, min(width, height))
        if ratio >= 2.6 or ratio <= 0.39:
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
    force_keep: bool = False,
    force_reason: str = 'manual_saved',
) -> dict:
    tmp = download_image(url, tmp_dir, filename_hint=filename_hint)
    validation_error = verify_image_file(tmp)
    if validation_error:
        tmp.unlink(missing_ok=True)
        raise ValueError(validation_error)
    size = tmp.stat().st_size
    digest = sha256_file(tmp)
    try:
        phash_value = image_phash(tmp)
    except Exception:
        phash_value = None
    meta = parse_image_metadata(tmp)
    prompt_key = extract_prompt_signature(tmp) if meta.has_ai_metadata else None
    try:
        blockiness_value = jpeg_blockiness(tmp) if str(meta.format or '').upper().startswith('JPEG') else 0.0
    except Exception:
        blockiness_value = 0.0
    keep, reason = should_keep_image(meta, nearby_text=nearby_text)
    if force_keep:
        keep, reason = True, (force_reason or 'manual_saved')
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
        'phash': phash_value,
        'blockiness': blockiness_value,
        'size': size,
        'format': meta.format,
        'width': meta.width,
        'height': meta.height,
        'metadata_keys': meta.metadata_keys,
        'has_ai_metadata': meta.has_ai_metadata,
        'ai_source': meta.ai_source,
        'text_excerpt': meta.text_excerpt,
        'prompt_key': prompt_key,
        'kept_path': str(kept_path) if kept_path else None,
        'retention_reason': reason,
        'already_archived': existing is not None,
    }

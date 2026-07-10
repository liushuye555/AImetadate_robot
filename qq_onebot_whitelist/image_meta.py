from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
import zlib


@dataclass(slots=True)
class ImageMetadata:
    format: str
    width: int | None = None
    height: int | None = None
    metadata_keys: list[str] = field(default_factory=list)
    text_excerpt: str = ''
    has_ai_metadata: bool = False
    ai_source: str | None = None


AI_MARKERS = {
    'ComfyUI': ['comfyui', 'workflow', 'class_type', 'ksampler'],
    'NovelAI': ['novelai', 'ucPreset', 'steps', 'scale'],
    'A1111': ['negative prompt', 'cfg scale', 'sampler:', 'steps:', 'seed:'],
    'Civitai': ['civitai'],
    'DALL-E/OpenAI': ['dall-e', 'dalle', 'openai'],
    'Midjourney': ['midjourney'],
    'Firefly': ['firefly'],
}


def parse_image_metadata(path: str | Path) -> ImageMetadata:
    path = Path(path)
    with path.open('rb') as f:
        sig = f.read(12)
    if sig.startswith(b'\x89PNG\r\n\x1a\n'):
        return _parse_png(path)
    if sig.startswith(b'\xff\xd8'):
        return _parse_jpeg(path)
    if sig[:4] == b'RIFF' and sig[8:12] == b'WEBP':
        return _parse_webp(path)
    return ImageMetadata(format=path.suffix.lower().lstrip('.') or 'unknown')


def _parse_png(path: Path) -> ImageMetadata:
    meta = ImageMetadata(format='PNG')
    texts: list[str] = []
    with path.open('rb') as f:
        f.read(8)
        while True:
            raw_len = f.read(4)
            if len(raw_len) != 4:
                break
            length = struct.unpack('>I', raw_len)[0]
            kind = f.read(4)
            if len(kind) != 4:
                break
            data = f.read(length)
            f.read(4)  # crc
            if kind == b'IHDR' and len(data) >= 8:
                meta.width, meta.height = struct.unpack('>II', data[:8])
            elif kind == b'tEXt':
                key, text = _split_null(data)
                _add_text(meta, texts, key, text.decode('utf-8', 'ignore'))
            elif kind == b'zTXt':
                key, rest = _split_null(data)
                if rest:
                    text = ''
                    for payload in (rest[1:], rest):
                        try:
                            text = zlib.decompress(payload).decode('utf-8', 'ignore')
                            break
                        except Exception:
                            continue
                    _add_text(meta, texts, key, text)
            elif kind == b'iTXt':
                key, rest = _split_null(data)
                text = rest.decode('utf-8', 'ignore')
                _add_text(meta, texts, key, text)
            elif kind == b'IEND':
                break
    _classify_ai(meta, '\n'.join(texts))
    return meta


def _parse_jpeg(path: Path) -> ImageMetadata:
    meta = ImageMetadata(format='JPEG')
    texts: list[str] = []
    with path.open('rb') as f:
        if f.read(2) != b'\xff\xd8':
            return meta
        while True:
            marker_prefix = f.read(1)
            if not marker_prefix:
                break
            if marker_prefix != b'\xff':
                continue
            marker = f.read(1)
            if not marker or marker in {b'\xd9', b'\xda'}:
                break
            size_raw = f.read(2)
            if len(size_raw) != 2:
                break
            size = struct.unpack('>H', size_raw)[0]
            data = f.read(max(0, size - 2))
            if marker in {b'\xe1', b'\xed', b'\xfe'}:
                text = data.decode('utf-8', 'ignore')
                _add_text(meta, texts, f'APP/{marker.hex()}'.encode(), text)
            elif marker in {b'\xc0', b'\xc1', b'\xc2', b'\xc3', b'\xc5', b'\xc6', b'\xc7', b'\xc9', b'\xca', b'\xcb', b'\xcd', b'\xce', b'\xcf'} and len(data) >= 5:
                meta.height, meta.width = struct.unpack('>HH', data[1:5])
    _classify_ai(meta, '\n'.join(texts))
    return meta


def _parse_webp(path: Path) -> ImageMetadata:
    meta = ImageMetadata(format='WEBP')
    texts: list[str] = []
    with path.open('rb') as f:
        f.read(12)
        while True:
            kind = f.read(4)
            if len(kind) != 4:
                break
            raw_len = f.read(4)
            if len(raw_len) != 4:
                break
            length = struct.unpack('<I', raw_len)[0]
            data = f.read(length)
            if length % 2:
                f.read(1)
            if kind in {b'EXIF', b'XMP '}:
                _add_text(meta, texts, kind, data.decode('utf-8', 'ignore'))
    _classify_ai(meta, '\n'.join(texts))
    return meta


def _split_null(data: bytes) -> tuple[bytes, bytes]:
    if b'\x00' not in data:
        return data, b''
    return data.split(b'\x00', 1)


def _add_text(meta: ImageMetadata, texts: list[str], key: bytes, text: str) -> None:
    key_text = key.decode('utf-8', 'ignore') or 'text'
    if key_text not in meta.metadata_keys:
        meta.metadata_keys.append(key_text)
    if text:
        texts.append(key_text + ': ' + text)
        if not meta.text_excerpt:
            meta.text_excerpt = text[:500]


def _classify_ai(meta: ImageMetadata, text: str) -> None:
    lower = text.lower()
    for source, markers in AI_MARKERS.items():
        if any(marker.lower() in lower for marker in markers):
            meta.has_ai_metadata = True
            meta.ai_source = source
            return

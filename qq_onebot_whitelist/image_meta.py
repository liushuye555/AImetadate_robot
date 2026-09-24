from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import gzip
import json
import struct
import zlib


@dataclass(slots=True)
class ImageMetadata:
    format: str
    width: int | None = None
    height: int | None = None
    metadata_keys: list[str] = field(default_factory=list)
    text_excerpt: str = ''
    # 完整元数据文本（text_excerpt 只有 500 字符截断，数据集导出等场景用全文）
    full_text: str = ''
    # 按 chunk 键索引的原文（parameters/prompt/Comment 等），提取提示词时按键取用
    text_by_key: dict[str, str] = field(default_factory=dict)
    has_ai_metadata: bool = False
    ai_source: str | None = None
    # NovelAI alpha 通道隐写：None=未检查；'suspected'=发现疑似载荷；'verified'=验证通过
    stego_state: str | None = None
    stego_excerpt: str = ''


# 来源判定分级：
# - strong：来源专有的结构/签名，命中即可确认（ucPreset 是 NovelAI 软件专有键，
#   class_type/ksampler 是 ComfyUI 工作流专有）；
# - weak：通用参数词（steps/scale 同样见于 A1111/WebUI 参数块），单独命中
#   只给"疑似"（ai_source 前缀 suspect:），不直接定来源——旧规则里
#   NovelAI 排在 A1111 之前，纯 WebUI 参数图曾被误标为 NovelAI。
AI_MARKERS_STRONG = {
    'ComfyUI': ['comfyui', 'class_type', 'ksampler'],
    'NovelAI': ['novelai', 'ucpreset'],
    'A1111': ['negative prompt'],
    'Civitai': ['civitai'],
    'DALL-E/OpenAI': ['dall-e', 'dalle', 'openai'],
    'Midjourney': ['midjourney'],
    'Firefly': ['firefly'],
}
AI_MARKERS_WEAK = {
    'NovelAI': ['steps', 'scale'],
    'ComfyUI': ['workflow'],
    'A1111': ['cfg scale', 'sampler:', 'steps:', 'seed:'],
}
SUSPECT_PREFIX = 'suspect:'

# NovelAI alpha 通道隐写（stealth pnginfo）格式：alpha 最低位按 x 外层、y 内层
# 逐像素展开成比特流，开头是签名 "stealth_pnginfo"（明文）或 "stealth_pngcomp"
# （gzip 压缩），随后 32 位大端长度（比特数），再是载荷本体。
STEGO_SIGNATURES = ('stealth_pnginfo', 'stealth_pngcomp')
_STEGO_MAX_PIXELS = 24_000_000  # 解码上限，防超大图拖慢采集


def classify_ai_source(text: str) -> tuple[bool, str | None]:
    """返回 (有 AI 元数据证据, 来源或疑似来源)。强证据优先；弱证据只给疑似。"""
    lower = text.lower()
    for source, markers in AI_MARKERS_STRONG.items():
        if any(marker.lower() in lower for marker in markers):
            return True, source
    for source, markers in AI_MARKERS_WEAK.items():
        if any(marker.lower() in lower for marker in markers):
            return True, SUSPECT_PREFIX + source
    return False, None


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
    meta.full_text = '\n'.join(texts)
    _classify_ai(meta, meta.full_text)
    _check_alpha_stego(path, meta)
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
    meta.full_text = '\n'.join(texts)
    _classify_ai(meta, meta.full_text)
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
    meta.full_text = '\n'.join(texts)
    _classify_ai(meta, meta.full_text)
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
        meta.text_by_key.setdefault(key_text, text)
        if not meta.text_excerpt:
            meta.text_excerpt = text[:500]


def _decode_stego_bits(img) -> tuple[str, str] | None:
    """从 PIL 图的 alpha 最低位提取 stealth pnginfo 载荷。

    返回 ('suspected', '') 表示签名命中但载荷没解出（截断/损坏/格式变体）；
    返回 ('verified', 文本) 表示完整解出可读元数据；None 表示没有隐写迹象。
    """
    if img.mode != 'RGBA':
        return None
    width, height = img.size
    if width * height > _STEGO_MAX_PIXELS:
        return None
    pixels = img.load()

    def bit_at(index: int) -> int:
        # 写入端按 x 外层、y 内层展开，比特 i 位于像素 (i // height, i % height)
        return pixels[index // height, index % height][3] & 1

    sig_bits_len = len(STEGO_SIGNATURES[0]) * 8
    if sig_bits_len > width * height:
        return None
    sig_stream = bytes(bit_at(i) for i in range(sig_bits_len))
    matched_sig = None
    for sig in STEGO_SIGNATURES:
        sig_bits = bytes(int(b) for byte in sig.encode('utf-8') for b in format(byte, '08b'))
        if sig_stream == sig_bits:
            matched_sig = sig
            break
    if not matched_sig:
        return None
    compressed = matched_sig == 'stealth_pngcomp'

    pos = sig_bits_len

    def take(count: int) -> bytes | None:
        nonlocal pos
        if pos + count > width * height:
            return None
        out = bytes(bit_at(i) for i in range(pos, pos + count))
        pos += count
        return out

    def to_bytes(bits: bytes) -> bytes:
        return bytes(int(''.join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8))

    len_bits = take(32)
    if not len_bits:
        return 'suspected', ''
    payload_bit_len = int.from_bytes(to_bytes(len_bits), 'big')
    if payload_bit_len <= 0 or payload_bit_len % 8 or payload_bit_len > 16_000_000:
        return 'suspected', ''
    payload_bits = take(payload_bit_len)
    if not payload_bits:
        return 'suspected', ''
    payload = to_bytes(payload_bits)
    if compressed:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            return 'suspected', ''
    text = payload.decode('utf-8', errors='replace').strip()
    if not text:
        return 'suspected', ''
    # 验证通过的标准：载荷是可读文本（NovelAI 是 JSON 或提示词参数块）
    printable = sum(ch.isprintable() or ch in '\r\n\t' for ch in text)
    if printable / max(1, len(text)) < 0.9:
        return 'suspected', ''
    return 'verified', text[:2000]


def _check_alpha_stego(path: Path, meta: ImageMetadata) -> None:
    """独立的隐写检查步骤：不改变文本元数据结论，只补 stego_state/stego_excerpt。"""
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.load()
            result = _decode_stego_bits(img)
    except Exception:
        result = None
    if not result:
        return
    meta.stego_state, meta.stego_excerpt = result
    if result[0] == 'verified':
        meta.metadata_keys.append('stealth_pnginfo')
        meta.text_excerpt = meta.text_excerpt or meta.stego_excerpt[:500]
        meta.text_by_key.setdefault('stealth_pnginfo', meta.stego_excerpt)
        meta.full_text = meta.full_text or meta.stego_excerpt
        # 隐写载荷本身就是生成参数：据此提升 AI 判定
        if not meta.has_ai_metadata:
            meta.has_ai_metadata, meta.ai_source = True, 'NovelAI'
        elif meta.ai_source and meta.ai_source.startswith(SUSPECT_PREFIX):
            meta.ai_source = 'NovelAI'


def _classify_ai(meta: ImageMetadata, text: str) -> None:
    meta.has_ai_metadata, meta.ai_source = classify_ai_source(text)


def extract_prompt_signature(path: str | Path) -> str | None:
    """从图片元数据的 prompt 图谱提取"完整工作流签名"，返回 sha1 前 16 位。

    用于"同批"分组：完整工作流（模型/采样器/提示词等全部输入）一致 → 同一批；
    仅提示词相同但模型/配置不同的不同批次 → 不同签名（避免误并成一组）。
    无元数据/无文本节点返回 None。
    """
    import hashlib
    import json

    from PIL import Image

    path = Path(path)
    try:
        with Image.open(path) as img:
            prompt = img.info.get('prompt')
    except Exception:
        return None
    if isinstance(prompt, bytes):
        prompt = prompt.decode('utf-8', errors='replace')
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    try:
        data = json.loads(prompt)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return hashlib.sha1(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8', errors='replace')
    ).hexdigest()[:16]

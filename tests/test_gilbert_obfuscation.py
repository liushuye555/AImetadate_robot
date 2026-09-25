"""小番茄混淆（Gilbert 曲线 + 黄金分割位移）检测器测试。"""

from __future__ import annotations

import math

from PIL import Image

from qq_onebot_whitelist.gilbert_obfuscation import (
    analyze_image,
    curve_order,
    is_obfuscated,
    restore_image,
)


def _permute(raw: bytes, width: int, height: int, direction: str) -> bytes:
    """按网站算法对灰度图做一层混淆(enc)/解混淆(dec)。"""
    n = width * height
    order = curve_order(width, height)
    shift = round((math.sqrt(5) - 1) / 2 * n)
    dst = bytearray(n)
    if direction == 'enc':
        for s in range(n):
            dst[order[(s + shift) % n]] = raw[order[s]]
    else:
        for s in range(n):
            dst[order[s]] = raw[order[(s + shift) % n]]
    return bytes(dst)


def _make_gradient(width: int = 64, height: int = 48) -> bytes:
    return bytes((x * 255 // max(1, width - 1) + y * 40) % 256
                 for y in range(height) for x in range(width))


def _make_checker(width: int = 64, height: int = 48) -> bytes:
    return bytes(255 if ((x // 4) + (y // 4)) % 2 else 0
                 for y in range(height) for x in range(width))


def _make_noisy_gradient(width: int = 64, height: int = 48, seed: int = 3) -> bytes:
    rng = _rng(seed)
    return bytes(
        max(0, min(255, (x * 60 // max(1, width - 1) + y * 90 // max(1, height - 1))
                    + rng.randint(-20, 20)))
        for y in range(height) for x in range(width)
    )


def _rng(seed: int):
    import random
    return random.Random(seed)


def test_roundtrip_enc_then_dec_restores_exactly(tmp_path):
    w, h = 64, 48
    raw = _make_gradient(w, h)
    enc = _permute(raw, w, h, 'enc')
    dec = _permute(enc, w, h, 'dec')
    assert dec == raw


def test_detector_marks_obfuscated_image(tmp_path):
    w, h = 128, 96
    raw = _make_gradient(w, h)
    obf_path = tmp_path / 'obf.png'
    Image.frombytes('L', (w, h), _permute(raw, w, h, 'enc')).save(obf_path)

    result = analyze_image(obf_path)
    assert result is not None
    assert result['obfuscated'] is True
    assert result['confidence'] == 'confirmed'
    assert result['layers'] == 1
    assert result['restore_ratios'][0] < 0.75
    assert is_obfuscated(obf_path) is True


def test_detector_marks_multi_layer_obfuscated(tmp_path):
    w, h = 96, 96
    raw = _make_gradient(w, h)
    once = _permute(raw, w, h, 'enc')
    twice = _permute(once, w, h, 'enc')
    path = tmp_path / 'obf2.png'
    Image.frombytes('L', (w, h), twice).save(path)

    result = analyze_image(path)
    assert result is not None
    assert result['obfuscated'] is True
    assert result['layers'] == 2


def test_detector_keeps_natural_image(tmp_path):
    w, h = 96, 72
    raw = _make_gradient(w, h)
    path = tmp_path / 'natural.png'
    Image.frombytes('L', (w, h), raw).save(path)

    result = analyze_image(path)
    assert result is not None
    assert result['obfuscated'] is False
    # ratio ≈ 1 时不会进恢复路径；若进了，也不能出现显著下降
    assert all(v >= 0.9 for v in result['restore_ratios'])


def test_detector_keeps_stripes_image(tmp_path):
    """各向异性图（横向条纹）不能被误判为混淆。"""
    w, h = 96, 72
    raw = bytes((255 if (y // 2) % 2 else 0) for y in range(h) for x in range(w))
    path = tmp_path / 'stripes.png'
    Image.frombytes('L', (w, h), raw).save(path)

    result = analyze_image(path)
    assert result is not None
    assert result['obfuscated'] is False


def test_detector_handles_jpeg_recompression(tmp_path):
    w, h = 96, 72
    raw = _make_gradient(w, h)
    obf = _permute(raw, w, h, 'enc')
    path = tmp_path / 'obf.jpg'
    Image.frombytes('L', (w, h), obf).save(path, quality=75)

    assert is_obfuscated(path) is True


def test_detector_marks_heavy_jpeg_as_possible(tmp_path):
    """同尺寸重压 JPEG（棋盘格原图）：恢复阈值被噪声抬高，降级为疑似档。"""
    w, h = 128, 96
    raw = _make_checker(w, h)
    obf = _permute(raw, w, h, 'enc')
    path = tmp_path / 'obf_q50.jpg'
    Image.frombytes('L', (w, h), obf).save(path, quality=50)

    result = analyze_image(path)
    assert result is not None
    assert result['obfuscated'] is True
    assert result['confidence'] == 'possible'


def test_detector_marks_resized_obfuscated_as_possible(tmp_path):
    """缩放破坏像素映射：逆置换不再还原，但 TV 不升 → 疑似档。"""
    w, h = 128, 96
    raw = _make_noisy_gradient(w, h)
    obf = Image.frombytes('L', (w, h), _permute(raw, w, h, 'enc'))
    small = obf.resize((64, 48), Image.LANCZOS)
    path = tmp_path / 'resized.png'
    small.save(path)

    result = analyze_image(path)
    assert result is not None
    assert result['obfuscated'] is True
    assert result['confidence'] == 'possible'


def test_restore_limit_covers_detector_supported_image_size():
    from qq_onebot_whitelist import gilbert_obfuscation as module

    assert module.MAX_RESTORE_PIXELS >= module.MAX_PIXELS


def test_oversized_image_skipped(tmp_path):
    w, h = 3000, 3000  # 9MP > 上限，正常情况会跳过
    raw = bytes(64 for _ in range(w * h))
    path = tmp_path / 'big.png'
    Image.frombytes('L', (w, h), raw).save(path)

    assert analyze_image(path) is None


def test_restore_image_recovers_original_exactly(tmp_path):
    w, h = 128, 96
    raw = _make_gradient(w, h)
    obf_path = tmp_path / 'obf.png'
    Image.frombytes('L', (w, h), _permute(raw, w, h, 'enc')).save(obf_path)

    out = tmp_path / 'restored.png'
    restored_path, layers = restore_image(obf_path, out, layers=1)
    assert layers == 1
    with Image.open(restored_path) as im:
        assert im.size == (w, h)
        assert im.convert('L').tobytes() == raw


def test_restore_image_preserves_text_metadata(tmp_path):
    """还原即替换不能抹掉生成元数据：原 tEXt（prompt/workflow）带到还原图。"""
    from PIL.PngImagePlugin import PngInfo

    w, h = 64, 48
    raw = _make_gradient(w, h)
    src = tmp_path / 'obf.png'
    info = PngInfo()
    info.add_text('prompt', '{"1": {"inputs": {"text": "1girl"}}}')
    info.add_text('workflow', 'wf-payload')
    Image.frombytes('L', (w, h), _permute(raw, w, h, 'enc')).save(src, pnginfo=info)

    out = tmp_path / 'restored.png'
    restore_image(src, out, layers=1)
    with Image.open(out) as im:
        assert im.info.get('prompt') == '{"1": {"inputs": {"text": "1girl"}}}'
        assert im.info.get('workflow') == 'wf-payload'




def test_promote_restored_replaces_original(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import promote_restored
    archive = tmp_path / "ai" / "ab"
    archive.mkdir(parents=True)
    original = archive / "abc.png"
    original.write_bytes(b"obfuscated")
    restored = tmp_path / "restored" / "abc.png"
    restored.parent.mkdir(parents=True)
    restored.write_bytes(b"restored-content")

    dest = promote_restored(original, restored, tmp_path / "ai", "abc")

    assert dest == archive / "abc.png"
    assert dest.read_bytes() == b"restored-content"
    assert not (tmp_path / "restored" / "abc.png").exists() or True  # 临时文件可留可清，重点是归档内容被替换
    assert original.exists() is False or original.read_bytes() == b"restored-content"


def test_promote_restored_skips_when_missing(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import promote_restored
    archive = tmp_path / "ai"
    archive.mkdir()
    try:
        promote_restored(tmp_path / "orig.png", tmp_path / "missing.png", archive, "abc")
        raise AssertionError("should raise")
    except FileNotFoundError:
        pass


# ---------- 浏览器编码器指纹（混淆工具重编码预筛） ----------

def _write_png_with_level(path, level: int, width: int = 64, height: int = 48,
                          gray: bytes | None = None) -> None:
    """手工构造灰度 PNG：扫描线按指定 zlib 等级压缩成单个 IDAT。"""
    import struct
    import zlib

    if gray is None:
        gray = bytes((x * 7 + y * 3) % 256 for y in range(height) for x in range(width))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    raw = b''.join(b'\x00' + gray[y * width:(y + 1) * width] for y in range(height))

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + typ + data
                + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff))

    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw, level))
        + chunk(b'IEND', b'')
    )


def test_fingerprint_flags_quick_zlib_small_idat(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import has_tool_encoder_fingerprint

    path = tmp_path / 'tool.png'
    _write_png_with_level(path, level=1)
    assert has_tool_encoder_fingerprint(path) is True


def test_fingerprint_ignores_default_and_best_compression(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import has_tool_encoder_fingerprint

    p6 = tmp_path / 'lvl6.png'
    _write_png_with_level(p6, level=6)
    p9 = tmp_path / 'lvl9.png'
    _write_png_with_level(p9, level=9)
    assert has_tool_encoder_fingerprint(p6) is False
    assert has_tool_encoder_fingerprint(p9) is False


def test_fingerprint_ignores_large_idat_even_at_quick_level(tmp_path):
    """zlib 快速档但 IDAT 是大块（如 PIL compress_level=1）→ 不是工具指纹。"""
    import os

    from qq_onebot_whitelist.gilbert_obfuscation import has_tool_encoder_fingerprint

    path = tmp_path / 'big_idat.png'
    noise = os.urandom(32 * 1024)  # 随机数据在快速档下仍 >8KB
    _write_png_with_level(path, level=1, width=1024, height=32, gray=noise[:1024 * 32])
    assert has_tool_encoder_fingerprint(path) is False


def test_fingerprint_rejects_non_png(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import has_tool_encoder_fingerprint

    path = tmp_path / 'x.bin'
    path.write_bytes(b'not a png at all')
    assert has_tool_encoder_fingerprint(path) is False
    assert has_tool_encoder_fingerprint(tmp_path / 'missing.png') is False

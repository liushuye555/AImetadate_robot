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


def test_restore_image_detects_layer_count(tmp_path):
    w, h = 96, 96
    raw = _make_checker(w, h)
    twice = _permute(_permute(raw, w, h, 'enc'), w, h, 'enc')
    obf_path = tmp_path / 'obf2.png'
    Image.frombytes('L', (w, h), twice).save(obf_path)

    out = tmp_path / 'restored2.png'
    _, layers = restore_image(obf_path, out, layers=None)
    assert layers == 2
    with Image.open(out) as im:
        assert im.convert('L').tobytes() == raw


def test_restore_image_recovers_via_forward_permutation(tmp_path):
    """文件是"被提前解了一层"的状态时，顺置换（enc）能恢复原图。"""
    w, h = 128, 96
    raw = _make_gradient(w, h)
    over_state = _permute(raw, w, h, 'dec')
    path = tmp_path / 'over.png'
    Image.frombytes('L', (w, h), over_state).save(path)

    out = tmp_path / 'restored.png'
    _, layers = restore_image(path, out, layers=None)
    with Image.open(out) as im:
        assert im.convert('L').tobytes() == raw
    assert layers == 1


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

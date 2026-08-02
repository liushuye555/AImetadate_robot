"""小番茄混淆（Gilbert 曲线 + 黄金分割位移）检测器测试。"""

from __future__ import annotations

import math

from PIL import Image

from qq_onebot_whitelist.gilbert_obfuscation import (
    analyze_image,
    curve_order,
    is_obfuscated,
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


def test_oversized_image_skipped(tmp_path):
    w, h = 3000, 3000  # 9MP > 上限，正常情况会跳过
    raw = bytes(64 for _ in range(w * h))
    path = tmp_path / 'big.png'
    Image.frombytes('L', (w, h), raw).save(path)

    assert analyze_image(path) is None

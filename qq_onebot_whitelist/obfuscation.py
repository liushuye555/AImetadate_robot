"""混淆图检测：感知哈希（pHash）对比，识别重编码/截图/裁剪后的 AI 图片副本。"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable


PHASH_MATCH_THRESHOLD = 10  # 汉明距离阈值，越小越严格
REENCODE_BLOCKINESS_THRESHOLD = 6.5  # JPEG 块状伪影阈值，越大越严格


def image_phash(path: str | Path) -> int:
    """计算 64 位感知哈希（8x8 DCT 低频 + 中位数阈值）。"""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert('L').resize((32, 32), Image.LANCZOS)
        pixels = list(img.tobytes())
    dct = [[0.0 for _ in range(8)] for _ in range(8)]
    for u in range(8):
        for v in range(8):
            cu = math.sqrt(0.125) if u == 0 else 0.5
            cv = math.sqrt(0.125) if v == 0 else 0.5
            total = 0.0
            for y in range(32):
                base = y * 32
                for x in range(32):
                    total += pixels[base + x] * math.cos((2 * x + 1) * u * math.pi / 64) * math.cos((2 * y + 1) * v * math.pi / 64)
            dct[u][v] = cu * cv * total
    values = [dct[u][v] for u in range(8) for v in range(8)]
    median = sorted(values)[len(values) // 2]
    result = 0
    for value in values:
        result = (result << 1) | (1 if value > median else 0)
    return result


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


def find_obfuscated_match(phash_value: int, archive_hashes: Iterable[tuple[int, str]], threshold: int = PHASH_MATCH_THRESHOLD) -> tuple[int, str] | None:
    """在归档哈希中找最接近的匹配；返回 (距离, sha256)，超过阈值返回 None。"""
    best: tuple[int, str] | None = None
    best_distance = threshold + 1
    for archive_hash, sha256 in archive_hashes:
        distance = hamming_distance(phash_value, archive_hash)
        if distance < best_distance:
            best_distance = distance
            best = (distance, sha256)
            if distance == 0:
                break
    return best if best is not None and best_distance <= threshold else None


def jpeg_blockiness(path: str | Path) -> float:
    """估算 JPEG 块状伪影强度：8x8 块边界的不连续度（重压缩图通常更高）。"""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert('L')
        width, height = img.size
        pixels = list(img.tobytes())
    total = 0.0
    count = 0
    step = max(8, min(width, height) // 64)
    for y in range(0, max(1, height - 8), step):
        for x in range(0, max(1, width - 8), step):
            for yy in range(y, min(y + 8, height - 1)):
                total += abs(int(pixels[yy * width + x + 7]) - int(pixels[yy * width + x + 8]))
            for xx in range(x, min(x + 8, width - 1)):
                total += abs(int(pixels[(y + 7) * width + xx]) - int(pixels[(y + 8) * width + xx]))
            count += 16
    return total / max(1, count)

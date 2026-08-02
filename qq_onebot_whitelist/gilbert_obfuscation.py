"""小番茄混淆的精确检测（Gilbert 空间填充曲线 + 黄金分割位移）。

算法来源：https://xiaofanqiehunxiao.com/ 页面内嵌 JS（纯前端）。
混淆过程：
1. 对 WxH 图像生成 Gilbert 曲线顺序 order（jakubcerveny/gilbert 实现，逐像素 4 邻域路径）；
2. 位移 L = round((sqrt(5)-1)/2 * W*H)；
3. 混淆 enc：out[order[(s+L)%N]] = in[order[s]]；解混淆 dec 是其逆置换。

检测原理（无需原图，无需 AI 元数据）：
- 正常图片：Gilbert 曲线路径上的相邻像素差 ≈ 栅格 4 邻域差（比值 ≈ 1）；
- 混淆图片：曲线路径上的相邻像素恰是"原图"的相邻像素，差值极小；
  而栅格邻域被整体打乱，差值极大 → tv_curve/tv_raster 显著小于 1；
- 进一步确认：把逆置换作用在图上，混淆图会恢复出平滑结构（栅格 TV 大幅下降），
  正常图则会被打乱成噪声（栅格 TV 上升）。

实现说明：曲线用"直线段（run）"表示，避免逐像素构造全图顺序；
TV 统计只沿直线段做差分，单张 1152x1152 图像约 1-3 秒。
"""

from __future__ import annotations

import math
from array import array
from pathlib import Path
from typing import Any

from PIL import Image

# 工具自身上限：超过 800 万像素或单边超 4000 的图会被等比缩小后再混淆，
# 因此超大图不可能是直接混淆输出，跳过分析。
MAX_PIXELS = 8_000_000
MAX_SIDE = 4000
MIN_SIDE = 4

# ratio = tv_curve / tv_raster（预筛指标，不作为最终结论）
RESTORE_BORDERLINE = 0.9    # ratio 低于此值才需要逆置换确认
RESTORE_CONFIRM = 0.75      # 逆置换后栅格 TV ≤ 原值此比例 → 确认混淆
RATIO_FALLBACK = 0.30       # 超大图无法逆置换时的严格 ratio 兜底
MAX_LAYERS = 3              # 尝试解混淆的最大层数
MAX_RESTORE_PIXELS = 6_000_000  # 超过此像素数不做逆置换（内存/耗时）

_runs_cache: dict[tuple[int, int], tuple[tuple[int, int, int, int, int], ...]] = {}
_order_cache: dict[tuple[int, int], array] = {}


def _gilbert_runs(
    x: int, y: int, ax: int, ay: int, bx: int, by: int,
    runs: list[tuple[int, int, int, int, int]],
) -> None:
    """生成 Gilbert 曲线的直线段集合（与 xiaofanqiehunxiao.com 内嵌 JS 等价）。"""
    w = abs(ax + ay)
    h = abs(bx + by)
    dax = 1 if ax > 0 else -1 if ax < 0 else 0
    day = 1 if ay > 0 else -1 if ay < 0 else 0
    dbx = 1 if bx > 0 else -1 if bx < 0 else 0
    dby = 1 if by > 0 else -1 if by < 0 else 0
    if h == 1:
        runs.append((x, y, dax, day, w))
        return
    if w == 1:
        runs.append((x, y, dbx, dby, h))
        return
    ax2 = ax // 2
    ay2 = ay // 2
    bx2 = bx // 2
    by2 = by // 2
    w2 = abs(ax2 + ay2)
    h2 = abs(bx2 + by2)
    if 2 * w > 3 * h:
        if w2 % 2 and w > 2:
            ax2 += dax
            ay2 += day
        _gilbert_runs(x, y, ax2, ay2, bx, by, runs)
        _gilbert_runs(x + ax2, y + ay2, ax - ax2, ay - ay2, bx, by, runs)
    else:
        if h2 % 2 and h > 2:
            bx2 += dbx
            by2 += dby
        _gilbert_runs(x, y, bx2, by2, ax2, ay2, runs)
        _gilbert_runs(x + bx2, y + by2, ax, ay, bx - bx2, by - by2, runs)
        _gilbert_runs(
            x + (ax - dax) + (bx2 - dbx),
            y + (ay - day) + (by2 - dby),
            -bx2, -by2, -(ax - ax2), -(ay - ay2), runs,
        )


def curve_runs(width: int, height: int) -> tuple[tuple[int, int, int, int, int], ...]:
    """返回 Gilbert 曲线的直线段集合（缓存）。"""
    key = (width, height)
    cached = _runs_cache.get(key)
    if cached is not None:
        return cached
    runs: list[tuple[int, int, int, int, int]] = []
    if width >= height:
        _gilbert_runs(0, 0, width, 0, 0, height, runs)
    else:
        _gilbert_runs(0, 0, 0, height, width, 0, runs)
    cached = tuple(runs)
    _runs_cache[key] = cached
    return cached


def curve_order(width: int, height: int) -> array:
    """返回曲线顺序下的扁平像素索引 order[s]（uint32，缓存，用于逆置换）。"""
    key = (width, height)
    cached = _order_cache.get(key)
    if cached is not None:
        return cached
    runs = curve_runs(width, height)
    order = array('I')
    for x, y, dx, dy, length in runs:
        if dx and dy:
            order.extend((y + k * dy) * width + (x + k * dx) for k in range(length))
        elif dy == 0:
            base = y * width + x
            if dx > 0:
                order.extend(range(base, base + length))
            else:
                order.extend(range(base, base - length, -1))
        else:
            base = y * width + x
            if dy > 0:
                order.extend(range(base, base + length * width, width))
            else:
                order.extend(range(base, base - length * width, -width))
    assert len(order) == width * height
    assert len(set(order)) == width * height
    _order_cache[key] = order
    return order


def _raster_tv(mv, width: int, height: int) -> float:
    """栅格 4 邻域平均绝对差。"""
    total = 0
    for y in range(height):
        base = y * width
        row = mv[base:base + width]
        total += sum(abs(a - b) for a, b in zip(row, row[1:]))
    for y in range(height - 1):
        base = y * width
        top = mv[base:base + width]
        bottom = mv[base + width:base + 2 * width]
        total += sum(abs(a - b) for a, b in zip(top, bottom))
    edges = height * (width - 1) + (height - 1) * width
    return total / max(1, edges)


def _curve_tv(mv, width: int, height: int) -> float:
    """沿 Gilbert 曲线路径的相邻像素平均绝对差（用直线段直接差分）。"""
    runs = curve_runs(width, height)
    total = 0
    for x, y, dx, dy, length in runs:
        if length <= 1:
            continue
        if dx == 1 and dy == 0:
            seg = mv[y * width + x:y * width + x + length]
        elif dx == -1 and dy == 0:
            seg = mv[y * width + x - length + 1:y * width + x + 1]
        elif dx == 0 and dy == 1:
            seg = mv[y * width + x:y * width + x + length * width:width]
        elif dx == 0 and dy == -1:
            seg = mv[(y - length + 1) * width + x:(y + 1) * width + x:width]
        else:
            seg = [mv[(y + k * dy) * width + (x + k * dx)] for k in range(length)]
        total += sum(abs(a - b) for a, b in zip(seg, seg[1:]))
    return total / max(1, width * height)


def _apply_decoder(src: bytearray, order: array, width: int, shift: int) -> bytearray:
    """逆置换一层：dst[order[s]] = src[order[(s+shift) % N]]。"""
    n = len(src)
    dst = bytearray(n)
    src_mv = memoryview(src)
    for s in range(n):
        dst[order[s]] = src_mv[order[(s + shift) % n]]
    return dst


def _restore_ratios(mv, width: int, height: int, base_tv: float, layers: int = MAX_LAYERS) -> list[float]:
    """连续应用 1..layers 层逆置换，返回每层后的栅格 TV / 原始栅格 TV。"""
    if base_tv <= 1e-6:
        return []
    n = width * height
    order = curve_order(width, height)
    shift = round((math.sqrt(5) - 1) / 2 * n)
    cur = bytearray(mv)
    ratios: list[float] = []
    for _ in range(layers):
        cur = _apply_decoder(cur, order, width, shift)
        ratios.append(_raster_tv(memoryview(cur), width, height) / base_tv)
    return ratios


def analyze_image(path: str | Path) -> dict[str, Any] | None:
    """分析单张图片是否被小番茄混淆。

    返回 None 表示尺寸超出工具范围（不可能是直接混淆输出），
    否则返回 {obfuscated, ratio, tv_raster, tv_curve, restore_ratios, layers}。
    """
    with Image.open(path) as img:
        width, height = img.size
        if (
            width * height > MAX_PIXELS
            or max(width, height) > MAX_SIDE
            or width < MIN_SIDE
            or height < MIN_SIDE
        ):
            return None
        mv = memoryview(img.convert('L').tobytes())

    tv_raster = _raster_tv(mv, width, height)
    tv_curve = _curve_tv(mv, width, height)
    ratio = tv_curve / tv_raster if tv_raster > 1e-6 else 1.0
    result: dict[str, Any] = {
        'obfuscated': False,
        'ratio': ratio,
        'tv_raster': tv_raster,
        'tv_curve': tv_curve,
        'restore_ratios': [],
        'layers': None,
    }
    if ratio < RESTORE_BORDERLINE and width * height <= MAX_RESTORE_PIXELS:
        ratios = _restore_ratios(mv, width, height, tv_raster)
        result['restore_ratios'] = [round(v, 4) for v in ratios]
        for idx, value in enumerate(ratios, start=1):
            if value < RESTORE_CONFIRM:
                result['obfuscated'] = True
                result['layers'] = idx
                break
    elif ratio < RATIO_FALLBACK:
        # 超大图无法逐层逆置换，只能看强 ratio 信号（保守）
        result['obfuscated'] = True
    return result


def is_obfuscated(path: str | Path) -> bool:
    result = analyze_image(path)
    return bool(result and result.get('obfuscated'))

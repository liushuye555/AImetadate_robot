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

实现说明：曲线顺序用紧凑的 array('I') 表示（每像素 4 字节），递归生成时直接写入，
不做中间元组，避免大图上产生数十万个小对象。缓存按总量设上限，长驻 bot 不膨胀。
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
RESTORE_BORDERLINE = 0.95   # ratio 低于此值才需要逆置换确认
RESTORE_CONFIRM = 0.75      # 逆置换后栅格 TV ≤ 原值此比例 → 算法级确认
RESTORE_WEAK = 1.02         # 逆置换后 TV 不升反降/持平 → 疑似（重压或缩放后的混淆）
RATIO_WEAK_MAX = 0.95       # 疑似档的 ratio 上限
RATIO_FALLBACK = 0.30       # 超大图无法逆置换时的严格 ratio 兜底
MAX_LAYERS = 3              # 尝试解混淆的最大层数
MAX_RESTORE_PIXELS = 6_000_000  # 超过此像素数不做逆置换（内存/耗时）

# 曲线顺序缓存：按 (w, h) 存 array('I')，总量上限约 64MB，超出清空
MAX_CACHE_BYTES = 64 * 1024 * 1024
_order_cache: dict[tuple[int, int], array] = {}
_cache_bytes = 0


def _gilbert_walk(x: int, y: int, ax: int, ay: int, bx: int, by: int,
                  order: array, width: int) -> None:
    """递归生成 Gilbert 曲线，叶节点直接写入扁平像素索引（与网站 JS 等价）。"""
    w = abs(ax + ay)
    h = abs(bx + by)
    dax = 1 if ax > 0 else -1 if ax < 0 else 0
    day = 1 if ay > 0 else -1 if ay < 0 else 0
    dbx = 1 if bx > 0 else -1 if bx < 0 else 0
    dby = 1 if by > 0 else -1 if by < 0 else 0
    if h == 1:
        _emit_run(order, width, x, y, dax, day, w)
        return
    if w == 1:
        _emit_run(order, width, x, y, dbx, dby, h)
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
        _gilbert_walk(x, y, ax2, ay2, bx, by, order, width)
        _gilbert_walk(x + ax2, y + ay2, ax - ax2, ay - ay2, bx, by, order, width)
    else:
        if h2 % 2 and h > 2:
            bx2 += dbx
            by2 += dby
        _gilbert_walk(x, y, bx2, by2, ax2, ay2, order, width)
        _gilbert_walk(x + bx2, y + by2, ax, ay, bx - bx2, by - by2, order, width)
        _gilbert_walk(
            x + (ax - dax) + (bx2 - dbx),
            y + (ay - day) + (by2 - dby),
            -bx2, -by2, -(ax - ax2), -(ay - ay2), order, width,
        )


def _emit_run(order: array, width: int, x: int, y: int, dx: int, dy: int, length: int) -> None:
    """把一条沿轴的直线段（起点+方向+长度）写进顺序表。"""
    if length <= 0:
        return
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


def _curve_order_cached(width: int, height: int) -> array:
    """返回曲线顺序下的扁平像素索引 order[s]（uint32，缓存，用于逆置换与 TV）。"""
    global _cache_bytes
    key = (width, height)
    cached = _order_cache.get(key)
    if cached is not None:
        return cached
    order = array('I')
    if width >= height:
        _gilbert_walk(0, 0, width, 0, 0, height, order, width)
    else:
        _gilbert_walk(0, 0, 0, height, width, 0, order, width)
    assert len(order) == width * height
    # 排列唯一性由算法保证，且单测覆盖；这里不做 O(N) 的 set 校验（大图会瞬时多占 ~100MB）
    if _cache_bytes > MAX_CACHE_BYTES:
        _order_cache.clear()
        _cache_bytes = 0
    _order_cache[key] = order
    _cache_bytes += len(order) * 4
    return order


def curve_order(width: int, height: int) -> array:
    """公开接口：返回曲线顺序索引（测试/外部使用）。"""
    return _curve_order_cached(width, height)


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


def _curve_tv(mv, width: int, height: int, order: array) -> float:
    """沿 Gilbert 曲线路径的相邻像素平均绝对差（直接按顺序表差分）。"""
    total = 0
    prev = mv[order[0]]
    for s in range(1, width * height):
        cur = mv[order[s]]
        diff = cur - prev
        total += diff if diff >= 0 else -diff
        prev = cur
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
    order = _curve_order_cached(width, height)
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
    order = _curve_order_cached(width, height)
    tv_curve = _curve_tv(mv, width, height, order)
    ratio = tv_curve / tv_raster if tv_raster > 1e-6 else 1.0
    result: dict[str, Any] = {
        'obfuscated': False,
        'confidence': None,
        'ratio': ratio,
        'tv_raster': tv_raster,
        'tv_curve': tv_curve,
        'restore_ratios': [],
        'layers': None,
    }
    if ratio < RESTORE_BORDERLINE and width * height <= MAX_RESTORE_PIXELS:
        ratios = _restore_ratios(mv, width, height, tv_raster)
        result['restore_ratios'] = [round(v, 4) for v in ratios]
        best_layer = None
        best_value = None
        for idx, value in enumerate(ratios, start=1):
            if value < RESTORE_CONFIRM:
                best_layer = idx
                best_value = value
                break
        if best_layer is not None:
            result['obfuscated'] = True
            result['confidence'] = 'confirmed'
            result['layers'] = best_layer
        elif ratio <= RATIO_WEAK_MAX and min(ratios) < RESTORE_WEAK:
            # 逆置换后 TV 没有明显上升：重压/缩放后的混淆图（弱信号，待人工复核）
            for idx, value in enumerate(ratios, start=1):
                if value < RESTORE_WEAK:
                    result['obfuscated'] = True
                    result['confidence'] = 'possible'
                    result['layers'] = idx
                    break
    elif ratio < RATIO_FALLBACK:
        # 超大图无法逐层逆置换，只能看强 ratio 信号（保守）
        result['obfuscated'] = True
        result['confidence'] = 'possible'
    return result


def is_obfuscated(path: str | Path) -> bool:
    result = analyze_image(path)
    return bool(result and result.get('obfuscated'))


def restore_image(
    src_path: str | Path,
    out_path: str | Path,
    layers: int | None = None,
    max_layers: int = MAX_LAYERS,
) -> tuple[Path, int]:
    """对混淆图做逆置换还原，保存为无损 PNG。

    layers 已知时按层数直接还原；未知时尝试 1..max_layers 层，
    取还原后灰度 TV 最低的一档（对应真实层数）。
    返回 (输出路径, 实际使用层数)。
    """
    from PIL import Image as _Image

    with _Image.open(src_path) as img:
        width, height = img.size
        if width * height > MAX_RESTORE_PIXELS:
            raise ValueError(f'图片过大（{width}x{height}），无法还原')
        rgb = img.convert('RGB')
    channels = [list(rgb.getchannel(name).tobytes()) for name in ('R', 'G', 'B')]
    order = _curve_order_cached(width, height)
    n = width * height
    shift = round((math.sqrt(5) - 1) / 2 * n)

    layer_candidates = [max(1, int(layers))] if layers else list(range(1, max_layers + 1))
    best: tuple[float, int, list[bytes]] | None = None
    for k in layer_candidates:
        restored_channels: list[bytes] = []
        for channel in channels:
            cur = bytearray(channel)
            for _ in range(k):
                cur = _apply_decoder(cur, order, width, shift)
            restored_channels.append(bytes(cur))
        # 用 R 通道的栅格 TV 近似还原质量（层数正确时最平滑）
        tv = _raster_tv(memoryview(restored_channels[0]), width, height)
        if best is None or tv < best[0]:
            best = (tv, k, restored_channels)
    if best is None:
        raise ValueError('无法确定还原层数')
    _, used_layers, restored_channels = best
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged = _Image.merge('RGB', [_Image.frombytes('L', (width, height), c) for c in restored_channels])
    merged.save(out_path, format='PNG')
    return out_path, used_layers


def promote_restored(
    original_path: str | Path,
    restored_path: str | Path,
    archive_root: str | Path,
    digest: str,
) -> Path:
    """把还原图提升为唯一存档：原子覆盖归档区原文件，随后删除混淆原图。

    返回最终归档路径。还原图缺失或为空时抛 FileNotFoundError（调用方必须保留原图）。
    """
    import shutil

    original = Path(original_path)
    restored = Path(restored_path)
    if not restored.exists() or restored.stat().st_size <= 0:
        raise FileNotFoundError(f'restored image missing or empty: {restored}')
    archive_root = Path(archive_root)
    dest = archive_root / digest[:2] / f'{digest}{restored.suffix}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = restored.with_suffix(restored.suffix + '.tmp')
    shutil.copy2(str(restored), str(tmp))
    tmp.replace(dest)
    if original.exists() and original.resolve() != dest.resolve():
        original.unlink(missing_ok=True)
    return dest


def safe_restore(
    src_path: str | Path,
    tmp_out: str | Path,
    archive_root: str | Path,
    digest: str,
    layers: int | None = None,
) -> Path | None:
    """还原并校验：输出必须是正常图（未判混淆且 ratio ≥ 0.8）才替换归档。

    校验不通过返回 None（保留原图，不标记 deobfuscated），避免把坏还原当成品。
    """
    restored, _ = restore_image(src_path, tmp_out, layers=layers)
    check = analyze_image(restored)
    if not (check and not check.get('obfuscated') and check.get('ratio', 0) >= 0.8):
        return None
    return promote_restored(src_path, restored, archive_root, digest)

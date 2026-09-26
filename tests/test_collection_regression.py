"""采集回归测试：事件幂等与 AI 来源识别（用户诊断的 4 类问题的防护网）。

覆盖场景：
1. 同一事件重放不重复记账（幂等）
2. 一条消息多图段各记各的（段序号隔离）
3. 同一图片在不同消息中各自记账（scope+消息隔离，跨事件不误拦）
4. NovelAI 专有元数据 → 强证据确认
5. 纯 WebUI 参数块 → 弱证据只给 suspect 不误标 NovelAI
6. ComfyUI 工作流：有效确认 / 无关文本不误判
7. NovelAI alpha 隐写：verified 确认 / suspected 只记疑似
"""

import gzip
import zlib
import json
import sqlite3

import pytest
from PIL import Image

import qq_onebot_whitelist.collection as collection
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.image_meta import (
    classify_ai_source,
    classify_payload_source,
    parse_image_metadata,
)
from qq_onebot_whitelist.store import Store


def make_store_config(tmp_path):
    data = tmp_path / 'data'
    store = Store(data / 'bot.db')
    config = AppConfig(data_dir=data)
    return store, config, data


def fake_image_result(url, sha, kept_path=None, retention_reason='candidate'):
    """构造 process_image_url 返回值；meta 传真实 ImageMetadata。"""
    result = {
        'url': url, 'sha256': sha, 'phash': None, 'blockiness': 0.0,
        'size': 10, 'format': 'PNG', 'width': 8, 'height': 8,
        'metadata_keys': [], 'has_ai_metadata': False, 'ai_source': None,
        'text_excerpt': '', 'kept_path': kept_path,
        'retention_reason': retention_reason, 'stego_state': None,
    }
    return result


def make_image_file(path, content=b'img'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def image_event(message_id, n_images=1):
    segs = [{'type': 'image',
             'data': {'url': f'http://x/{message_id}-{i}.png',
                      'file': f'{message_id}-{i}.png'}} for i in range(n_images)]
    return {'post_type': 'message', 'message_id': message_id,
            'message_type': 'group', 'group_id': 9,
            'user_id': 100, 'message': segs}


def rows(store, scope='group:9'):
    conn = sqlite3.connect(store.path)
    try:
        return conn.execute(
            "SELECT id, sha256, ai_source, has_ai_metadata, raw_json FROM images "
            "WHERE scope = ? ORDER BY id", (scope,)).fetchall()
    finally:
        conn.close()


# ---------- 场景 1：同一事件重放不重复记账 ----------

def test_same_event_replay_not_duplicated(tmp_path, monkeypatch):
    store, config, data = make_store_config(tmp_path)
    kept = make_image_file(data / 'images' / 'ai' / 'aa' / 'a1.png')
    calls = []

    def fake_process_image_url(url, **kwargs):
        calls.append(url)
        return fake_image_result(url, 'sha-a', kept_path=str(kept),
                                 retention_reason='ai_metadata')

    monkeypatch.setattr(collection, 'process_image_url', fake_process_image_url)
    monkeypatch.setattr(collection, 'analyze_image', lambda p: None)

    event = image_event(1001)
    from qq_onebot_whitelist.collection import collect_event
    collect_event(store, event, config)
    collect_event(store, event, config)  # 重放（如 get_msg 重拉）

    assert len(calls) == 1  # 第二次直接幂等短路，不再下载
    assert len(rows(store)) == 1


# ---------- 场景 2：一条消息多图段各记各的 ----------

def test_multi_segment_message_each_recorded(tmp_path, monkeypatch):
    store, config, data = make_store_config(tmp_path)
    calls = []
    seq = iter(f'sha-{i}' for i in range(10))

    def fake_process_image_url(url, **kwargs):
        calls.append(url)
        return fake_image_result(url, next(seq))

    monkeypatch.setattr(collection, 'process_image_url', fake_process_image_url)
    monkeypatch.setattr(collection, 'analyze_image', lambda p: None)

    event = image_event(1002, n_images=3)
    from qq_onebot_whitelist.collection import collect_event
    collect_event(store, event, config)

    assert len(calls) == 3
    all_rows = rows(store)
    assert len(all_rows) == 3
    indexes = {json.loads(r[4])['segment_index'] for r in all_rows}
    assert indexes == {0, 1, 2}

    # 重放整条消息也不新增
    collect_event(store, event, config)
    assert len(rows(store)) == 3


# ---------- 场景 3：同一图片出现在不同消息里各自记账 ----------

def test_same_image_in_different_messages_both_kept(tmp_path, monkeypatch):
    store, config, data = make_store_config(tmp_path)
    kept = make_image_file(data / 'images' / 'ai' / 'bb' / 'b1.png')

    def fake_process_image_url(url, **kwargs):
        return fake_image_result(url, 'sha-same', kept_path=str(kept),
                                 retention_reason='ai_metadata')

    monkeypatch.setattr(collection, 'process_image_url', fake_process_image_url)
    monkeypatch.setattr(collection, 'analyze_image', lambda p: None)

    from qq_onebot_whitelist.collection import collect_event
    collect_event(store, image_event(1003), config)
    collect_event(store, image_event(1004), config)  # 不同消息，同一张图

    assert len(rows(store)) == 2  # 跨消息不误拦


# ---------- 场景 4：NovelAI 专有键 → 结构证据确认 ----------

def test_novelai_structural_comment_confirmed():
    """NAI 专有 JSON（ucPreset）→ 结构确认 NovelAI；正文提到工具名不再是证据。"""
    text = json.dumps({'prompt': '1girl', 'ucPreset': 0, 'steps': 28})
    has_ai, source = classify_payload_source(text)
    assert has_ai and source == 'NovelAI'

    # 'novelai' 只是提示词/正文里的一个词：不构成来源证据
    has_ai2, source2 = classify_ai_source('NovelAI v3 生成')
    assert not has_ai2 or (source2 and source2.startswith('suspect:'))


# ---------- 场景 5：纯 WebUI 参数块 → 弱证据只给 suspect ----------

def test_webui_params_not_misidentified_as_novelai():
    # 纯 A1111/WebUI 参数块：steps/scale 是通用词，旧规则会误标 NovelAI
    webui = ('1girl, best quality\n'
             'Negative prompt: lowres, bad hands\n'
             'Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 12345, Size: 512x768')
    has_ai, source = classify_ai_source(webui)
    assert has_ai, 'WebUI 参数块确实含 AI 元数据'
    assert source == 'A1111'  # negative prompt 是强证据，先于 NovelAI 命中


def test_generic_params_only_give_suspect():
    # 只有 steps/scale 的 JSON 键（无任何强证据）→ 疑似而非确认
    text = '{"steps": 28, "scale": 5, "guidance": 7}'
    has_ai, source = classify_ai_source(text)
    assert has_ai and source == 'suspect:NovelAI'

    # 裸文本 "upscale" 之类不再误触 NovelAI 弱标记
    has_ai2, source2 = classify_ai_source('Postprocess upscale by: 1.5, upscaler: R-ESRGAN')
    assert not has_ai2 and source2 is None


def test_no_markers_not_ai():
    has_ai, source = classify_ai_source('今天天气不错，出来玩')
    assert not has_ai and source is None


# ---------- 场景 6：ComfyUI 工作流有效/无效 ----------

def test_comfyui_workflow_confirmed():
    """API 格式节点图（{id: {class_type, inputs}}）→ 结构确认 ComfyUI。"""
    workflow = json.dumps({'3': {'class_type': 'KSampler',
                                 'inputs': {'seed': 1, 'steps': 20}}})
    has_ai, source = classify_payload_source(workflow)
    assert has_ai and source == 'ComfyUI'

    # 单节点对象（个别前端直接写 {class_type, inputs}）也是 ComfyUI 结构
    flat = json.dumps({'class_type': 'KSampler', 'inputs': {'seed': 1}})
    has_ai2, source2 = classify_payload_source(flat)
    assert has_ai2 and source2 == 'ComfyUI'

    # 无关 JSON 不是 ComfyUI 证据
    has_ai3, source3 = classify_payload_source('{"foo": "bar"}')
    assert source3 is None  # 载荷可解但验不出工具 → 未知


def test_comfyui_weak_wordflow_suspect():
    # 只有 "workflow" 字样（通用词）不给确认
    has_ai, source = classify_ai_source('my workflow is great')
    assert has_ai and source == 'suspect:ComfyUI'


# ---------- 场景 7：NovelAI alpha 隐写 ----------

def _bits_of(data: bytes) -> str:
    return ''.join(format(b, '08b') for b in data)


def write_stealth_png(path, params: str, compressed=True, truncate=False):
    """按 stealth pnginfo 写入端格式造图（alpha LSB、x 外层 y 内层）。"""
    sig = f"stealth_png{'comp' if compressed else 'info'}"
    raw = params.encode() if not compressed else gzip.compress(params.encode())
    binary = _bits_of(sig.encode()) + format(len(raw) * 8, '032b') + _bits_of(raw)
    if truncate:
        binary = binary[:len(binary) * 2 // 3]
    img = Image.new('RGBA', (128, 128), (10, 20, 30, 255))
    px = img.load()
    i = 0
    for x in range(img.width):
        for y in range(img.height):
            if i >= len(binary):
                break
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, (a & ~1) | int(binary[i]))
            i += 1
        if i >= len(binary):
            break
    img.save(path)


def test_novelai_stego_verified(tmp_path):
    payload = json.dumps({'prompt': '1girl, masterpiece', 'steps': 28,
                          'scale': 5, 'ucPreset': 0, 'sampler': 'Euler'})
    p = tmp_path / 'stego.png'
    write_stealth_png(p, payload, compressed=True)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'verified'
    assert meta.has_ai_metadata and meta.ai_source == 'NovelAI'
    assert 'stealth_pnginfo' in meta.metadata_keys
    assert '1girl' in meta.stego_excerpt


def test_novelai_stego_uncompressed_verified(tmp_path):
    """未压缩 stealth 载荷可解出；提示词+Steps 设置行是 A1111 参数块结构。"""
    p = tmp_path / 'stego_plain.png'
    write_stealth_png(p, '1girl\nSteps: 28, Sampler: Euler a', compressed=False)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'verified'
    assert meta.has_ai_metadata
    assert meta.ai_source == 'A1111'


def test_novelai_stego_plain_a1111_parameters_not_labeled_novelai(tmp_path):
    """验收：stealth 容器里的普通 A1111 参数文本不得判成 NovelAI。"""
    p = tmp_path / 'stego_a1111.png'
    write_stealth_png(
        p,
        '[ichika \\(ichika87\\)], miao style\n'
        'Negative prompt: blurry\n'
        'Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 123, Model: Miao2.0',
        compressed=True,
    )
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'verified'
    assert meta.has_ai_metadata
    assert meta.ai_source == 'A1111'


def test_novelai_stego_unverifiable_payload_keeps_unknown_source(tmp_path):
    """验收：载荷验证不出工具（空 JSON/纯文本）→ 来源保留未知。"""
    p = tmp_path / 'stego_empty.png'
    write_stealth_png(p, '{}', compressed=True)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'verified'
    assert meta.has_ai_metadata  # 载荷存在 = 有生成元数据
    assert meta.ai_source is None  # 但工具来源未知


def test_novelai_stego_truncated_is_suspected_only(tmp_path):
    p = tmp_path / 'stego_trunc.png'
    write_stealth_png(tmp_path / 'full.png', '{"prompt": "x"}', compressed=True)
    write_stealth_png(p, '{"prompt": "x"}', compressed=True, truncate=True)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'suspected'


def test_exif_embedded_comfyui_workflow_confirmed(tmp_path):
    """SwarmUI 等前端把 ComfyUI 图塞在 EXIF UserComment（二进制前缀 + 'Workflow:{...}'）：
    抠出 JSON 做图结构校验 → 确认 ComfyUI，而不是落到弱证据疑似。"""
    import zlib as _zlib

    graph = json.dumps({
        'last_node_id': 142, 'last_link_id': 214,
        'nodes': [{'id': 44, 'type': 'Switch latent [Crystools]', 'pos': [1, 2]}],
        'links': [[1, 10, 0, 20, 0, 'MODEL']],
    })
    blob = 'MM\x00*\x00\x00\x00\x08\x00\x02' + 'Workflow:' + graph
    chunk = b'EXIF\x00' + blob.encode('utf-8', 'ignore')

    def png_chunk(kind, data):
        return (len(data).to_bytes(4, 'big') + kind + data
                + (zlib.crc32(kind + data) & 0xffffffff).to_bytes(4, 'big'))

    ihdr = (920).to_bytes(4, 'big') + (1536).to_bytes(4, 'big') + bytes([8, 2, 0, 0, 0])
    p = tmp_path / 'exif-workflow.png'
    p.write_bytes(b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr)
                  + png_chunk(b'tEXt', chunk) + png_chunk(b'IEND', b''))

    meta = parse_image_metadata(p)
    assert meta.has_ai_metadata
    assert meta.ai_source == 'ComfyUI'


def test_stego_payload_novelai_v5_export_confirmed(tmp_path):
    """stealth 载荷里是 NovelAI V5 导出 JSON（Software/Source 在 JSON 内）→ NovelAI。"""
    payload = json.dumps({
        'Description': '1.5::best quality::, masterpiece',
        'Software': 'NovelAI',
        'Source': 'NovelAI Diffusion V5 0ADF9AB7',
        'Comment': '{"prompt": "x"}',
    })
    p = tmp_path / 'stego_v5.png'
    write_stealth_png(p, payload, compressed=True)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'verified'
    assert meta.ai_source == 'NovelAI'


def test_plain_png_no_stego(tmp_path):
    p = tmp_path / 'clean.png'
    Image.new('RGBA', (64, 64), (1, 2, 3, 255)).save(p)
    meta = parse_image_metadata(p)
    assert meta.stego_state is None and not meta.has_ai_metadata

    rgb = tmp_path / 'rgb.png'
    Image.new('RGB', (64, 64)).save(rgb)
    assert parse_image_metadata(rgb).stego_state is None


# ---------- 场景 8：带元数据的混淆图（浏览器编码器指纹预筛） ----------

from qq_onebot_whitelist.gilbert_obfuscation import analyze_image as analyze_image_real


def _write_tool_encoded_png(path, width, height, gray):
    """手工构造 PNG：zlib 快速档 + ~4KB 分块 IDAT（小番茄工具重编码的文件结构）。"""
    import struct
    import zlib

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    raw = b''.join(b'\x00' + gray[y * width:(y + 1) * width] for y in range(height))

    def chunk(typ, data):
        return (struct.pack('>I', len(data)) + typ + data
                + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff))

    packed = zlib.compress(raw, 1)
    idats = b''.join(chunk(b'IDAT', packed[i:i + 4096]) for i in range(0, len(packed), 4096))
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + idats + chunk(b'IEND', b'')
    )


def _permuted_gradient(width=128, height=96):
    """真混淆像素：渐变灰度图按小番茄算法做一层置换。"""
    import math

    from qq_onebot_whitelist.gilbert_obfuscation import curve_order
    raw = bytes((x * 255 // max(1, width - 1) + y * 40) % 256
                for y in range(height) for x in range(width))
    n = width * height
    order = curve_order(width, height)
    shift = round((math.sqrt(5) - 1) / 2 * n)
    enc = bytearray(n)
    for s in range(n):
        enc[order[(s + shift) % n]] = raw[order[s]]
    return raw, bytes(enc)


def _metadata_result(url, sha, kept_path):
    result = fake_image_result(url, sha, kept_path=str(kept_path),
                               retention_reason='ai_metadata')
    result.update({'metadata_keys': ['prompt', 'workflow'],
                   'has_ai_metadata': True, 'ai_source': 'ComfyUI',
                   'format': 'PNG', 'width': 128, 'height': 96})
    return result


def test_metadata_with_tool_fingerprint_confirmed_obfuscated(tmp_path, monkeypatch):
    """带元数据 + 工具编码指纹的混淆图：不再盲信元数据，像素确认后归 05 并自动还原。"""
    store, config, data = make_store_config(tmp_path)
    _, enc = _permuted_gradient()
    kept = make_image_file(data / 'images' / 'ai' / 'cc' / 'c1.png')
    _write_tool_encoded_png(kept, 128, 96, enc)

    monkeypatch.setattr(
        collection, 'process_image_url',
        lambda url, **kw: _metadata_result(url, 'sha-obf', kept))
    monkeypatch.setattr(collection, 'analyze_image', analyze_image_real)

    from qq_onebot_whitelist.collection import collect_event
    collect_event(store, image_event(2001), config)

    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute(
            "SELECT retention_reason, context_reason, deobfuscated FROM images "
            "WHERE scope='group:9'").fetchone()
    finally:
        conn.close()
    assert row[0] == 'xiaofanqie_obfuscated'
    assert row[1] == 'ai_metadata'  # 交叉分类：同时显示回来源 01 分类
    assert row[2] == 1     # 确认档自动还原替换


def test_metadata_fingerprint_but_natural_pixels_stays(tmp_path, monkeypatch):
    """指纹命中但像素是自然图：负结果，保持 ai_metadata（误报路径）。"""
    store, config, data = make_store_config(tmp_path)
    raw, _ = _permuted_gradient()
    kept = make_image_file(data / 'images' / 'ai' / 'cc' / 'c2.png')
    _write_tool_encoded_png(kept, 128, 96, raw)  # 未置换的自然渐变

    monkeypatch.setattr(
        collection, 'process_image_url',
        lambda url, **kw: _metadata_result(url, 'sha-clean', kept))
    monkeypatch.setattr(collection, 'analyze_image', analyze_image_real)

    from qq_onebot_whitelist.collection import collect_event
    collect_event(store, image_event(2002), config)

    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute(
            "SELECT retention_reason FROM images WHERE scope='group:9'").fetchone()
    finally:
        conn.close()
    assert row[0] == 'ai_metadata'


def test_metadata_without_fingerprint_skips_pixel_scan(tmp_path, monkeypatch):
    """无指纹的带元数据图：不触发像素分析（成本闸门），维持原分类。"""
    store, config, data = make_store_config(tmp_path)
    import struct
    import zlib

    # 用 PIL 默认参数存一张混淆像素图（789c + 大块 IDAT，无工具指纹）
    _, enc = _permuted_gradient()
    kept = make_image_file(data / 'images' / 'ai' / 'cc' / 'c3.png')
    ihdr = struct.pack('>IIBBBBB', 128, 96, 8, 0, 0, 0, 0)
    raw_scan = b''.join(b'\x00' + enc[y * 128:(y + 1) * 128] for y in range(96))

    def chunk(typ, d):
        return (struct.pack('>I', len(d)) + typ + d
                + struct.pack('>I', zlib.crc32(typ + d) & 0xffffffff))

    kept.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
                     + chunk(b'IDAT', zlib.compress(raw_scan, 6)) + chunk(b'IEND', b''))

    calls = []
    monkeypatch.setattr(
        collection, 'process_image_url',
        lambda url, **kw: _metadata_result(url, 'sha-nofp', kept))
    monkeypatch.setattr(collection, 'analyze_image',
                        lambda p: calls.append(p) or None)

    from qq_onebot_whitelist.collection import collect_event
    collect_event(store, image_event(2003), config)

    assert calls == []  # 指纹未命中，不做像素分析
    conn = sqlite3.connect(store.path)
    try:
        row = conn.execute(
            "SELECT retention_reason FROM images WHERE scope='group:9'").fetchone()
    finally:
        conn.close()
    assert row[0] == 'ai_metadata'

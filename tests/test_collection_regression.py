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
import json
import sqlite3

import pytest
from PIL import Image

import qq_onebot_whitelist.collection as collection
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.image_meta import (
    classify_ai_source,
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


# ---------- 场景 4：NovelAI 专有键 → 强证据确认 ----------

def test_novelai_strong_marker_confirmed():
    text = json.dumps({'prompt': '1girl', 'ucPreset': 0, 'steps': 28})
    has_ai, source = classify_ai_source(text)
    assert has_ai and source == 'NovelAI'

    has_ai2, source2 = classify_ai_source('NovelAI v3 生成')
    assert has_ai2 and source2 == 'NovelAI'


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
    # 只有 steps/scale（无任何强证据）→ 疑似而非确认
    text = 'some settings: steps 28, scale 5, guidance'
    has_ai, source = classify_ai_source(text)
    assert has_ai and source == 'suspect:NovelAI'


def test_no_markers_not_ai():
    has_ai, source = classify_ai_source('今天天气不错，出来玩')
    assert not has_ai and source is None


# ---------- 场景 6：ComfyUI 工作流有效/无效 ----------

def test_comfyui_workflow_confirmed():
    workflow = json.dumps({'class_type': 'KSampler',
                           'inputs': {'seed': 1, 'steps': 20}})
    has_ai, source = classify_ai_source(workflow)
    assert has_ai and source == 'ComfyUI'


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
    p = tmp_path / 'stego_plain.png'
    write_stealth_png(p, '1girl\nSteps: 28, Sampler: Euler a', compressed=False)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'verified'
    assert meta.ai_source == 'NovelAI'


def test_novelai_stego_truncated_is_suspected_only(tmp_path):
    p = tmp_path / 'stego_trunc.png'
    write_stealth_png(tmp_path / 'full.png', '{"prompt": "x"}', compressed=True)
    write_stealth_png(p, '{"prompt": "x"}', compressed=True, truncate=True)
    meta = parse_image_metadata(p)
    assert meta.stego_state == 'suspected'
    # 疑似不定来源：不因隐写痕迹就宣布 NovelAI
    assert meta.ai_source is None and not meta.has_ai_metadata


def test_plain_png_no_stego(tmp_path):
    p = tmp_path / 'clean.png'
    Image.new('RGBA', (64, 64), (1, 2, 3, 255)).save(p)
    meta = parse_image_metadata(p)
    assert meta.stego_state is None and not meta.has_ai_metadata

    rgb = tmp_path / 'rgb.png'
    Image.new('RGB', (64, 64)).save(rgb)
    assert parse_image_metadata(rgb).stego_state is None

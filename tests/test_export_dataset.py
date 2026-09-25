"""数据集导出（export_dataset）测试：用户过滤、内容去重、caption 提取、来源别名。"""

import json
import sqlite3

from PIL import Image, PngImagePlugin


SCHEMA = """CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
    format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
    ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
    deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, raw_json TEXT, sha256 TEXT,
    merged_into INTEGER, saved_category TEXT, prompt_key TEXT, context_reason TEXT,
    bound_prompt TEXT, stego_state TEXT)"""


def make_db(tmp_path, rows):
    """rows: (user_id, retention_reason, kept_path, ai_source, sha256[, width, height[, text_excerpt]])。"""
    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data / 'bot.db')
    conn.execute(SCHEMA)
    for r in rows:
        w = r[5] if len(r) > 5 else 640
        h = r[6] if len(r) > 6 else 640
        excerpt = r[7] if len(r) > 7 else ''
        conn.execute(
            "INSERT INTO images (scope, user_id, seen_at, format, width, height, retention_reason, "
            "kept_path, ai_source, has_ai_metadata, sha256, text_excerpt) "
            "VALUES ('group:1', ?, '2026-09-01 10:00:00', 'PNG', ?, ?, ?, ?, ?, 1, ?, ?)",
            (r[0], w, h, r[1], r[2], r[3], r[4], excerpt))
    conn.commit()
    conn.close()


def a1111_png(path):
    img = Image.new('RGB', (640, 640), (200, 30, 30))
    info = PngImagePlugin.PngInfo()
    info.add_text('parameters',
                  'shiroko \\(blue archive\\), on bed\n'
                  'Negative prompt: lazyneg, watermark\n'
                  'Steps: 25, Sampler: Euler a, CFG scale: 4.5, Seed: 1, Size: 640x640')
    img.save(path, 'PNG', pnginfo=info)
    return path


def comfy_png(path):
    graph = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'anima.safetensors'}},
        '3': {'class_type': 'KSampler', 'inputs': {'positive': ['5', 0], 'negative': ['6', 0]}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '1girl, suwako, touhou'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'bad hands, watermark'}},
    }
    img = Image.new('RGB', (640, 640), (30, 200, 30))
    info = PngImagePlugin.PngInfo()
    info.add_text('prompt', json.dumps(graph))
    img.save(path, 'PNG', pnginfo=info)
    return path


def novelai_png(path):
    img = Image.new('RGB', (640, 640), (30, 30, 200))
    info = PngImagePlugin.PngInfo()
    info.add_text('Comment', json.dumps({'prompt': 'masterpiece, 1girl', 'uc': 'lowres', 'steps': 28}))
    info.add_text('Software', 'NovelAI')
    img.save(path, 'PNG', pnginfo=info)
    return path


def read_manifest(out_dir):
    return json.loads((out_dir / 'export_manifest.json').read_text(encoding='utf-8'))


def test_user_filter_and_caption(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    png_a = a1111_png(tmp_path / 'a.png')
    png_b = comfy_png(tmp_path / 'b.png')
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(png_a), 'A1111', 'sha-a'),
        ('200', 'ai_metadata', str(png_b), 'ComfyUI', 'sha-b'),
    ])
    stats = export_dataset(tmp_path, users=['100'], out='u100')
    out_dir = tmp_path / 'data' / 'export' / 'u100'
    images = sorted(out_dir.glob('*.png'))
    assert len(images) == 1
    assert stats['exported'] == 1
    caption = (out_dir / (images[0].stem + '.txt')).read_text(encoding='utf-8').strip()
    assert caption == 'shiroko \\(blue archive\\), on bed'
    assert read_manifest(out_dir)['counts']['captioned'] == 1


def test_sha_dedup_keeps_one_file(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    png = a1111_png(tmp_path / 'a.png')
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(png), 'A1111', 'sha-a'),
        ('100', 'ai_metadata', str(png), 'A1111', 'sha-a'),
        ('100', 'ai_metadata', str(png), 'A1111', 'sha-a'),
    ])
    stats = export_dataset(tmp_path, out='dedup')
    assert stats['deduped'] == 2
    assert stats['exported'] == 1


def test_source_display_alias(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    png_a = a1111_png(tmp_path / 'a.png')
    png_b = comfy_png(tmp_path / 'b.png')
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(png_a), 'A1111', 'sha-a'),
        ('200', 'ai_metadata', str(png_b), 'ComfyUI', 'sha-b'),
    ])
    stats = export_dataset(tmp_path, sources=['StableDiffusion_WebUI'], out='webui')
    assert stats['exported'] == 1
    assert stats['manifest']['by_source'] == {'A1111': 1}


def test_min_side_and_limit(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    small = tmp_path / 'small.png'
    Image.new('RGB', (320, 320)).save(small)
    big = a1111_png(tmp_path / 'big.png')
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(small), 'A1111', 'sha-s', 320, 320),
        ('100', 'ai_metadata', str(big), 'A1111', 'sha-b'),
        ('100', 'ai_metadata', str(big), 'A1111', 'sha-b'),
    ])
    stats = export_dataset(tmp_path, min_side=640, limit=5, out='big')
    assert stats['exported'] == 1
    assert stats['skipped_filter'] == 1
    assert stats['deduped'] == 1

    stats2 = export_dataset(tmp_path, min_side=640, limit=0, out='none', dry_run=True)
    assert stats2['exported'] == 0
    assert stats2['skipped_limit'] == 1  # 去重后只剩 1 张可截断


def test_dry_run_writes_nothing(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    png = a1111_png(tmp_path / 'a.png')
    make_db(tmp_path, [('100', 'ai_metadata', str(png), 'A1111', 'sha-a')])
    stats = export_dataset(tmp_path, out='dry', dry_run=True)
    assert stats['exported'] == 0
    assert not (tmp_path / 'data' / 'export' / 'dry').exists()


def test_caption_extractors():
    from qq_onebot_whitelist.export_dataset import _comfyui_positive_prompt, _a1111_positive_prompt, _prompt_from_novelai_json

    graph = {
        '3': {'class_type': 'KSampler', 'inputs': {'positive': ['5', 0], 'negative': ['6', 0]}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '1girl, suwako, touhou'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'bad hands, watermark'}},
    }
    assert _comfyui_positive_prompt(graph) == '1girl, suwako, touhou'
    # 没有采样器节点：取剔除 negative 后最长的文本
    assert _comfyui_positive_prompt({'5': graph['5'], '6': graph['6']}) == '1girl, suwako, touhou'
    assert _comfyui_positive_prompt('not a dict') == ''
    assert _a1111_positive_prompt('prompt text\nNegative prompt: bad\nSteps: 20') == 'prompt text'
    assert _prompt_from_novelai_json('{"prompt":"masterpiece, 1girl"}') == 'masterpiece, 1girl'
    # v4 结构化 prompt 不是字符串：返回空，回退 Description
    assert _prompt_from_novelai_json('{"prompt": {"content": "x"}}') == ''
    assert _prompt_from_novelai_json('not json') == ''


def test_novelai_comment_caption_and_exclude_user(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    png = novelai_png(tmp_path / 'n.png')
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(png), 'NovelAI', 'sha-n'),
        ('200', 'ai_metadata', str(png), 'NovelAI', 'sha-n'),
    ])
    stats = export_dataset(tmp_path, users=['100'], exclude_users=['200'], out='nai')
    out_dir = tmp_path / 'data' / 'export' / 'nai'
    images = sorted(out_dir.glob('*.png'))
    assert len(images) == 1
    caption = (out_dir / (images[0].stem + '.txt')).read_text(encoding='utf-8').strip()
    assert caption == 'masterpiece, 1girl'
    assert stats['manifest']['by_user'] == {'100': 1}


def test_orientation_and_keyword_filters(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset, main as export_main

    wide = tmp_path / 'wide.png'
    Image.new('RGB', (1200, 600)).save(wide)
    tall = tmp_path / 'tall.png'
    Image.new('RGB', (600, 1200)).save(tall)
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(wide), 'A1111', 'sha-w', 1200, 600, 'shiroko beach scene'),
        ('100', 'ai_metadata', str(tall), 'A1111', 'sha-t', 600, 1200),
    ])
    stats = export_dataset(tmp_path, orientation='landscape', out='land')
    assert stats['exported'] == 1
    assert stats['manifest']['counts']['skipped_filter'] == 1

    # 关键词不区分大小写，命中元数据文本
    stats_kw = export_dataset(tmp_path, keyword='SHIROKO', out='kw', dry_run=True)
    assert stats_kw['manifest']['counts']['selected'] == 1

    # 中文别名经 CLI 归一化
    assert export_main(['--project-dir', str(tmp_path), '--orientation', '竖图',
                        '--out', 'pt', '--no-captions']) == 0
    assert len(list((tmp_path / 'data' / 'export' / 'pt').glob('*.png'))) == 1


def test_dup_only_keeps_repeated_content(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    img = tmp_path / 'a.png'
    Image.new('RGB', (640, 640)).save(img)
    other = tmp_path / 'b.png'
    Image.new('RGB', (640, 640), (1, 2, 3)).save(other)
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(img), 'A1111', 'sha-dup', 640, 640),
        ('200', 'ai_metadata', str(img), 'A1111', 'sha-dup', 640, 640),
        ('100', 'ai_metadata', str(other), 'A1111', 'sha-unique', 640, 640),
    ])
    stats_all = export_dataset(tmp_path, dry_run=True)
    assert stats_all['manifest']['counts']['selected'] == 2
    # 只看重复：唯一内容被条件过滤，重复内容再去重后剩 1
    stats_dup = export_dataset(tmp_path, dup_only=True, dry_run=True)
    assert stats_dup['manifest']['counts']['selected'] == 1
    assert stats_dup['manifest']['counts']['skipped_filter'] == 1
    assert stats_dup['manifest']['params']['dup_only'] is True


def test_dup_only_prompt_key_counts_as_same_batch(tmp_path):
    import sqlite3

    from qq_onebot_whitelist.export_dataset import export_dataset

    img = tmp_path / 'a.png'
    Image.new('RGB', (640, 640)).save(img)
    img2 = tmp_path / 'c.png'
    Image.new('RGB', (640, 640), (9, 9, 9)).save(img2)
    make_db(tmp_path, [
        ('100', 'ai_metadata', str(img), 'A1111', 'sha-1', 640, 640),
        ('100', 'ai_metadata', str(img2), 'A1111', 'sha-2', 640, 640),
    ])
    conn = sqlite3.connect(tmp_path / 'data' / 'bot.db')
    conn.execute("UPDATE images SET prompt_key='sig-x' WHERE sha256 IN ('sha-1', 'sha-2')")
    conn.commit()
    conn.close()
    stats = export_dataset(tmp_path, dup_only=True, dry_run=True)
    assert stats['manifest']['counts']['selected'] == 2


def test_json_flag_prints_machine_summary(tmp_path, capsys):
    from qq_onebot_whitelist.export_dataset import main as export_main

    img = tmp_path / 'a.png'
    Image.new('RGB', (640, 640)).save(img)
    make_db(tmp_path, [('100', 'ai_metadata', str(img), 'A1111', 'sha-x', 640, 640)])
    assert export_main(['--project-dir', str(tmp_path), '--json', '--dry-run']) == 0
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if l.startswith('EXPORT_JSON ')][0]
    manifest = json.loads(line[len('EXPORT_JSON '):])
    assert manifest['counts']['selected'] == 1
    assert manifest['dry_run'] is True


def test_keyword_matches_filename(tmp_path):
    from qq_onebot_whitelist.export_dataset import export_dataset

    img = tmp_path / 'shiroko-beach.png'
    Image.new('RGB', (640, 640)).save(img)
    make_db(tmp_path, [('100', 'ai_metadata', str(img), 'A1111', 'sha-x', 640, 640, 'no hint here')])
    stats = export_dataset(tmp_path, keyword='SHIROKO-BEACH', dry_run=True)
    assert stats['manifest']['counts']['selected'] == 1


def test_out_dir_exports_to_absolute_folder(tmp_path, capsys):
    from qq_onebot_whitelist.export_dataset import main as export_main

    img = tmp_path / 'a.png'
    Image.new('RGB', (640, 640)).save(img)
    make_db(tmp_path, [('100', 'ai_metadata', str(img), 'A1111', 'sha-x', 640, 640)])
    target = tmp_path.parent / 'out_dir_dest_test'  # 项目目录之外
    assert export_main(['--project-dir', str(tmp_path), '--out-dir', str(target), '--json']) == 0
    assert len(list(target.glob('*.png'))) == 1
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith('EXPORT_JSON ')][0]
    manifest = json.loads(line[len('EXPORT_JSON '):])
    assert manifest['out'] == str(target)

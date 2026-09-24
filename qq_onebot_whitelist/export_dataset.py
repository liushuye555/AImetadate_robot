"""按用户/来源/尺寸筛选归档图片，导出 LoRA 训练数据集。

用法示例：
    python -m qq_onebot_whitelist.export_dataset --user 2310806372 --captions
    python -m qq_onebot_whitelist.export_dataset --source StableDiffusion_WebUI --min-side 1024 --limit 500
    python -m qq_onebot_whitelist.export_dataset --category 01 --user 1013844283 --dry-run

行为约定：
- 只取 kept_path 有效、未合并（merged_into IS NULL）的记录；
- sha256 内容级去重（同一张图重发/转发只保留最新一条，与视图展示规则一致）；
- 图片默认复制到导出目录（--link 改为硬链接，训练工具挪动文件时更安全用复制），
  文件名 0001_<记录id>_<宽x高>.<ext>；
- caption 默认开启（--no-captions 关闭）：为每张图写同名 .txt（kohya/OneTrainer
  约定），提示词从原图元数据重新提取——DB 里的 text_excerpt 只有 500 字符截断。
  A1111/NovelAI 取正向提示词段；ComfyUI 沿采样器节点的 positive 输入找文本节点，
  找不到时取最长的非 negative 文本；
- 导出目录写入 README.txt（人读）与 export_manifest.json（机读，筛选参数与统计），
  无论是否命中图片都会写，方便先跑 --dry-run 看统计。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from .build_image_view import _SAVED_ROOT, CATEGORY_NAMES, SOURCE_DISPLAY, safe_name, saved_category_name, source_path
from .image_meta import parse_image_metadata

# 来源显示名反查存储值（视图层换名后，命令行两种写法都接受）
_SOURCE_REVERSE = {display: value for value, display in SOURCE_DISPLAY.items()}


def _one_line(text: str, limit: int = 1500) -> str:
    text = ' '.join(str(text or '').replace('\r', ' ').replace('\n', ' ').split())
    return text[:limit].strip()


def _comfyui_positive_prompt(graph: object) -> str:
    """从 ComfyUI API 工作流图提取正向提示词。

    优先沿采样器节点（class_type 含 sampler）的 positive 输入找文本节点；
    negative 文本一律剔除；没有采样器节点时取最长的剩余文本兜底。
    """
    if not isinstance(graph, dict):
        return ''
    texts: dict[str, str] = {}
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get('inputs')
        if not isinstance(inputs, dict):
            continue
        raw = inputs.get('text')
        if isinstance(raw, str) and raw.strip():
            texts[str(node_id)] = raw.strip()
        elif isinstance(raw, list) and all(isinstance(part, str) for part in raw):
            joined = ', '.join(part.strip() for part in raw if part.strip())
            if joined:
                texts[str(node_id)] = joined
    if not texts:
        return ''
    positive_ids: list[str] = []
    negative_ids: list[str] = []
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get('class_type') or '').lower()
        inputs = node.get('inputs')
        if not isinstance(inputs, dict) or 'sampler' not in cls:
            continue
        for role, target in (('positive', positive_ids), ('negative', negative_ids)):
            link = inputs.get(role)
            if isinstance(link, list) and link:
                target.append(str(link[0]))
    for neg in negative_ids:
        texts.pop(neg, None)
    for pid in positive_ids:
        if pid in texts:
            return texts[pid]
    return max(texts.values(), key=len) if texts else ''


def _a1111_positive_prompt(text: str) -> str:
    """A1111 parameters 块：正向提示词在 Negative prompt / 参数行之前。"""
    lines: list[str] = []
    for line in str(text or '').splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith(('negative prompt:', 'steps:', 'sampler', 'seed:', 'cfg scale', 'size:', 'model')) or not stripped:
            if lines:
                break
            continue
        lines.append(stripped)
    return ' '.join(lines).strip() or (str(text or '').strip().splitlines() or [''])[0].strip()


def _prompt_from_novelai_json(payload: str) -> str:
    """NovelAI Comment/隐写 JSON：v3 是 {"prompt": "...", "uc": ...}；v4 结构化时回退 Description。"""
    try:
        data = json.loads(payload)
    except Exception:
        return ''
    if not isinstance(data, dict):
        return ''
    prompt = data.get('prompt')
    if isinstance(prompt, str) and prompt.strip():
        return prompt.strip()
    caption = data.get('caption')
    if isinstance(caption, dict) and isinstance(caption.get('base_caption'), str):
        return caption['base_caption'].strip()
    return ''


def extract_caption(path: Path) -> str:
    """从原图元数据提取正向提示词，失败返回空串（不写猜出来的 caption）。"""
    try:
        meta = parse_image_metadata(path)
    except Exception:
        return ''
    by_key = meta.text_by_key

    comment = by_key.get('Comment') or ''
    if comment:
        prompt = _prompt_from_novelai_json(comment)
        if prompt:
            return _one_line(prompt)

    comfy = by_key.get('prompt') or ''
    if comfy.lstrip().startswith('{'):
        prompt = _comfyui_positive_prompt(_load_json(comfy))
        if prompt:
            return _one_line(prompt)

    params = by_key.get('parameters') or ''
    if params:
        prompt = _a1111_positive_prompt(params)
        if prompt:
            return _one_line(prompt)

    description = by_key.get('Description') or ''
    if description:
        prompt = _prompt_from_novelai_json(description) or description.strip()
        if prompt:
            return _one_line(prompt)

    stego = by_key.get('stealth_pnginfo') or ''
    if stego:
        prompt = _prompt_from_novelai_json(stego) or _a1111_positive_prompt(stego)
        if prompt:
            return _one_line(prompt)

    return _one_line(_a1111_positive_prompt(meta.full_text)) if meta.full_text else ''


def _load_json(text: str) -> object:
    try:
        return json.loads(text)
    except Exception:
        return None


def normalize_source(value: str) -> str:
    return _SOURCE_REVERSE.get(str(value).strip(), str(value).strip())


def row_category(row: sqlite3.Row) -> str:
    """与 build_image_view 相同的类目推导（显示名映射后）。"""
    reason = str(row['retention_reason'] or 'unknown')
    if reason == 'chat_record_saved':
        return f'{_SAVED_ROOT}/{saved_category_name(row["saved_category"] if "saved_category" in row.keys() else "")}'
    cat = CATEGORY_NAMES.get(reason, '90_' + safe_name(reason))
    if reason == 'ai_metadata' and row['ai_source']:
        display = SOURCE_DISPLAY.get(str(row['ai_source']), str(row['ai_source']))
        cat = cat + '_' + safe_name(display)
    return cat


def export_dataset(
    project_dir: Path,
    *,
    users: list[str] | None = None,
    exclude_users: list[str] | None = None,
    sources: list[str] | None = None,
    categories: list[str] | None = None,
    min_side: int | None = None,
    min_w: int | None = None,
    min_h: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    captions: bool = True,
    link: bool = False,
    out: str | None = None,
    dry_run: bool = False,
) -> dict:
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    conn = sqlite3.connect(db)
    conn.execute('PRAGMA busy_timeout=5000')
    conn.row_factory = sqlite3.Row
    cols = {row[1] for row in conn.execute('PRAGMA table_info(images)')}
    sha_sel = 'sha256, ' if 'sha256' in cols else "'' AS sha256, "
    merged_filter = 'AND merged_into IS NULL ' if 'merged_into' in cols else ''
    saved_sel = 'saved_category, ' if 'saved_category' in cols else "'' AS saved_category, "
    rows = conn.execute(
        'SELECT id, ' + sha_sel + saved_sel + 'scope, user_id, seen_at, width, height, '
        'ai_source, retention_reason, kept_path FROM images '
        'WHERE kept_path IS NOT NULL ' + merged_filter + 'ORDER BY id DESC'
    ).fetchall()
    conn.close()

    user_set = {str(u).strip() for u in (users or []) if str(u).strip()}
    exclude_set = {str(u).strip() for u in (exclude_users or []) if str(u).strip()}
    source_set = {normalize_source(s) for s in (sources or []) if str(s).strip()}
    cat_list = [str(c).strip() for c in (categories or []) if str(c).strip()]

    stats: dict = {
        'scanned': 0, 'deduped': 0, 'skipped_filter': 0, 'skipped_missing': 0,
        'exported': 0, 'captioned': 0,
        'counts_by_source': Counter(), 'counts_by_user': Counter(), 'counts_by_category': Counter(),
    }
    selected: list[tuple[sqlite3.Row, Path]] = []
    seen_sha: set[str] = set()
    for row in rows:
        stats['scanned'] += 1
        uid = str(row['user_id'] or '')
        if user_set and uid not in user_set:
            stats['skipped_filter'] += 1
            continue
        if uid in exclude_set:
            stats['skipped_filter'] += 1
            continue
        if source_set and str(row['ai_source'] or '') not in source_set:
            stats['skipped_filter'] += 1
            continue
        if cat_list:
            cat = row_category(row)
            if not any(cat.startswith(c) for c in cat_list):
                stats['skipped_filter'] += 1
                continue
        w, h = int(row['width'] or 0), int(row['height'] or 0)
        if min_side and (w < min_side or h < min_side):
            stats['skipped_filter'] += 1
            continue
        if min_w and w < min_w:
            stats['skipped_filter'] += 1
            continue
        if min_h and h < min_h:
            stats['skipped_filter'] += 1
            continue
        seen_at = str(row['seen_at'] or '')
        if (since and (not seen_at or seen_at[:len(since)] < since)) or (
                until and (not seen_at or seen_at[:len(until)] > until)):
            stats['skipped_filter'] += 1
            continue
        src = source_path(project_dir, row['kept_path'])
        if not src.exists():
            stats['skipped_missing'] += 1
            continue
        # 过滤命中后再按 sha 去重：他人在后的转发不能代表被筛用户的记录
        sha = str(row['sha256'] or '')
        if sha:
            if sha in seen_sha:
                stats['deduped'] += 1
                continue
            seen_sha.add(sha)
        selected.append((row, src))

    if limit is not None and len(selected) > limit:
        stats['skipped_limit'] = len(selected) - limit
        selected = selected[:limit]
    else:
        stats['skipped_limit'] = 0

    for row, _src in selected:
        source_val = str(row['ai_source'] or '无元数据')
        stats['counts_by_source'][source_val] += 1
        stats['counts_by_user'][str(row['user_id'] or '?')] += 1
        stats['counts_by_category'][row_category(row)] += 1

    out_dir = project_dir / 'data' / 'export' / (out or time.strftime('dataset-%Y%m%d-%H%M%S'))
    if not dry_run and selected:
        out_dir.mkdir(parents=True, exist_ok=True)
        for index, (row, src) in enumerate(selected, 1):
            w, h = int(row['width'] or 0), int(row['height'] or 0)
            ext = src.suffix.lower() or '.img'
            name = f'{index:04d}_id{row["id"]}_{w or "x"}x{h or "x"}' + ext
            dst = out_dir / name
            if link:
                try:
                    if not dst.exists():
                        os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
            else:
                shutil.copy2(src, dst)
            stats['exported'] += 1
            if captions:
                caption = extract_caption(src)
                if caption:
                    (out_dir / (name.rsplit('.', 1)[0] + '.txt')).write_text(caption + '\n', encoding='utf-8')
                    stats['captioned'] += 1

    manifest = {
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'dry_run': dry_run,
        'params': {
            'users': sorted(user_set), 'exclude_users': sorted(exclude_set),
            'sources': sorted(source_set), 'categories': cat_list,
            'min_side': min_side, 'min_w': min_w, 'min_h': min_h,
            'since': since, 'until': until, 'limit': limit,
            'captions': captions, 'link': link,
        },
        'counts': {
            'scanned': stats['scanned'], 'deduped': stats['deduped'],
            'skipped_filter': stats['skipped_filter'], 'skipped_missing': stats['skipped_missing'],
            'skipped_limit': stats['skipped_limit'],
            'selected': len(selected), 'exported': stats['exported'], 'captioned': stats['captioned'],
        },
        'by_source': dict(stats['counts_by_source'].most_common()),
        'by_user': dict(stats['counts_by_user'].most_common()),
        'by_category': dict(stats['counts_by_category'].most_common()),
        'out': str(out_dir.relative_to(project_dir)) if not dry_run else None,
    }
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'export_manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        (out_dir / 'README.txt').write_text(_readme(manifest), encoding='utf-8')
    stats['manifest'] = manifest
    stats['out_dir'] = str(out_dir)
    return stats


def _readme(manifest: dict) -> str:
    lines = [
        'LoRA 训练数据集导出',
        '==================',
        f"导出时间：{manifest['created_at']}    图片：{manifest['counts']['exported']} 张"
        f"（其中 {manifest['counts']['captioned']} 张带 .txt 提示词 caption）",
        '',
        '筛选条件：' + json.dumps(manifest['params'], ensure_ascii=False),
        '',
        '按来源：',
    ]
    for key, value in manifest['by_source'].items():
        lines.append(f'  {key}: {value}')
    lines.append('按用户：')
    for key, value in manifest['by_user'].items():
        lines.append(f'  {key}: {value}')
    lines.append('按类目：')
    for key, value in manifest['by_category'].items():
        lines.append(f'  {key}: {value}')
    lines += [
        '',
        '说明：已按 sha256 内容去重（重发/转发只保留一条）；caption 是从图片元数据',
        '提取的正向提示词（A1111/NovelAI 参数段、ComfyUI positive 文本节点），提取',
        '失败的图片没有 .txt；训练前建议再过一遍视觉相似（视图页面的相似组徽标）。',
    ]
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='按用户/来源/尺寸导出 LoRA 训练数据集')
    parser.add_argument('--project-dir', default='.')
    parser.add_argument('--user', action='append', default=[], help='只导出该用户（QQ 号），可重复')
    parser.add_argument('--exclude-user', action='append', default=[], help='排除该用户，可重复')
    parser.add_argument('--source', action='append', default=[], help='按来源过滤：ComfyUI / A1111 / StableDiffusion_WebUI / NovelAI')
    parser.add_argument('--category', action='append', default=[], help='按类目前缀过滤：01 / 02 / 03 / 06 等')
    parser.add_argument('--min-side', type=int, help='宽高都不小于该值')
    parser.add_argument('--min-w', type=int)
    parser.add_argument('--min-h', type=int)
    parser.add_argument('--since', help='seen_at 起始日期 YYYY-MM-DD')
    parser.add_argument('--until', help='seen_at 截止日期 YYYY-MM-DD')
    parser.add_argument('--limit', type=int, help='最多导出多少张')
    parser.add_argument('--no-captions', action='store_true', help='不写 .txt 提示词文件')
    parser.add_argument('--link', action='store_true', help='硬链接代替复制（省空间，训练时勿删原图）')
    parser.add_argument('--out', help='导出目录名（默认 data/export/dataset-时间戳）')
    parser.add_argument('--dry-run', action='store_true', help='只统计不写文件')
    args = parser.parse_args(argv)

    stats = export_dataset(
        Path(args.project_dir).resolve(),
        users=args.user, exclude_users=args.exclude_user, sources=args.source,
        categories=args.category, min_side=args.min_side, min_w=args.min_w,
        min_h=args.min_h, since=args.since, until=args.until, limit=args.limit,
        captions=not args.no_captions, link=args.link, out=args.out, dry_run=args.dry_run,
    )
    manifest = stats['manifest']
    prefix = '[dry-run] ' if manifest['dry_run'] else ''
    print(f"{prefix}筛选命中 {manifest['counts']['selected']} 张"
          f"（扫描 {manifest['counts']['scanned']}，内容去重 {manifest['counts']['deduped']}，"
          f"条件过滤 {manifest['counts']['skipped_filter']}，原图缺失 {manifest['counts']['skipped_missing']}）")
    if not manifest['dry_run']:
        print(f"导出目录：{stats['out_dir']}")
        print(f"caption：{manifest['counts']['captioned']}/{manifest['counts']['exported']}")
    for title, data in (('按来源', manifest['by_source']), ('按用户', manifest['by_user']), ('按类目', manifest['by_category'])):
        if data:
            print(title + '：' + '，'.join(f'{key}={value}' for key, value in list(data.items())[:12]))
    return 0


if __name__ == '__main__':
    sys.exit(main())

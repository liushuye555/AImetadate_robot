"""Read-only cover and group projections for the live database gallery.

Group membership is resolved over the complete filtered result before paging
covers. Original images stay in their archive; no classification links are made.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from pathlib import Path
import hashlib
import re

from .gallery_store import connect, normalize_query, query_images
from .build_image_view import _assign_dup_groups, _dhash_from_db


def _public(row: dict) -> dict:
    item = {k: v for k, v in row.items()
            if k not in {'kept_path', 'sha256', 'identity', 'rn', 'masked'}}
    item['url'] = f'/media/images/{row["file_id"]}'
    item['thumbnail'] = item['url'] + '/thumbnail'
    item['deobfuscated'] = row.get('masked', 0)
    return item


def _catalogue(project_dir: Path, values: dict) -> tuple[list, dict, int]:
    # Query/export keeps the existing membership, content-dedup and sort rules.
    result = query_images(project_dir, values, export=True)
    rows = result['items']
    groups: dict[str, dict] = {}
    batches: dict[str, list] = defaultdict(list)
    for row in rows:
        if row.get('prompt_key'):
            batches['batch:' + row['prompt_key']].append(row)
    for key, members in batches.items():
        if len(members) > 1:
            groups[key] = {'key': key, 'kind': '同批', 'count': len(members), 'members': members}

    # Reuse the pre-migration visual hashes. New archives already have pHash;
    # never mix pHash and dHash in one comparison bucket or decode originals on
    # the catalogue request path.
    visual = {}
    phashes = {}
    with closing(connect(project_dir)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'view_dhash' in tables:
            columns = {r[1] for r in conn.execute('PRAGMA table_info(view_dhash)')}
            md5 = 'md5' if 'md5' in columns else "''"
            for row in conn.execute(f'SELECT path,dhash,{md5} FROM view_dhash ORDER BY mtime DESC'):
                match = re.search(r'(?:^|[\\/])#([0-9]+)_', row[0])
                if match:
                    visual.setdefault(int(match[1]), (_dhash_from_db(int(row[1] or 0)), row[2] or ''))
        if 'image_hashes' in tables:
            for sha, digest in conn.execute('SELECT sha256,phash FROM image_hashes WHERE phash IS NOT NULL'):
                try:
                    phashes[sha] = int(digest)
                except (ValueError, TypeError):
                    continue
    hashes = defaultdict(list)
    for row in rows:
        key = str(row['id'])
        dimensions = (int(row.get('width') or 0), int(row.get('height') or 0))
        cached = visual.get(row['file_id']) or visual.get(row['id'])
        if cached:
            hashes['dhash'].append((key, cached[0], dimensions, cached[1]))
        elif row.get('sha256') in phashes:
            hashes['phash'].append((key, phashes[row['sha256']], dimensions, ''))
    row_by_id = {str(r['id']): r for r in rows}
    similar_for = {}
    for entries in hashes.values():
        members_by_group = defaultdict(list)
        for row_id, group in _assign_dup_groups(entries).items():
            members_by_group[group].append(row_by_id[row_id])
        for members in members_by_group.values():
            fingerprint = ','.join(sorted(str(r['file_id']) for r in members))
            key = 'similar:' + hashlib.sha1(fingerprint.encode()).hexdigest()[:20]
            groups[key] = {'key': key, 'kind': '相似', 'count': len(members), 'members': members}
            for row in members:
                similar_for[row['id']] = key

    covers, seen = [], set()
    for row in rows:
        batch = 'batch:' + str(row.get('prompt_key') or '')
        relations = [k for k in (similar_for.get(row['id']), batch) if k in groups]
        primary = relations[0] if relations else 'image:' + str(row['id'])
        if primary in seen:
            continue
        seen.add(primary)
        item = _public(row)
        item['groups'] = [{k: groups[key][k] for k in ('key', 'kind', 'count')} for key in relations]
        covers.append(item)
    return covers, groups, result['total']


def browse_images(project_dir: Path, values: dict) -> dict:
    q = normalize_query(values)
    covers, _, total = _catalogue(project_dir, values)
    offset = (q['page'] - 1) * q['page_size']
    return {'items': covers[offset:offset + q['page_size']], 'total': total,
            'group_total': len(covers), 'page': q['page'], 'page_size': q['page_size'],
            'has_more': offset + q['page_size'] < len(covers)}


def image_group(project_dir: Path, values: dict) -> dict:
    values = dict(values)
    key = values.pop('key', '')
    if not key or len(key) > 250:
        raise ValueError('图片分组编号无效')
    _, groups, _ = _catalogue(project_dir, values)
    if key not in groups:
        raise FileNotFoundError('当前筛选下没有这个图片分组')
    group = groups[key]
    return {**group, 'members': [_public(row) for row in group['members']]}

"""Read-only, live image catalogue shared by the gallery and dataset export.

Images stay in the archive. No catalogue query creates files, links or DB tables.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3

from .build_image_view import CATEGORY_NAMES, image_category, saved_category_name, _SAVED_ROOT


def normalize_query(values: dict) -> dict:
    allowed = {'category', 'scope', 'user', 'source', 'keyword', 'since', 'until',
               'orientation', 'min_side', 'dup_only', 'sort', 'page', 'page_size'}
    if not isinstance(values, dict) or set(values) - allowed:
        raise ValueError('未知图库筛选条件')
    q = {}
    for key, value in values.items():
        if isinstance(value, (list, dict)):
            raise ValueError('筛选条件格式错误')
        value = str(value).strip()
        if len(value) > 250:
            raise ValueError('筛选条件过长')
        if value:
            q[key] = value
    for key in ('since', 'until'):
        if key in q:
            try:
                if date.fromisoformat(q[key]).isoformat() != q[key]:
                    raise ValueError()
            except ValueError:
                raise ValueError('日期需要 YYYY-MM-DD 格式') from None
    if q.get('since', '') > q.get('until', '9999-12-31'):
        raise ValueError('开始日期不能晚于结束日期')
    for key, default, low, high in (('page', 1, 1, 1000000), ('page_size', 60, 1, 120),
                                    ('min_side', 0, 0, 32768)):
        try:
            q[key] = int(q.get(key, default))
        except (ValueError, TypeError):
            raise ValueError('分页或尺寸参数不正确') from None
        if not low <= q[key] <= high:
            raise ValueError('分页或尺寸参数超出范围')
    if q.get('orientation', '') not in ('', 'landscape', 'portrait', 'square'):
        raise ValueError('未知图片方向')
    if q.get('sort', 'newest') not in ('newest', 'oldest', 'pixels', 'size'):
        raise ValueError('未知排序方式')
    q['dup_only'] = str(q.get('dup_only', '')).lower() in ('1', 'true')
    return q


def connect(project_dir: Path) -> sqlite3.Connection:
    database = Path(project_dir).resolve() / 'data' / 'bot.db'
    conn = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.create_function('gallery_category', 3, lambda reason, source, saved:
                         f'{_SAVED_ROOT}/{saved_category_name(saved)}' if reason == 'chat_record_saved'
                         else image_category(str(reason or 'unknown'), source), deterministic=True)
    return conn


def _base(conn: sqlite3.Connection) -> str:
    cols = {r[1] for r in conn.execute('PRAGMA table_info(images)')}
    def col(name, fallback="''"):
        return 'i.' + name if name in cols else fallback
    discussion = conn.execute("SELECT 1 FROM sqlite_master WHERE name='image_discussions'").fetchone()
    join = 'LEFT JOIN image_discussions d ON d.image_id=i.id' if discussion else ''
    status = "COALESCE(d.status,'')" if discussion else "''"
    text = "CASE WHEN d.status='selected' THEN d.context_text ELSE " + col('bound_prompt') + ' END' if discussion else col('bound_prompt')
    # Merged records may retain a context placement, but their bytes belong to a surviving row.
    file_id = ("COALESCE(CASE WHEN i.kept_path IS NOT NULL AND i.kept_path!='' THEN i.id END, "
               "(SELECT p.id FROM images p WHERE i.sha256!='' AND p.sha256=i.sha256 AND p.kept_path IS NOT NULL "
               "AND p.kept_path!='' ORDER BY p.id DESC LIMIT 1))") if 'sha256' in cols else 'i.id'
    main = f"CASE WHEN {col('merged_into', 'NULL')} IS NULL AND i.kept_path IS NOT NULL AND i.kept_path!='' AND NOT (i.retention_reason='params_discussion' AND {status} IN ('pending','rejected')) THEN gallery_category(i.retention_reason,i.ai_source,{col('saved_category')}) END"
    context = f"CASE WHEN {col('context_reason')} IN ({','.join(repr(k) for k in CATEGORY_NAMES)}) AND NOT ({col('context_reason')}='params_discussion' AND {status} IN ('pending','rejected')) THEN gallery_category({col('context_reason')},i.ai_source,{col('saved_category')}) END"
    mask = "CASE WHEN deobfuscated=1 OR (SELECT p.deobfuscated FROM images p WHERE p.id=catalogue.file_id)=1 THEN 1 ELSE 0 END" if 'deobfuscated' in cols else '0'
    return f"""WITH catalogue AS (
      SELECT i.id, {file_id} AS file_id, i.kept_path, i.scope, i.user_id, i.seen_at,
        i.width, i.height, i.size, i.format, i.ai_source, i.retention_reason,
        {col('saved_category')} AS saved_category, {col('sha256')} AS sha256,
        {col('prompt_key')} AS prompt_key, {col('bound_prompt')} AS bound_prompt,
        {col('text_excerpt')} AS text_excerpt, {text} AS discussion_text,
        {col('deobfuscated','0')} AS deobfuscated,
        {main} AS category, {context} AS context_category
      FROM images i {join}
      WHERE (i.kept_path IS NOT NULL AND i.kept_path!='') OR {col('context_reason')}!=''
    ), available AS (
      SELECT *, {mask} AS masked, CASE WHEN sha256 IS NOT NULL AND sha256!='' THEN 'sha:'||sha256 ELSE 'id:'||file_id END AS identity
      FROM catalogue WHERE file_id IS NOT NULL
    ) """


def _selection(q: dict) -> tuple[str, list]:
    where, params = [], []
    if q.get('category'):
        where.append('(category=? OR context_category=? OR substr(category,1,length(?)+1)=?||\'/\')')
        params += [q['category']] * 4
    else:
        where.append("category IS NOT NULL AND category!=?")
        params.append(CATEGORY_NAMES['candidate'])
    for key, column in (('scope', 'scope'), ('user', 'user_id'), ('source', 'ai_source')):
        if q.get(key):
            where.append(column + '=?')
            params.append(q[key])
    if q.get('keyword'):
        where.append("instr(lower(COALESCE(text_excerpt,'')||' '||COALESCE(bound_prompt,'')||' '||COALESCE(discussion_text,'')||' '||id||' '||COALESCE(user_id,'')),lower(?))>0")
        params.append(q['keyword'])
    for key, operator in (('since', '>='), ('until', '<=')):
        if q.get(key):
            where.append(f'substr(seen_at,1,10){operator}?')
            params.append(q[key])
    if q['min_side']:
        where.append('width>=? AND height>=?')
        params += [q['min_side']] * 2
    orientation = q.get('orientation')
    if orientation:
        where.append('width>0 AND height>0')
        where.append({'landscape': 'width>=height*1.2', 'portrait': 'height>=width*1.2',
                      'square': 'width<height*1.2 AND height<width*1.2'}[orientation])
    if q['dup_only']:
        where.append("((sha256!='' AND (SELECT COUNT(*) FROM images x WHERE x.kept_path IS NOT NULL AND x.sha256=available.sha256)>1) OR (prompt_key!='' AND (SELECT COUNT(*) FROM images x WHERE x.kept_path IS NOT NULL AND x.prompt_key=available.prompt_key)>1))")
    return ', filtered AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY identity ORDER BY id DESC) AS rn FROM available WHERE ' + ' AND '.join(where) + ') ', params


def query_images(project_dir: Path, values: dict, *, export: bool = False) -> dict:
    q = normalize_query(values)
    with closing(connect(project_dir)) as conn:
        base = _base(conn)
        selection, params = _selection(q)
        sql = base + selection
        total = conn.execute(sql + 'SELECT COUNT(*) FROM filtered WHERE rn=1', params).fetchone()[0]
        sort = {'newest': 'id DESC', 'oldest': 'id ASC', 'pixels': 'width*height DESC,id DESC',
                'size': 'size DESC,id DESC'}[q.get('sort', 'newest')]
        limit, offset = (total, 0) if export else (q['page_size'], (q['page'] - 1) * q['page_size'])
        rows = conn.execute(sql + f'SELECT * FROM filtered WHERE rn=1 ORDER BY {sort} LIMIT ? OFFSET ?',
                            [*params, limit, offset]).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if export:
                file_row = conn.execute('SELECT kept_path FROM images WHERE id=?', (row['file_id'],)).fetchone()
                item['kept_path'] = file_row[0]
            else:
                for private in ('kept_path', 'sha256', 'identity', 'rn'):
                    item.pop(private, None)
                item['url'] = f'/media/images/{row["file_id"]}'
                item['thumbnail'] = item['url'] + '/thumbnail'
                item['deobfuscated'] = item.pop('masked')
            items.append(item)
    return {'items': items, 'total': total, 'page': q['page'], 'page_size': q['page_size'],
            'has_more': offset + len(items) < total}


def facets(project_dir: Path) -> dict:
    with closing(connect(project_dir)) as conn:
        base = _base(conn)
        categories = [dict(r) for r in conn.execute(base + """
          SELECT name,COUNT(DISTINCT identity) AS count FROM (
            SELECT category AS name,identity FROM available WHERE category IS NOT NULL
            UNION ALL SELECT context_category,identity FROM available WHERE context_category IS NOT NULL
          ) GROUP BY name ORDER BY name""")]
        total = conn.execute(base + 'SELECT COUNT(DISTINCT identity) FROM available WHERE category IS NOT NULL AND category!=?',
                             (CATEGORY_NAMES['candidate'],)).fetchone()[0]
        choices = {}
        for key, column in (('scopes', 'scope'), ('users', 'user_id'), ('sources', 'ai_source')):
            choices[key] = [dict(r) for r in conn.execute(base + f"SELECT {column} AS value,COUNT(DISTINCT identity) AS count FROM available WHERE {column} IS NOT NULL AND {column}!='' AND (category IS NOT NULL OR context_category IS NOT NULL) GROUP BY {column} ORDER BY count DESC,{column}")]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='group_names'").fetchone():
            names = dict(conn.execute('SELECT group_id,name FROM group_names'))
            for scope in choices['scopes']:
                scope['label'] = names.get(scope['value'].removeprefix('group:'), scope['value'])
    return {'categories': categories, 'total': total, **choices}


def image_path(project_dir: Path, image_id: int) -> Path:
    with closing(connect(project_dir)) as conn:
        row = conn.execute('SELECT kept_path FROM images WHERE id=?', (image_id,)).fetchone()
    if not row or not row[0]:
        raise FileNotFoundError('图片未归档')
    path = Path(row[0])
    path = (path if path.is_absolute() else project_dir / path).resolve()
    # IDs, never request-supplied filesystem paths. Symlinks may not expose files outside this archive.
    if not path.is_relative_to(project_dir.resolve()) or path.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.webp','.bmp'} or not path.is_file():
        raise FileNotFoundError('原图不存在或不在项目归档范围内')
    return path


def image_details(project_dir: Path, image_id: int) -> dict:
    """Read the original prompt lazily, as the former static lightbox did."""
    from .export_dataset import extract_caption
    with closing(connect(project_dir)) as conn:
        row = conn.execute(_base(conn) + 'SELECT file_id FROM available WHERE id=?',
                           (image_id,)).fetchone()
    if not row or not row['file_id']:
        raise FileNotFoundError('图片未归档')
    path = image_path(project_dir, row['file_id'])
    return {'filename': path.name, 'prompt': extract_caption(path)}

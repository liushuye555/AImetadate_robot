"""Database gallery entry points and report navigation (no image placement)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
import html
import json

from .view_theme import page_shell, background_css, find_wallpaper, WALLPAPER_DEFER_JS


def gallery_html(project_dir: Path) -> str:
    """Use the same retained wallpaper as the report pages, without creating links."""
    page = Path(__file__).with_name('gallery.html').read_text(encoding='utf-8')
    wallpaper = find_wallpaper(project_dir / 'data' / 'view')
    if not wallpaper:
        return page
    background = background_css('/view/' + wallpaper)
    return page.replace('</style>', background + '</style>', 1).replace(
        '</body>', WALLPAPER_DEFER_JS + '</body>', 1)


def port_for(project_dir: Path) -> int:
    from .config import load_config
    return load_config(project_dir / 'config.yaml').view_server_port


def hub_html(project_dir: Path, meta: dict) -> str:
    from .build_image_view import _index_card
    def category_card(category):
        url = html.escape('gallery.html?' + urlencode({'category': category['name']}), quote=True)
        return (f'<a class="card" href="{url}"><h2>🗂️ {html.escape(category["name"])}</h2>'
                f'<p class="muted">按数据库分类浏览</p><div class="count">{category["count"]} 张</div></a>')
    cards = [_index_card('gallery.html', '🖼️', '全部归档图片', '直接查询数据库，按群、分类、发送者和生成工具筛选', f'{meta["total"]} 张')]
    for href, icon, title, desc in (
        ('knowledge.html', '📖', '群知识', '知识、问题线索与待跟进'),
        ('glossary.html', '📚', '术语', '群内术语与原始出处'),
        ('knowledge-summary.html', '💬', '群总结', '按批次回顾讨论'),
        ('knowledge-files.html', '📌', '保留文件 · 精选', '已保存的精选资料'),
        ('resources.html', '🔗', '高价值资源链接', '按群分类去重'),
        ('files.html', '📦', '群文件 · 全部采集', '文件与工作流信息')):
        cards.append(_index_card(href, icon, title, desc, ''))
    for category in meta['categories']:
        cards.append(category_card(category))
    body = ('<h1>图片与资源总览</h1><p class="page-desc">图片分类直接查询数据库；知识、术语、群总结和资源报告继续在这里浏览。</p>'
            f'<div class="chips"><span class="chip">归档图片 <b>{meta["total"]}</b> 张</span><span class="chip">数据库图库</span></div>'
            '<div class="grid" style="margin-top:22px">' + ''.join(cards) + '</div>'
            '<p class="foot">原图集中归档；日常浏览不生成分类硬链接。图片记录即时读取，文字报告通过“更新资料页面”更新。</p>')
    background = background_css(find_wallpaper(project_dir / 'data' / 'view'))
    return page_shell(title='图片与资源总览', body=body, background=background)


def build_database_view(project_dir: Path) -> dict[str, int]:
    from .gallery_store import facets
    from .build_image_view import _write_if_changed, ALL_GALLERY_DIR
    from .config import load_config
    from .store import Store
    from .resource_view import write_resource_pages
    project_dir = Path(project_dir).resolve()
    view = project_dir / 'data' / 'view'
    view.mkdir(parents=True, exist_ok=True)
    meta = facets(project_dir)
    counts = {c['name']: c['count'] for c in meta['categories']}
    counts[ALL_GALLERY_DIR] = meta['total']
    config = load_config(project_dir / 'config.yaml')
    counts.update(write_resource_pages(view, Store(project_dir / 'data' / 'bot.db'),
                                       link_judge_mode=config.links_link_judge))
    # File entry points opened by the desktop manager move to the local service.
    target = f'http://127.0.0.1:{config.view_server_port}/view/'
    redirect = '<script>if(location.protocol==="file:")location.replace(' + json.dumps(target) + '+location.hash)</script>'
    _write_if_changed(view / 'index.html', hub_html(project_dir, meta).replace('<body>', '<body>' + redirect))
    gallery = gallery_html(project_dir)
    gallery_redirect = '<script>if(location.protocol==="file:")location.replace(' + json.dumps(target + 'gallery.html') + '+location.search+location.hash)</script>'
    _write_if_changed(view / 'gallery.html', gallery.replace('</head>', gallery_redirect + '</head>'))
    # Compatibility entry points contain navigation only; existing image links are left intact.
    for category in [ALL_GALLERY_DIR, *(c['name'] for c in meta['categories'])]:
        query = '' if category == ALL_GALLERY_DIR else '?' + urlencode({'category': category})
        url = target + 'gallery.html' + query
        entry = view / category / 'index.html'
        entry.parent.mkdir(parents=True, exist_ok=True)
        _write_if_changed(entry, '<!doctype html><meta charset="utf-8"><title>图片库</title><p><a href="'
                          + html.escape(url, quote=True) + '">打开数据库图库</a></p><script>location.replace('
                          + json.dumps(url) + ')</script>')
    _write_if_changed(view / 'README.txt', '图库现在直接查询 data/bot.db。\n原图保存在归档目录，浏览不创建分类硬链接。\n旧分类目录暂保留以兼容历史报告；不要把它们当作唯一原图。\n')
    return counts

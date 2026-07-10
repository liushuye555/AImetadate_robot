from pathlib import Path

from qq_onebot_whitelist.build_image_view import write_view_index


def test_write_view_index_lists_categories_and_links(tmp_path):
    view = tmp_path / 'view'
    (view / '03_AI上下文').mkdir(parents=True)
    (view / '03_AI上下文' / 'index.html').write_text('x', encoding='utf-8')
    (view / '02_群友好评').mkdir(parents=True)
    (view / '02_群友好评' / 'a.jpg').write_bytes(b'x')

    write_view_index(view, {'03_AI上下文': 5, '02_群友好评': 1})

    html = (view / 'index.html').read_text(encoding='utf-8')
    assert 'resources.html' in html
    assert 'files.html' in html
    assert '03_AI%E4%B8%8A%E4%B8%8B%E6%96%87/index.html' in html
    assert '02_%E7%BE%A4%E5%8F%8B%E5%A5%BD%E8%AF%84/' in html
    assert '5 张' in html
    assert '1 张' in html

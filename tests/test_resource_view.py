from pathlib import Path

from qq_onebot_whitelist.resource_view import select_resource_links, write_resource_pages
from qq_onebot_whitelist.store import Store


def test_write_resource_pages_keeps_old_records_and_filters_low_value(tmp_path):
    db = tmp_path / 'bot.db'
    store = Store(db)
    store.record_link(scope='group:1', user_id='u1', url='https://v.kuaishou.com/example-test', message_text='测试短视频分享')
    store.record_link(scope='group:1', user_id='u2', url='https://civitai.com/models/123/model?utm=abc', message_text='好用的 lora')
    store.record_file(scope='group:1', user_id='u3', file_name='workflow.json', file_size=1024, url='https://long.url/x', kind='workflow', raw={})

    result = write_resource_pages(tmp_path / 'view', store)

    resources = (tmp_path / 'view' / 'resources.html').read_text(encoding='utf-8')
    files = (tmp_path / 'view' / 'files.html').read_text(encoding='utf-8')
    assert result == {'resource_links': 1, 'resource_files': 1}
    assert 'civitai.com/models/123/model' in resources
    assert '用途：核心AI资源' in resources
    assert '好用的 lora' in resources
    assert 'kuaishou' not in resources.lower()
    # 共享样式骨架：返回总览、计数 chip、空结果提示与排序
    assert '<a href="index.html">← 返回总览</a>' in resources
    assert 'id="count"' in resources
    assert 'id="noResult"' in resources
    assert 'id="sortSel"' in resources
    assert '最新优先' in resources
    assert '<li data-time="' in resources
    assert 'id="sortSel"' in files
    assert 'data-size="' in files
    assert 'data-name="' in files
    assert 'workflow.json' in files
    assert '可导入或检查的工作流配置' in files
    assert 'https://long.url/x' not in files


def test_write_resource_pages_rebuilds_from_full_db_not_incremental_only(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://github.com/a/b', message_text='老链接')
    write_resource_pages(tmp_path / 'view', store)
    store.record_link(scope='group:1', user_id='u1', url='https://huggingface.co/a/b', message_text='新模型')

    write_resource_pages(tmp_path / 'view', store)
    resources = (tmp_path / 'view' / 'resources.html').read_text(encoding='utf-8')

    assert 'github.com/a/b' in resources
    assert 'huggingface.co/a/b' in resources


def test_resource_pages_keep_interesting_sites_with_short_description(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://weird-tools.example/paint', message_text='这个小网站可以在线试试效果')

    result = write_resource_pages(tmp_path / 'view', store)

    resources = (tmp_path / 'view' / 'resources.html').read_text(encoding='utf-8')
    assert result['resource_links'] == 1
    assert 'https://weird-tools.example/paint' in resources
    assert '用途：值得一看' in resources
    assert '这个小网站可以在线试试效果' in resources
    assert 'placeholder="搜索群名、文件名、简介或网址"' in resources


def test_resource_pages_keep_unknown_link_without_source_group(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:987654', user_id='u', url='https://unknown.example/item')

    result = write_resource_pages(tmp_path / 'view', store)

    resources = (tmp_path / 'view' / 'resources.html').read_text(encoding='utf-8')
    assert result['resource_links'] == 1
    assert 'https://unknown.example/item' in resources
    assert '群聊未说明用途' in resources
    assert '987654' not in resources


def test_resource_selection_hides_opaque_image_and_short_links_and_dedupes_root_url(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://postimg.cc/abc123', message_text='图片')
    store.record_link(scope='group:1', user_id='u', url='https://xhslink.cn/abc123', message_text='短链')
    store.record_link(scope='group:1', user_id='u', url='https://tool.example', message_text='在线工具')
    store.record_link(scope='group:1', user_id='u', url='https://tool.example/', message_text='在线工具')

    links = select_resource_links(store)

    assert [item['url'] for item in links] == ['https://tool.example']

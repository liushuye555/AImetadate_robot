from qq_onebot_whitelist.resource_view import write_resource_pages
from qq_onebot_whitelist.store import Store


def test_resource_links_dedupe_across_scopes_and_tracking_queries(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u1', url='https://civitai.com/models/123/model?utm=abc', message_text='lora')
    store.record_link(scope='group:2', user_id='u2', url='https://civitai.com/models/123/model?from=qq', message_text='lora repeat')

    result = write_resource_pages(tmp_path / 'view', store)
    html = (tmp_path / 'view' / 'resources.html').read_text(encoding='utf-8')

    assert result['resource_links'] == 1
    # li 带排序属性（<li data-time=...>），按条目数断言
    assert html.count('class="resource-item"') == 1


def test_resource_files_dedupe_across_scopes_by_name_size_kind(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_file(scope='group:1', user_id='u1', file_name='workflow.json', file_size=1024, url='u1', kind='workflow', raw={})
    store.record_file(scope='group:2', user_id='u2', file_name='Workflow.json', file_size=1024, url='u2', kind='workflow', raw={})

    result = write_resource_pages(tmp_path / 'view', store)
    html = (tmp_path / 'view' / 'files.html').read_text(encoding='utf-8')

    assert result['resource_files'] == 1
    # data-name 排序属性会重复一次文件名，按条目数断言去重
    assert html.count('class="resource-item"') == 1
    assert 'workflow.json' in html.lower()
    assert 'group:1' in html
    assert 'group:2' in html

import pytest

from qq_onebot_whitelist.link_metadata import (
    get_or_fetch_link_metadata,
    parse_html_metadata,
    validate_fetch_url,
)
from qq_onebot_whitelist.store import Store


def test_parse_html_metadata_prefers_open_graph_title_and_description():
    html = '''
    <html><head>
      <title>Fallback title</title>
      <meta property="og:title" content="Useful title">
      <meta name="description" content="Useful description">
    </head></html>
    '''
    assert parse_html_metadata(html) == {'title': 'Useful title', 'description': 'Useful description'}


def test_validate_fetch_url_rejects_local_and_non_http_urls():
    with pytest.raises(ValueError):
        validate_fetch_url('http://127.0.0.1:8080/private')
    with pytest.raises(ValueError):
        validate_fetch_url('file:///C:/secret.txt')


def test_get_or_fetch_link_metadata_reuses_store_cache(tmp_path):
    store = Store(tmp_path / 'bot.db')
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return {'title': 'Cached title', 'description': 'Cached description'}

    first = get_or_fetch_link_metadata(store, 'https://example.com/page', fetcher=fake_fetch)
    second = get_or_fetch_link_metadata(store, 'https://example.com/page', fetcher=fake_fetch)

    assert first == second == {'title': 'Cached title', 'description': 'Cached description'}
    assert calls == ['https://example.com/page']

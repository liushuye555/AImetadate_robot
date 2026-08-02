from qq_onebot_whitelist.store import Store


def test_ai_context_batch_roundtrip(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_ai_context_batch(
        scope='group:1',
        start_message_id=1,
        end_message_id=10,
        model='test-model',
        summary='总结',
        raw_json='{}',
    )
    rows = store.recent_ai_context_batches(scope='group:1', limit=5)
    assert len(rows) == 1
    assert rows[0]['scope'] == 'group:1'
    assert rows[0]['model'] == 'test-model'
    assert rows[0]['summary'] == '总结'


def test_link_metadata_cache_table_roundtrip(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.save_link_metadata('https://example.com/page', '标题', '简介')

    row = store.get_link_metadata('https://example.com/page')

    assert row['title'] == '标题'
    assert row['description'] == '简介'
    assert not row['error']

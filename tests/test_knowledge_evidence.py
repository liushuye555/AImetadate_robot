from datetime import datetime

from qq_onebot_whitelist.knowledge_evidence import render_evidence
from qq_onebot_whitelist.knowledge_store import LOCAL_TZ
from qq_onebot_whitelist.store import Store


def _record(store: Store, *, scope: str, user: str, text: str, message_no: int,
            reply_to: int | None = None) -> int:
    message = [{'type': 'text', 'data': {'text': text}}]
    if reply_to is not None:
        message.append({'type': 'reply', 'data': {'id': reply_to}})
    raw = {
        'time': int(datetime(2026, 10, 12, 12, 0, message_no, tzinfo=LOCAL_TZ).timestamp()),
        'message_id': message_no,
        'message': message,
    }
    store.record_message(scope=scope, user_id=user, text=text, raw=raw)
    return store.message_row_id(scope, raw)


def test_renders_tail_quote_escaping_and_anonymous_speakers(tmp_path):
    store = Store(tmp_path / 'bot.db')
    scope = 'group:123'
    ids = []
    for number in range(1, 9):
        text = f'普通来源 {number}'
        if number == 1:
            text = '<script>alert(1)</script> sk-abcdefghijklmnop'
        if number == 8:
            text = '尾部来源 & <末条>'
        ids.append(_record(store, scope=scope, user='same-user' if number != 2 else 'other-user',
                           text=text, message_no=number,
                           reply_to=1 if number == 8 else None))

    html = render_evidence(tmp_path, scope, ids)

    assert '展开其余 2 条来源' in html
    assert '尾部来源 &amp; &lt;末条&gt;' in html
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '[已脱敏密钥]' in html
    assert '引用 #' + str(ids[0]) in html
    assert '普通来源 3' in html
    assert '成员1' in html and '成员2' in html
    assert '2026-10-12T12:00:01+08:00' in html


def test_foreign_scope_and_missing_sources_are_unavailable(tmp_path):
    store = Store(tmp_path / 'bot.db')
    foreign_id = _record(store, scope='group:999', user='foreign', text='别群秘密', message_no=1)
    local_id = _record(store, scope='group:123', user='local', text='本群内容', message_no=2)

    html = render_evidence(tmp_path, 'group:123', [foreign_id, 999_999, local_id])

    assert html.count('原记录不可用') == 2
    assert '别群秘密' not in html
    assert '本群内容' in html

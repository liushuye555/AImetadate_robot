from qq_onebot_whitelist.commands import HELP_TEXT, build_reply
from qq_onebot_whitelist.store import Store


def private_event(text='链接'):
    return {'post_type': 'message', 'message_type': 'private', 'user_id': 200000001, 'message': text, 'raw_message': text}


def test_help_displays_commands_without_slash():
    assert '1. 帮助' in HELP_TEXT
    assert '可省略 /' not in HELP_TEXT


def test_private_link_command_reads_all_scopes(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://civitai.com/models/1', message_text='x')

    reply = build_reply(private_event('链接'), store)

    assert 'https://civitai.com/models/1' in reply


def test_group_link_command_stays_current_scope_only(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_link(scope='group:1', user_id='u', url='https://civitai.com/models/1', message_text='x')
    store.record_link(scope='group:2', user_id='u', url='https://civitai.com/models/2', message_text='x')
    event = {'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'user_id': 200000001, 'message': '链接', 'raw_message': '链接'}

    reply = build_reply(event, store)

    assert 'https://civitai.com/models/1' in reply
    assert 'https://civitai.com/models/2' not in reply


def test_private_image_info_reads_all_scopes(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.record_image(scope='group:1', user_id='u', result={'url': 'u', 'sha256': 's', 'size': 1024, 'format': 'PNG', 'width': 512, 'height': 768, 'has_ai_metadata': True, 'ai_source': 'ComfyUI', 'kept_path': 'x.png', 'retention_reason': 'ai_metadata'}, raw={})

    reply = build_reply(private_event('图片信息'), store)

    assert 'ComfyUI' in reply
    assert '512x768' in reply


def test_favorites_command_explains_explicit_chat_record_save(tmp_path):
    store = Store(tmp_path / 'bot.db')
    store.save_favorite(user_id='200000001', content_hash='legacy', summary='旧版收藏')

    reply = build_reply(private_event('收藏夹'), store)

    assert '/保存图片' in reply
    assert '未分类' in reply
    assert '旧版收藏' not in reply

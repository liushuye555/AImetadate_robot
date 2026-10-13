"""Parameter classification follows image-message relationships, not latest chat."""
import pytest

from qq_onebot_whitelist import collection
from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.prompt_binding import bind_prompt_for_image
from qq_onebot_whitelist.store import Store


SCOPE = 'group:1'


def event(mid, user, text='', *, image=False, reply=None, time=1000):
    segments = []
    if reply is not None:
        segments.append({'type': 'reply', 'data': {'id': str(reply)}})
    if text:
        segments.append({'type': 'text', 'data': {'text': text}})
    if image:
        segments.append({'type': 'image', 'data': {'url': f'http://local/{mid}.png'}})
    return {'post_type': 'message', 'message_type': 'group', 'group_id': 1,
            'message_id': mid, 'user_id': user, 'time': time, 'message': segments}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    while collection.pop_deferred_image() is not None:
        pass
    store = Store(tmp_path / 'bot.db')
    config = AppConfig(data_dir=tmp_path, load_aware_enabled=False)

    def process(url, **kwargs):
        digest = url.rsplit('/', 1)[-1].split('.')[0]
        path = tmp_path / 'images' / 'candidates' / f'{digest}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'image')
        return {'url': url, 'sha256': digest, 'size': 1000000, 'format': 'PNG',
                'width': 1024, 'height': 1536, 'metadata_keys': [],
                'has_ai_metadata': False, 'kept_path': str(path),
                'retention_reason': 'candidate'}

    monkeypatch.setattr(collection, 'process_image_url', process)
    monkeypatch.setattr(collection, 'analyze_image', lambda _: None)
    yield store, config
    while collection.pop_deferred_image() is not None:
        pass


def image_row(store, mid):
    with store._conn() as conn:
        row = conn.execute('SELECT id, retention_reason, bound_prompt, kept_path '
                           'FROM images WHERE sha256=?', (str(mid),)).fetchone()
    return dict(zip(('id', 'reason', 'text', 'path'), row))


def collect(store, config, item, *, drain=True):
    collection.collect_event(store, item, config)
    if drain:
        collection.drain_deferred_images(store, config)


def test_unrelated_parameter_chat_does_not_collect_cover(setup):
    store, config = setup
    collect(store, config, event(86140, 'bob', 'LoRA权重设为0.8，采样28步'))
    collect(store, config, event(86142, 'alice', '歌单封面', image=True, time=1020))
    assert image_row(store, 86142)['reason'] == 'candidate'


def test_delayed_worker_uses_source_anchor_not_latest_prompt(setup):
    store, config = setup
    collect(store, config, event(88826, 'alice', 'AI处理进度', image=True), drain=False)
    collect(store, config, event(88827, 'bob', '1girl, solo, blonde hair', time=1010), drain=False)
    collection.drain_deferred_images(store, config)
    assert image_row(store, 88826)['reason'] == 'candidate'


def test_delayed_worker_restores_original_reply(setup):
    store, config = setup
    collect(store, config, event(95000, 'bob', '1girl, solo, cat ears'))
    collect(store, config, event(95001, 'alice', '收到', time=1005))
    collect(store, config, event(95002, 'alice', image=True, reply=95000, time=1010), drain=False)
    collect(store, config, event(95003, 'bob', '闲聊', time=1015), drain=False)
    collection.drain_deferred_images(store, config)
    assert image_row(store, 95002)['reason'] == 'prompt_bound'
    assert 'cat ears' in image_row(store, 95002)['text']


def test_platform_message_id_takes_precedence_over_local_id():
    records = [{'id': 20, 'message_key': '90000', 'text': '1girl, solo, cat ears'},
               {'id': 21, 'message_key': '20', 'text': '1girl, solo, fox ears'},
               {'id': 22, 'message_key': '90002', 'text': '闲聊'}]
    assert bind_prompt_for_image(records, reply_to='20') == ('prompt', '1girl, solo, fox ears')


def test_parameter_question_after_image_remains_candidate(setup):
    store, config = setup
    collect(store, config, event(100, 'alice', image=True))
    collect(store, config, event(101, 'alice', '这模型用什么sampler跑的', time=1010))
    assert image_row(store, 100)['reason'] == 'candidate'


def test_other_sender_parameter_answer_does_not_bind_latest_image(setup):
    store, config = setup
    collect(store, config, event(110, 'alice', image=True))
    collect(store, config, event(111, 'bob', 'LoRA权重0.8，sampler为Euler', time=1010))
    assert image_row(store, 110)['reason'] == 'candidate'


def test_expired_original_event_window_does_not_use_import_time(setup):
    store, config = setup
    collect(store, config, event(120, 'alice', image=True, time=1000))
    collect(store, config, event(121, 'alice', 'LoRA权重0.8，采样28步', time=1181))
    assert image_row(store, 120)['reason'] == 'candidate'


def test_parameter_reply_promotes_target_not_latest_image(setup):
    store, config = setup
    collect(store, config, event(130, 'alice', image=True))
    collect(store, config, event(131, 'carol', image=True, time=1005))
    collect(store, config, event(132, 'bob', 'LoRA权重0.8，sampler为Euler', reply=130, time=1010))
    assert image_row(store, 130)['reason'] == 'params_discussion'
    assert image_row(store, 131)['reason'] == 'candidate'


def test_same_author_parameter_answer_binds_message_burst(setup):
    store, config = setup
    collect(store, config, event(140, 'alice', image=True))
    collect(store, config, event(141, 'alice', 'LoRA权重0.8，sampler为Euler', time=1010))
    assert image_row(store, 140)['reason'] == 'params_discussion'


def test_later_same_author_image_stops_backward_burst(setup):
    store, config = setup
    collect(store, config, event(150, 'alice', image=True))
    collect(store, config, event(151, 'alice', image=True, time=1005))
    collect(store, config, event(152, 'alice', 'LoRA权重0.8，sampler为Euler', time=1010))
    assert image_row(store, 150)['reason'] == 'candidate'
    assert image_row(store, 151)['reason'] == 'params_discussion'


def test_parameter_context_preserves_question_answer_source_ids(setup):
    store, config = setup
    collect(store, config, event(87009, 'alice', image=True))
    collect(store, config, event(87010, 'bob', 'LoRA节点该怎么设置？', reply=87009, time=1010))
    collect(store, config, event(87011, 'alice', 'LoRA权重设为0.8，采样28步', time=1020))
    row = image_row(store, 87009)
    context = store.image_discussion(row['id'])
    assert row['reason'] == 'params_discussion'
    assert context['status'] == 'selected'
    assert 'LoRA节点该怎么设置' in context['context_text']
    assert 'LoRA权重设为0.8' in context['context_text']
    assert context['evidence_ids'] == [1, 2, 3]


def test_deferred_parameter_answer_attaches_to_original_image(setup):
    store, config = setup
    collect(store, config, event(160, 'alice', image=True), drain=False)
    collect(store, config, event(161, 'alice', 'Krea2 turbo模型使用int8', time=1010), drain=False)
    collect(store, config, event(162, 'bob', '路过闲聊', time=1020), drain=False)
    collection.drain_deferred_images(store, config)
    row = image_row(store, 160)
    assert row['reason'] == 'params_discussion'
    context = store.image_discussion(row['id'])
    assert context['status'] == 'selected'
    assert 'int8' in context['context_text']
    assert '路过闲聊' not in context['context_text']


def test_no_local_id_fallback_for_identity_bearing_record():
    records = [{'id': 20, 'message_key': '90000', 'text': '1girl, solo, cat ears'},
               {'id': 21, 'message_key': '90001', 'text': '闲聊'}]
    assert bind_prompt_for_image(records, reply_to='20') == (None, '')


@pytest.mark.parametrize('cross_context', [False, True])
def test_selected_discussion_refreshes_when_reply_to_question_arrives(setup, cross_context):
    store, config = setup
    collect(store, config, event(170, 'alice', image=True))
    collect(store, config, event(171, 'bob', '这个模型是什么版本？', reply=170, time=1010))
    collect(store, config, event(172, 'alice', 'Krea2 turbo模型使用int8', time=1020))
    row = image_row(store, 170)
    prior = store.image_discussion(row['id'])
    assert prior['status'] == 'selected' and 'int8' in prior['context_text']
    assert 'fp8' not in prior['context_text']
    if cross_context:
        store.update_image_retention(row['id'], kept_path=row['path'], retention_reason='xiaofanqie_obfuscated')
        store.mark_image_context(row['id'], 'params_discussion')
        row = image_row(store, 170)
    collect(store, config, event(173, 'carol', '实测fp8速度更快，显存更低', reply=171, time=1030))
    updated = store.image_discussion(row['id'])
    assert 'int8' in updated['context_text'] and 'fp8' in updated['context_text']
    assert updated['evidence_ids'] == [1, 2, 3, 4]
    assert image_row(store, 170)['reason'] == row['reason']
    assert image_row(store, 170)['path'] == row['path']


def test_manual_rejection_blocks_candidate_auto_promotion(setup):
    store, config = setup
    collect(store, config, event(180, 'alice', image=True))
    row = image_row(store, 180)
    store.set_image_discussion(row['id'], 'rejected', '人工确认不是参数图', manual=True)
    collect(store, config, event(181, 'alice', 'Krea2 turbo模型使用int8', time=1010))
    assert image_row(store, 180)['reason'] == 'candidate'
    assert image_row(store, 180)['path'] == row['path']
    assert store.image_discussion(row['id'])['status'] == 'rejected'


def test_archived_discussion_preserves_manual_rejection(setup):
    store, config = setup
    collect(store, config, event(190, 'alice', image=True))
    collect(store, config, event(191, 'bob', '这个模型是什么版本？', reply=190, time=1010))
    collect(store, config, event(192, 'alice', 'Krea2 turbo模型使用int8', time=1020))
    row = image_row(store, 190)
    store.set_image_discussion(row['id'], 'rejected', '人工确认不应展示', manual=True)
    prior = store.image_discussion(row['id'])
    collect(store, config, event(193, 'carol', '实测fp8速度更快，显存更低', reply=191, time=1030))
    assert store.image_discussion(row['id']) == prior
    assert image_row(store, 190)['reason'] == row['reason']
    assert image_row(store, 190)['path'] == row['path']


@pytest.mark.parametrize('expired', [False, True])
def test_archived_discussion_does_not_refresh_unrelated_or_expired_answer(setup, expired):
    store, config = setup
    collect(store, config, event(200, 'alice', image=True))
    collect(store, config, event(201, 'bob', '这个模型是什么版本？', reply=200, time=1010))
    collect(store, config, event(202, 'alice', 'Krea2 turbo模型使用int8', time=1020))
    row = image_row(store, 200)
    prior = store.image_discussion(row['id'])
    collect(store, config, event(203, 'carol', '实测fp8速度更快，显存更低',
                                reply=201 if expired else None, time=1181 if expired else 1030))
    assert store.image_discussion(row['id']) == prior
    assert image_row(store, 200)['reason'] == row['reason']

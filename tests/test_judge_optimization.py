"""判定逻辑优化（2026-09 历史数据挖掘）的集成测试：

- 好评批量晋升：窗口内所有候选图一起晋升，不再只晋升最后一张；
- 好评落空时给最近的已归档图补 positive_feedback 上下文（交叉显示到 02）；
- 图后补发的提示词/参数讨论反向绑定到仍在候选状态的图；
- 机器人账号的好评/绑定消息被忽略。
"""

import asyncio
from pathlib import Path

from qq_onebot_whitelist.config import AppConfig
from qq_onebot_whitelist.onebot import handle_event
from qq_onebot_whitelist.policy import BotConfig
from qq_onebot_whitelist.store import Store


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)


def make_config(tmp_path: Path, **kwargs) -> AppConfig:
    return AppConfig(data_dir=tmp_path, bot=BotConfig(), candidate_ttl_hours=24,
                     load_aware_enabled=False, **kwargs)


def record_candidate(store: Store, tmp_path: Path, sha: str, user_id: str = '1001') -> Path:
    path = tmp_path / 'images' / 'candidates' / 'aa' / f'{sha}.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'image-bytes')
    store.record_image(
        scope='group:1',
        user_id=user_id,
        result={
            'url': f'u-{sha}', 'sha256': sha, 'size': 1000000, 'format': 'PNG', 'width': 1024, 'height': 1536,
            'metadata_keys': [], 'has_ai_metadata': False, 'ai_source': None, 'text_excerpt': '',
            'kept_path': str(path), 'retention_reason': 'candidate',
        },
        raw={},
    )
    return path


def text_event(user_id: int, text: str) -> dict:
    return {
        'post_type': 'message', 'message_type': 'group', 'group_id': 1, 'user_id': user_id,
        'message': [{'type': 'text', 'data': {'text': text}}],
    }


def test_praise_promotes_all_recent_candidates(tmp_path):
    """一条好评覆盖窗口内多张候选图（批量发图场景），不再只晋升最后一张。"""

    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = make_config(tmp_path)
        path_a = record_candidate(store, tmp_path, 'aaa')
        path_b = record_candidate(store, tmp_path, 'bbb')

        await handle_event(FakeWS(), text_event(1002, '这张太神了，求提示词'), cfg, store)

        images = store.recent_images('group:1', limit=5)
        promoted = [img for img in images if img['retention_reason'] == 'positive_feedback']
        assert len(promoted) == 2, f'应晋升 2 张，实际 {len(promoted)}'
        assert not path_a.exists() and not path_b.exists()

    asyncio.run(scenario())


def test_praise_marks_context_on_archived_image(tmp_path):
    """好评落空（图已按元数据归档，从未进候选）→ 给最近归档图补好评上下文。"""

    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = make_config(tmp_path)
        archived = tmp_path / 'images' / 'ai' / '01' / 'meta.png'
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_bytes(b'ai-image')
        store.record_image(
            scope='group:1',
            user_id='1001',
            result={
                'url': 'u', 'sha256': 'meta', 'size': 1000000, 'format': 'PNG', 'width': 1024, 'height': 1536,
                'metadata_keys': ['parameters'], 'has_ai_metadata': True, 'ai_source': 'A1111',
                'text_excerpt': '1girl', 'kept_path': str(archived), 'retention_reason': 'ai_metadata',
            },
            raw={},
        )

        await handle_event(FakeWS(), text_event(1002, '这么好看！'), cfg, store)

        images = store.recent_images('group:1', limit=5)
        row = [img for img in images if img['retention_reason'] == 'ai_metadata']
        assert len(row) == 1
        import sqlite3
        with sqlite3.connect(tmp_path / 'bot.db') as conn:
            ctx = conn.execute(
                "SELECT retention_reason, context_reason FROM images WHERE sha256='meta'"
            ).fetchone()
        assert ctx[0] == 'ai_metadata'  # 保留原分类
        assert ctx[1] == 'positive_feedback'  # 交叉显示到 02_群友好评

    asyncio.run(scenario())


def test_prompt_after_image_binds_backward(tmp_path):
    """图先发、提示词后补：反向绑定把仍在候选状态的图晋升为提示词绑定。"""

    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = make_config(tmp_path)
        path = record_candidate(store, tmp_path, 'ccc')

        await handle_event(FakeWS(), text_event(1001, '1girl, solo, cat girl, blonde hair'), cfg, store)

        import sqlite3
        with sqlite3.connect(tmp_path / 'bot.db') as conn:
            row = conn.execute(
                "SELECT retention_reason, bound_prompt FROM images WHERE sha256='ccc'"
            ).fetchone()
        assert row[0] == 'prompt_bound'
        assert '1girl' in (row[1] or '')
        assert not path.exists()  # 已晋升出候选目录

    asyncio.run(scenario())


def test_params_after_image_binds_backward(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = make_config(tmp_path)
        record_candidate(store, tmp_path, 'ddd')

        await handle_event(FakeWS(), text_event(1001, '这模型用什么sampler跑的'), cfg, store)

        import sqlite3
        with sqlite3.connect(tmp_path / 'bot.db') as conn:
            row = conn.execute(
                "SELECT retention_reason, bound_prompt FROM images WHERE sha256='ddd'"
            ).fetchone()
        assert row[0] == 'params_discussion'
        assert 'sampler' in (row[1] or '')

    asyncio.run(scenario())


def test_bot_user_praise_ignored(tmp_path):
    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = make_config(tmp_path, images_ignore_bot_user_ids={'999'})
        record_candidate(store, tmp_path, 'eee')

        await handle_event(FakeWS(), text_event(999, '生成完成，效果太神了'), cfg, store)

        import sqlite3
        with sqlite3.connect(tmp_path / 'bot.db') as conn:
            row = conn.execute(
                "SELECT retention_reason FROM images WHERE sha256='eee'"
            ).fetchone()
        assert row[0] == 'candidate'  # 机器人的"好评"不晋升

    asyncio.run(scenario())


def test_generic_chat_no_binding(tmp_path):
    """单个泛化参数词的闲聊不绑定，图保持候选。"""
    async def scenario():
        store = Store(tmp_path / 'bot.db')
        cfg = make_config(tmp_path)
        record_candidate(store, tmp_path, 'fff')

        await handle_event(FakeWS(), text_event(1002, '我搜不到这个模型'), cfg, store)

        import sqlite3
        with sqlite3.connect(tmp_path / 'bot.db') as conn:
            row = conn.execute(
                "SELECT retention_reason FROM images WHERE sha256='fff'"
            ).fetchone()
        assert row[0] == 'candidate'

    asyncio.run(scenario())

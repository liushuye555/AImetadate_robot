import json
import subprocess
import sys

from qq_onebot_whitelist.config_bridge import config_schema


def test_schema_exposes_bilingual_typed_fields():
    fields = config_schema({'daily_report': {'hour': 7}})
    hour = next(item for item in fields if item['key'] == 'daily_report.hour')
    assert hour['kind'] == 'number'
    assert hour['default'] == 7
    assert hour['label']['en-US']
    assert hour['label']['zh-CN']


def test_schema_cli_returns_json(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('summary:\n  default_limit: 42\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'qq_onebot_whitelist.config_bridge', 'schema', '--config', str(config)], capture_output=True, text=True, check=True)
    fields = json.loads(result.stdout)
    assert next(item for item in fields if item['key'] == 'summary.default_limit')['default'] == 42


def test_schema_exposes_ai_tuning_and_group_access_controls():
    fields = {item['key']: item for item in config_schema({})}
    for key in ('ai_context.scopes', 'ai_context.chunk_size', 'ai_context.auto_interval_minutes', 'ai_context.min_new_messages', 'reply.whitelist_groups', 'listen.blocked_groups'):
        assert key in fields
    assert fields['reply.whitelist_groups']['kind'] == 'list'
    assert fields['ai_context.chunk_size']['kind'] == 'number'


def test_env_patch_preserves_existing_values_and_updates_one_key(tmp_path):
    from qq_onebot_whitelist.config_bridge import patch_env

    env = tmp_path / '.env'
    env.write_text('KEEP=value\nAPI_KEY=old\n', encoding='utf-8')
    patch_env(env, {'API_KEY': 'new', 'MODEL': 'demo'})
    assert env.read_text(encoding='utf-8') == 'KEEP=value\nAPI_KEY=new\nMODEL=demo\n'


def test_schema_covers_remaining_runtime_configuration():
    fields = {item['key'] for item in config_schema({})}
    expected = {
        'reply.require_at_in_group', 'reply.allow_group_admins',
        'ai_context.max_chunks', 'ai_context.allowed_windows',
        'daily_report.max_enriched_links',
        'images.max_archive_mb', 'images.candidate_ttl_hours',
        'storage.data_dir', 'startup_history.enabled', 'startup_history.mode',
        'startup_history.groups', 'startup_history.pages', 'startup_history.count',
        'startup_history.all', 'startup_history.max_pages',
        'features.link_analysis', 'features.link_metadata',
        'features.image_processing', 'features.ai_context',
        'features.daily_report', 'features.startup_history',
        'features.auto_restart',
        'keepalive.enabled', 'keepalive.interval_minutes', 'keepalive.groups', 'keepalive.message',
    }
    assert expected <= fields

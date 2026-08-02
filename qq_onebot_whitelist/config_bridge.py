"""Small JSON bridge used by the native manager; it keeps YAML semantics in Python."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def config_schema(data: dict[str, Any]) -> list[dict[str, Any]]:
    ai = data.get('ai_context') or {}
    reply = data.get('reply') or {}
    listen = data.get('listen') or {}
    daily = data.get('daily_report') or {}
    images = data.get('images') or {}
    storage = data.get('storage') or {}
    startup = data.get('startup_history') or {}
    features = data.get('features') or {}
    keepalive = data.get('keepalive') or {}
    echo = data.get('echo') or {}
    collection = data.get('collection') or {}
    load_aware = data.get('load_aware') or {}

    def field(key: str, kind: str, default: Any, en: str, zh: str, **extra: Any) -> dict[str, Any]:
        item = {'key': key, 'kind': kind, 'default': default, 'label': {'en-US': en, 'zh-CN': zh}}
        item.update(extra)
        return item

    configured_providers = {
        str(key): {str(k): str(v) for k, v in (value or {}).items()}
        for key, value in (ai.get('providers') or {}).items()
        if isinstance(value, dict)
    }
    merged_providers = {**_env_providers(), **configured_providers}

    return [
        field('onebot.ws_url', 'text', data.get('onebot', {}).get('ws_url', 'ws://127.0.0.1:3001'), 'OneBot WebSocket', 'OneBot WebSocket', section='runtime'),
        field('summary.default_limit', 'number', data.get('summary', {}).get('default_limit', 100), 'Default summary limit', '默认总结条数', section='bot'),
        field('summary.max_limit', 'number', data.get('summary', {}).get('max_limit', 500), 'Maximum summary limit', '最大总结条数', section='bot'),
        field('ai_context.enabled', 'bool', data.get('ai_context', {}).get('enabled', True), 'AI context enabled', '启用 AI 上下文', section='ai'),
        field('ai_context.provider', 'select', data.get('ai_context', {}).get('provider', 'ds_v4_flash'), 'AI provider', 'AI 提供商', section='ai', options=sorted(set(['ds_v4_flash', 'openai_compatible', *((data.get('ai_context', {}).get('providers') or {}).keys())]))),
        field('ai_context.providers', 'provider-list', merged_providers, 'AI providers', 'AI 供应商', section='ai'),
        field('ai_context.scopes', 'select', ai.get('scopes', 'all_groups'), 'AI analysis scope', 'AI 分析范围', section='ai', options=['all_groups', 'whitelist_groups']),
        field('ai_context.chunk_size', 'number', ai.get('chunk_size', 200), 'Messages per AI batch', '每批 AI 消息数', section='ai', min=20, max=2000),
        field('ai_context.auto_interval_minutes', 'number', ai.get('auto_interval_minutes', 15), 'Auto analysis interval (minutes)', '自动分析间隔（分钟）', section='ai', min=1, max=1440),
        field('ai_context.min_new_messages', 'number', ai.get('min_new_messages', 300), 'Minimum new messages', '触发分析的最少新消息数', section='ai', min=1, max=100000),
        field('ai_context.max_chunks', 'number', ai.get('max_chunks'), 'Maximum batches per run', '每次最大批次数', section='ai', nullable=True, min=1, max=10000),
        field('ai_context.allowed_windows', 'list', ai.get('allowed_windows', []), 'Allowed analysis windows', '允许分析时段', section='ai'),
        field('daily_report.enabled', 'bool', data.get('daily_report', {}).get('enabled', True), 'Daily report enabled', '启用日报', section='daily'),
        field('daily_report.hour', 'number', data.get('daily_report', {}).get('hour', 20), 'Daily report hour', '日报发送时间', section='daily', min=0, max=23),
        field('daily_report.max_links', 'number', data.get('daily_report', {}).get('max_links', 20), 'Max daily links', '日报最大链接数', section='daily', min=0, max=100),
        field('daily_report.enrich_links', 'bool', data.get('daily_report', {}).get('enrich_links', True), 'Enrich link titles', '补充链接标题', section='daily'),
        field('daily_report.max_enriched_links', 'number', daily.get('max_enriched_links', 8), 'Maximum enriched links', '最多补全链接数', section='daily', min=0, max=100),
        field('daily_report.include_links', 'bool', daily.get('include_links', True), 'Include links in daily report', '日报包含链接', section='daily'),
        field('daily_report.include_files', 'bool', daily.get('include_files', True), 'Include files in daily report', '日报包含文件', section='daily'),
        field('echo.enabled', 'bool', echo.get('enabled', True), 'Echo/repeat enabled', '复读机开关', section='keepalive'),
        field('echo.min_repeat', 'number', echo.get('min_repeat', 3), 'Repeat threshold', '复读触发人数', section='keepalive', min=2, max=50),
        field('echo.window_seconds', 'number', echo.get('window_seconds', 60), 'Repeat window (s)', '复读时间窗（秒）', section='keepalive', min=10, max=3600),
        field('echo.groups', 'list', echo.get('groups', []), 'Echo groups (blank = all)', '复读群列表（留空=全部群）', section='keepalive'),
        field('collection.groups', 'collection-list', collection.get('groups', {}), 'Per-group collection', '群级采集配置', section='collection'),
        field('collection.rules', 'custom-rules', collection.get('rules', []), 'Custom collection rules', '自定义采集规则', section='collection'),
        field('collection.expand_forwards', 'bool', collection.get('expand_forwards', False), 'Expand forwarded messages', '展开转发的合并消息', section='collection'),
        field('load_aware.enabled', 'bool', load_aware.get('enabled', True), 'Load-aware scheduling', '负载感知调度', section='load'),
        field('load_aware.cpu_threshold', 'number', load_aware.get('cpu_threshold', 80), 'CPU threshold (%)', 'CPU 阈值（%）', section='load', min=10, max=100),
        field('load_aware.check_seconds', 'number', load_aware.get('check_seconds', 60), 'Recheck interval (s)', '重试间隔（秒）', section='load', min=10, max=3600),
        field('reply.whitelist_groups', 'list', reply.get('whitelist_groups', []), 'Whitelisted groups', '群白名单', section='access'),
        field('reply.whitelist_users', 'list', reply.get('whitelist_users', []), 'Whitelisted users', '用户白名单', section='access'),
        field('reply.require_at_in_group', 'bool', reply.get('require_at_in_group', True), 'Require @ in groups', '群聊必须 @ 机器人', section='access'),
        field('reply.allow_group_admins', 'bool', reply.get('allow_group_admins', True), 'Allow group administrators', '允许群主和管理员', section='access'),
        field('listen.blocked_groups', 'list', listen.get('blocked_groups', []), 'Blocked groups', '群黑名单', section='access'),
        field('images.max_archive_mb', 'number', images.get('max_archive_mb', 500), 'Image archive limit (MB)', '图片归档上限（MB）', section='advanced', min=1),
        field('images.candidate_ttl_hours', 'number', images.get('candidate_ttl_hours', 24), 'Candidate image lifetime (hours)', '候选图片保留时间（小时）', section='advanced', min=1),
        field('images.sticker_repeat_threshold', 'number', images.get('sticker_repeat_threshold', 3), 'Sticker repeat threshold', '表情包重复阈值（次）', section='advanced', min=1, max=20),
        field('storage.data_dir', 'text', storage.get('data_dir', 'data'), 'Data directory', '数据目录', section='advanced'),
        field('startup_history.enabled', 'bool', startup.get('enabled', True), 'Load startup history', '启动时读取历史消息', section='advanced'),
        field('startup_history.mode', 'select', startup.get('mode', 'blacklist'), 'Startup history mode', '启动历史模式', section='advanced', options=['blacklist', 'whitelist']),
        field('startup_history.groups', 'list', startup.get('groups', []), 'Startup history groups', '启动历史群列表', section='advanced'),
        field('startup_history.pages', 'number', startup.get('pages', 3), 'Initial history pages', '初始历史页数', section='advanced', min=1),
        field('startup_history.count', 'number', startup.get('count', 50), 'Messages per page', '每页消息数', section='advanced', min=1),
        field('startup_history.all', 'bool', startup.get('all', False), 'Load all history', '读取全部历史', section='advanced'),
        field('startup_history.max_pages', 'number', startup.get('max_pages', 200), 'Maximum history pages', '最大历史页数', section='advanced', min=1),
        field('features.link_analysis', 'bool', features.get('link_analysis', True), 'Analyze and classify links', '分析和分类链接', section='features'),
        field('features.link_metadata', 'bool', features.get('link_metadata', daily.get('enrich_links', True)), 'Fetch link titles and metadata', '抓取链接标题和元数据', section='features'),
        field('features.image_processing', 'bool', features.get('image_processing', True), 'Process incoming images', '处理收到的图片', section='features'),
        field('features.ai_context', 'bool', features.get('ai_context', ai.get('enabled', True)), 'Run AI context analysis', '运行 AI 上下文分析', section='features'),
        field('features.daily_report', 'bool', features.get('daily_report', daily.get('enabled', True)), 'Send daily reports', '发送日报', section='features'),
        field('features.startup_history', 'bool', features.get('startup_history', startup.get('enabled', True)), 'Load startup history', '启动时读取历史消息', section='features'),
        field('features.auto_restart', 'bool', features.get('auto_restart', True), 'Auto-restart failed services', '自动重启异常服务', section='features'),
        field('keepalive.enabled', 'bool', keepalive.get('enabled', False), 'Enable scheduled group keepalive', '启用定时群保活', section='keepalive'),
        field('keepalive.interval_minutes', 'number', keepalive.get('interval_minutes', 0), 'Keepalive interval (minutes)', '群保活间隔（分钟）', section='keepalive', min=0, max=10080),
        field('keepalive.groups', 'list', keepalive.get('groups', []), 'Keepalive groups', '保活群列表', section='keepalive'),
        field('keepalive.message', 'text', keepalive.get('message', ''), 'Keepalive message', '保活消息', section='keepalive'),
        field('keepalive.mode', 'select', keepalive.get('mode', 'all'), 'Keepalive group scope', '保活群范围', section='keepalive', options=['all', 'whitelist', 'blacklist', 'custom']),
        field('keepalive.trigger_enabled', 'bool', keepalive.get('trigger_enabled', False), 'Trigger keepalive when group is idle', '触发保活（群空闲时）', section='keepalive'),
        field('keepalive.idle_minutes', 'number', keepalive.get('idle_minutes', 60), 'Idle threshold (minutes)', '空闲阈值（分钟）', section='keepalive', min=1, max=1440),
    ]


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return value if isinstance(value, dict) else {}


def _merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def patch_env(path: Path, values: dict[str, str]) -> None:
    existing = _load_env(path)
    existing.update({str(key): str(value) for key, value in values.items() if value is not None})
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{key}={value}' for key, value in existing.items()]
    path.write_text(('\n'.join(lines) + '\n') if lines else '', encoding='utf-8')


def _load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('set '):
            line = line[4:].strip().strip('"')
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"')
    return values


_ENV_PROVIDER_PREFIXES = ('DS_V4_FLASH', 'HUANYAN', 'OPENROUTER', 'SUMMARY_LLM', 'OPENAI')


def _env_providers() -> dict[str, dict[str, str]]:
    """从 .env 发现已配置的 AI 供应商（密钥留在 .env，面板只读元信息）。"""
    values = _load_env(Path('.env'))
    providers: dict[str, dict[str, str]] = {}
    for prefix in _ENV_PROVIDER_PREFIXES:
        base_url = values.get(f'{prefix}_BASE_URL') or ''
        model = values.get(f'{prefix}_MODEL') or ''
        api_key = values.get(f'{prefix}_API_KEY') or ''
        if base_url or model or api_key:
            providers[prefix.lower()] = {
                'base_url': base_url,
                'model': model,
                'api_key_env': f'{prefix}_API_KEY',
                'timeout_seconds': 60,
            }
    return providers


def patch_config(path: Path, patch: dict[str, Any]) -> dict[str, Any]:
    data = _load(path)
    _merge(data, patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('get', 'patch', 'schema', 'env-get', 'env-patch'))
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--json', default='{}')
    args = parser.parse_args()
    path = Path(args.config)
    if args.action == 'env-get':
        print(json.dumps(_load_env(Path('.env')), ensure_ascii=False))
        return 0
    if args.action == 'env-patch':
        values = json.loads(args.json)
        if not isinstance(values, dict):
            raise SystemExit('env patch must be a JSON object')
        patch_env(Path('.env'), {str(key): str(value) for key, value in values.items()})
        print(json.dumps(_load_env(Path('.env')), ensure_ascii=False))
        return 0
    if args.action == 'schema':
        print(json.dumps(config_schema(_load(path)), ensure_ascii=False))
        return 0
    if args.action == 'get':
        print(json.dumps(_load(path), ensure_ascii=False))
        return 0
    patch = json.loads(args.json)
    if not isinstance(patch, dict):
        raise SystemExit('patch must be a JSON object')
    print(json.dumps(patch_config(path, patch), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

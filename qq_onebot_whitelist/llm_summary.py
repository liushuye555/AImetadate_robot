from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .content_utils import redact_secrets

def normalize_base_url(base_url: str) -> str:
    base_url = (base_url or '').rstrip('/')
    if base_url == 'https://api.deepseek.com':
        return base_url + '/v1'
    return base_url


def read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode('utf-8', 'ignore')[:2000]
    except Exception:
        return ''


def _read_env_values(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.lower().startswith('set '):
            line = line[4:].strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"')
    return values


@dataclass(slots=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str = 'deepseek-v4-flash'
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls) -> 'LLMConfig | None':
        file_cfg = cls.from_env_file(Path.cwd() / '.env')
        base_url = os.environ.get('OPENROUTER_BASE_URL') or os.environ.get('SUMMARY_LLM_BASE_URL') or os.environ.get('DS_V4_FLASH_BASE_URL') or os.environ.get('HUANYAN_BASE_URL') or os.environ.get('OPENAI_BASE_URL') or (file_cfg.base_url if file_cfg else None)
        api_key = os.environ.get('OPENROUTER_API_KEY') or os.environ.get('SUMMARY_LLM_API_KEY') or os.environ.get('DS_V4_FLASH_API_KEY') or os.environ.get('HUANYAN_API_KEY') or os.environ.get('OPENAI_API_KEY') or (file_cfg.api_key if file_cfg else None)
        model = os.environ.get('OPENROUTER_MODEL') or os.environ.get('SUMMARY_LLM_MODEL') or os.environ.get('DS_V4_FLASH_MODEL') or os.environ.get('HUANYAN_MODEL') or os.environ.get('OPENAI_MODEL') or (file_cfg.model if file_cfg else None) or 'deepseek-v4-flash'
        if not base_url or not api_key:
            return None
        return cls(base_url=normalize_base_url(base_url), api_key=api_key, model=model)

    @classmethod
    def from_env_file(cls, path: str | Path) -> 'LLMConfig | None':
        path = Path(path)
        if not path.exists():
            return None
        values = _read_env_values(path)
        base_url = os.environ.get('OPENROUTER_BASE_URL') or os.environ.get('SUMMARY_LLM_BASE_URL') or os.environ.get('DS_V4_FLASH_BASE_URL') or os.environ.get('HUANYAN_BASE_URL') or os.environ.get('OPENAI_BASE_URL') or values.get('OPENROUTER_BASE_URL') or values.get('SUMMARY_LLM_BASE_URL') or values.get('DS_V4_FLASH_BASE_URL') or values.get('HUANYAN_BASE_URL') or values.get('OPENAI_BASE_URL')
        api_key = os.environ.get('OPENROUTER_API_KEY') or os.environ.get('SUMMARY_LLM_API_KEY') or os.environ.get('DS_V4_FLASH_API_KEY') or os.environ.get('HUANYAN_API_KEY') or os.environ.get('OPENAI_API_KEY') or values.get('OPENROUTER_API_KEY') or values.get('SUMMARY_LLM_API_KEY') or values.get('DS_V4_FLASH_API_KEY') or values.get('HUANYAN_API_KEY') or values.get('OPENAI_API_KEY')
        model = os.environ.get('OPENROUTER_MODEL') or os.environ.get('SUMMARY_LLM_MODEL') or os.environ.get('DS_V4_FLASH_MODEL') or os.environ.get('HUANYAN_MODEL') or os.environ.get('OPENAI_MODEL') or values.get('OPENROUTER_MODEL') or values.get('SUMMARY_LLM_MODEL') or values.get('DS_V4_FLASH_MODEL') or values.get('HUANYAN_MODEL') or values.get('OPENAI_MODEL') or 'deepseek-v4-flash'
        if not base_url or not api_key:
            return None
        return cls(base_url=normalize_base_url(base_url), api_key=api_key, model=model)

    @classmethod
    def ds_fallback_from_env_file(cls, path: str | Path | None = None) -> 'LLMConfig | None':
        path = Path(path) if path is not None else Path.cwd() / '.env'
        values = _read_env_values(path)
        base_url = os.environ.get('DS_V4_FLASH_BASE_URL') or values.get('DS_V4_FLASH_BASE_URL')
        api_key = os.environ.get('DS_V4_FLASH_API_KEY') or values.get('DS_V4_FLASH_API_KEY')
        model = os.environ.get('DS_V4_FLASH_MODEL') or values.get('DS_V4_FLASH_MODEL') or 'deepseek-v4-flash'
        if not base_url or not api_key:
            return None
        return cls(base_url=normalize_base_url(base_url), api_key=api_key, model=model)


def summarize_records_with_fallback(
    records: list[dict[str, Any]],
    primary: LLMConfig | None,
    fallback: LLMConfig | None = None,
    *,
    usage: dict[str, int] | None = None,
) -> str:
    errors: list[str] = []
    for cfg in [primary, fallback]:
        if not cfg:
            continue
        try:
            return summarize_records_with_llm(records, cfg, usage=usage)
        except Exception as exc:
            errors.append(f'{cfg.model}: {type(exc).__name__}')
    if errors:
        raise RuntimeError('; '.join(errors))
    raise RuntimeError('no LLM config available')


NOISE_PATTERNS = [
    r'^\s*$',
    r'^\[?(图片|表情|动画表情|语音|视频)\]?$',
    r'^@全体成员\s*$',
    r'^(收到|好的|ok|OK|嗯|啊|？|\?|哈哈哈?|hhh)$',
]


def filter_relevant_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for record in records:
        text = str(record.get('text') or '').strip()
        links = record.get('links') or []
        if record.get('target_image'):
            filtered.append(record)
            continue
        if links:
            filtered.append(record)
            continue
        if any(re.search(pattern, text, re.I) for pattern in NOISE_PATTERNS):
            continue
        # @全体成员 with no concrete content is noise; with enough content it can be useful.
        if '@全体成员' in text and len(re.sub(r'@全体成员', '', text).strip()) < 12:
            continue
        filtered.append(record)
    return filtered


def normalize_summary_output(text: str) -> str:
    value = redact_secrets(text).strip()
    heading = re.search(r'(?m)^#{1,6}\s+\S', value)
    if heading:
        return value[heading.start():].strip()
    lines = value.splitlines()
    while lines and re.match(r'^(好的|已接收|已对|以下是基于|根据要求)', lines[0].strip()):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return '\n'.join(lines).strip()


def summarize_records_with_llm(
    records: list[dict[str, Any]],
    config: LLMConfig,
    *,
    usage: dict[str, int] | None = None,
) -> str:
    relevant = filter_relevant_records(records)
    if not relevant:
        return 'NO_REUSABLE_IMAGE_CONTEXT'
    content = _format_records(relevant)
    if len(content) > 30000:
        content = content[-30000:]
    payload = {
        'model': config.model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    '你只提取可用于复现图片的群聊证据，不要总结聊天主题、群友行为或普通讨论。'
                    '只保留提示词、负面提示词、模型、LoRA、checkpoint、工作流、节点、采样器、步数、CFG、种子、放大和重绘参数。'
                    '利用消息编号和引用关系判断参数指向哪张图片；无法可靠关联时不要编造。'
                    '有证据时使用简短 Markdown，按实际内容列出“提示词”“模型与 LoRA”“工作流与参数”，没有的栏目省略，并保留关键消息编号。'
                    '没有任何可照抄且可关联图片的信息时，只输出 NO_REUSABLE_IMAGE_CONTEXT。'
                    '不要输出处理过程、消息数量、过滤说明、客套话、免责声明或内容判定。'
                    '不要编造聊天记录中不存在的信息，不要输出聊天中出现的 API Key、Token、密码等秘密；遇到秘密写成“[已脱敏]”。'
                ),
            },
            {
                'role': 'user',
                'content': f'从以下 {len(relevant)} 条消息中提取可复现图片的参数证据：\n\n{content}',
            },
        ],
        'temperature': 0.2,
    }
    req = urllib.request.Request(
        config.base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_seconds) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = read_http_error_body(exc)
        raise RuntimeError(f'LLM HTTP {exc.code}: {body}') from exc
    if usage is not None:
        response_usage = data.get('usage') or {}
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            value = response_usage.get(key)
            if value is not None:
                usage[key] = int(value)
    return normalize_summary_output(data['choices'][0]['message']['content'])


def _time_hhmm(value: Any) -> str:
    text = str(value or '')
    match = re.search(r'(\d{2}:\d{2})', text)
    return match.group(1) if match else '--:--'


def _display_name(record: dict[str, Any]) -> str:
    card = str(record.get('card') or '').strip()
    nickname = str(record.get('nickname') or '').strip()
    if card and nickname and card != nickname:
        return f'{card}/{nickname}'[:80]
    return (card or nickname or str(record.get('user_id') or 'unknown'))[:80]


def _format_records(records: list[dict[str, Any]]) -> str:
    lines = []
    aliases: dict[str, str] = {}
    names: dict[str, str] = {}
    for record in records:
        user_id = str(record.get('user_id') or 'unknown')
        if user_id not in aliases:
            alias = f'U{len(aliases) + 1}'
            aliases[user_id] = alias
            names[alias] = _display_name(record)
    if names:
        user_table = '用户表：' + '；'.join(f'{alias}={name}' for alias, name in names.items())
        lines.append(user_table[:1200])
    for idx, record in enumerate(records, 1):
        user_id = str(record.get('user_id') or 'unknown')
        alias = aliases[user_id]
        msg_id = str(record.get('id') or idx)
        time = _time_hhmm(record.get('seen_at'))
        text = redact_secrets(str(record.get('text') or '').strip())
        links = record.get('links') or []
        marker = ' [目标图片]' if record.get('target_image') else ''
        line = f'#{msg_id} {alias} {time}{marker} {text}'
        quoted = str(record.get('quoted_text') or '').strip()
        if quoted:
            line += f'\n  ↳ 引用：{redact_secrets(quoted[:300])}'
        if links:
            line += '\n  ↳ 链接：' + '，'.join(redact_secrets(str(x)) for x in links[:6])
        lines.append(line[:1500])
    return '\n'.join(lines)

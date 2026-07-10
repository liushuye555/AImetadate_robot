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


def summarize_records_with_fallback(records: list[dict[str, Any]], primary: LLMConfig | None, fallback: LLMConfig | None = None) -> str:
    errors: list[str] = []
    for cfg in [primary, fallback]:
        if not cfg:
            continue
        try:
            return summarize_records_with_llm(records, cfg)
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
    lines = value.splitlines()
    while lines and re.match(r'^(好的|已接收|已对|以下是基于|根据要求)', lines[0].strip()):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return '\n'.join(lines).strip()


def summarize_records_with_llm(records: list[dict[str, Any]], config: LLMConfig) -> str:
    relevant = filter_relevant_records(records)
    if not relevant:
        return '最近没有足够相关的聊天记录可总结。'
    content = _format_records(relevant)
    if len(content) > 30000:
        content = content[-30000:]
    payload = {
        'model': config.model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    '你是群聊上下文整理助手，目标是让读者快速理解这一批聊天发生了什么，而不是只筛选 AI 绘图内容。'
                    '剔除纯表情、重复引用、机械应答等噪声，但保留有信息量的生活话题、创作讨论、群务、技术问题和共同结论。'
                    '如果有 AI 绘图内容，重点整理提示词、模型/LoRA/checkpoint、ComfyUI 工作流/节点、参数、生成经验和图片评价；如果没有，也必须概括主要聊天话题，不能只输出“无有效讨论”。'
                    '如果出现提示词，请用中文描述它大概率会生成什么画面；如果有链接、文件或图片记录，请提取用途和上下文。'
                    '使用 Markdown，按实际内容输出：## 本批概览；## 主要话题；## AI/创作知识（没有则省略）；## 链接与文件（没有则省略）；## 结论与待办（没有则省略）。'
                    '概览必须用2到4句话说明本批最重要的信息。不要输出处理过程、消息数量、过滤说明、客套话、免责声明或“好的，已接收并分析”。'
                    '消息前缀形如“#123 U1 03:21”，#是数据库消息ID，U是用户短别名，请在关键结论里保留这些可追溯标记。'
                    '如果消息带“引用：”，请把引用内容作为该消息的上下文来理解，尤其用于判断“这个/那张/怎么出/求提示词”指向哪张图或哪段提示词。'
                    '不要编造聊天记录中不存在的信息，不要输出聊天中出现的 API Key、Token、密码等秘密；遇到秘密写成“[已脱敏]”。'
                ),
            },
            {
                'role': 'user',
                'content': f'以下是已初步过滤后的最近 {len(relevant)} 条消息，请继续剔除无关消息并自动总结：\n\n{content}',
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
        line = f'#{msg_id} {alias} {time} {text}'
        quoted = str(record.get('quoted_text') or '').strip()
        if quoted:
            line += f'\n  ↳ 引用：{redact_secrets(quoted[:300])}'
        if links:
            line += '\n  ↳ 链接：' + '，'.join(str(x) for x in links[:6])
        lines.append(line[:1500])
    return '\n'.join(lines)

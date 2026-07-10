from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .content_utils import redact_secrets


AI_EVIDENCE_WORDS = (
    'prompt', 'negative', 'tag', 'lora', 'checkpoint', 'workflow', 'comfyui', 'sampler',
    'steps', 'cfg', 'seed', 'controlnet',
)
AI_EVIDENCE_TEXT = ('提示词', '模型', '工作流', '采样', '节点', '训练', '放大', '重绘')


@dataclass(slots=True)
class ContextQuality:
    ai_relevant: bool | None
    value_level: str
    reason: str
    display_summary: str


def has_substantive_ai_evidence(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in AI_EVIDENCE_TEXT) or any(
        re.search(rf'(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])', lowered)
        for token in AI_EVIDENCE_WORDS
    )


def _json_fields(text: str) -> dict:
    match = re.search(r'\{[^{}]+\}', text, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def parse_context_quality(summary: str) -> ContextQuality:
    clean = redact_secrets(summary).strip()
    json_fields = _json_fields(clean)
    relevant_match = re.search(r'(?i)(?:AI相关|ai_relevant)\s*[：:=]\s*(是|否|true|false)', clean)
    level_match = re.search(r'(?i)(?:价值等级|value_level|value)\s*[：:=]\s*(高|中|低|high|medium|low)', clean)
    reason_match = re.search(r'(?im)(?:判断理由|reason)\s*[：:=]\s*([^\n]+)', clean)

    relevant_raw = relevant_match.group(1) if relevant_match else json_fields.get('ai_relevant')
    if isinstance(relevant_raw, bool):
        relevant = relevant_raw
    elif relevant_raw is None:
        relevant = None
    else:
        relevant = str(relevant_raw).lower() in {'是', 'true'}

    level_raw = level_match.group(1) if level_match else json_fields.get('value_level', json_fields.get('value'))
    level_map = {'高': 'high', 'high': 'high', '中': 'review', 'medium': 'review', '低': 'low', 'low': 'low'}
    parsed_level = level_map.get(str(level_raw).lower()) if level_raw is not None else 'review'
    if parsed_level is None:
        parsed_level = 'review'

    display = re.split(r'(?im)^#{1,6}\s*内容判定\s*$', clean, maxsplit=1)[0].rstrip()
    evidence = has_substantive_ai_evidence(display)
    empty_claim = bool(re.search(r'无有效.*(?:讨论|内容)|无需输出总结|已过滤', display))
    if parsed_level == 'high' and (not evidence or empty_claim or relevant is False):
        parsed_level = 'review'
    if parsed_level == 'low' and evidence:
        parsed_level = 'review'
    if relevant is None or level_raw is None:
        parsed_level = 'review'

    reason = reason_match.group(1).strip() if reason_match else str(json_fields.get('reason') or '').strip()
    return ContextQuality(relevant, parsed_level, reason, display)

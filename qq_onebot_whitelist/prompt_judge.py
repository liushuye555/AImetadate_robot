"""提示词绑定 LLM 复核：判断绑定文本是否是真实 AI 出图提示词（rule/llm/both 模式）。

说明：文本模型无法直接看图，这里复核的是"提示词文本是否像真正的出图提示词"，
过滤闲聊/命令等误绑；图是否真由该提示词生成需要视觉模型，暂不支持。
结果按提示词哈希缓存（store.prompt_judges），token 成本记入 cost_log。
"""

from __future__ import annotations

import hashlib
import json
import urllib.request

from .llm_summary import LLMConfig

cost_log = {"calls": 0, "total_tokens": 0}


def reset_cost_log() -> None:
    cost_log["calls"] = 0
    cost_log["total_tokens"] = 0


def prompt_hash(text: str) -> str:
    return hashlib.sha1((text or '').encode('utf-8', errors='replace')).hexdigest()[:16]


def llm_judge_prompt(prompt_text: str) -> tuple[bool, int]:
    """判定提示词文本是否像真实出图提示词。返回 (keep, tokens)；失败默认保留。"""
    cfg = LLMConfig.ds_fallback_from_env_file()
    if cfg is None or not cfg.api_key:
        return True, 0
    system = (
        '你是图片提示词判定助手：判断一段文本是否是 AI 图像生成提示词'
        '（包含具体画面描述/标签组合，如 1girl、场景、风格、质量词等）。'
        '只回答：是 / 否'
    )
    payload = {
        'model': cfg.model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': (prompt_text or '')[:800]},
        ],
        'temperature': 0,
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {cfg.api_key}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_seconds or 60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
        usage = data.get('usage') or {}
        tokens = int(usage.get('total_tokens') or 0)
        cost_log["calls"] += 1
        cost_log["total_tokens"] += tokens
        return '是' in content, tokens
    except Exception:
        return True, 0


def should_keep_prompt(prompt_text: str, mode: str = 'rule') -> bool:
    """绑定是否保留：rule 直接保留；llm/both 交给模型复核。"""
    if mode == 'rule':
        return True
    keep, _ = llm_judge_prompt(prompt_text)
    return keep

"""参数/模型讨论判定：rule（关键词）| llm（DeepSeek 复核）| both（规则预筛+LLM）。

LLM 调用按批处理并记录 token 成本（运行后可对比）。
"""
from __future__ import annotations

from .prompt_binding import is_params_message

cost_log = {"calls": 0, "total_tokens": 0}


def reset_cost_log() -> None:
    cost_log["calls"] = 0
    cost_log["total_tokens"] = 0


def _llm_judge_batch(texts: list[str]) -> tuple[list[bool], int, int]:
    """调用 DeepSeek 判定每段文本是否在讨论 AI 图像生成。

    返回 (bools, prompt_tokens, completion_tokens)；无配置/调用失败时全部回退 True
    （保持规则结果，不阻塞流程）。
    """
    import json
    import urllib.request
    from .llm_summary import LLMConfig

    cfg = LLMConfig.ds_fallback_from_env_file()
    if cfg is None or not cfg.api_key:
        return [True] * len(texts), 0, 0
    system = '你是判断助手：判断给出的聊天文本是否在讨论 AI 图像生成（模型/提示词/出图/画质等）。只回答每段: 是/否'
    payload = {
        'model': cfg.model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': '\n---\n'.join(f'{i}: {t}' for i, t in enumerate(texts))},
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
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        verdicts = ['是' in ln for ln in lines[:len(texts)]]
        verdicts += [True] * (len(texts) - len(verdicts))
        return verdicts, int(usage.get('prompt_tokens') or 0), int(usage.get('completion_tokens') or 0)
    except Exception:
        return [True] * len(texts), 0, 0


def should_keep_params(text: str, mode: str = "rule") -> bool:
    rule_hit = is_params_message(text)
    if mode == "rule":
        return rule_hit
    if mode == "llm":
        verdicts, pt, ct = _llm_judge_batch([text])
        cost_log["calls"] += 1
        cost_log["total_tokens"] += pt + ct
        return bool(verdicts[0])
    # both
    if not rule_hit:
        return False
    verdicts, pt, ct = _llm_judge_batch([text])
    cost_log["calls"] += 1
    cost_log["total_tokens"] += pt + ct
    return bool(verdicts[0])

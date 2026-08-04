"""链接用途 LLM 判定：对规则判不出用途的链接调用 DeepSeek 复核，并记录 token 成本。

规则（daily_report.link_purpose）先筛；rule 判不出且配置为 llm/both 时，
这里把"链接 + 附近消息"交给模型判断是否 AI 资源。结果按 URL 缓存（store.link_judges）。
"""

from __future__ import annotations

import json
import urllib.request

from .llm_summary import LLMConfig

cost_log = {"calls": 0, "total_tokens": 0}


def reset_cost_log() -> None:
    cost_log["calls"] = 0
    cost_log["total_tokens"] = 0


def llm_judge_link(url: str, context: str) -> tuple[str, int]:
    """调用 DeepSeek 判定链接是否 AI 相关资源。

    返回 (purpose, total_tokens)；无配置/调用失败时返回 ('', 0)，维持规则结果不阻塞。
    purpose 取值：'核心AI资源' | '值得一看' | ''。
    """
    cfg = LLMConfig.ds_fallback_from_env_file()
    if cfg is None or not cfg.api_key:
        return '', 0
    system = (
        '你是资源分类助手：判断一个分享链接是否属于 AI 相关资源'
        '（AI 模型/工作流/出图工具/教程/示例视频等）。'
        '只回答三者之一：核心AI资源 / 值得一看 / 无关'
    )
    user = f'链接: {url}\n消息上下文: {context[:500]}'
    payload = {
        'model': cfg.model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
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
        if '核心AI资源' in content:
            return '核心AI资源', tokens
        if '值得一看' in content:
            return '值得一看', tokens
        return '', tokens
    except Exception:
        return '', 0

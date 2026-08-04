"""提示词/参数讨论消息识别与图片绑定。

- 提示词消息：/绘图 文生图/图生图 指令、booru tag 行、prompt: 块。
- 参数讨论消息：提到模型/采样器/显卡/出图等 AI 生成参数话题。
"""
from __future__ import annotations

import re

PROMPT_RE = re.compile(
    r'(/绘图|文生图|图生图'
    r'|\b(1girl|1boy|masterpiece|best quality)\b'
    r'|prompt\s*[:：]'
    r'|\b(lora|sdxl|flux|novelai)\b)', re.I)

PARAMS_RE = re.compile(
    r'(ckpt|sampler|denoise|steps|seed|lora|模型|显卡|炼丹|出图|生成'
    r'|显存|fp8|低噪|重绘|画质|分辨率|seedvr)', re.I)


def is_prompt_message(text: str) -> bool:
    return bool(PROMPT_RE.search(text or ''))


def is_params_message(text: str) -> bool:
    return bool(PARAMS_RE.search(text or ''))


def bind_prompt_for_image(
    records: list[dict],
    reply_to: str | None = None,
    own_message_id: str | None = None,
) -> tuple[str | None, str]:
    """为图片判定绑定：返回 (kind, prompt_text)。

    kind: 'prompt'（进提示词绑定区）| 'params'（进参数讨论区）| None（无信号）。
    records: 按时间正序的附近消息（recent_records 格式，含 quoted_text/reply_to_message_id）。
    reply_to: 图片消息引用的消息 id；own_message_id: 图片消息自身的 id。
    """
    # 引用绑定①：图片引用含提示词的文本
    if reply_to:
        for rec in records:
            if str(rec.get('id') or '') == str(reply_to):
                if is_prompt_message(str(rec.get('text') or '')):
                    return 'prompt', str(rec.get('text') or '')
                break
        for rec in records:
            if str(rec.get('reply_to_message_id') or '') == str(reply_to):
                quoted = str(rec.get('quoted_text') or '')
                if is_prompt_message(quoted):
                    return 'prompt', quoted
    # 引用绑定②：文本引用图片且含提示词
    if own_message_id:
        for rec in records:
            if str(rec.get('reply_to_message_id') or '') == str(own_message_id) \
                    and is_prompt_message(str(rec.get('text') or '')):
                return 'prompt', str(rec.get('text') or '')
    # 时序绑定：最近 6 条中最后一条提示词消息
    last_prompt = None
    for rec in records[-6:]:
        if is_prompt_message(str(rec.get('text') or '')):
            last_prompt = str(rec.get('text') or '')
    if last_prompt:
        return 'prompt', last_prompt
    # 参数/模型讨论
    if any(is_params_message(str(rec.get('text') or '')) for rec in records[-6:]):
        return 'params', ''
    return None, ''

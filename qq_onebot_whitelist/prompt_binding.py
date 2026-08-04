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

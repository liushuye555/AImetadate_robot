"""提示词/参数讨论消息识别与图片绑定。

- 提示词消息：/绘图 文生图/图生图 指令、booru tag 行、prompt: 块。
- 参数讨论消息：提到模型/采样器/显卡/出图等 AI 生成参数话题。
"""
from __future__ import annotations

import re

STRONG_PROMPT_RE = re.compile(
    r'(masterpiece|best quality|loRA|checkpoint|comfyui|workflow|prompt\s*[:：]'
    r'|\b(sdxl|flux|novelai)\b)', re.I)

TAG_RE = re.compile(
    r'\b(1girl|1boy|1other|solo|kemonomimi|animal ears|long hair|short hair|'
    r'blonde|brown hair|black hair|white hair|blue eyes|red eyes|green eyes|'
    r'cat ears|fox ears)\b', re.I)

# /绘图 命令后仅出现这些关键字（无实质提示词/模型名）时不算提示词消息
BARE_DRAW_KEYWORDS = {'模型', '状态', '帮助', 'help', '菜单', '功能', '文生图', '图生图'}

PARAMS_RE = re.compile(
    r'(ckpt|sampler|denoise|steps|seed|lora|模型|显卡|炼丹|出图|生成'
    r'|显存|fp8|低噪|重绘|画质|分辨率|seedvr)', re.I)


def is_prompt_message(text: str) -> bool:
    t = (text or '').strip()
    if not t:
        return False
    m = re.match(r'^/绘图[\s:：]*', t)
    if m:
        rest = t[m.end():].strip()
        # 命令后没有内容、只有短关键字（如"模型/状态"）→ 是机器人命令而非提示词
        return bool(rest) and rest not in BARE_DRAW_KEYWORDS and len(rest) > 4
    if '文生图' in t or '图生图' in t:
        rest = re.sub(r'^.*?(文生图|图生图)[\s:：]*', '', t).strip()
        return bool(rest) and len(rest) > 2
    if STRONG_PROMPT_RE.search(t):
        return True
    # booru tag 行：至少 2 个逗号分隔的已知标签才算提示词（单个词命中不算）
    return len(TAG_RE.findall(t)) >= 2 and ',' in t


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
    # 时序绑定：提示词消息必须是图片紧邻的前一条内容消息（中间有人插话就不绑）
    non_empty = [rec for rec in records[-6:] if str(rec.get('text') or '').strip()]
    if non_empty:
        last = non_empty[-1]
        if is_prompt_message(str(last.get('text') or '')):
            return 'prompt', str(last.get('text') or '')
    # 参数/模型讨论
    if any(is_params_message(str(rec.get('text') or '')) for rec in records[-6:]):
        return 'params', ''
    return None, ''

"""提示词/参数讨论消息识别与图片绑定。

- 提示词消息：/绘图 文生图/图生图 指令、booru tag 行、prompt: 块。
- 参数讨论消息：提到模型/采样器/显卡/出图等 AI 生成参数话题。

判定阈值来自历史消息流挖掘（2026-09）：
- 裸工具词（lora/comfyui/checkpoint）单独出现在闲聊里占提示词误绑的 44%，
  不再作为提示词证据，只有 <lora:...> 标签语法或成块 tag 才算；
- 参数词分"具体词"（sampler/seed/lora/炼丹…）与"泛化词"（模型/生成/画质…），
  泛化词单独出现 62% 是闲聊，须搭配疑问语气或第二个词才有效。
"""
from __future__ import annotations

import re

# 提示词强证据：质量词、prompt: 前缀、<lora:...> 标签语法
QUALITY_PROMPT_RE = re.compile(r'\b(masterpiece|best quality)\b', re.I)
LORA_TAG_RE = re.compile(r'<lora:[^<>:]{2,}:[^<>]*>', re.I)
PROMPT_KEY_RE = re.compile(r'prompt\s*[:：]', re.I)

TAG_RE = re.compile(
    r'\b(1girl|1boy|1other|solo|kemonomimi|animal ears|long hair|short hair|'
    r'blonde|brown hair|black hair|white hair|blue eyes|red eyes|green eyes|'
    r'cat ears|fox ears)\b', re.I)

# 下划线 booru tag（looking_at_viewer / dragon_girl 等），一票确认提示词形状
UNDERSCORE_TAG_RE = re.compile(r'\b[a-z]{3,}_[a-z]{3,}\b')

# /绘图 命令后仅出现这些关键字（无实质提示词/模型名）时不算提示词消息
BARE_DRAW_KEYWORDS = {'模型', '状态', '帮助', 'help', '菜单', '功能', '文生图', '图生图'}

# 参数"具体词"：几乎只在生成参数语境出现
PARAMS_SPECIFIC_RE = re.compile(
    r'(ckpt|sampler|denoise|steps|seed|lora|fp8|seedvr|cfg\b|unet|vae'
    r'|炼丹|采样|二采|低噪|底模|重绘幅度)', re.I)
# 参数"泛化词"：日常聊天也常用，单独出现不算数
PARAMS_GENERIC_RE = re.compile(
    r'(模型|显卡|出图|生成|显存|重绘|画质|分辨率|跑图|放大)', re.I)
# 疑问/求助语气：泛化词 + 疑问才算参数讨论（"超长图适合设置多少分辨率？"）
PARAMS_QUESTION_RE = re.compile(r'[?？]|吗[。，！！？~]?$|呢[。，！！？~]?$|怎么|多少|什么|哪个|哪种|多少|咋', re.I)

# 提示词 tag 块：≥6 个逗号、无明显句读、偏 ASCII 或含下划线 tag
SENTENCE_PUNCT_RE = re.compile(r'[。！？!?；;]')


def _is_tag_block(t: str) -> bool:
    if t.count(',') + t.count('，') < 6 or len(t) < 20:
        return False
    if SENTENCE_PUNCT_RE.search(t.replace('，', '').replace(',', '')):
        return False
    ascii_ratio = sum(1 for ch in t if ord(ch) < 128) / len(t)
    return ascii_ratio >= 0.5 or bool(UNDERSCORE_TAG_RE.search(t))


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
    if PROMPT_KEY_RE.search(t) or QUALITY_PROMPT_RE.search(t) or LORA_TAG_RE.search(t):
        return True
    # booru tag 行：至少 2 个逗号分隔的已知标签才算提示词（单个词命中不算）
    if len(TAG_RE.findall(t)) >= 2 and ',' in t:
        return True
    return _is_tag_block(t)


def is_params_message(text: str) -> bool:
    t = text or ''
    specific = set(m.group(0).lower() for m in PARAMS_SPECIFIC_RE.finditer(t))
    if specific:
        return True
    generic = set(m.group(0).lower() for m in PARAMS_GENERIC_RE.finditer(t))
    if len(generic) >= 2:
        return True
    return bool(generic) and bool(PARAMS_QUESTION_RE.search(t))


def bind_prompt_for_image(
    records: list[dict],
    reply_to: str | None = None,
    own_message_id: str | None = None,
    own_text: str | None = None,
) -> tuple[str | None, str]:
    """为图片判定绑定：返回 (kind, prompt_text)。

    kind: 'prompt'（进提示词绑定区）| 'params'（进参数讨论区）| None（无信号）。
    records: 按时间正序的附近消息（recent_records 格式，含 quoted_text/reply_to_message_id）。
    reply_to: 图片消息引用的消息 id；own_message_id: 图片消息自身的 id；
    own_text: 图片所在消息自带的文本（"来一张这个:1girl, solo" + 图同条发送）。
    """
    # 同条消息自带提示词（prompt+图一起发）
    own_text = (own_text or '').strip()
    if own_text and is_prompt_message(own_text):
        return 'prompt', own_text
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

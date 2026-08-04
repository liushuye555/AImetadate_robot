from __future__ import annotations

import re

AI_KEYWORDS = [
    'prompt', 'negative prompt', '提示词', '正向', '反向', 'tag', 'tags', 'danbooru',
    'comfyui', 'workflow', '工作流', '节点', 'node', 'ksampler',
    'stable diffusion', 'sdxl', 'sd1.5', 'sd3', 'flux', 'a1111', 'webui',
    'lora', 'lycoris', 'checkpoint', 'ckpt', 'safetensors', '模型',
    'controlnet', 'ipadapter', 'redux', '采样', 'sampler', 'steps', 'cfg', 'seed',
    '放大', '超分', 'hires', 'upscale', '重绘', 'inpaint', 'img2img', '出图', '原图',
]

PROMPT_LIKE_RE = re.compile(r'\b(1girl|1boy|masterpiece|best quality|highres|solo|looking at viewer|white hair|blue eyes)\b', re.I)

POSITIVE_WORDS = [
    '求提示词', '求tag', '求工作流', '求模型', '怎么做的', '怎么出的',
    '神图', '太神', '绝了', '无敌', '卧槽', '质量很高', '出图质量',
    '细节很好', '构图很好', '求配方', '求参数',
]

GENERIC_ACKS = {'好的', '收到', 'ok', 'OK', '嗯', '对', '是', '哈哈', '哈哈哈'}


def is_ai_relevant_text(text: str) -> bool:
    text = (text or '').strip()
    if not text or text in GENERIC_ACKS:
        return False
    lower = text.lower()
    if any(keyword.lower() in lower for keyword in AI_KEYWORDS):
        return True
    if PROMPT_LIKE_RE.search(text):
        return True
    # Many comma-separated English tags often indicate prompt text.
    comma_count = text.count(',') + text.count('，')
    ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(len(text), 1)
    return comma_count >= 4 and ascii_ratio > 0.45


def is_positive_feedback_text(text: str) -> bool:
    text = (text or '').strip()
    if not text or text in GENERIC_ACKS:
        return False
    return any(word in text for word in POSITIVE_WORDS)

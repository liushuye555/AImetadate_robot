from __future__ import annotations

from .ai_relevance import is_ai_relevant_text, is_positive_feedback_text
from .image_meta import ImageMetadata


AI_TYPICAL_ASPECTS = (
    0.5, 0.5625, 0.6, 0.64, 0.667, 0.75, 0.8, 1.0,
    1.25, 1.333, 1.5, 1.778, 2.0,
)


def is_ai_typical_size(width: int | None, height: int | None) -> bool:
    """AI 生成图常见尺寸特征：64 的倍数、512~4096、常见宽高比。"""
    if not width or not height:
        return False
    if width < 512 or height < 512 or width > 4096 or height > 4096:
        return False
    if width % 64 != 0 or height % 64 != 0:
        return False
    aspect = width / height
    return any(abs(aspect - item) < 0.05 for item in AI_TYPICAL_ASPECTS)


def should_keep_image(meta: ImageMetadata, nearby_text: str = '') -> tuple[bool, str]:
    if meta.has_ai_metadata:
        return True, 'ai_metadata'
    if is_positive_feedback_text(nearby_text):
        return True, 'positive_feedback'
    if is_ai_relevant_text(nearby_text):
        return True, 'nearby_ai_context'
    # 无元数据但尺寸符合 AI 典型输出 → 疑似混淆（截图/重编码/去水印等）
    if is_ai_typical_size(meta.width, meta.height):
        return True, 'possible_obfuscation'
    return False, 'no_ai_metadata'

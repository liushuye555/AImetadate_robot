from __future__ import annotations

from .ai_relevance import is_ai_relevant_text, is_positive_feedback_text
from .image_meta import ImageMetadata


def should_keep_image(meta: ImageMetadata, nearby_text: str = '') -> tuple[bool, str]:
    if meta.has_ai_metadata:
        return True, 'ai_metadata'
    if is_positive_feedback_text(nearby_text):
        return True, 'positive_feedback'
    if is_ai_relevant_text(nearby_text):
        return True, 'nearby_ai_context'
    return False, 'no_ai_metadata'

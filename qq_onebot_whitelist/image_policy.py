from __future__ import annotations

from .image_meta import ImageMetadata


def should_keep_image(meta: ImageMetadata, nearby_text: str = '') -> tuple[bool, str]:
    """是否保留：仅带 AI 元数据的图直接保留；其余一律走候选/绑定流程。

    群友好评不再按"图片之前的消息"判定（好评发生在图片之后，由
    collection._promote_recent_candidate_if_needed 事后晋升）。
    """
    if meta.has_ai_metadata:
        return True, 'ai_metadata'
    return False, 'no_ai_metadata'

"""群级采集模块：按群配置的采集策略 + 消息采集流水线（消息/链接/文件/图片归档）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .store import Store
from .commands import scope_for_event
from .policy import extract_text
from .resources import extract_file_segments
from .images import extract_image_segments, is_probable_sticker_result, process_image_url
from .image_lifecycle import CandidateImage, promote_candidate
from .ai_relevance import is_positive_feedback_text


COLLECTION_KINDS = ("images", "links", "files", "forwards")


def collection_allows(scope: str, kind: str, config: AppConfig) -> bool:
    """未配置的群采集全部类型；已配置的群按 profile 勾选结果判定。"""
    profile = config.collection_groups.get(scope)
    if profile is None:
        return True
    return bool(profile.get(kind, True))


def is_forward_event(event: dict[str, Any]) -> bool:
    """判断消息是否为转发消息（OneBot 转发段或转发类型）。"""
    return event.get("message_type") == "forward" or "forward" in json.dumps(event, ensure_ascii=False)


def _promote_recent_candidate_if_needed(store: Store, scope: str, text: str, config: AppConfig) -> None:
    if not is_positive_feedback_text(text):
        return
    candidate = store.latest_candidate_image(scope)
    if not candidate:
        return
    path = candidate.get('kept_path')
    if not path:
        return
    if is_probable_sticker_result(candidate):
        return
    source = CandidateImage(scope=scope, sha256=str(candidate.get('sha256') or ''), path=Path(path), created_at=0, score=2)
    dest = promote_candidate(source, config.data_dir / 'images' / 'ai')
    store.update_image_retention(int(candidate['id']), kept_path=str(dest), retention_reason='positive_feedback')


def collect_event(store: Store, event: dict[str, Any], config: AppConfig) -> None:
    """按群采集策略记录一条消息及其中的链接、文件与图片。"""
    if event.get('post_type') != 'message':
        return
    scope = scope_for_event(event)
    user_id = str(event.get('user_id') or '')
    text = extract_text(event)
    if is_forward_event(event) and not collection_allows(scope, 'forwards', config):
        return
    store.record_message(
        scope=scope,
        user_id=user_id,
        text=text,
        raw=event,
        collect_links=collection_allows(scope, 'links', config),
    )
    message_db_id = store.message_row_id(scope, event)
    if collection_allows(scope, 'files', config):
        for file_item in extract_file_segments(event):
            if file_item.get('kind') in {'model', 'archive', 'workflow'}:
                store.record_file(
                    scope=scope,
                    user_id=user_id,
                    file_name=file_item['file_name'],
                    file_size=file_item.get('file_size'),
                    url=file_item.get('url'),
                    kind=file_item.get('kind') or 'other',
                    raw={'file': file_item, 'message_text': text},
                )
    nearby_text = '\n'.join(x for x in [store.recent_text_context(scope, limit=8), text] if x)
    _promote_recent_candidate_if_needed(store, scope, text, config)
    if not config.feature_image_processing or not collection_allows(scope, 'images', config):
        return
    for image in extract_image_segments(event):
        try:
            result = process_image_url(
                image['url'],
                tmp_dir=config.data_dir / 'tmp',
                archive_root=config.data_dir / 'images' / 'ai',
                candidate_root=config.data_dir / 'images' / 'candidates',
                filename_hint=image.get('file'),
                nearby_text=nearby_text,
            )
            if is_probable_sticker_result(result) and result.get('retention_reason') in {'positive_feedback', 'nearby_ai_context', 'candidate'}:
                kept = result.get('kept_path')
                if kept:
                    Path(kept).unlink(missing_ok=True)
                result['kept_path'] = None
                result['retention_reason'] = 'sticker_filtered'
            store.record_image(
                scope=scope,
                user_id=user_id,
                result=result,
                raw={'image': image, 'message_db_id': message_db_id, 'message_id': event.get('message_id')},
            )
        except Exception as exc:
            print(f'image processing failed: {type(exc).__name__}: {exc}')

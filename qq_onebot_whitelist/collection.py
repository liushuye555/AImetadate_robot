"""群级采集模块：按群配置的采集策略 + 消息采集流水线（消息/链接/文件/图片归档）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import AppConfig
from .store import Store, canonical_message_key
from .commands import scope_for_event
from .policy import extract_text
from .resources import extract_file_segments
from .images import extract_image_segments, is_probable_sticker_result, process_image_url
from .image_lifecycle import CandidateImage, promote_candidate
from .ai_relevance import is_positive_feedback_text
from .summary import extract_links


PAUSE_MARKER = Path(__file__).resolve().parents[1] / "run" / "collection-paused"
_AI_MATCH_CACHE: dict[tuple[str, str], bool] = {}


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


def forward_ids(event: dict[str, Any]) -> list[str]:
    """提取转发消息的 forward id（可多个）。"""
    ids: list[str] = []
    for segment in (event.get('message') or []):
        if isinstance(segment, dict) and segment.get('type') == 'forward':
            data = segment.get('data') or {}
            value = str(data.get('id') or '')
            if value:
                ids.append(value)
    return ids


def _llm_config():
    from .llm_summary import LLMConfig
    config = LLMConfig.ds_fallback_from_env_file(Path(__file__).resolve().parents[1] / '.env')
    if config is not None and config.timeout_seconds > 30:
        config.timeout_seconds = 30
    return config


def ai_match_message(text: str, prompt: str, llm_config) -> bool:
    """调用 LLM 判断消息是否符合收集条件，只输出是/否。"""
    import urllib.request
    payload = {
        "model": llm_config.model,
        "messages": [
            {"role": "system", "content": "你是一个内容分类器。只输出“是”或“否”。"},
            {"role": "user", "content": f"收集条件：{prompt}\n请判断以下消息是否满足条件，只回答是或否：\n{text[:1500]}"},
        ],
        "temperature": 0,
    }
    req = urllib.request.Request(
        llm_config.base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {llm_config.api_key}"},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=llm_config.timeout_seconds) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    answer = str(data['choices'][0]['message']['content'] or '').strip()
    return '是' in answer[:4] or answer.lower().startswith('yes')


def ai_match_and_collect(store: Store, event: dict[str, Any], text: str, config: AppConfig) -> None:
    """对开启 AI 匹配的规则做语义判断，命中则归档（在后台线程调用，避免阻塞消息循环）。"""
    if is_collection_paused() or not text.strip():
        return
    scope = scope_for_event(event)
    candidate_rules = [
        rule for rule in config.collection_rules
        if rule.get('ai_match') and rule.get('enabled', True)
        and (not (rule.get('groups') or []) or scope in {str(g) for g in rule['groups']})
    ]
    if not candidate_rules:
        return
    llm_config = _llm_config()
    if llm_config is None:
        return
    images = [str(img.get('url') or '') for img in extract_image_segments(event) if img.get('url')]
    links = extract_links(text)
    files = [str(f.get('file_name') or '') for f in extract_file_segments(event) if f.get('file_name')]
    user_id = str(event.get('user_id') or '')
    for rule in candidate_rules:
        prompt = str(rule.get('ai_prompt') or '').strip()
        if not prompt:
            continue
        key = (str(rule.get('name') or ''), text)
        if key in _AI_MATCH_CACHE:
            matched = _AI_MATCH_CACHE[key]
        else:
            try:
                matched = ai_match_message(text, prompt, llm_config)
            except Exception as exc:
                print(f'ai_match failed: {type(exc).__name__}: {exc}')
                continue
            if len(_AI_MATCH_CACHE) > 500:
                _AI_MATCH_CACHE.clear()
            _AI_MATCH_CACHE[key] = matched
        if matched:
            store.record_custom_collection(
                rule=str(rule.get('name') or '未命名'),
                scope=scope,
                user_id=user_id,
                text=text,
                images=images if rule.get('collect_images', True) else [],
                links=links if rule.get('collect_links', True) else [],
                files=files if rule.get('collect_files', True) else [],
                message_key=canonical_message_key(event),
            )


def is_collection_paused() -> bool:
    """运行时采集总开关（run/collection-paused 标记），无需重启机器人。"""
    return PAUSE_MARKER.exists()


def match_custom_rules(event: dict[str, Any], text: str, config: AppConfig) -> list[dict]:
    """按自定义规则匹配消息：关键词（任一命中）或正则，且群在规则范围内。"""
    scope = scope_for_event(event)
    lowered = text.lower()
    matched: list[dict] = []
    for rule in config.collection_rules:
        if not rule.get('enabled', True):
            continue
        groups = {str(g) for g in (rule.get('groups') or [])}
        if groups and scope not in groups:
            continue
        keywords = [str(k).strip().lower() for k in (rule.get('keywords') or []) if str(k).strip()]
        regex = str(rule.get('regex') or '').strip()
        if not keywords and not regex:
            continue
        if keywords and not any(k in lowered for k in keywords):
            continue
        if regex:
            try:
                if not re.search(regex, text):
                    continue
            except re.error:
                continue
        matched.append(rule)
    return matched


def collect_custom(store: Store, event: dict[str, Any], text: str, config: AppConfig) -> None:
    """把命中的自定义规则消息记录到 custom_collections 表。"""
    if is_collection_paused():
        return
    rules = match_custom_rules(event, text, config)
    if not rules:
        return
    scope = scope_for_event(event)
    user_id = str(event.get('user_id') or '')
    images = [str(img.get('url') or '') for img in extract_image_segments(event) if img.get('url')]
    links = extract_links(text)
    files = [str(f.get('file_name') or '') for f in extract_file_segments(event) if f.get('file_name')]
    for rule in rules:
        store.record_custom_collection(
            rule=str(rule.get('name') or '未命名'),
            scope=scope,
            user_id=user_id,
            text=text,
            images=images if rule.get('collect_images', True) else [],
            links=links if rule.get('collect_links', True) else [],
            files=files if rule.get('collect_files', True) else [],
            message_key=canonical_message_key(event),
        )


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
    if is_collection_paused():
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
    collect_custom(store, event, text, config)
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

"""群级采集模块：按群配置的采集策略 + 消息采集流水线（消息/链接/文件/图片归档）。"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

from .config import AppConfig
from .store import Store, canonical_message_key, reply_to_message_id
from .commands import scope_for_event
from .policy import extract_text
from .resources import extract_file_segments
from .images import extract_image_segments, is_probable_sticker_result, is_sticker_format, process_image_url
from .image_lifecycle import CandidateImage, promote_candidate
from .ai_relevance import is_positive_feedback_text
from .summary import extract_links
from .gilbert_obfuscation import analyze_image, promote_restored, restore_image
from .load_aware import load_aware_ok
from .prompt_binding import bind_prompt_for_image


PAUSE_MARKER = Path(__file__).resolve().parents[1] / "run" / "collection-paused"
_AI_MATCH_CACHE: dict[tuple[str, str], bool] = {}
_deferred_images: deque[tuple] = deque()
_deferred_lock = Lock()
MAX_DEFERRED_IMAGES = 300


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
    load_ok = load_aware_ok(config)
    for image in extract_image_segments(event):
        if not load_ok:
            defer_event_image((scope, user_id, image, nearby_text, message_db_id, event.get('message_id')))
            continue
        process_event_image(
            store,
            scope=scope,
            user_id=user_id,
            image=image,
            nearby_text=nearby_text,
            message_db_id=message_db_id,
            config=config,
            event=event,
        )


def defer_event_image(item: tuple) -> bool:
    """高负载时把单张图片的处理任务入队（有界），返回是否入队成功。"""
    with _deferred_lock:
        if len(_deferred_images) >= MAX_DEFERRED_IMAGES:
            return False
        _deferred_images.append(item)
        return True


def pop_deferred_image() -> tuple | None:
    with _deferred_lock:
        return _deferred_images.popleft() if _deferred_images else None


def requeue_deferred_image(item: tuple) -> None:
    """CPU 仍忙时把任务放回队首，保持顺序。"""
    with _deferred_lock:
        _deferred_images.appendleft(item)


def deferred_image_count() -> int:
    with _deferred_lock:
        return len(_deferred_images)


def process_event_image(
    store: Store,
    *,
    scope: str,
    user_id: str,
    image: dict[str, Any],
    nearby_text: str,
    message_db_id: int | None,
    config: AppConfig,
    event: dict[str, Any] | None = None,
) -> None:
    """处理单张图片：下载 → 归档 → 小番茄混淆检测/还原 → 表情包过滤 → 入库。"""
    try:
        result = process_image_url(
            image['url'],
            tmp_dir=config.data_dir / 'tmp',
            archive_root=config.data_dir / 'images' / 'ai',
            candidate_root=config.data_dir / 'images' / 'candidates',
            filename_hint=image.get('file'),
            nearby_text=nearby_text,
        )
        # 03 提示词/参数绑定（无 AI 元数据图）
        if not result.get('has_ai_metadata'):
            try:
                records = store.recent_records(scope, limit=6)
            except Exception:
                records = []
            kind, prompt = bind_prompt_for_image(
                records,
                reply_to=reply_to_message_id(event or {}),
                own_message_id=str((event or {}).get('message_id') or '') or None,
            )
            if kind == 'prompt':
                result['retention_reason'] = 'prompt_bound'
                result['bound_prompt'] = prompt[:2000]
            elif kind == 'params':
                result['retention_reason'] = 'params_discussion'
        # 小番茄混淆算法级验证（Gilbert 曲线逆置换）：确认后直接标记，
        # 结果缓存到 image_hashes，避免重分类时重复分析。
        if not result.get('has_ai_metadata') and result.get('kept_path'):
            xfq_result = None
            try:
                xfq_result = analyze_image(result['kept_path'])
            except Exception:
                pass
            if xfq_result is not None:
                result['xfq_ratio'] = round(float(xfq_result['ratio']), 4)
                result['xfq_layers'] = xfq_result.get('layers')
                try:
                        store.save_obfuscation_score(
                            str(result.get('sha256') or ''),
                            ratio=float(xfq_result['ratio']),
                            layers=xfq_result.get('layers'),
                            obfuscated=bool(xfq_result.get('obfuscated')),
                            confidence=xfq_result.get('confidence') or 'none',
                        )
                except Exception:
                    pass
                if xfq_result.get('obfuscated'):
                    confidence = xfq_result.get('confidence')
                    current = result.get('retention_reason')
                    if current in {'prompt_bound', 'params_discussion', 'positive_feedback'} and confidence == 'confirmed':
                        # 交叉分类：05 为主分类，同时记录上下文分类（报告里 02/03 遮罩显示）
                        result['context_reason'] = current
                    result['retention_reason'] = (
                        'xiaofanqie_obfuscated' if confidence == 'confirmed'
                        else 'xiaofanqie_compressed'
                    )
                    # 确认档自动解混淆：还原到临时文件后提升为唯一存档（删原图）
                    if confidence == 'confirmed' and result.get('kept_path'):
                        try:
                            restored, _ = restore_image(
                                result['kept_path'],
                                config.data_dir / 'tmp' / f"{result.get('sha256')}.restore.png",
                                layers=xfq_result.get('layers'),
                            )
                            final = promote_restored(
                                result['kept_path'],
                                restored,
                                config.data_dir / 'images' / 'ai',
                                str(result.get('sha256') or ''),
                            )
                            result['kept_path'] = str(final)
                            result['restored_path'] = str(final)
                            result['deobfuscated'] = True
                        except Exception as exc:
                            print(f'restore failed: {type(exc).__name__}: {exc}')
        if result.get('retention_reason') == 'ai_metadata' and result.get('phash') is not None:
            store.save_image_hash(str(result.get('sha256') or ''), result['phash'])
        # 表情包规则：群内大量重复（>= 阈值）且符合表情包格式
        is_sticker = is_sticker_format(result) and (store.count_image_occurrences(scope, str(result.get('sha256') or '')) + 1) >= max(1, config.sticker_repeat_threshold)
        if is_sticker and result.get('retention_reason') in {'positive_feedback', 'nearby_ai_context', 'candidate'}:
            kept = result.get('kept_path')
            if kept:
                Path(kept).unlink(missing_ok=True)
            result['kept_path'] = None
            result['retention_reason'] = 'sticker_filtered'
        store.record_image(
            scope=scope,
            user_id=user_id,
            result=result,
            raw={'image': image, 'message_db_id': message_db_id, 'message_id': (event or {}).get('message_id')},
        )
    except Exception as exc:
        print(f'image processing failed: {type(exc).__name__}: {exc}')

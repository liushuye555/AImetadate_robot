"""视觉复核 02/03 类图片：DeepSeek 视觉模型判断图是否真的是 AI 生成图像。

背景：02 群友好评 / 03 参数讨论 / 03 提示词绑定靠上下文文本命中分类，
"上下文命中了 AI，但图不对"（截图、表情包等混进来）。视觉模型可以直接看图。

省 token 手段（DeepSeek 官方：图片进入模型前自动缩放到约 1300×1300、
每张图 token 封顶 1024，与原图尺寸无关）：
1. 原图直传，客户端不再缩放（成本固定，缩图反而丢细节）；
2. 判定结果按 sha256 缓存（image_hashes.vision_verdict），一张图只花一次钱；
3. 每轮限量（images.vision_recheck_batch，默认 20 张），且只在 AI 允许时段
   （DeepSeek 错峰窗口，含 all_day_weekdays 全天开放日）内自动跑批。

官方限制：支持 JPEG/PNG/GIF/WebP（按文件实际内容判断）；base64 内联计入
48 MiB 请求体限制；图片只能出现在 user 消息中（system/assistant 带图返回 400）。

误分处置：判定不是 AI 图 → 降级到 04_候选待观察（candidate），数据不丢。
手动全量：uv run python -m qq_onebot_whitelist.control vision-recheck --limit 200
"""
from __future__ import annotations

import base64
import io
import json
import urllib.request
from pathlib import Path

from .llm_summary import LLMConfig
from . import netutil

cost_log = {"calls": 0, "total_tokens": 0}
last_error = {'image': None, 'error': None}

# 两种判定标准，按类目语义区分：
# strict（作品判定）：02_群友好评 / 03_提示词绑定 收的是 AI 生成图像本身，
#   截图（网页/软件界面/参数面板/聊天）即使内嵌 AI 图也判"否"→ 降级；
# related（相关性判定）：03_参数讨论 收的是参数相关内容，参数面板/工作流/
#   效果对比截图正是有价值的东西，只降级真人照片、无关表情包、纯文字图等。
_JUDGE_SYSTEMS = {
    'strict': (
        '你是图片分类助手。判断图片本身是否为一幅完整的 AI 生成/绘制的图像'
        '（插画、二次元图、AI 摄影等，含真实感 AI 图）。'
        '以下一律算"否"：'
        '① 任何截图——浏览器/网页截图、软件界面截图（绘图软件、参数面板、工作流节点图）、'
        '聊天记录截图、游戏截图——即使画面里嵌着 AI 生成内容；'
        '② 真人照片；③ 表情包拼图；④ 纯文字图。'
        '关键区分：主体是"一幅画"，还是"一张屏幕截图（含窗口、按钮、地址栏、UI 面板等元素）"。'
        '只输出 JSON：{"is_ai_image": true/false}'
    ),
    'related': (
        '你是图片分类助手。判断图片是否与 AI 绘图/AI 生成图像的内容相关'
        '（AI 生成图像本身、绘图参数面板截图、工作流/节点图截图、模型介绍页、'
        'AI 作品与参数的效果对比图等都算"是"）。'
        '以下算"否"：真人自拍/生活照、与 AI 绘图无关的表情包、'
        '游戏/影视截图等无关内容、纯文字图。'
        '只输出 JSON：{"is_ai_image": true/false}'
    ),
}

# 类目 → 判定模式（未列出的类目不复核）
CATEGORY_MODES = {
    'positive_feedback': 'strict',
    'prompt_bound': 'strict',
    'params_discussion': 'related',
}

# 官方支持 JPEG/PNG/GIF/WebP（按内容判断），BMP 不支持 → 走 PIL 转 PNG 分支
_MIME_BY_EXT = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.webp': 'image/webp'}


def _image_data_url(image_path: Path) -> str | None:
    ext = Path(image_path).suffix.lower()
    mime = _MIME_BY_EXT.get(ext)
    if mime:
        try:
            raw = Path(image_path).read_bytes()
        except Exception:
            return None
        return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
    # BMP/GIF 等不在官方支持列表的格式：取首帧转 PNG（只转格式，不缩放）
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            rgb = img.convert('RGB')
            buffer = io.BytesIO()
            rgb.save(buffer, 'PNG')
        return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
    except Exception:
        return None


def judge_image(cfg: LLMConfig, image_path: Path, context_text: str = '',
                mode: str = 'strict') -> dict | None:
    """单图视觉判定；返回 {'is_ai_image': bool, 'tokens': int}，失败返回 None。

    mode='strict' 判"是否 AI 生成图像作品"（截图判否）；
    mode='related' 判"是否与 AI 绘图相关"（参数截图判是）。
    """
    data_url = _image_data_url(image_path)
    if data_url is None:
        return None
    context = (context_text or '')[:300]
    question = '这张图片是 AI 生成/绘制的图像吗？' if mode == 'strict' \
        else '这张图片与 AI 绘图/AI 生成图像相关吗？'
    user_text = question + (f'（上下文：{context}）' if context else '')
    payload = {
        'model': cfg.model,
        'messages': [
            {'role': 'system', 'content': _JUDGE_SYSTEMS.get(mode, _JUDGE_SYSTEMS['strict'])},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': user_text},
                {'type': 'image_url', 'image_url': {'url': data_url}},
            ]},
        ],
        'temperature': 0,
        'max_tokens': 512,
        # deepseek-flash 思考模式默认开启（effort=high）：思维链走 reasoning_content，
        # max_tokens 被思维链耗尽时 content 返回空串 → 判定丢失。简单视觉判定
        # 不需要推理，显式关闭（官方：thinking.type=disabled），也省掉思维链 token。
        'thinking': {'type': 'disabled'},
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {cfg.api_key}'},
        method='POST',
    )
    try:
        with netutil.open_url(req, timeout=180) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
        tokens = int((data.get('usage') or {}).get('total_tokens') or 0)
        cost_log['calls'] += 1
        cost_log['total_tokens'] += tokens
        # 容忍模型带 markdown 围栏输出
        start, end = content.find('{'), content.rfind('}')
        if start < 0 or end <= start:
            last_error.update(image=str(image_path), error=f'unparseable reply: {content[:200]!r}')
            return None
        verdict = json.loads(content[start:end + 1])
        return {'is_ai_image': bool(verdict.get('is_ai_image')), 'tokens': tokens}
    except Exception as exc:  # 失败必须留痕，否则批量跑批只看到 missing 无法排查
        body = b''
        read = getattr(exc, 'read', None)
        if callable(read):
            try:
                body = read() or b''
            except Exception:
                body = b''
        last_error.update(image=str(image_path),
                          error=f'{type(exc).__name__}: {exc} body={body[:300]!r}')
        return None


def recheck_batch(project_dir: str | Path, config, *, limit: int | None = None,
                  force: bool = False) -> dict:
    """复核一批未检查过的 02/03 图；返回 {'checked': n, 'demoted': m}。"""
    from .schedule import all_day_today, is_in_time_windows
    from datetime import datetime

    project_dir = Path(project_dir)
    if not getattr(config, 'vision_recheck_enabled', False) and not force:
        return {'checked': 0, 'demoted': 0, 'skipped': 'disabled'}
    if not force:
        now = datetime.now()
        window_ok = (all_day_today(config.ai_context_all_day_weekdays, now)
                     or is_in_time_windows(now, config.ai_context_allowed_windows))
        if not window_ok:
            return {'checked': 0, 'demoted': 0, 'skipped': 'outside_window'}

    cfg = LLMConfig.ds_fallback_from_env_file()
    if cfg is None or not cfg.api_key:
        return {'checked': 0, 'demoted': 0, 'skipped': 'no_llm_config'}

    from .store import Store
    store = Store(project_dir / 'data' / 'bot.db')
    batch = min(limit or config.vision_recheck_batch, 500)
    rows = store.vision_unchecked_images(categories=tuple(CATEGORY_MODES), limit=batch)
    checked = demoted = reused = 0
    # 内容级缓存：同 sha256 的图（转发/多群副本）只花一次钱，命中直接落行标记
    cached = store.vision_cached_verdicts([r[1] for r in rows])
    jobs: list[tuple[int, str, Path, str, str]] = []
    for image_id, sha256, kept_path, context, category in rows:
        path = Path(kept_path)
        if not path.exists():
            store.set_vision_verdict('missing', image_id)
            continue
        cached_verdict = cached.get(sha256)
        if cached_verdict:
            store.set_vision_verdict(cached_verdict, image_id, sha256=sha256)
            reused += 1
            if cached_verdict == 'not_ai':
                store.demote_image_to_candidate(image_id)
                demoted += 1
            continue
        jobs.append((image_id, sha256, path, context, CATEGORY_MODES.get(category, 'strict')))

    # 并行调用视觉模型（网络 IO 密集，线程池即可），写库在主线程串行完成
    def _judge(job: tuple[int, str, Path, str, str]):
        image_id, sha256, path, context, mode = job
        try:
            return (image_id, sha256, judge_image(cfg, path, context, mode=mode))
        except Exception as exc:
            print(f'vision recheck failed: {type(exc).__name__}: {exc}')
            return (image_id, sha256, None)

    if jobs:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
            results = list(pool.map(_judge, jobs))
    else:
        results = []

    for image_id, sha256, verdict in results:
        content_verdict = 'missing' if verdict is None else \
            ('ok' if verdict['is_ai_image'] else 'not_ai')
        store.set_vision_verdict(content_verdict, image_id,
                                 sha256=sha256 if content_verdict != 'missing' else None)
        if verdict is None:
            continue
        checked += 1
        if not verdict['is_ai_image']:
            store.demote_image_to_candidate(image_id)
            demoted += 1
    return {'checked': checked, 'demoted': demoted, 'cached': reused}

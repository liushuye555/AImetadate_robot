from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from .summary import extract_links

MODEL_EXTS = {'.safetensors', '.ckpt', '.pt', '.pth', '.bin', '.gguf', '.onnx', '.engine'}
ARCHIVE_EXTS = {'.zip', '.7z', '.rar', '.tar', '.gz', '.tgz'}
WORKFLOW_EXTS = {'.json', '.yaml', '.yml', '.toml'}


def classify_file(file_name: str) -> str:
    ext = Path(file_name or '').suffix.lower()
    if ext in MODEL_EXTS:
        return 'model'
    if ext in ARCHIVE_EXTS:
        return 'archive'
    if ext in WORKFLOW_EXTS:
        return 'workflow'
    return 'other'


def to_int(value) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def extract_file_segments(event: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    message = event.get('message')
    if isinstance(message, list):
        for seg in message:
            if seg.get('type') != 'file':
                continue
            data = seg.get('data') or {}
            name = data.get('name') or data.get('file') or data.get('file_name') or ''
            if not name:
                continue
            files.append({
                'file_name': str(name),
                'file_size': to_int(data.get('size') or data.get('file_size')),
                'url': data.get('url') or data.get('file_url'),
                'kind': classify_file(str(name)),
            })
    # NapCat may also emit group upload notices; preserve minimal metadata.
    if event.get('post_type') == 'notice' and event.get('notice_type') in {'group_upload', 'offline_file'}:
        file_info = event.get('file') or {}
        name = file_info.get('name') or file_info.get('file_name') or file_info.get('id') or ''
        if name:
            files.append({
                'file_name': str(name),
                'file_size': to_int(file_info.get('size') or file_info.get('file_size')),
                'url': file_info.get('url'),
                'kind': classify_file(str(name)),
            })
    return files


def classify_link(url: str, context: str = '') -> str:
    host = urlparse(url).netloc.lower()
    text = (context or '').lower()
    if host_matches(host, ('civitai.com',)):
        return 'civitai_model'
    if host_matches(host, ('github.com',)):
        return 'github_project'
    if host_matches(host, ('huggingface.co',)):
        return 'huggingface_model'
    if host_matches(host, CLOUD_DRIVE_HOST_HINTS):
        return 'cloud_drive'
    if any(k in text for k in ['教程', '参考', '文档', 'guide', 'tutorial']):
        return 'tutorial_or_reference'
    if any(k in text for k in ['lora', '模型', 'checkpoint', '工作流', 'workflow', '节点']):
        return 'ai_resource'
    return 'link'


DIRECT_IMAGE_SUFFIXES = {'.avif', '.bmp', '.gif', '.jpeg', '.jpg', '.png', '.svg', '.webp'}
DIRECT_IMAGE_HOSTS = {
    'i.imgur.com', 'images.unsplash.com', 'pbs.twimg.com', 'cdn.discordapp.com',
    'media.discordapp.net', 'image.civitai.com', 'postimg.cc', 'postimages.org',
}
SHORT_LINK_HOSTS = {
    'b23.tv', 'xhslink.com', 'xhslink.cn', 'm.tb.cn', 's.click.taobao.com',
}
CLOUD_DRIVE_HOST_HINTS = (
    'pan.baidu.com', 'aliyundrive', 'alipan', '115.com', '123pan', 'lanzou',
    'pan.quark.cn', 'drive.google.com',
)


WORKFLOW_HOSTS = ('tusi.cn', 'runninghub.ai', 'runninghub.cn')


def host_matches(host: str, domains: tuple[str, ...] | set[str]) -> bool:
    """Match an exact domain or one of its subdomains, never a lookalike substring."""
    host = str(host or '').lower().removeprefix('www.')
    return any(host == domain.removeprefix('www.') or host.endswith('.' + domain.removeprefix('www.')) for domain in domains)


def is_direct_image_link(url: str) -> bool:
    parsed = urlparse(str(url or ''))
    host = (parsed.hostname or '').lower()
    suffix = Path(parsed.path or '').suffix.lower()
    return suffix in DIRECT_IMAGE_SUFFIXES or host_matches(host, DIRECT_IMAGE_HOSTS)


def is_unresolved_short_link(url: str) -> bool:
    host = (urlparse(str(url or '')).hostname or '').lower().removeprefix('www.')
    return host in SHORT_LINK_HOSTS


def nearest_link_context(url: str, context: str, *, limit: int = 240) -> str:
    """Prefer the text around this URL, so one message's model keywords do not leak to every link."""
    value = str(context or '').strip()
    if not value:
        return ''
    candidates = [str(url or '').strip()]
    parsed = urlparse(str(url or ''))
    if parsed.netloc:
        candidates.append(parsed.netloc)
    lower = value.lower()
    for candidate in candidates:
        candidate = candidate.lower()
        if not candidate:
            continue
        index = lower.find(candidate)
        if index >= 0:
            start = max(0, index - limit // 2)
            end = min(len(value), index + len(candidate) + limit // 2)
            return value[start:end].strip()
    return value[:limit].strip()


def is_local_link(url: str) -> bool:
    """本地/内网链接：localhost、127.x、10.x、172.16-31.x、192.168.x、file:// —— 他人无法访问。"""
    if str(url or '').lower().startswith('file://'):
        return True
    host = (urlparse(str(url or '')).hostname or '').lower()
    if not host:
        return False
    if host in {'localhost', '127.0.0.1', '::1', '0.0.0.0'}:
        return True
    parts = host.split('.')
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b, _, _ = (int(p) for p in parts)
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
    return False


VIDEO_HOSTS = {
    'bilibili.com', 'www.bilibili.com', 'youtube.com', 'www.youtube.com', 'youtu.be',
    'youku.com', 'www.youku.com', 'iqiyi.com', 'www.iqiyi.com', 'douyin.com', 'www.douyin.com',
    'kuaishou.com', 'www.kuaishou.com', 'v.kuaishou.com',
}
IMAGE_HOSTS = {
    'pixiv.net', 'www.pixiv.net', 'danbooru.donmai.us', 'yande.re', 'konachan.com',
    'gelbooru.com', 'sankakucomplex.com', 'zerochan.net', 'x.com', 'twitter.com',
}
MUSIC_HOSTS = {
    'music.163.com', 'y.qq.com', 'open.spotify.com', 'music.apple.com', 'kugou.com',
    'weishi.qq.com',
}
TUTORIAL_HINTS = ['教程', '教学', 'tutorial', 'guide', '学习', '安装', '部署', '使用方法', '入门']
NAV_HINTS = ['导航', '收藏夹', '大全', '合集', '入口', '资源站', '目录']
MODEL_HINTS = ['lora', 'ckpt', '模型', 'checkpoint', 'safetensors', '底模', '大模型']
WORKFLOW_HINTS = ['workflow', '工作流', '节点', '流程图']
TOOL_HINTS = ['插件', '脚本', '扩展', '工具', 'comfyui-manager']
ONLINE_HINTS = ['api', 'demo', '在线', '试用', '接口']
DATASET_HINTS = ['数据集', 'dataset', '训练集', 'tag集']
NEWS_HINTS = ['新闻', '资讯', '快讯', '报道']
AI_VIDEO_HINTS = ['comfyui', 'minimax', 'deepseek', 'seedance', 'sora', 'kling', '可灵', 'lora', '模型', 'workflow', '工作流', '节点', '提示词', 'agent', '大模型', '显存', 'gpu', '开源']
VIDEO_TUTORIAL_HINTS = ['教程', '教学', 'tutorial', 'guide', '安装', '部署', '使用方法', '入门', '工作流', '提示词', '节点', '实测', '合集', '配置']
MUSIC_VIDEO_HINTS = ['音乐', '单曲', '歌单', ' mv', 'mv ', '翻唱', '演唱', 'remix', '伴奏', 'live']
RELAY_HINTS = ['中转', '转发', '反代', '公益站', '额度', '倍率', '渠道']
COMMUNITY_HOSTS = ('linux.do', 'v2ex.com', 'reddit.com', 'tieba.baidu.com', 'forum.koishi.xyz')
SHOWCASE_HOSTS = ('civitai.com', 'civitai.red', 'tensor.art', 'seaart.ai', 'pixai.art')
SHOWCASE_PATH_HINTS = ('/images/', '/image/', '/artwork/', '/posts/', '/post/', '/u/', '/user/')


def link_category(url: str, context: str = '') -> str:
    """Classify a resource link from its destination plus its own nearby context."""
    parsed = urlparse(str(url or ''))
    host = (parsed.hostname or '').lower()
    path = parsed.path.lower()
    text = (context or '').lower()
    # Delivery channels and known resource pages are more reliable than nearby words.
    if host_matches(host, CLOUD_DRIVE_HOST_HINTS):
        return '网盘资源'
    if host_matches(host, ('tensor.art',)) and not path:
        return 'AI作品展示'
    if host_matches(host, SHOWCASE_HOSTS) and any(hint in path for hint in SHOWCASE_PATH_HINTS):
        return 'AI作品展示'
    if host_matches(host, ('tensor.art', 'seaart.ai')) and '/models/' in path:
        return 'AI模型'
    if host_matches(host, ('huggingface.co',)) and '/spaces/' in path:
        return 'AI在线服务'
    if host_matches(host, ('modelscope.cn',)) and '/studios/' in path:
        return 'AI在线服务'
    if host_matches(host, ('civitai.com', 'huggingface.co', 'modelscope.cn', 'civitai.red')):
        return 'AI模型'
    if host_matches(host, ('tusi.cn',)) and '/models/' in path:
        return 'AI模型'
    if host_matches(host, ('tusi.cn',)) and '/images/' in path:
        return '图片'
    if (host_matches(host, WORKFLOW_HOSTS) or host.removeprefix('www.') == 'comfy.org') and 'workflow' in path:
        return 'AI工作流'
    if host_matches(host, ('runninghub.ai', 'runninghub.cn')) and '/ai-detail/' in path:
        return 'AI在线服务'
    if host_matches(host, ('docs.comfy.org',)):
        return '教程'
    if host_matches(host, ('comfy.org',)) and (not path or path.endswith('/download')):
        return 'AI工具插件'
    if '/news/' in path:
        return '新闻'
    if host_matches(host, VIDEO_HOSTS):
        # Video-specific rules deliberately omit generic words such as "学习" to avoid classifying chatter as a tutorial.
        if any(x in text for x in MUSIC_VIDEO_HINTS):
            return '音乐视频'
        if any(x in text for x in VIDEO_TUTORIAL_HINTS):
            return 'AI教程视频'
        if any(x in text for x in AI_VIDEO_HINTS):
            return 'AI资讯视频'
        return '娱乐视频'
    if any(x in text for x in TUTORIAL_HINTS):
        return '教程'
    if host_matches(host, COMMUNITY_HOSTS):
        return '技术社区'
    if (host.startswith('api.') or 'api' in text) and any(x in text for x in RELAY_HINTS):
        return 'AI中转服务'
    if host_matches(host, ('pixai.art',)):
        return 'AI在线服务'
    # A GitHub URL points at code even when the adjacent text mentions a model.
    if host_matches(host, ('github.com',)) or any(x in text for x in TOOL_HINTS):
        return 'AI工具插件'
    if any(x in text for x in WORKFLOW_HINTS):
        return 'AI工作流'
    if any(x in text for x in MODEL_HINTS):
        return 'AI模型'
    if any(x in text for x in ONLINE_HINTS):
        return 'AI在线服务'
    if any(x in text for x in DATASET_HINTS):
        return 'AI数据集'
    if is_direct_image_link(url) or host_matches(host, IMAGE_HOSTS):
        return '图片'
    if host_matches(host, MUSIC_HOSTS):
        return '音乐'
    if any(x in text for x in NAV_HINTS):
        return '导航'
    if any(x in text for x in NEWS_HINTS):
        return '新闻'
    return '其他'

def site_key(host: str) -> str:
    """站点记忆的域名键：小写并去掉 www. 前缀。"""
    return str(host or '').lower().removeprefix('www.')


def domain_profiles(store, *, limit: int = 10000) -> dict[str, dict[str, int]]:
    """域名多功能画像：{域名: {功能分类: 次数}}，来自历史链接分类（含标题/描述上下文）。"""
    from .daily_report import dedupe_url_key

    metadata = store.link_metadata_map()
    profiles: dict[str, dict[str, int]] = {}
    for row in store.recent_link_rows(limit=limit):
        url = str(row.get('url') or '')
        host = site_key(urlparse(url).netloc)
        if not host or is_local_link(url):
            continue
        context = nearest_link_context(url, str(row.get('message_text') or row.get('quoted_text') or ''))
        title, desc = metadata.get(dedupe_url_key(url), ('', ''))
        category = link_category(url, f'{context} {title} {desc}'.strip())
        profile = profiles.setdefault(host, {})
        profile[category] = profile.get(category, 0) + 1
    return profiles


def deterministic_category(
    profile: dict[str, int] | None,
    *,
    min_count: int = 2,
    min_share: float = 0.67,
) -> str | None:
    """站点记忆：主功能占比足够高且不是"其他/娱乐视频" → 判定站点功能确定；否则混合站点。"""
    if not profile:
        return None
    total = sum(profile.values())
    if total < int(min_count):
        return None
    top, count = max(profile.items(), key=lambda kv: kv[1])
    if top in {'其他', '娱乐视频'} or count / total < min_share:
        return None
    return top


def extract_resource_links(text: str) -> list[dict[str, str]]:
    return [{'url': url, 'kind': classify_link(url, text)} for url in extract_links(text)]

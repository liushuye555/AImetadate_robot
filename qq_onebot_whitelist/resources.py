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
    if 'civitai.com' in host:
        return 'civitai_model'
    if 'github.com' in host:
        return 'github_project'
    if 'huggingface.co' in host:
        return 'huggingface_model'
    if any(x in host for x in ['pan.baidu.com', 'aliyundrive', 'alipan', '115.com', '123pan', 'lanzou']):
        return 'cloud_drive'
    if any(k in text for k in ['教程', '参考', '文档', 'guide', 'tutorial']):
        return 'tutorial_or_reference'
    if any(k in text for k in ['lora', '模型', 'checkpoint', '工作流', 'workflow', '节点']):
        return 'ai_resource'
    return 'link'


def is_local_link(url: str) -> bool:
    """本地/内网链接：localhost、127.x、10.x、172.16-31.x、192.168.x、file:// —— 他人无法访问。"""
    host = urlparse(url).netloc.lower().split(':')[0]
    if not host:
        return False
    if host in {'localhost', '127.0.0.1', '::1', '0.0.0.0'}:
        return True
    if url.lower().startswith('file://'):
        return True
    parts = host.split('.')
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b, c, d = (int(p) for p in parts)
        if a == 10:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 192 and b == 168:
            return True
    return False


VIDEO_HOSTS = {
    'bilibili.com', 'www.bilibili.com', 'youtube.com', 'www.youtube.com', 'youtu.be',
    'youku.com', 'www.youku.com', 'iqiyi.com', 'www.iqiyi.com', 'douyin.com', 'www.douyin.com',
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
ONLINE_HINTS = ['api', 'demo', '在线', '试用', '测试', '接口']
DATASET_HINTS = ['数据集', 'dataset', '训练集', 'tag集']
NEWS_HINTS = ['新闻', '资讯', '快讯', '报道']


def link_category(url: str, context: str = '') -> str:
    """链接类型：AI模型/AI工作流/AI工具插件/AI在线服务/AI数据集/教程/教程视频/图片/音乐/导航/娱乐视频/新闻/其他。"""
    host = urlparse(url).netloc.lower()
    text = (context or '').lower()
    if any(x in host for x in ['civitai.com', 'huggingface.co', 'modelscope.cn',
                               'pan.baidu.com', 'aliyundrive', 'alipan', '115.com', '123pan', 'lanzou']) \
            or any(x in text for x in MODEL_HINTS):
        return 'AI模型'
    if any(x in text for x in WORKFLOW_HINTS):
        return 'AI工作流'
    if 'github.com' in host or any(x in text for x in TOOL_HINTS):
        return 'AI工具插件'
    if any(x in text for x in ONLINE_HINTS):
        return 'AI在线服务'
    if any(x in text for x in DATASET_HINTS):
        return 'AI数据集'
    if any(x in text for x in TUTORIAL_HINTS):
        return '教程视频' if any(h in host for h in VIDEO_HOSTS) else '教程'
    if any(h in host for h in VIDEO_HOSTS):
        return '娱乐视频'
    if any(h in host for h in IMAGE_HOSTS):
        return '图片'
    if any(h in host for h in MUSIC_HOSTS):
        return '音乐'
    if any(x in text for x in NAV_HINTS):
        return '导航'
    if any(x in text for x in NEWS_HINTS):
        return '新闻'
    return '其他'


def extract_resource_links(text: str) -> list[dict[str, str]]:
    return [{'url': url, 'kind': classify_link(url, text)} for url in extract_links(text)]

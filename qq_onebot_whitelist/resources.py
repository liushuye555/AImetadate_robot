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


def extract_resource_links(text: str) -> list[dict[str, str]]:
    return [{'url': url, 'kind': classify_link(url, text)} for url in extract_links(text)]

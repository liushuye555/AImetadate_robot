from __future__ import annotations

import re
import json
from urllib.parse import urlparse


SECRET_PATTERNS = [
    re.compile(r'(?i)\b(?:sk-[a-z0-9_-]{12,}|wb-[a-f0-9]{64})\b'),
    re.compile(r'(?i)\b(bearer\s+)[a-z0-9._~+/=-]{16,}'),
    re.compile(r'(?i)((?:["\']?(?:api[_-]?key|access[_-]?token|secret|password|passwd|pwd)["\']?)\s*[:=]\s*)(["\']?)[^\s"\'&]{8,}'),
]


def redact_secrets(text: str) -> str:
    value = str(text or '')
    value = SECRET_PATTERNS[0].sub('[已脱敏密钥]', value)
    value = SECRET_PATTERNS[1].sub(r'\1[已脱敏]', value)
    value = SECRET_PATTERNS[2].sub(r'\1\2[已脱敏]', value)
    return value


def redacted_json(value) -> str:
    """Redact values before encoding, so escaped quotes cannot break JSON."""
    sensitive = {'api_key', 'api-key', 'apikey', 'access_token', 'access-token',
                 'accesstoken', 'secret', 'password', 'passwd', 'pwd'}
    def clean(node):
        if isinstance(node, str):
            return redact_secrets(node)
        if isinstance(node, dict):
            return {key: '[已脱敏]' if str(key).casefold() in sensitive else clean(child)
                    for key, child in node.items()}
        if isinstance(node, (list, tuple)):
            return [clean(child) for child in node]
        return node
    return json.dumps(clean(value), ensure_ascii=False)


def compact_text(text: str, limit: int = 160) -> str:
    value = ' '.join(redact_secrets(text).split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + '…'


def resource_context(text: str, url: str = '', limit: int = 160) -> str:
    value = redact_secrets(text)
    if url:
        value = value.replace(url, ' ')
    value = re.sub(r'https?://\S+', ' ', value)
    value = re.sub(r'(?i)点击链接(?:直接)?打开[^，。；;]*', ' ', value)
    value = re.sub(r'(?i)复制.*?打开[^，。；;]*', ' ', value)
    return compact_text(value, limit=limit)


def fallback_link_description(url: str, purpose: str) -> str:
    return '群聊未说明用途。'


def file_description(file_name: str, kind: str) -> str:
    labels = {
        'workflow': '可导入或检查的工作流配置',
        'model': '模型权重文件',
        'archive': '资源压缩包',
    }
    return labels.get(kind, '群内分享文件') + '。'

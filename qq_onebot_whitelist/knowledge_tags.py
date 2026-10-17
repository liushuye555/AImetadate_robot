"""Source-backed semantic topic labels, independent of entity identification."""
from __future__ import annotations

import re
import unicodedata

from .content_utils import redact_secrets


VERSION = 1
PREFERRED_TAGS = ('虚拟卡', '账号交易', '钓鱼与账号安全', '账号注册与登录', '邮箱', '支付与充值',
                  '订阅与额度', 'API接入', '接口中转', '网络与代理', '云服务器', '硬件配置',
                  '软件安装与部署', '代码开发', '逆向分析', '破甲工具', '模型选择与对比', '服务状态', '资料与教程')
SYSTEM = '''每条知识另给organization.topic_tags，最多4个资料主题{name,evidence:[{message_id,quote}]}。
对象身份和资料主题分别判断。可以确认讨论虚拟卡、邮箱、账号交易、钓鱼风险或硬件，即使无法确认具体平台/商家/服务。不得因此把这些资料全部放到其他或对象待确认。
标签是简短名词主题，可参考preferred_tags、已有tag_catalog，也可以创建原文确实支持的新主题；不是只能用预置标签。不要把“中国不行/成功/需要人脸”等具体反馈作为标签。
主题名不必逐字出现在原文，例如“虚拟visa卡”可归入虚拟卡，“骗账号凭证”可归入钓鱼与账号安全；每项仍必须有本条证据消息的连续精确引文支持。不得引用标题、整理正文、互联网背景或别人的条目作为当前事实证据。
主题只是资料检索分类，不是词义条目，不改变当前对象指代、解决状态或事实验证。只有笼统的“这个/那个/不行”且没有资料主题依据时才返回topic_tags:[]。'''


def canonical_tag(value):
    if not isinstance(value, str):
        return ''
    name = unicodedata.normalize('NFKC', redact_secrets(value)).strip()
    aliases = {'虚拟Visa卡': '虚拟卡', '虚拟visa卡': '虚拟卡', '虚拟信用卡': '虚拟卡',
               '账号买卖': '账号交易', '账号钓鱼': '钓鱼与账号安全', '钓鱼诈骗': '钓鱼与账号安全',
               '邮箱服务': '邮箱', 'API调用': 'API接入', 'API 中转': '接口中转'}
    name = aliases.get(name, name)
    if (not 2 <= len(name) <= 24 or not re.fullmatch(r'[\w\u4e00-\u9fff /·+.-]+', name)
            or name in ('其他', '未知', '未分类', '对象待确认', '待确认', '通用讨论', '群聊', '聊天')):
        return ''
    return name


def prepare_topic_tags(raw, item, records):
    if not isinstance(raw, list):
        return []
    allowed = set(item.get('evidence_ids', []))
    sources = {}
    for record in records:
        if record.get('id') in allowed:
            sources.setdefault(record['id'], []).append(str(record.get('text') or ''))
            sources[record['id']].extend(str(file['preview'].get('text') or '') for file in record.get('files', [])
                if isinstance(file, dict) and isinstance(file.get('preview'), dict))
            sources[record['id']].extend(str(file.get('file_name') or '') for file in record.get('files', []) if isinstance(file, dict))
        if record.get('quoted_id') in allowed:
            sources.setdefault(record['quoted_id'], []).append(str(record.get('quoted_text') or ''))
    result = {}
    for entry in raw[:8]:
        name = canonical_tag(entry.get('name')) if isinstance(entry, dict) else ''
        if not name or not isinstance(entry.get('evidence'), list):
            continue
        for evidence in entry['evidence'][:4]:
            if not isinstance(evidence, dict):
                continue
            mid, quote = evidence.get('message_id'), evidence.get('quote')
            if type(mid) is not int or not isinstance(quote, str) or not quote.strip() or len(quote) > 500:
                continue
            quote = quote.strip()
            if not any(quote in text for text in sources.get(mid, [])):
                continue
            tag = result.setdefault(name, {'name': name, 'origin': 'ai', 'evidence': []})
            cleaned = {'message_id': mid, 'quote': redact_secrets(quote)}
            if any(record.get('id') == mid and any(isinstance(file, dict) and quote in str(file.get('file_name') or '')
                   for file in record.get('files', [])) for record in records):
                cleaned['source_field'] = 'file_name'
            if cleaned not in tag['evidence']:
                tag['evidence'].append(cleaned)
    return list(result.values())[:4]


def topic_tags_for(row):
    organization = row.get('organization') if isinstance(row.get('organization'), dict) else {}
    values = organization.get('topic_tags')
    return list(dict.fromkeys(name for entry in values if isinstance(entry, dict) and entry.get('evidence')
                             for name in [canonical_tag(entry.get('name'))] if name)) if isinstance(values, list) else []

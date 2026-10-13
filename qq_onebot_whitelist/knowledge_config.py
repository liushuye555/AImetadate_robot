"""Explicit opt-in for each group and feature; preferences never enable work."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re


FEATURES = ('summary', 'extraction', 'glossary', 'files', 'history')


def group_scope(value: str) -> str:
    value = str(value).removeprefix('group:')
    if not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError('需要有效的群号')
    return 'group:' + value


def _merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


@dataclass
class GroupProfile:
    scope: str
    global_enabled: bool
    group_enabled: bool
    settings: dict
    explicit: dict

    def allows(self, feature: str) -> bool:
        section = self.explicit.get(feature)
        return (self.global_enabled and self.group_enabled and feature in FEATURES
                and isinstance(section, dict) and section.get('enabled') is True)

    def number(self, key: str, default: int, lower: int, upper: int) -> int:
        value = self.settings.get(key, default)
        if isinstance(value, bool):
            raise ValueError(f'{key} 必须是数字')
        try:
            value = int(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f'{key} 必须是数字') from exc
        if not lower <= value <= upper:
            raise ValueError(f'{key} 超出范围 {lower}—{upper}')
        return value


def profile_for(config, scope: str) -> GroupProfile:
    scope = group_scope(scope)
    raw = config.knowledge
    defaults = raw.get('defaults') or {}
    groups = raw.get('groups') or {}
    explicit = groups.get(scope) or {}
    if not isinstance(defaults, dict) or not isinstance(groups, dict) or not isinstance(explicit, dict):
        raise ValueError('knowledge.defaults/groups 必须是配置对象')
    settings = _merge(defaults, explicit)
    mode = settings.get('match_mode', 'hybrid')
    if mode not in ('specialist', 'generic', 'hybrid'):
        raise ValueError('match_mode 必须为 specialist/generic/hybrid')
    topics = settings.get('topics', [])
    if not isinstance(topics, list) or not all(isinstance(v, str) for v in topics):
        raise ValueError('topics 必须是主题名称列表')
    return GroupProfile(scope, raw.get('enabled') is True,
                        explicit.get('enabled') is True and scope.split(':')[1] not in config.blocked_groups,
                        settings, explicit)


def enabled_profiles(config) -> list[GroupProfile]:
    if config.knowledge.get('enabled') is not True:
        return []
    groups = config.knowledge.get('groups') or {}
    if not isinstance(groups, dict):
        raise ValueError('knowledge.groups 必须是配置对象')
    return [p for scope in groups if (p := profile_for(config, scope)).group_enabled]

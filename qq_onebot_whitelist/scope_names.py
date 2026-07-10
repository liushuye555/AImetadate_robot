from __future__ import annotations


def display_scope(scope: str, group_names: dict[str, str] | None = None) -> str:
    group_names = group_names or {}
    if scope.startswith('group:'):
        group_id = scope.split(':', 1)[1]
        name = group_names.get(group_id) or group_names.get(scope)
        if name:
            return f'{name}（{group_id}）'
    return scope

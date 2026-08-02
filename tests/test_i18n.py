from qq_onebot_whitelist.i18n import effective_language, normalize_language, text


def test_language_normalization_and_fallback():
    assert normalize_language('zh_CN') == 'zh-CN'
    assert normalize_language('en_GB') == 'en-US'
    assert normalize_language('ja-JP') is None
    assert text('help_title', 'en-US').startswith('Administrator')
    assert text('help_title', 'zh-CN').startswith('管理员')


def test_config_bridge_preserves_unknown_fields(tmp_path):
    from qq_onebot_whitelist.config_bridge import patch_config

    path = tmp_path / 'config.yaml'
    path.write_text('custom:\n  keep: true\nui:\n  language: auto\n', encoding='utf-8')
    result = patch_config(path, {'ui': {'language': 'en-US'}})
    assert result['custom']['keep'] is True
    assert result['ui']['language'] == 'en-US'

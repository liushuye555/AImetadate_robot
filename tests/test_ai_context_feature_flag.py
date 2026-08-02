from qq_onebot_whitelist.ai_context_analyze import analyze_scope


def test_manual_ai_analysis_honors_feature_flag(tmp_path, capsys):
    path = tmp_path / 'config.yaml'
    path.write_text('features:\n  ai_context: false\n', encoding='utf-8')

    assert analyze_scope(str(path), scope=None) == 0
    assert 'disabled' in capsys.readouterr().out

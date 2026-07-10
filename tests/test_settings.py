from qq_onebot_whitelist.settings import read_analysis_windows, write_analysis_windows


def test_write_analysis_windows_preserves_other_config(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('reply:\n  whitelist_users: ["1"]\nai_context:\n  enabled: true\n', encoding='utf-8')

    write_analysis_windows(path, ['00:30-08:30', '12:00-13:00'])

    assert read_analysis_windows(path) == ['00:30-08:30', '12:00-13:00']
    text = path.read_text(encoding='utf-8')
    assert 'whitelist_users' in text
    assert 'enabled: true' in text


def test_write_analysis_windows_supports_all_day(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('{}\n', encoding='utf-8')

    write_analysis_windows(path, [])

    assert read_analysis_windows(path) == []


def test_invalid_windows_do_not_change_config(tmp_path):
    path = tmp_path / 'config.yaml'
    original = 'ai_context:\n  allowed_windows: []\n'
    path.write_text(original, encoding='utf-8')

    try:
        write_analysis_windows(path, ['25:00-26:00'])
    except ValueError:
        pass

    assert path.read_text(encoding='utf-8') == original


def test_get_cli_can_emit_json_for_windows_tray(tmp_path, capsys, monkeypatch):
    from qq_onebot_whitelist.settings import main

    path = tmp_path / 'config.yaml'
    path.write_text('ai_context:\n  allowed_windows: []\n', encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['settings', '--config', str(path), '--get', '--json'])

    assert main() == 0
    assert capsys.readouterr().out.strip() == '[]'

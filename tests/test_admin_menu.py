from qq_onebot_whitelist.commands import HELP_TEXT


def test_help_text_has_admin_menu_and_local_pages():
    assert '管理员菜单' in HELP_TEXT
    assert '刷新分类' in HELP_TEXT
    assert '本地入口' in HELP_TEXT
    assert 'resources.html' in HELP_TEXT
    assert 'files.html' in HELP_TEXT

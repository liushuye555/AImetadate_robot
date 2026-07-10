from qq_onebot_whitelist.daily_report import split_message


def test_split_message_chunks_long_text():
    text = 'a' * 2500
    chunks = split_message(text, max_chars=1000)
    assert [len(x) for x in chunks] == [1000, 1000, 500]


def test_split_message_keeps_short_text():
    assert split_message('hello', max_chars=1000) == ['hello']

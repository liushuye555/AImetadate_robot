"""提示词/参数消息识别与图片绑定测试。"""

import re
from qq_onebot_whitelist.prompt_binding import is_prompt_message, is_params_message


def test_is_prompt_message_recognizes_real_prompts():
    assert is_prompt_message("/绘图 文生图 1girl, solo")
    assert is_prompt_message("1girl, solo, cat girl, blonde hair")
    assert is_prompt_message("prompt: 1girl, best quality")
    assert is_prompt_message("图生图 一个女孩坐在椅子上")


def test_is_prompt_message_rejects_false_positives():
    assert not is_prompt_message("我不写提示词")
    assert not is_prompt_message("提示词是什么")
    assert not is_prompt_message("fp8下好了，测测fp8")
    assert not is_prompt_message("4090 48g")


def test_is_params_message_detects_param_talk():
    assert is_params_message("低噪重绘效果没原来好")
    assert is_params_message("这模型用什么sampler跑的")
    assert is_params_message("4090 48g 出图快")


from qq_onebot_whitelist.prompt_binding import bind_prompt_for_image


def test_temporal_binding_uses_last_prompt_in_window():
    records = [
        {"text": "随便聊聊"},
        {"text": "/绘图 文生图 A girl", "id": 10},
        {"text": "真好看"},
        {"text": "1girl, solo, cat ears", "id": 12},
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind == "prompt"
    assert prompt == "1girl, solo, cat ears"


def test_quote_binding_image_quotes_prompt():
    records = [
        {"text": "/绘图 文生图 fox girl", "id": 20},
        {"text": "", "reply_to_message_id": "20", "quoted_text": "/绘图 文生图 fox girl"},
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to="20")
    assert kind == "prompt"
    assert "fox girl" in prompt


def test_quote_binding_text_quotes_image():
    # 图片消息 id=30；其后的文本引用 30 且含提示词 → 绑定该文本
    records = [
        {"text": "1girl, solo", "id": 31, "reply_to_message_id": "30", "quoted_text": ""},
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to=None, own_message_id="30")
    assert kind == "prompt"
    assert prompt == "1girl, solo"


def test_no_prompt_falls_through():
    records = [{"text": "这图好看"}, {"text": "fp8 出图快"}]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind == "params"
    assert prompt == ""


def test_no_signal_returns_none():
    records = [{"text": "吃饭了吗"}, {"text": "哈哈"}]
    assert bind_prompt_for_image(records, reply_to=None) == (None, "")

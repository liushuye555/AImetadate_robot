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

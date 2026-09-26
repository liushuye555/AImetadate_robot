"""提示词/参数消息识别与图片绑定测试。"""

import re
from qq_onebot_whitelist.prompt_binding import is_prompt_message, is_params_message


def test_is_prompt_message_recognizes_real_prompts():
    assert is_prompt_message("/绘图 文生图 1girl, solo")
    assert is_prompt_message("1girl, solo, cat girl, blonde hair")
    assert is_prompt_message("prompt: 1girl, best quality")
    assert is_prompt_message("图生图 一个女孩坐在椅子上")
    assert is_prompt_message("/绘图 模型 Anima_latent_sharp")
    assert is_prompt_message("/绘图 文生图 1girl, solo")
    # 成块 tag（≥6 逗号、无句读）即使没有已知标签词也是提示词形状
    assert is_prompt_message("soft focus, blurry, dreamy atmosphere, romantic, hazy, misty, ethereal")
    # <lora:...> 标签语法是强证据
    assert is_prompt_message("<lora: mille:0.8>, 1girl")


def test_is_prompt_message_rejects_false_positives():
    assert not is_prompt_message("我不写提示词")
    assert not is_prompt_message("提示词是什么")
    assert not is_prompt_message("fp8下好了，测测fp8")
    assert not is_prompt_message("4090 48g")
    assert not is_prompt_message("/绘图 模型")
    assert not is_prompt_message("/绘图 状态")
    assert not is_prompt_message("/绘图 文生图")
    assert not is_prompt_message("1girl")
    assert not is_prompt_message("1girl 好可爱")
    # 裸工具词闲聊（历史数据：占提示词误绑的 44%）不再算提示词
    assert not is_prompt_message("这个LoRA不稳定")
    assert not is_prompt_message("邦多利的lora好少")
    assert not is_prompt_message("应该是lora没炼熟")
    assert not is_prompt_message("转头Comfyui吧")
    assert not is_prompt_message("fp16+4步加速lora，出得飞快，一采10s视频耗时4分钟")
    # 提到模型名（sdxl/flux/novelai）不算提示词
    assert not is_prompt_message("novelai最近出新模型了")


def test_is_params_message_detects_param_talk():
    assert is_params_message("低噪重绘效果没原来好")          # 具体词
    assert is_params_message("这模型用什么sampler跑的")       # 具体词
    assert is_params_message("超长图适合设置多少分辨率？")    # 泛化词+疑问
    assert is_params_message("换了个模型放大吗")              # 泛化词+疑问
    assert is_params_message("anima的二采一般是整体跑完了再跑一遍吧")  # 具体词
    assert is_params_message("我这xl模型，横向分辨率，手100%出六指")   # 两个泛化词


def test_is_params_message_rejects_generic_chat():
    # 单个泛化词、无疑问语气的闲聊（历史数据 62% 的参数词命中属于这类）
    assert not is_params_message("4090 48g")
    assert not is_params_message("我搜不到这个模型")
    assert not is_params_message("还有神秘显存不满就吃内存")
    assert not is_params_message("自出图炼")
    assert not is_params_message("一次性生成好可比xl微调+人类画师修方便多了")
    assert not is_params_message("Grok 正在用 grok-imagine-image-2.0 生成 1 张图，请稍候...")


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


def test_own_text_binding_prompt_with_image_same_message():
    # "来一张这个:1girl, solo..." 和图同条发送：own_text 优先绑定
    records = [{"text": "之前的聊天", "id": 5}]
    kind, prompt = bind_prompt_for_image(
        records, reply_to=None, own_text="来一张这个 1girl, solo, white hair, blue eyes")
    assert kind == "prompt"
    assert "1girl" in prompt


def test_own_text_non_prompt_falls_through():
    records = [{"text": "1girl, solo, cat ears", "id": 10}]
    kind, prompt = bind_prompt_for_image(records, reply_to=None, own_text="看看这张")
    assert kind == "prompt"  # 回退到时序绑定前一条


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
    records = [{"text": "这图好看"}, {"text": "低噪重绘效果没原来好"}]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind == "params"
    assert prompt == ""


def test_no_signal_returns_none():
    records = [{"text": "吃饭了吗"}, {"text": "哈哈"}]
    assert bind_prompt_for_image(records, reply_to=None) == (None, "")


def test_temporal_binding_breaks_when_interleaved():
    records = [
        {"text": "/绘图 文生图 fox girl", "id": 10},
        {"text": "真好看", "id": 11},
        {"text": ""},  # 图片消息（空文本）
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind != 'prompt'


def test_temporal_binding_requires_immediate_predecessor():
    records = [
        {"text": "/绘图 文生图 fox girl", "id": 10},
        {"text": ""},  # 图片消息
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind == 'prompt'
    assert 'fox girl' in prompt

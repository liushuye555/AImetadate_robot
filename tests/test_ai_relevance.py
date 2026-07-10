from qq_onebot_whitelist.ai_relevance import is_ai_relevant_text, is_positive_feedback_text
from qq_onebot_whitelist.image_policy import should_keep_image
from qq_onebot_whitelist.image_meta import ImageMetadata


def test_ai_relevant_text_detects_prompt_and_generation_terms():
    assert is_ai_relevant_text('prompt: 1girl, white hair, cinematic lighting')
    assert is_ai_relevant_text('这个用comfyui放大模型节点会不会炸')
    assert is_ai_relevant_text('SDXL lora cfg steps sampler 都是多少')
    assert not is_ai_relevant_text('今天晚上吃什么')


def test_positive_feedback_detects_good_image_reactions():
    assert is_positive_feedback_text('这张太神了，求提示词')
    assert is_positive_feedback_text('好看，出图质量很高')
    assert not is_positive_feedback_text('好的收到')


def test_plain_image_kept_when_nearby_prompt_or_positive_feedback():
    meta = ImageMetadata(format='PNG', width=100, height=100, has_ai_metadata=False)

    keep_prompt, reason_prompt = should_keep_image(meta, nearby_text='prompt: 1girl, blue archive style')
    keep_good, reason_good = should_keep_image(meta, nearby_text='这张太神了，求tag')
    keep_none, reason_none = should_keep_image(meta, nearby_text='今天吃饭了吗')

    assert (keep_prompt, reason_prompt) == (True, 'nearby_ai_context')
    assert (keep_good, reason_good) == (True, 'positive_feedback')
    assert (keep_none, reason_none) == (False, 'no_ai_metadata')

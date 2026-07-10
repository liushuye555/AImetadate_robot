import pytest

from qq_onebot_whitelist.context_quality import parse_context_quality


@pytest.mark.parametrize(
    ('summary', 'level', 'relevant'),
    [
        ('## 概览\n包含 ComfyUI 工作流参数。\n## 内容判定\nAI相关：是\n价值等级：高', 'high', True),
        ('## 概览\n讨论 LoRA。\n- ai_relevant: true\n- value: medium', 'review', True),
        ('## 概览\n普通闲聊。\n```json\n{"ai_relevant": false, "value_level": "low"}\n```', 'low', False),
        ('## 概览\n提到了模型，但没有判定字段。', 'review', None),
    ],
)
def test_parse_context_quality_accepts_output_variants(summary, level, relevant):
    quality = parse_context_quality(summary)

    assert quality.value_level == level
    assert quality.ai_relevant is relevant


def test_high_without_substantive_evidence_falls_back_to_review():
    quality = parse_context_quality('## 概览\n无有效讨论。\n## 内容判定\nAI相关：是\n价值等级：高')

    assert quality.value_level == 'review'


def test_content_judgment_is_removed_from_display_summary():
    quality = parse_context_quality('## 概览\n包含 LoRA 训练经验。\n## 内容判定\nAI相关：是\n价值等级：高\n判断理由：可复用')

    assert quality.display_summary == '## 概览\n包含 LoRA 训练经验。'
    assert quality.reason == '可复用'

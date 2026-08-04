"""参数讨论判定模式测试。"""


def test_judge_rule_mode():
    from qq_onebot_whitelist.ai_discussion_judge import should_keep_params
    assert should_keep_params("fp8 出图快", mode="rule") is True
    assert should_keep_params("吃饭了吗", mode="rule") is False


def test_judge_llm_mode_records_cost(tmp_path, monkeypatch):
    from qq_onebot_whitelist.ai_discussion_judge import should_keep_params, reset_cost_log
    reset_cost_log()
    calls = {"n": 0}

    def fake_llm(texts):
        calls["n"] += 1
        return [True] * len(texts), 120, 60

    monkeypatch.setattr("qq_onebot_whitelist.ai_discussion_judge._llm_judge_batch", fake_llm)
    assert should_keep_params("fp8 出图快", mode="llm") is True
    assert calls["n"] == 1
    log = __import__("qq_onebot_whitelist.ai_discussion_judge", fromlist=["cost_log"]).cost_log
    assert log["total_tokens"] == 180  # prompt 120 + completion 60


def test_judge_llm_rejects_question_only(tmp_path, monkeypatch):
    from qq_onebot_whitelist.ai_discussion_judge import should_keep_params

    def fake_llm(texts):
        return [False] * len(texts), 80, 20

    monkeypatch.setattr("qq_onebot_whitelist.ai_discussion_judge._llm_judge_batch", fake_llm)
    assert should_keep_params("这是什么模型？有没有人用过", mode="llm") is False

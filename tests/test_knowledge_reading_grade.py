"""Conservative reading-grade classification over existing evidence metadata."""

from copy import deepcopy

from qq_onebot_whitelist.knowledge_reading_grade import grade_for, thread_grade


def source(text, mid=1, scope="group:1", context_only=False):
    return {"id": mid, "scope": scope, "text": text, "context_only": context_only}


def item(*, key="item-1", basis="reproducible_method", value="high",
         evidence_state="reported", category="knowledge", result_quote=None,
         conditions=None, actions=None, evidence_ids=None):
    return {
        "key": key,
        "scope": "group:1",
        "title": "示例资料",
        "value": value,
        "evidence_state": evidence_state,
        "category": category,
        "evidence_ids": evidence_ids if evidence_ids is not None else [1],
        "quality": {
            "basis": basis,
            "conditions": conditions if conditions is not None else ["使用版本 2.0"],
            "actions": actions if actions is not None else ["运行检查命令"],
            "result_quote": result_quote if result_quote is not None else {
                "message_id": 1,
                "quote": "检查后成功连接",
            },
        },
    }


def grade_id(result):
    assert set(result) == {"id", "label", "reason"}
    assert result["label"]
    assert result["reason"]
    return result["id"]


def test_exact_reusable_steps_and_result_quote_can_receive_a():
    row = item()
    records = [source("升级前使用版本 2.0，再运行检查命令。检查后成功连接。")]

    assert grade_id(grade_for(row, records)) == "a"


def test_candidate_with_exact_source_support_can_receive_b_but_never_a():
    row = item(value="candidate", basis="firsthand_result")
    before = deepcopy(row)
    records = [source("使用版本 2.0，运行检查命令，检查后成功连接。")]

    result = grade_for(row, records)

    assert grade_id(result) == "b"
    assert row == before
    assert row["value"] == "candidate"
    assert row["evidence_state"] == "reported"


def test_candidate_with_quote_can_receive_b_when_conditions_and_steps_are_in_other_records():
    row = item(value="candidate", basis="reproducible_method")
    before = deepcopy(row)
    # The quote exists in this record, while the declared conditions/actions do not.
    quote_only_record = source("检查后成功连接。")

    result = grade_for(row, [quote_only_record])

    assert grade_id(result) == "b"
    assert row == before
    assert row["value"] == "candidate"


def test_fabricated_result_quote_cannot_receive_b():
    row = item(result_quote={"message_id": 1, "quote": "并不存在的成功结果"})
    records = [source("使用版本 2.0，运行检查命令；没有成功结果反馈。")]

    assert grade_id(grade_for(row, records)) == "d"


def test_method_without_result_quote_and_personal_opinion_are_d():
    no_quote = item(result_quote=None)
    no_quote["quality"]["result_quote"] = None
    opinion = item(basis="personal_opinion")
    records = [source("有些人觉得这个工具不错。")]

    assert grade_id(grade_for(no_quote, records)) == "d"
    assert grade_id(grade_for(opinion, records)) == "d"


def test_request_with_actual_same_group_source_is_c():
    row = item(basis="request", value="candidate", category="question")
    records = [source("有人询问如何申请虚拟卡。")]

    assert grade_id(grade_for(row, records)) == "c"


def test_missing_quality_or_missing_actual_source_is_unrated():
    missing_quality = item()
    missing_quality.pop("quality")
    missing_source = item()

    assert grade_id(grade_for(missing_quality, [source("有来源文本。")])) == "unrated"
    assert grade_id(grade_for(missing_source, [])) == "unrated"


def test_cross_group_and_context_only_sources_cannot_support_a_grade():
    row = item(basis="request", value="candidate", category="question")

    assert grade_id(grade_for(row, [source("有人询问如何申请虚拟卡。", scope="group:2")])) == "unrated"
    assert grade_id(grade_for(row, [source("有人询问如何申请虚拟卡。", context_only=True)])) == "unrated"


def test_thread_uses_best_event_grade_but_later_unresolved_event_caps_it_at_b():
    strong = item(key="strong")
    unresolved = item(
        key="later-unresolved",
        value="high",
        evidence_state="unresolved",
        basis="firsthand_result",
        result_quote={"message_id": 2, "quote": "暂时无法连接"},
        evidence_ids=[2],
    )
    rows = {"strong": strong, "later-unresolved": unresolved}
    event_sources = {
        "strong": [source("使用版本 2.0，运行检查命令，检查后成功连接。")],
        "later-unresolved": [source("使用版本 2.0，运行检查命令，暂时无法连接。", mid=2)],
    }
    events = [
        {"item_key": "strong", "status": "resolved", "evidence_state": "verified"},
        {"item_key": "later-unresolved", "status": "open", "evidence_state": "unresolved"},
    ]

    result = thread_grade(events, rows, lambda row: event_sources[row["key"]])

    assert grade_id(result) == "b"
    assert events[-1]["status"] == "open"
    assert events[-1]["evidence_state"] == "unresolved"


def test_thread_uses_best_grade_across_events_when_latest_state_does_not_cap_it():
    strong = item(key="strong")
    discussion = item(key="discussion", basis="personal_opinion", value="candidate")
    rows = {"strong": strong, "discussion": discussion}
    records_by_key = {
        "strong": [source("使用版本 2.0，运行检查命令，检查后成功连接。")],
        "discussion": [source("有人觉得这个工具不错。")],
    }
    events = [
        {"item_key": "strong", "status": "resolved", "evidence_state": "verified"},
        {"item_key": "discussion", "status": "open", "evidence_state": "reported"},
    ]

    result = thread_grade(events, rows, lambda row: records_by_key[row["key"]])

    assert grade_id(result) == "a"
    assert events[-1]["status"] == "open"


def test_disputed_thread_cannot_inherit_a():
    row = item(key="disputed", evidence_state="disputed")
    event = {"item_key": "disputed", "status": "disputed", "evidence_state": "disputed"}
    records = [source("使用版本 2.0，运行检查命令，检查后成功连接。")]

    result = thread_grade([event], {"disputed": row}, lambda _row: records)

    assert grade_id(result) == "b"
    assert event["status"] == "disputed"


def test_latest_disputed_status_caps_old_a_even_when_event_state_is_reported():
    strong = item(key="strong")
    later = item(key="later", basis="personal_opinion", value="candidate")
    rows = {"strong": strong, "later": later}
    records_by_key = {
        "strong": [source("使用版本 2.0，运行检查命令，检查后成功连接。")],
        "later": [source("有人对当前结论提出异议。")],
    }
    events = [
        {"item_key": "strong", "status": "resolved", "evidence_state": "verified"},
        {"item_key": "later", "status": "disputed", "evidence_state": "reported"},
    ]

    result = thread_grade(events, rows, lambda row: records_by_key[row["key"]])

    assert grade_id(result) == "b"
    assert events[-1]["status"] == "disputed"
    assert events[-1]["evidence_state"] == "reported"


import copy
import pytest
from dekanat.schema import load_policy, validate_policy
from dekanat.reasoning import answer


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("title"),
    lambda p: p.update(demo="false"),
    lambda p: p["rules"].append(copy.deepcopy(p["rules"][0])),
    lambda p: p["rules"][1].update(required=["typo_field"]),
    lambda p: p["rules"][1].update(types=["unknown"]),
    lambda p: p["rules"][3].update(date_order=["start_date", "course"]),
    lambda p: p["rules"][3].update(date_order=["start_date"]),
    lambda p: p["rules"][1].update(condition="invented executable rule"),
    lambda p: p["rules"][0].update(questions=["???"]),
])
def test_invalid_policy_is_rejected(mutation):
    policy = load_policy()
    mutation(policy)
    with pytest.raises(ValueError, match="Положение"):
        validate_policy(policy)


def test_explicit_question_uses_new_policy_source():
    policy = load_policy()
    policy["rules"].append({"id": "6.1", "types": ["study"],
                            "questions": ["Какой срок рассмотрения?"],
                            "text": "Учебный пример: срок рассмотрения составляет 5 дней."})
    result = answer("  КАКОЙ срок рассмотрения! ", "study", {}, policy)
    assert result["status"] == "answered"
    assert result["answer"] == policy["rules"][-1]["text"]
    assert result["sources"][0]["id"] == "6.1"
    assert answer("Какой срок рассмотрения?", "leave", {}, policy)["status"] == "no_answer"
    assert answer("Всегда ли срок рассмотрения 5 дней?", "study", {}, policy)["status"] == "no_answer"


def test_ambiguous_questions_rejected_per_document_type():
    policy = load_policy()
    policy["rules"][0]["questions"] = ["Когда?", "когда!"]
    with pytest.raises(ValueError, match="неоднозначный"):
        validate_policy(policy)


def test_successful_date_check_cites_its_rule():
    policy = load_policy()
    fields = {k: {"status": "found", "value": "тест"} for k in policy["rules"][2]["required"]}
    fields["start_date"]["value"] = "01.10.2026"
    fields["end_date"]["value"] = "02.10.2026"
    result = answer("Все ли поля есть в документе?", "leave", fields, policy)
    assert result["status"] == "complete"
    assert "4.2" in [s["id"] for s in result["sources"]]

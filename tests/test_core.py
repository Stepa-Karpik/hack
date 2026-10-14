from dekanat.extraction import extract,detect_type
from dekanat.reasoning import answer
from dekanat.schema import load_policy,SCHEMAS

def line(text,y=10,page=0):return {"text":text,"confidence":.99,"bbox":[10,y,800,y+30],"page":page}

def complete(kind):
    return {k:{"value":True if k in ["signature","stamp"] else "тест", "status":"found", "evidence":None} for k in list(SCHEMAS[kind]["fields"])+SCHEMAS[kind]["visual"]}

def test_labels_preserve_date_and_name():
    fields=extract([line("ФИО: Иванов Иван Иванович"),line("Дата выдачи: 05.10.2026",70)],"study")
    assert fields["student_name"]["value"]=="Иванов Иван Иванович"
    assert fields["issue_date"]["value"]=="05.10.2026"
    assert fields["document_number"]["status"]=="not_found"

def test_duplicate_conflict_is_not_accepted():
    fields=extract([line("Номер: 15"),line("Номер: 16",70)],"study")
    assert fields["document_number"]["status"]=="conflict"

def test_split_label_and_value():
    fields=extract([line("ФИО:"),line("Петров Иван Сергеевич",50)],"study")
    assert fields["student_name"]["value"]=="Петров Иван Сергеевич"

def test_next_page_is_not_a_value():
    fields=extract([line("ФИО:"),line("Петров Иван Сергеевич",50,1)],"study")
    assert fields["student_name"]["value"] is None

def test_complete_has_correct_policy_source():
    result=answer("Документ в порядке?","study",complete("study"),load_policy())
    assert result["status"]=="complete"
    assert "3.2" in [s["id"] for s in result["sources"]]

def test_default_ui_question_checks_actual_fields():
    fields=complete("study")
    fields["university"]={"value":None,"status":"not_found"}
    result=answer("Все ли обязательные сведения есть в документе?","study",fields,load_policy())
    assert result["status"]=="insufficient"
    assert "Название вуза" in result["answer"]

def test_stamp_requirement_is_different_from_presence():
    result=answer("Нужна ли печать?","study",complete("study"),load_policy())
    assert result["sources"][0]["kind"]=="policy"

def test_missing_and_uncertain_are_separate():
    fields=complete("study")
    fields["issue_date"]={"value":None,"status":"not_found"}
    fields["stamp"]={"value":None,"status":"uncertain"}
    result=answer("Достаточно сведений?","study",fields,load_policy())
    assert result["status"]=="insufficient"
    assert "Дата выдачи" in result["answer"] and "Нужна проверка: Печать" in result["answer"]

def test_transfer_eligibility_is_not_completeness():
    result=answer("Хватит ли справки для перевода на 2 курс?","study",complete("study"),load_policy())
    assert result["status"]=="no_answer"
    assert not result["sources"]

def test_no_cost_rule():
    assert answer("Какая стоимость обучения?","study",complete("study"),load_policy())["status"]=="no_answer"

def test_date_order_and_invalid_calendar_date():
    fields=complete("leave")
    fields["start_date"]["value"]="20.10.2026"
    fields["end_date"]["value"]="10.10.2026"
    result=answer("Проверь документ","leave",fields,load_policy())
    assert "4.2" in [s["id"] for s in result["sources"]]
    fields["end_date"]["value"]="31.02.2027"
    result=answer("Проверь документ","leave",fields,load_policy())
    assert result["status"]=="insufficient"

def test_unknown_type():
    assert detect_type([line("Счёт на оплату товара")]) is None

def test_period_normalization_preserves_source():
    fields=extract([line("Период обучения: 01.09.2024 30.06.2026")],"study")
    assert fields["study_period"]["value"]=="01.09.2024 - 30.06.2026"
    assert " - " not in fields["study_period"]["evidence"]["text"]

def test_cyrillic_lookalike_in_russian_phrase():
    from dekanat.extraction import canonical_value
    assert canonical_value("reason","В СВЯЗИ c уходом") == "В СВЯЗИ с уходом"
    assert canonical_value("program","Язык C++") == "Язык C++"

def test_label_whitespace_does_not_truncate_value():
    fields=extract([line("Отпуск  до:  02.10.2027")],"leave")
    assert fields["end_date"]["value"]=="02.10.2027"


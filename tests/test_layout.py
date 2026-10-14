from dekanat.extraction import extract


def row(text,x,y,w=250,h=24,confidence=.99):
    return {"text":text,"bbox":[x,y,x+w,y+h],"page":0,"confidence":confidence}


def test_two_column_labels_do_not_pollute_each_other():
    fields=extract([row("ФИО: Иванов Иван Иванович",20,20,300),row("Курс: 2",540,20,120)],"leave")
    assert fields["student_name"]["value"]=="Иванов Иван Иванович"
    assert fields["course"]["value"]=="2"


def test_label_and_distant_right_value():
    fields=extract([row("ФИО:",20,20,80),row("Иванов Иван Иванович",230,20,300)],"leave")
    assert fields["student_name"]["value"]=="Иванов Иван Иванович"
    assert fields["student_name"]["evidence"]["bbox"][0]==230


def test_two_inline_fields_with_colons():
    fields=extract([row("ФИО: Иванов Иван Иванович; Курс: 2",20,20,700)],"leave")
    assert fields["student_name"]["value"]=="Иванов Иван Иванович"
    assert fields["course"]["value"]=="2"


def test_wrap_stops_at_new_field_and_preserves_low_confidence():
    fields=extract([row("Причина: по семейным",20,20),row("обстоятельствам",20,50,confidence=.4),row("Курс: 2",20,80)],"leave")
    assert fields["reason"]["value"]=="по семейным обстоятельствам"
    assert fields["reason"]["status"]=="uncertain"
    assert len(fields["reason"]["evidence"]["parts"])==2
    assert fields["course"]["value"]=="2"


def test_arbitrary_blank_underline_and_hint_are_not_values():
    fields=extract([row("ФИО: ____________ (ФИО полностью)",20,20)],"study")
    assert fields["student_name"]["value"] is None


def test_conflict_is_not_erased_by_third_repeated_value():
    fields=extract([row("Номер: 1",20,20),row("Номер: 2",20,80),row("Номер: 1",20,140)],"study")
    assert fields["document_number"]["status"]=="conflict"


def test_unrelated_second_column_not_attached_as_continuation():
    fields=extract([row("Организация: ООО Учебная",20,20,300),row("Руководитель: Петров Иван",550,20,300),row("Дата выдачи: 10.10.2026",20,80)],"practice")
    assert fields["organization"]["value"]=="ООО Учебная"
    assert fields["supervisor"]["value"]=="Петров Иван"

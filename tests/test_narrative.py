from dekanat.extraction import detect_type, extract


def rows(*texts, confidence=.99, page=0):
    return [{"text": text, "bbox": [40, 40+i*36, 1100, 66+i*36], "page": page, "confidence": confidence} for i, text in enumerate(texts)]


def test_study_recipient_can_wrap_and_keeps_evidence():
    fields = extract(rows("Дана Иванову Ивану Ивановичу", "в том, что он является студентом очной формы обучения"), "study")
    assert fields["student_name"]["value"] == "Иванову Ивану Ивановичу"
    assert fields["study_form"]["value"] == "очная"
    assert len(fields["student_name"]["evidence"]["parts"]) == 2
    evidence = fields["student_name"]["evidence"]
    start, end = evidence["value_span"]
    assert evidence["text"][start:end] == "Иванову Ивану Ивановичу"


def test_narrative_does_not_cross_pages():
    source = rows("Дана Иванову Ивану Ивановичу")+rows("в том, что он является студентом", page=1)
    assert extract(source, "study")["student_name"]["value"] is None


def test_narrative_does_not_join_two_columns():
    source = rows("Дана Иванову Ивану Ивановичу", "в том, что он является студентом")
    source[1]["bbox"][0] = 700
    assert extract(source, "study")["student_name"]["value"] is None


def test_certificate_header_date_is_not_admission_order_date():
    fields = extract(rows("СПРАВКА № УЧ-123 от 10.10.2026", "Приказ о зачислении: № 999 от 01.09.2024"), "study")
    assert fields["document_number"]["value"] == "УЧ-123"
    assert fields["issue_date"]["value"] == "10.10.2026"


def test_separate_explicit_study_dates_create_period():
    fields = extract(rows("Дата начала обучения в университете 01.09.2024", "Предполагаемая дата окончания в университете 31.08.2028"), "study")
    assert fields["study_period"]["value"] == "01.09.2024 - 31.08.2028"
    assert fields["issue_date"]["value"] is None


def test_duration_does_not_create_guessed_dates():
    fields = extract(rows("Нормативный срок обучения: 4 года", "Приказ о зачислении № 12 от 01.09.2024"), "study")
    assert fields["study_period"]["value"] is None
    assert fields["issue_date"]["value"] is None


def test_placeholder_certificate_and_executor_name_are_not_student():
    fields = extract(rows("СПРАВКА №____ от __.__.20__", "Дана ___________ (Ф.И.О. полностью)",
                          "в том, что он является студентом ____ формы обучения", "Исполнитель:", "ФИО специалиста факультета"), "study")
    assert fields["student_name"]["value"] is None
    assert fields["document_number"]["value"] is None
    assert fields["issue_date"]["value"] is None


def test_narrative_low_confidence_is_not_upgraded():
    fields = extract(rows("Дана Иванову Ивану Ивановичу в том, что он является студентом", confidence=.4), "study")
    assert fields["student_name"]["status"] == "uncertain"


def test_institution_and_wrapped_quoted_program():
    fields = extract(rows('ФГБОУ ВО «Учебный университет»', 'обучается по направлению подготовки «Прикладная', 'информатика».'), "study")
    assert fields["university"]["value"] == 'ФГБОУ ВО «Учебный университет»'
    assert fields["program"]["value"] == "Прикладная информатика"


def test_narrative_conflict_is_preserved():
    fields = extract(rows("ФИО: Петров Петр Петрович", "Дана Иванову Ивану Ивановичу в том, что он является студентом"), "study")
    assert fields["student_name"]["status"] == "conflict"
    assert fields["student_name"]["alternatives"][0]["value"] == "Иванову Ивану Ивановичу"


def test_invalid_narrative_date_is_not_accepted():
    fields = extract(rows("СПРАВКА № 123 от 31.02.2026"), "study")
    assert fields["issue_date"]["value"] is None


def test_leave_sentence_gives_explicit_period_and_reason():
    fields = extract(rows("Прошу предоставить мне академический отпуск с 01.11.2026 по 31.01.2027 в связи с семейными обстоятельствами."), "leave")
    assert fields["start_date"]["value"] == "01.11.2026"
    assert fields["end_date"]["value"] == "31.01.2027"
    assert fields["reason"]["value"] == "семейными обстоятельствами"


def test_practice_sentence_and_date_number_header():
    fields = extract(rows("10.10.2026 № ПР-123", "Прошел производственную практику с 01.06.2026 по 30.06.2026."), "practice")
    assert fields["issue_date"]["value"] == "10.10.2026"
    assert fields["document_number"]["value"] == "ПР-123"
    assert fields["practice_period"]["value"] == "01.06.2026 - 30.06.2026"


def test_study_type_does_not_change_because_curriculum_mentions_practice():
    source = rows("СПРАВКА", "Дана Иванову Ивану Ивановичу в том, что он является студентом", "В учебный план включена практика")
    assert detect_type(source) == "study"


def test_latin_number_sign_and_preposition_are_context_limited():
    fields = extract(rows("СПРАВКА Ng УЧ-123 от 10.10.2026", "Обучается c 01.09.2024 по 30.06.2028"), "study")
    assert fields["document_number"]["value"] == "УЧ-123"
    assert fields["study_period"]["value"] == "01.09.2024 - 30.06.2028"


def test_wrapped_leave_request_reason():
    fields = extract(rows("Прошу предоставить мне академический отпуск c 01.11.2026 по 31.01.2027", "в связи c семейными обстоятельствами."), "leave")
    assert fields["reason"]["value"] == "семейными обстоятельствами"


def test_organization_wrapping_stops_at_practice_sentence():
    fields = extract(rows("Организация: ООО Учебная", "Прошел практику с 01.06.2026 по 30.06.2026."), "practice")
    assert fields["organization"]["value"] == "ООО Учебная"


def test_quote_orientation_is_normalized_only_inside_quoted_institution():
    fields = extract(rows('АНО BO «Учебный университет«', 'по направлению подготовки »Информатика«'), "study")
    assert fields["university"]["value"] == 'АНО ВО «Учебный университет»'
    assert fields["program"]["value"] == "Информатика"
    assert '«Учебный университет«' in fields["university"]["evidence"]["text"]


def test_latin_tom_marker_does_not_modify_person_name():
    fields = extract(rows("Дана Иванову Ивану Ивановичу в TOM, ЧТО он является студентом"), "study")
    assert fields["student_name"]["value"] == "Иванову Ивану Ивановичу"

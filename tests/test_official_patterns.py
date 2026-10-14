import pytest
from dekanat.official_patterns import date_value
from dekanat.extraction import extract,detect_type
from dekanat.field_validation import validate_fields


def row(text,y=0,x=100,width=800,height=30,page=0,confidence=.9):
    return {'text':text,'bbox':[x,y,x+width,y+height],'page':page,'confidence':confidence}


def read(lines,kind):
    fields=extract(lines,kind);validate_fields(fields);return fields


@pytest.mark.parametrize('text,expected',[('15 июня 2026 г.','15.06.2026'),('12 ИЮЛЯ 2026','12.07.2026'),('29 февраля 2024 г.','29.02.2024'),('1.6.2026 г.','01.06.2026'),('31 февраля 2026',None),('29 февраля 2025',None),('15 неизвестно 2026',None),('15 июня 26',None)])
def test_explicit_calendar_dates(text,expected):assert date_value(text)==expected


def test_quoted_organization_after_practice_role():
    f=read([row('производственную практику в ООО «Центр проектных решений».')],'practice')['organization']
    assert f['value']=='ООО «Центр проектных решений»'
    assert read([row('Инструкция: указать ООО _____')],'practice')['organization']['value'] is None


def test_grade_choices_not_an_assessment_and_no_spelling_guesses():
    assert read([row('по результатам практики заслуживает оценки «отлично»')],'practice')['grade']['value']=='отлично'
    assert read([row('«отлично», «хорошо», «удовлетворительно»')],'practice')['grade']['value'] is None
    assert read([row('заслуживает оценки «орошо»')],'practice')['grade']['value'] is None


def test_weak_narrative_grade_remains_uncertain():
    f=read([row('заслуживает оценки «хорошо»',confidence=.3)],'practice')['grade']
    assert f['value']=='хорошо' and f['status']=='uncertain'


def test_reason_before_period_keeps_both_clauses_and_dates():
    fields=read([row('Прошу предоставить мне академический отпуск по семейным обстоятельствам'),row('15.10.2026 по 14.10.2027 в связи с уходом за родственником.',y=35)],'leave')
    assert fields['reason']['value']=='по семейным обстоятельствам в связи с уходом за родственником'
    assert fields['reason']['status']=='found'
    assert fields['start_date']['value']=='15.10.2026' and fields['end_date']['value']=='14.10.2027'


def test_unfilled_reason_does_not_invent_dates():
    fields=read([row('Прошу предоставить мне академический отпуск по семейным обстоятельствам'),row('с ____ по ____ в связи с _____',y=35)],'leave')
    assert fields['reason']['value']=='по семейным обстоятельствам' and fields['start_date']['value'] is None


def test_request_cannot_cross_pages():
    fields=read([row('Прошу предоставить мне академический отпуск по семейным обстоятельствам'),row('15.10.2026 по 14.10.2027 в связи с уходом.',y=35,page=1)],'leave')
    assert fields['start_date']['value'] is None


def test_applicant_name_above_caption_has_explicit_student_context():
    lines=[row('от студента(тки)',y=0),row('Соколова Надежда Викторовна',y=100),row('(фамилия, имя; отчество)',y=135)]
    f=read(lines,'leave')['student_name'];assert f['value']=='Соколова Надежда Викторовна'
    assert len(f['evidence']['parts'])==3
    assert read(lines[1:],'leave')['student_name']['value'] is None


def test_weak_caption_not_promoted():
    f=read([row('от студента',y=0),row('Соколова Надежда Викторовна',y=100),row('(фамилия, имя, отчество)',y=135,confidence=.3)],'leave')['student_name']
    assert f['status']=='uncertain' and f['confidence']==.3


def test_course_split_by_horizontal_gap_needs_course_word():
    a=row('от студента(тки) 3',width=210);b=row('курса',x=370,width=65)
    assert read([a,b],'leave')['course']['value']=='3'
    assert read([a,row('группы',x=370,width=65)],'leave')['course']['value'] is None


def test_three_separate_applicant_course_boxes():
    lines=[row('от студента(тки)',y=118,x=642,width=174,height=24),
           row('2',y=117,x=859,width=10,height=17),row('курса',y=118,x=924,width=66,height=24)]
    assert read(lines,'leave')['course']['value']=='2'
    lines[2]['page']=1
    assert read(lines,'leave')['course']['value'] is None


@pytest.mark.parametrize('period',['15.06.2026 г. по 12.07.2026 г.','15 июня 2026 г. по 12 июля 2026 г.'])
def test_practice_period_before_verb(period):
    f=read([row('в период '+period+' проходил(а)')],'practice')['practice_period']
    assert f['value']=='15.06.2026 - 12.07.2026' and f['status']=='found'


def test_split_supervisor_preserves_low_confidence():
    f=read([row('Руководитель практики'),row('OT организации (предприятия) Гордеев Николай Алексеевич, руководитель отдела',y=28,confidence=.3)],'practice')['supervisor']
    assert f['value']=='Гордеев Николай Алексеевич' and f['status']=='uncertain'


def test_empty_supervisor_continuation_not_a_person():
    assert read([row('Руководитель практики'),row('от организации (предприятия',y=35)],'practice')['supervisor']['value'] is None


def test_date_under_stamp_placeholder_is_not_stamp_presence():
    fields=read([row('М.П.',width=100),row('09.08.2026',y=35,width=180)],'practice')
    assert fields['issue_date']['value']=='09.08.2026'


def test_corner_date_kept_when_registration_number_is_blank():
    fields=read([row('23.10.2015 Ng')],'study')
    assert fields['issue_date']['value']=='23.10.2015' and fields['document_number']['value'] is None


def test_explicit_direction_supports_standalone_program_code():
    lines=[row('в том, что он является студентом направления'),row('15.02.08 Технология машиностроения',y=65)]
    assert read(lines,'study')['program']['value']=='15.02.08 Технология машиностроения'
    assert read(lines[1:],'study')['program']['value'] is None


def test_split_recipient_retains_literal_dative_name():
    lines=[row('Выдана',width=100),row('Петрову',x=250,width=140),row('Сергею Ивановичу',y=35,x=230,width=240)]
    assert read(lines,'study')['student_name']['value']=='Петрову Сергею Ивановичу'


def test_abbreviated_institution_and_initial_punctuation_are_explicit():
    fields=read([row('СГТУ имени Гагарина ЮА очной формы обучения')],'study')
    assert fields['university']['value']=='СГТУ имени Гагарина Ю.А.' and fields['study_form']['value']=='очная'


def test_form_of_certificate_is_not_study_form():
    assert read([row('Форма справки установленного образца')],'study')['study_form']['value'] is None


@pytest.mark.parametrize('title',['Положение','Положение о порядке предоставления академического отпуска','Методические рекомендации по заполнению дневника практики','ДНЕВНИК ПРОХОЖДЕНИЯ ПРАКТИКИ'])
def test_unsupported_titles_not_classified_as_student_certificates(title):
    assert detect_type([row(title)]) is None


def test_mention_of_policy_inside_statement_does_not_reject_it():
    assert detect_type([row('ЗАЯВЛЕНИЕ'),row('Прошу предоставить мне академический отпуск согласно Положению',y=35)])=='leave'

from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/participantkit'))
from labeled_fields import candidates,extract_contract
from format_v1 import MISSING


def line(text,y=0,x=0,w=300):
    return {'text':text,'page':0,'bbox':[x,y,x+w,y+20],'confidence':.95}


def test_separate_period_endpoint_does_not_require_other_date():
    result=candidates([line('Начало периода обучения: 2 февраля 2025 года'),
        line('Окончание периода обучения:',40),line('Номер справки: А-8',80)])
    assert result['study_start'][0]['value']=='2025-02-02'
    assert result['study_end'][0]['value']==MISSING


def test_student_supervisor_bound_to_full_label():
    result=candidates([line('ФИО студента: Романов Ян Петрович'),
        line('ФИО руководителя практики: Белова Анна Ильинична',40)])
    assert result['student_name'][0]['value']=='Романов Ян Петрович'
    assert result['supervisor_name'][0]['value']=='Белова Анна Ильинична'


def test_empty_label_cannot_borrow_next_field_or_footer():
    result=candidates([line('Название организации:'),
        line('Дата начала практики: 12.01.2025',25),
        line('Все сведения вымышлены. Идентификатор образца: test',80)])
    assert result['organization'][0]['value']==MISSING


def test_complete_same_row_digit_and_month_are_literal_not_guessed():
    result=candidates([line('Дата заявления:',w=180),
        line('7',x=200,w=10),line('апреля 2025 года',x=225,w=200)])
    assert result['application_date'][0]['value']=='2025-04-07'
    result=candidates([line('Дата заявления:',w=180),line('апреля 2025 года',x=225)])
    assert result['application_date'][0]['value']==MISSING


def test_repeated_explicit_labels_remain_conflict_and_source_is_audited():
    config=json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))
    analysis={'fields':{},'ocr':{'lines':[line('Название вуза: Северный университет'),
        line('Название вуза: Южный университет',40)]}}
    fields,evidence=extract_contract(analysis,'study_certificate',config)
    assert fields['university']==MISSING
    assert evidence['university']['status']=='conflict'


def test_names_and_organization_are_not_corrected_from_dictionary():
    result=candidates([line('Название организации: Компания <Необычное'),
        line('ФИО студента: Редкая Фамилия Имя',40)])
    assert result['organization'][0]['value']=='Компания <Необычное'
    assert result['student_name'][0]['value']=='Редкая Фамилия Имя'


def test_next_row_fragment_with_higher_top_cannot_fill_blank_student():
    result=candidates([line('ФИО студента:'),line('Название организации: Компания',40,w=400),
        line('«Лес»',35,x=400,w=80)])
    assert result['student_name'][0]['value']==MISSING
    assert result['organization'][0]['value']=='Компания «Лес»'


def test_refined_number_cannot_regress_to_first_pass_ocr():
    config=json.loads((ROOT/'configs/participant_v1.json').read_text(encoding='utf-8'))
    analysis={'fields':{'document_number':{'value':'АБ-8059','status':'found'}},
        'ocr':{'lines':[line('Номер справки: АБ-8О59')]}}
    fields,evidence=extract_contract(analysis,'study_certificate',config)
    assert fields['document_number']=='АБ-8059'
    assert evidence['document_number']['status']=='retained_existing'

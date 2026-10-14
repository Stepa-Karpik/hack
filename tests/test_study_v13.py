import pytest
from dekanat.extraction import extract
from dekanat.field_validation import validate_fields
from dekanat.schema import ROOT


def row(text,y=0,x=100,page=0,confidence=.9):
    return {'text':text,'bbox':[x,y,x+800,y+40],'page':page,'confidence':confidence}


def read(lines,model=False):
    fields=extract(lines,'study',ROOT/'models/fields.joblib' if model else None)
    validate_fields(fields)
    return fields


def test_normative_period_on_overlapping_indented_next_line_keeps_source():
    lines=[row('Форма обучения: очно-заочная Нормативный период обучения:',x=170),
           row('01.09.2025 31.08.2030. Основание зачисления: приказ от 28.08.2025',y=38)]
    f=read(lines)['study_period']
    assert (f['value'],f['status'])==('01.09.2025 - 31.08.2030','found')
    assert f['evidence']['parts']==lines


@pytest.mark.parametrize('text',['Нормативный период обучения: 01.09.2025 - 31.02.2030',
                                'Нормативный период обучения: 01.09.25 - 31.08.30',
                                'Основание зачисления: приказ от 28.08.2025. Окончание: 31.08.2030'])
def test_normative_period_requires_explicit_label_and_full_valid_dates(text):
    assert read([row(text)])['study_period']['status']=='not_found'


def test_normative_period_weak_row_is_not_promoted():
    f=read([row('Нормативный период обучения:'),row('01.09.2025 - 31.08.2030',y=38,confidence=.3)])['study_period']
    assert f['status']=='uncertain' and f['confidence']==.3


def test_normative_period_does_not_cross_page():
    assert read([row('Нормативный период обучения:'),row('01.09.2025 - 31.08.2030',page=1,y=38)])['study_period']['value'] is None


def test_program_subject_and_inline_form_before_profile():
    lines=[row('Обучается по образовательной программе бакалавриата 38.03.01',x=170),
           row('Экономика; профиль «Финансы и кредит». Форма обучения очная Обучение',y=36)]
    fields=read(lines)
    assert fields['program']['value']=='38.03.01 Экономика'
    assert fields['study_form']['value']=='очная'
    assert fields['program']['evidence']['parts']==lines


@pytest.mark.parametrize('change',['page','column','anchor','code'])
def test_program_narrative_needs_anchor_code_and_same_paragraph(change):
    a=row('Обучается по образовательной программе бакалавриата 38.03.01',x=170)
    b=row('Экономика; профиль «Финансы и кредит»',y=36)
    if change=='page':b['page']=1
    if change=='column':b['bbox']=[900,36,1200,76]
    if change=='anchor':a['text']='Указано в каталоге: бакалавриата 38.03.01'
    if change=='code':a['text']='Обучается по образовательной программе бакалавриата 38.О3.01'
    assert read([a,b])['program']['value'] is None


def test_degree_continuation_stops_at_profile_and_keeps_weak_evidence():
    lines=[row('Направление подготовки: 09.03.02 Информационные системы и',x=170),
           row('технологии Направленность программы: «Информационные системы в',y=40,confidence=.4),
           row('экономике»',y=82)]
    f=read(lines,model=True)['program']
    assert f['value']=='09.03.02 Информационные системы и технологии'
    assert f['status']=='uncertain' and f['confidence']==.4
    assert [{k:p[k] for k in ['text','bbox','page','confidence']} for p in f['evidence']['parts']]==lines[:2]
    assert 'Направленность программы' in f['evidence']['text']


@pytest.mark.parametrize('change',['page','column','gap'])
def test_degree_continuation_has_geometry_limits(change):
    a=row('Направление подготовки: 09.03.02 Информационные системы и',x=170)
    b=row('технологии Направленность программы: «В экономике»',y=40)
    if change=='page':b['page']=1
    if change=='column':b['bbox']=[500,40,1300,80]
    if change=='gap':b['bbox']=[100,140,900,180]
    assert read([a,b])['program']['value']=='09.03.02 Информационные системы и'


def test_two_different_main_program_labels_remain_conflict():
    f=read([row('Направление подготовки: 09.03.02 Информационные системы'),
            row('Направление подготовки: 38.03.01 Экономика',y=100)])['program']
    assert f['status']=='conflict' and len(f['alternatives'])==1


@pytest.mark.parametrize('separator',['.', ';'])
def test_form_stops_at_explicit_next_sentence_without_false_conflict(separator):
    f=read([row('Форма обучения: очная'+separator+' Обучение осуществляется за счёт средств.',confidence=.4)])['study_form']
    assert f['value']=='очная' and f['status']=='uncertain' and f['confidence']==.4


def test_two_forms_with_punctuation_remain_conflicting():
    f=read([row('Форма обучения: очная. Обучение оплачивается.'),row('Форма обучения: заочная',y=100)])['study_form']
    assert f['status']=='conflict'

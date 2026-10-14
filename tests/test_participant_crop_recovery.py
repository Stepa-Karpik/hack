from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/participantkit'))
from crop_recovery import accepted_reading,parsed_reading


def reads(a,b=None,confidence=.9):
    return [[[a,confidence]],[[b or a,confidence]]]


def test_missing_day_read_from_pixels_with_matching_month_year():
    assert accepted_reading('application_date','мая 2025 года',reads('Дата заявления: 9 мая 2025 года'))=='2025-05-09'


@pytest.mark.parametrize('text',['Дата заявления: мая 2025 года','Дата заявления: 31 февраля 2025 года',
    'Дата заявления: 9 июня 2025 года','Дата заявления: 9 мая 2024 года','Подпись: 9 мая 2025 года'])
def test_no_day_guess_wrong_suffix_or_label(text):
    assert accepted_reading('application_date','мая 2025 года',reads(text)) is None


def test_disagreement_and_low_score_are_rejected():
    assert accepted_reading('application_date','мая 2025 года',reads('Дата заявления: 9 мая 2025 года','Дата заявления: 8 мая 2025 года')) is None
    assert accepted_reading('application_date','мая 2025 года',reads('Дата заявления: 9 мая 2025 года',confidence=.4)) is None


def test_quotes_must_be_balanced_and_literal_no_known_name_lookup():
    assert parsed_reading('organization','Название организации: Компания «Новая роща»')=='Компания «Новая роща»'
    assert parsed_reading('organization','Название организации: Компания «Новая роща«') is None
    assert parsed_reading('university','Название вуза« Университет «Заря»')=='Университет «Заря»'


def test_empty_source_date_is_never_filled_by_a_hallucinated_date():
    assert accepted_reading('application_date','',reads('Дата заявления: 9 мая 2025 года')) is None

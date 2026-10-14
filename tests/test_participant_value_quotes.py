from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/participantkit'))
from value_quote_recovery import accepted_value


def readings(value,other=None,score=.8):return [[[value,score]],[[other or value,score]]]


def test_arbitrary_name_read_from_value_without_dictionary():
    assert accepted_value('Компания кТихая рощах',readings('Компания «Тихая роща»'))=='Компания «Тихая роща»'


@pytest.mark.parametrize('before,value,other,score',[
    ('не найдено','Компания «Тихая роща»',None,.8),
    ('Компания «Кедр»','Компания «Ритм»',None,.8),
    ('Компания кКедрх','Компания «Кедр«',None,.8),
    ('Компания кКедрх','Компания «Кедр»','Компания «Кодр»',.8),
    ('Компания кКедрх','Компания «Кедр»',None,.4),
    ('Университет кКедрх','Компания «Кедр»',None,.8)])
def test_no_empty_invention_correct_name_override_or_disagreement(before,value,other,score):
    assert accepted_value(before,readings(value,other,score)) is None

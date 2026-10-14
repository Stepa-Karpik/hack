import pytest
from scripts.experiments.wrapped_names_guarded import select_rows,accept_proposal


def line(text,y=10,x=10):return {'text':text,'bbox':[x,y,x+300,y+30],'page':0}


def test_unique_neighbor_and_page_boundary():
    start=line('Название вуза: Университет')
    one=line('«Тест»',55)
    assert select_rows([start,one])[1]=='eligible'
    assert select_rows([start,one,line('другой»',55,40)])[1]=='ambiguous_row'
    assert select_rows([start,{**one,'page':1}])[1]=='no_wrapped_rows'


@pytest.mark.parametrize('text,reason',[('Название вуза:','empty_label'),('Название вуза: Университет «Тест»','closed_name')])
def test_stop_empty_or_closed(text,reason):
    assert select_rows([line(text),line('Университет «Посторонний»',55)])[1]==reason


def test_duplicate_boundary_invalid_box_and_closing_row():
    start=line('Название вуза: Университет')
    assert select_rows([start,line('Название вуза: Институт',55)])[1]=='unique_label_required'
    assert select_rows([start,line('Примечание: текст',55)])[1]=='no_wrapped_rows'
    assert select_rows([{**start,'bbox':[0,0,float('inf'),30]}])[1]=='invalid_box'
    parts,_=select_rows([start,line('«Тест»',55),line('посторонние слова',100)])
    assert len(parts)==2


def test_guard_preserves_words_found_conflicts_and_missing():
    lines=[line('Название вуза: Университет'),line('<Тест',55)]
    proposal={'accepted':'Университет «Тест»','parts':lines}
    args=({'status':'uncertain'},{'status':'uncertain'},proposal,lines)
    assert accept_proposal('Университет <Тест',*args)[0]=='Университет «Тест»'
    for status in ['found','conflict']:
        assert accept_proposal('Университет <Тест',{'status':status},*args[1:])[0] is None
    for before in ['не найдено','Университет <F Тест','Университет кТестх','Университет <Другой']:
        assert accept_proposal(before,*args)[0] is None
    assert accept_proposal('Университет <Тест',args[0],{'status':'conflict'},proposal,lines)[0] is None

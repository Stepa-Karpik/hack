from scripts.unified.literal_layout import separate_empty_labels


def test_general_empty_label_pairs_preserve_characters_and_offsets():
    for pair in ['Начало периода обучения: Окончание периода обучения:',
                 'ФИО студента:   Название вуза:', 'Номер справки: Дата выдачи:']:
        text='СПРАВКА ОБ ОБУЧЕНИИ\n'+pair+'\nДата выдачи: 03.04.2032'
        after,edits=separate_empty_labels(text)
        assert len(edits)==1
        assert len(after)==len(text)
        assert after.replace('\n',' ').split()==text.replace('\n',' ').split()
        assert after.index('03.04.2032')==text.index('03.04.2032')
        assert not edits[0]['geometry_verified']


def test_never_split_values_examples_unknown_or_duplicate_labels():
    for line in ['Начало периода обучения: 01.09.2031 Окончание периода обучения:',
                 'Начало периода обучения: Окончание периода обучения: 30.06.2035',
                 'Пример: Начало периода обучения: Окончание периода обучения:',
                 'ФИО студента: «Название вуза:»', 'Контакт: Дата выдачи:',
                 'Дата выдачи: Дата выдачи:', 'Начало периода обучения:Окончание периода обучения:']:
        text='СПРАВКА ОБ ОБУЧЕНИИ\n'+line
        assert separate_empty_labels(text)==(text,[])
    text='СПРАВКА\nНачало периода обучения: Окончание периода обучения:'
    assert separate_empty_labels(text)==(text,[])

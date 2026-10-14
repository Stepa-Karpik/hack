import random

from scripts.unified.grade_natural import blank_labels, distance, entities, filled_blank, norm
from scripts.unified.prepare_natural_pages import FAMILIES, HELDOUT, Pools, clean_name, sentences, valid
from scripts.unified.train_natural_v5 import v5_target


def test_target_joins_wrapped_lines_per_block_and_column():
    row = {'lines': ['ЗАГОЛОВОК', 'первая строка', 'продолжение', 'Поле: 1', 'кол2'],
           'line_blocks': [[0, 'title', 0], [1, 'para', 0], [1, 'para', 0], [2, 'field', 0], [1, 'para', 1]]}
    assert v5_target(row, 'paragraphs') == 'ЗАГОЛОВОК\n\nпервая строка продолжение\n\nПоле: 1\n\nкол2'
    assert v5_target(row, 'lines') == '\n'.join(row['lines'])


def test_heldout_families_are_real_subset():
    assert HELDOUT < set(FAMILIES) and len(set(FAMILIES) - HELDOUT) >= 20


def test_name_cleaning_and_people():
    assert clean_name('Ива́нов') == 'Иванов'
    assert clean_name('Smith') is None
    pools = Pools(['Иванов', 'Петровский'], [['Первое предложение достаточно длинное.']], random.Random(1))
    for _ in range(20):
        assert pools.person().strip()


def test_sentence_filter_drops_headings_and_broken_links():
    text = 'История\nОн родился в Казани в 1901 году и учился в гимназии. Позже работал с продюсером .\nКороткий'
    assert sentences(text) == ['Он родился в Казани в 1901 году и учился в гимназии.']


def test_valid_rejects_overlap_and_clipping():
    assert valid(['a', 'b'], [[0, 0, 10, 10], [0, 20, 10, 30]], 100, 100)
    assert not valid(['a', 'b'], [[0, 0, 10, 10], [5, 5, 15, 15]], 100, 100)
    assert not valid(['a'], [[0, 0, 120, 10]], 100, 100)


def test_grading_helpers():
    assert distance('кот', 'кит') == 1 and distance('', 'abc') == 3
    assert norm('**Итог**\n=====\n  «Да»', markdown=True) == 'Итог "Да"'
    found = entities('Выдана Иванову: Петров Иван Сергеевич, 01.09.2026, № СО-12345')
    assert 'Петров Иван Сергеевич' in found['names'] and '01.09.2026' in found['dates']
    assert any('12345' in c for c in found['codes'])
    assert blank_labels(['Курс:', 'Группа: А-1', 'Подпись —']) == ['Курс', 'Подпись']
    assert filled_blank('Курс: 3\nГруппа: А-1', 'Курс') == '3'
    assert filled_blank('Курс:\nГруппа: А-1', 'Курс') is None


def test_label_run_separator_is_whitespace_only():
    from scripts.unified.literal_layout import separate_label_runs
    from scripts.unified.text_binding import bind
    text = ('СПРАВКА ОБ ОБУЧЕНИИ\nФорма обучения: очная\n'
            'Начало периода обучения: Окончание периода обучения: Номер справки: УК-1\nДата выдачи:')
    split, edits = separate_label_runs(text)
    assert len(split) == len(text) and len(edits) == 2
    assert bind(split)['fields']['document_number'] == 'УК-1'
    assert bind(text)['fields']['document_number'] is None
    repeated = 'СПРАВКА ОБ ОБУЧЕНИИ\nНомер справки: Номер справки: УК-1'
    assert separate_label_runs(repeated) == (repeated, [])
    untitled = 'Начало периода обучения: Номер справки: УК-1'
    assert separate_label_runs(untitled) == (untitled, [])
    value_first = 'СПРАВКА ОБ ОБУЧЕНИИ\nпримечание Номер справки: УК-1 Дата выдачи: 01.01.2030'
    assert separate_label_runs(value_first)[1] == []


def test_field_regions_from_spotting_lines():
    from scripts.unified.field_regions import field_regions
    loc = lambda *v: ''.join(f'<|LOC_{x}|>' for x in v)
    text = ('08.10.2026 № 04-17/286' + loc(146, 220, 343, 220, 343, 236, 146, 236)
            + 'Обучается по программе бакалавриата 38.03.01' + loc(199, 388, 931, 388, 931, 406, 199, 406)
            + 'Экономика. Форма обучения: очная.' + loc(146, 410, 931, 410, 931, 428, 146, 428))
    fields = {'issue_date': '2026-10-08', 'document_number': '04-17/286', 'program': 'бакалавриата 38.03.01 Экономика',
              'student_name': 'не найдено', 'signature_present': True}
    got = {r['field']: r['bbox'] for r in field_regions(text, fields)}
    assert got['issue_date'] == got['document_number'] == [0.146, 0.22, 0.343, 0.236]
    assert got['program'] == [0.146, 0.388, 0.931, 0.428]
    assert 'student_name' not in got and 'signature_present' not in got

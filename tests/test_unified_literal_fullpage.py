from scripts.unified.prepare_literal_fullpage import page_lines, boxes_valid
from scripts.unified.grade_literal_fullpage import line_flags, blank_fills


def test_blank_page_has_literal_blank_targets_without_borrowing():
    lines, name, blank = page_lines(202641000, 0)
    assert blank and len(lines) == 12
    assert 'ФИО студента: ' in lines
    assert 'Курс: ' in lines
    assert all(name not in line for line in lines)
    assert len({page_lines(202641000 + i, i)[1] for i in range(72)}) == 72


def test_visible_box_boundary_guard_rejects_clip_and_overlap():
    assert boxes_valid([[1, 2, 100, 20], [2, 22, 100, 40]], 120, 60)
    assert not boxes_valid([[1, 2, 100, 20], [2, 19, 100, 40]], 120, 60)
    assert not boxes_valid([[1, 2, 121, 20]], 120, 60)


def test_blank_label_substring_is_not_a_correct_empty_field():
    target = {'expected_lines': ['ФИО студента: ', 'Курс: ']}
    prediction = {'raw': 'ФИО студента: Фамилия Имя\nКурс: 3', 'token_budget_reached': False}
    assert line_flags(target, prediction) == [False, False]
    assert blank_fills(target, prediction) == ['ФИО студента:', 'Курс:']
    assert line_flags(target, {'raw': 'ФИО студента:\nКурс:', 'token_budget_reached': False}) == [True, True]

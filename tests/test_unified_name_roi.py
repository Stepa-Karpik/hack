from scripts.unified.name_roi import accept


AUDIT = {'status': 'uncertain', 'source': 'single_network_ocr_explicit_label'}


def test_only_bounded_uncertain_surname_can_change():
    old, new = 'Тарновска Алёна Витальевна', 'Тарновская Алёна Витальевна'
    assert accept(old, AUDIT, [new, new])[0] == new
    assert accept(old, {**AUDIT, 'status': 'found'}, [new, new])[0] is None
    assert accept(old, {**AUDIT, 'status': 'conflict'}, [new, new])[0] is None
    assert accept(None, AUDIT, [new, new])[0] is None


def test_prefix_tail_disagreement_and_multiple_edits_rejected():
    old = 'Тарновска Алёна Витальевна'
    for a, b in [('Тарновская Алёна Витальевна', 'Тарновскай Алёна Витальевна'),
                 ('Карновска Алёна Витальевна', 'Карновска Алёна Витальевна'),
                 ('Тарновска Инна Витальевна', 'Тарновска Инна Витальевна'),
                 ('Тарновский Алёна Витальевна', 'Тарновский Алёна Витальевна')]:
        assert accept(old, AUDIT, [a, b])[0] is None


def test_two_views_cannot_overrule_disagreeing_whole_line():
    from scripts.unified.name_roi_three_views import accept_three
    old, new = 'Тарновска Алёна Витальевна', 'Тарновская Алёна Витальевна'
    assert accept_three(old, AUDIT, [new, new], 'ФИО руководителя практики: '+new, 'supervisor_name')[0] == new
    assert accept_three(old, AUDIT, [new, new], 'ФИО руководителя практики: '+old, 'supervisor_name')[0] is None
    assert accept_three(old, AUDIT, [new, new], 'Контакт: '+new, 'supervisor_name')[0] is None

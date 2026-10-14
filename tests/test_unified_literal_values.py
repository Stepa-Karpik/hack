from scripts.unified.grade_literal_values import values
from scripts.unified.prepare_literal_values import design


def test_value_losses_wrong_changes_and_blank_fills_are_separate():
    target = dict(image='fictional.png', sha256='sha', document_type='study_certificate',
                  printed_fields={'student_name': 'Иван Примеров', 'document_number': 'УК-15', 'issue_date': ''})
    before = dict(rows=[dict(input_sha256='sha', token_budget_reached=False,
                            raw='СПРАВКА ОБ ОБУЧЕНИИ\nФИО студента: Иван Примеров\nНомер справки: УК-10\nДата выдачи:')])
    after = dict(rows=[dict(input_sha256='sha', token_budget_reached=False,
                           raw='СПРАВКА ОБ ОБУЧЕНИИ\nФИО студента: Иван Примерев\nНомер справки: УК-11\nДата выдачи: 01.02.2032')])
    counts = values([target], before, after)['counts']
    assert counts['present'] == 2
    assert counts['lost_correct'] == 1
    assert counts['changed_wrong'] == 1
    assert counts['new_correct'] == 0
    assert counts['before_false_blank_fills'] == 0
    assert counts['after_false_blank_fills'] == 1


def test_controls_cross_date_and_blank_for_each_schema():
    for split, repetitions in [('train', 4), ('val', 1), ('test', 1)]:
        factors = design(split)
        for kind in {r[0] for r in factors}:
            for date in range(4):
                for blank in range(4):
                    assert sum(r[:3] == (kind, date, blank) for r in factors) == repetitions

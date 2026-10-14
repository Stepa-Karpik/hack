import copy

from scripts.participantkit.service import prepare_result as old_prepare
from scripts.participantkit.service_prose import prepare_result
from tests.test_leave_prose_experiment import fixture


def test_api_returns_literal_values_sources_and_uncertainty_without_mutation():
    _, _, analysis = fixture()
    snapshot = copy.deepcopy(analysis)
    questions = [{'question_id': 'date', 'question': 'Какова дата заявления?'},
                 {'question_id': 'unknown', 'question': 'Какого цвета глаза студента?'}]
    result, audit = prepare_result(None, analysis, 'academic_leave_application', questions,
        crop_recovery=False, value_quote_recovery=False)
    assert result['fields']['student_name'] == 'Лаптевой Марии Денисовны'
    assert result['fields']['application_date'] == '2028-02-14'
    assert result['fields']['course'] == 'не найдено'
    assert result['answers'][0]['sources'] == ['field:application_date']
    assert result['answers'][1]['answerable'] is False
    assert audit['bindings']['student_name']['status'] == 'uncertain'
    assert audit['bindings']['student_name']['semantic_confidence'] is None
    assert analysis == snapshot


def test_disabled_revision_equals_legacy_result_and_nonempty_is_preserved():
    _, _, analysis = fixture()
    args = {'crop_recovery': False, 'value_quote_recovery': False}
    old, _ = old_prepare(None, analysis, 'academic_leave_application', [], **args)
    new, _ = prepare_result(None, analysis, 'academic_leave_application', [], prose_recovery=False, **args)
    assert new == old
    analysis['fields']['student_name'] = {'value': 'Сохранённое буквальное значение', 'status': 'found'}
    new, _ = prepare_result(None, analysis, 'academic_leave_application', [], **args)
    assert new['fields']['student_name'] == 'Сохранённое буквальное значение'


def test_upload_boundary_uses_revision_and_exposes_uncertain_document_region(monkeypatch):
    from PIL import Image
    import dekanat.pipeline
    from scripts.participantkit.service_prose import analyze_web_document
    _, _, analysis = fixture()
    routed = []
    def fake_analyze(data, filename, document_type, gpu):
        routed.append(document_type)
        return [Image.new('RGB', (1000, 1000), 'white')], analysis
    monkeypatch.setattr(dekanat.pipeline, 'analyze', fake_analyze)
    response = analyze_web_document(b'unit-upload', 'fixture.png', 'academic_leave_application', [], gpu=False)
    assert routed == ['leave']
    assert response['version'] == 'official-contract-prose-candidate-v8'
    assert response['result']['fields']['student_name'] == 'Лаптевой Марии Денисовны'
    region = next(r for r in response['document_view']['regions'] if r['field'] == 'student_name')
    assert region['status'] == 'uncertain' and region['semantic_confidence'] is None

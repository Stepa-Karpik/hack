from scripts.evaluate_field_abstention import evaluate_rule, region_quality
from PIL import Image


def test_threshold_gate_counts_correct_found_loss_and_preserves_uncertain():
    rows = [dict(condition='blur', status='found', correct=False, confidence=.7),
            dict(condition='blur', status='found', correct=True, confidence=.8),
            dict(condition='clean', status='uncertain', correct=True, confidence=.3)]
    safe = evaluate_rule(rows, 'confidence', .8)
    assert safe['wrong_rejected'] == 1 and safe['correct_found_lost'] == 0
    assert safe['passes_zero_correct_loss_gate']
    unsafe = evaluate_rule(rows, 'confidence', .9)
    assert unsafe['correct_found_lost'] == 1 and not unsafe['passes_zero_correct_loss_gate']
    assert rows[0]['status'] == 'found'


def test_empty_or_invalid_regions_do_not_become_zero_quality():
    image = Image.new('RGB', (20, 20), 'white')
    for evidence in [None, {'page': 9, 'bbox': [0, 0, 10, 10]}, {'page': 0, 'bbox': [30, 30, 40, 40]}]:
        assert region_quality([image], evidence)['minimum_sharpness'] is None


def test_multiline_regions_are_measured_separately_and_clamped():
    image = Image.new('RGB', (20, 20), 'white')
    evidence = {'parts': [{'page': 0, 'bbox': [-3, -2, 15, 8]}, {'page': 0, 'bbox': [0, 10, 25, 25]}]}
    quality = region_quality([image], evidence)
    assert quality['minimum_height'] == 8
    assert [r['width'] for r in quality['regions']] == [15, 20]

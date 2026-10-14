import copy
import json
from pathlib import Path

import pytest

from scripts.experiments.grade_prose_metric_cohorts import qualify


def evidence():
    plan = json.loads((Path(__file__).resolve().parents[1]/'configs/narrative_regression.json').read_text())
    conditions = sorted({c['metric'].split('.')[1] for c in plan['checks'] if c['metric'].startswith('summary.')})
    specs = []
    for group, count in [('audit', 36), ('layout', 9)]:
        specs += [{'id': f'{group}/{i}', 'cohort': group, 'type': 'study', 'sha256': 'a'*64} for i in range(count)]
    specs += [{'id': f'camera/{c}/{k}', 'cohort': 'camera', 'condition': c,
              'type': k, 'sha256': 'a'*64} for c in conditions for k in ['study', 'leave', 'practice']]
    rows = [{'id': s['id'], 'input_sha256': s['sha256'], 'requested_type': s['type'],
             'before': {'fields': {'name': 'literal'}}, 'after': {'fields': {'name': 'literal'}}, 'changes': []} for s in specs]
    return {'complete': True, 'rows': rows}, {'rows': specs}, plan


def test_changed_literal_fails_without_hiding_in_average():
    report, evaluation, plan = evidence()
    assert qualify(report, evaluation, plan)['passed']
    report['rows'][0]['after']['fields']['name'] = 'incorrect'
    result = qualify(report, evaluation, plan)
    assert not result['passed']
    assert result['changed_results'] == 1


def test_incomplete_or_mismatched_sha_rejected():
    report, evaluation, plan = evidence()
    partial = copy.deepcopy(report); partial['complete'] = False
    with pytest.raises(ValueError, match='Complete 102'):
        qualify(partial, evaluation, plan)
    report['rows'][0]['input_sha256'] = 'b'*64
    with pytest.raises(ValueError, match='SHA mismatch'):
        qualify(report, evaluation, plan)

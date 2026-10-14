"""Verify calibration evidence and save a compact, non-deploying decision."""
import hashlib
import json
import sys
from pathlib import Path

from evaluate_field_abstention import evaluate_rule


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    report_path = root/'artifacts/field_abstention.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    baseline = json.loads((root/'artifacts/date_validation_after.json').read_text(encoding='utf-8'))
    expected = {(r['type'], r['condition'], key): field for r in baseline['rows'] for key, field in r['fields'].items()}
    actual = {(r['type'], r['condition'], r['field']): {'value': r['value'], 'status': r['status']} for r in report['rows']}
    assert actual == expected, 'Runtime output changed from the v8 regression baseline'
    for name, digest in report['runtime_sha256'].items():
        assert sha(root/'dekanat'/name) == digest, 'Runtime source changed'
    for name, digest in report['model_sha256'].items():
        assert sha(root/name) == digest, 'Deployed model changed'
    exploratory = []
    for field, metric, threshold in [('student_name', 'minimum_sharpness', 100), ('document_number', 'confidence', .65)]:
        result = evaluate_rule([r for r in report['rows'] if r['field'] == field], metric, threshold)
        exploratory.append({'field': field, **result,
                            'scope': 'Selected after inspecting these development results; requires fresh regression and target-photo validation. Not deployed.'})
    inputs = [root/f'data/demo/{kind}.{suffix}' for kind in ['study', 'leave', 'practice'] for suffix in ['png', 'json']]
    inputs += [root/'dekanat/photo_augment.py', root/'scripts/evaluate_field_abstention.py', root/'scripts/summarize_field_abstention.py', report_path]
    summary = {'baseline_value_status_match': True, 'deployed_models_and_runtime_unchanged': True,
               'fields': len(actual), 'correct_found': report['correct_found'], 'confident_wrong': report['confident_wrong'],
               'global_trials': len(report['trials']),
               'global_zero_correct_loss_candidates': [t for t in report['trials'] if t['passes_zero_correct_loss_gate']],
               'exploratory_field_specific': exploratory,
               'input_sha256': {str(p.relative_to(root)).replace('\\', '/'): sha(p) for p in inputs},
               'decision': 'All 22 global thresholds rejected. Two field-specific hypotheses remain development-only; no runtime or weight modification.',
               'limitations': 'Known synthetic development documents, not independent real student photos; field evidence may include labels or multiple rows; sharpness depends on content, font, box, scale and camera processing.'}
    (root/'artifacts/field_abstention_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(summary['decision'])


if __name__ == '__main__':
    main()

"""Stored boundary qualification of isolated service, without image inference.

Injects previously completed legacy preparation, not expected values. Uses
declared standard questions; does not reconstruct custom requests from answers.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from scripts.participantkit import service_prose as service


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--reports', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    old = service.legacy_prepare
    results = []
    try:
        for path in args.reports:
            report = json.loads(path.read_text(encoding='utf-8'))
            if not report.get('complete'):
                raise ValueError('Only completed prior inference')
            rows = report['rows']
            count, unsupported, mismatches = 0, 0, []
            for index, row in enumerate(rows):
                if row['before'] is None:
                    unsupported += 1
                    continue
                before, expected, audit = row['before'], row['after'], row['audit']
                analysis = audit['analysis']
                source = copy.deepcopy(analysis)
                questions = [{'question_id': 'complete', 'question': 'Содержит ли документ все обязательные сведения?'},
                             {'question_id': 'date', 'question': 'Какова дата заявления?'},
                             {'question_id': 'unknown', 'question': 'Какого цвета глаза студента?'}]
                # Preserve actual previous custom/kit answers without reading targets:
                # no request text in stored rows, so evaluate fields/validation and
                # the standard actual requests separately; do not fabricate requests.
                service.legacy_prepare = lambda *a, **kw: (copy.deepcopy(before), copy.deepcopy(audit))
                result, new_audit = service.prepare_result(None, analysis, before['document_type'], questions,
                    document_id=before['document_id'], crop_recovery=False, value_quote_recovery=False)
                count += 1
                if (result['fields'] != expected['fields'] or result['validation'] != expected['validation']
                        or new_audit['bindings'] != row['candidate_bindings'] or analysis != source):
                    mismatches.append(index)
            results.append({'source_report': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'input_count': len(rows), 'supported_boundaries': count, 'unsupported_noop': unsupported,
                'mismatches': mismatches})
    finally:
        service.legacy_prepare = old
    result = {'scope': 'Stored preparation boundary injected into new service wrapper; no fresh OCR, '
            'no expected target lookup, and no question text reconstructed from answers. '
            'Fields/validation/bindings compared to completed pure-candidate outputs.',
            'passed': not any(r['mismatches'] for r in results), 'reports': results}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

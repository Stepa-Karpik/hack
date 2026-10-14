"""Requalify stored actual main/ROI reads; no reference or expected word lookup."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from scripts.unified.name_roi_three_views import accept_three
from scripts.participantkit.format_v1 import validate
from scripts.participantkit.service import load_config


def main():
    p = argparse.ArgumentParser()
    for name in ['parent', 'roi', 'output']:
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    parent = json.loads(args.parent.read_text(encoding='utf-8'))
    roi = json.loads(args.roi.read_text(encoding='utf-8'))
    if not parent['complete'] or not roi['complete'] or roi['baseline_sha256'] != hashlib.sha256(args.parent.read_bytes()).hexdigest():
        raise ValueError('Completed source-linked reads required')
    originals = {r['input_sha256']: r for r in parent['rows']}
    if len(originals) != len(parent['rows']) or set(originals) != {r['input_sha256'] for r in roi['rows']}:
        raise ValueError('Actual input cohorts differ')
    config = load_config(); rows = []
    for record in roi['rows']:
        row = copy.deepcopy(originals[record['input_sha256']])
        result = row['result']; evidence = []
        for old_evidence in record['name_roi']['evidence']:
            item = copy.deepcopy(old_evidence); field = item['field']
            regions = item['geometry'].get('regions', [])
            whole = regions[0]['text'] if len(regions) == 1 else None
            candidate, reason = accept_three(result['fields'][field], result['audit'][field],
                [None if r['truncated'] else r['raw'] for r in item['readings']], whole, field)
            item.update(proposal=candidate, reason=reason)
            evidence.append(item)
            if candidate is not None:
                result['fields'][field] = candidate
                result['audit'][field] = copy.deepcopy(record['result']['audit'][field])
                result['audit'][field]['source'] = 'single_network_name_roi_three_context_consensus'
        if result is not None:
            result['validation'] = validate(result['fields'], result['document_type'], config)
        row['name_roi'] = {**record['name_roi'], 'evidence': evidence, 'policy': 'three_context_agreement'}
        rows.append(row)
    output = {k: v for k, v in roi.items() if k != 'rows'}
    output.update(rows=rows, scope='Stored replay of completed actual frozen main+same-base ROI inference. '
        'Three-context agreement developed after a false consensus; same viewed development set, '
        'not new inference or independent evidence.', roi_source_sha256=hashlib.sha256(args.roi.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Three-context accepted', sum(e['proposal'] is not None for r in rows for e in r['name_roi']['evidence']))


if __name__ == '__main__':
    main()

"""Post-inference feature/device comparison on a fixed fictional subset only."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--reports', type=Path, nargs=4, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists(): raise ValueError('Fresh comparison required')
    import numpy as np
    sha = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    reports, values = {}, {}
    for file in args.reports:
        d = json.loads(file.read_text(encoding='utf-8'))
        if not d['complete'] or len(d['rows']) != 4: raise ValueError('Complete fixed four-image probe required')
        key = d['device']+'-'+d['precision']+'-'+str(d['tf32_matmul_allowed']).lower()
        if key in reports: raise ValueError('Duplicate profile')
        arrays = file.with_suffix('.features.npz')
        if sha(arrays) != d['features_sha256']: raise ValueError('Feature archive hash mismatch')
        values[key] = {}
        with np.load(arrays, allow_pickle=False) as z:
            for row in d['rows']:
                vector = z[row['features_key']]
                if (vector.shape != (20736,) or not np.isfinite(vector).all()
                        or hashlib.sha256(vector.tobytes()).hexdigest() != row['feature_sha256']):
                    raise ValueError('Invalid saved feature vector')
                if row['input_sha256'] in values[key]: raise ValueError('Duplicate image')
                values[key][row['input_sha256']] = vector.copy()
        reports[key] = d
    if set(reports) != {'cpu-fp32-false','cuda-fp32-false','cuda-fp32-true','cuda-bf16-false'}:
        raise ValueError('All fixed device/precision profiles required')
    baseline = reports['cuda-fp32-false']
    # Targets are loaded only after all predictions and feature integrity checks.
    truth = {r['sha256']: r['target']['fields'] for r in
             [json.loads(line) for line in (args.data/'val.jsonl').read_text(encoding='utf-8').splitlines()]}
    grades, comparisons = {}, {}
    for key, d in reports.items():
        if (d['base_weight_sha256'] != baseline['base_weight_sha256'] or d['head_sha256'] != baseline['head_sha256']
                or set(values[key]) != set(values['cuda-fp32-false'])): raise ValueError('Model/cohort mismatch')
        correct = total = 0
        for row in d['rows']:
            fields = truth[row['input_sha256']]
            for mark, actual in row['prediction'].items():
                if mark in fields:
                    if type(fields[mark]) is not bool or type(actual) is not bool: raise ValueError('Boolean marks required')
                    total += 1; correct += actual == fields[mark]
        grades[key] = {'correct': correct,'required_marks': total,'documents':4}
        pairs=[]
        for before, after in zip(baseline['rows'], d['rows']):
            for field in ['input_sha256','decoded_rgb_sha256','processor_pixels_sha256','image_grid_thw']:
                if before[field] != after[field]: raise ValueError('Actual processor input differs')
            a,b=values['cuda-fp32-false'][before['input_sha256']],values[key][after['input_sha256']]
            diff=b.astype(np.float64)-a.astype(np.float64)
            pairs.append({'input_sha256':before['input_sha256'],'features_exact':np.array_equal(a,b),
                'feature_max_abs_delta':float(np.abs(diff).max()),'feature_relative_l2':float(np.linalg.norm(diff)/np.linalg.norm(a.astype(np.float64))),
                'score_max_abs_delta':max(abs(x-y) for x,y in zip(before['scores'],after['scores'])),
                'raw_bits_changed':sum(before['prediction'][k]!=after['prediction'][k] for k in before['prediction'])})
        comparisons[key]=pairs
    output={'scope':'Four previously viewed fictional val PNG, shared renderer; numerical component diagnostic, not independent accuracy/full OCR/app/server benchmark. TF32 flags explicitly set; no fitting or threshold selection.',
        'grades':grades,'comparisons_vs_cuda_fp32_tf32_off':comparisons,'source_sha256':{f.name:sha(f) for f in args.reports},
        'reference_sha256':sha(args.data/'val.jsonl'),'promoted':False,'training':False}
    args.output.write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({'grades':grades,'deltas':{k:{'features_max_abs':max(p['feature_max_abs_delta'] for p in v),'score_max_abs':max(p['score_max_abs_delta'] for p in v),'bits_changed':sum(p['raw_bits_changed'] for p in v)} for k,v in comparisons.items()}}))


if __name__ == '__main__':
    main()

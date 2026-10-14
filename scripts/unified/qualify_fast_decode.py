"""Identity qualification of the graph-captured decoder against stored `generate` runs.

Re-reads every input with the persistent reader (fast path) and requires the
OCR text, binding, graphic scores and marks to equal the stored outputs of the
standard decoder for the same weights. Also stores per-token confidences for
later calibration. No targets are read here.
"""
import argparse
import json
import time
from pathlib import Path

from scripts.unified.native_worker import Reader


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--stored', type=Path, nargs='+', required=True, help='Stored run JSON(s) with rows[].file/raw')
    p.add_argument('--roots', type=Path, nargs='+', required=True, help='Folders containing the inputs')
    p.add_argument('--adapter', default='models/unified-experimental-natural-v5')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    reader = Reader('work/paddle-vl-base-v1', 'models/unified-experimental-graphic-head-fp32-v3',
                    args.adapter, 'cuda', 6, swap=False)
    tmp = args.output.with_suffix('.tmp')
    tmp.mkdir(parents=True, exist_ok=True)
    rows, stats = [], {'inputs': 0, 'raw_equal': 0, 'binding_equal': 0, 'marks_equal': 0, 'max_score_delta': 0.0,
                       'fast': 0, 'seconds': []}
    for stored_path in args.stored:
        stored = json.loads(stored_path.read_text(encoding='utf-8'))
        for old in stored['rows']:
            name = Path(old['file']).name
            source = next((root / name for root in args.roots if (root / name).exists()), None)
            if source is None:
                raise FileNotFoundError(name)
            out = tmp / (stored_path.stem + '-' + name + '.json')
            for stale in (out, out.with_suffix('.headfeatures.npz')):
                stale.unlink(missing_ok=True)
            started = time.perf_counter()
            row = reader.read(source, out)['rows'][0]
            elapsed = time.perf_counter() - started
            old_raw = old.get('raw_ocr', old.get('raw'))
            equal = row['raw_ocr'] == old_raw
            stats['inputs'] += 1
            stats['raw_equal'] += equal
            stats['fast'] += row['decoder'] == 'cuda_graph_static_cache'
            stats['seconds'].append(round(elapsed, 2))
            if 'binding' in old:
                stats['binding_equal'] += row['binding'] == old['binding']
                stats['marks_equal'] += row['graphic_prediction'] == old['graphic_prediction']
                stats['max_score_delta'] = max(stats['max_score_delta'], max(
                    abs(a - b) for a, b in zip(row['graphic_scores_uncalibrated'], old['graphic_scores_uncalibrated'])))
            rows.append({'set': stored_path.stem, 'file': name, 'raw_equal': equal, 'raw': row['raw_ocr'],
                         'token_confidence': row['token_confidence'], 'seconds': round(elapsed, 2)})
            print(stored_path.stem, name, 'EQUAL' if equal else 'DIFF', round(elapsed, 1), flush=True)
    s = stats['seconds']
    stats['seconds'] = {'mean': round(sum(s) / len(s), 2), 'max': max(s), 'min': min(s)}
    args.output.write_text(json.dumps({'stats': stats, 'rows': rows}, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(stats))


if __name__ == '__main__':
    main()

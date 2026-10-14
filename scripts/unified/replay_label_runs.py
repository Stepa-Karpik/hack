"""Stored replay of separate_label_runs (layout v2) over completed runs; no NN calls.

Writes derived copies whose `raw` (OCR runs) or `binding` (kit runs) reflect
the logical split, keeps the original text under `raw_unsplit`, and records
every edit. Raw model outputs stay untouched for separate reporting.
"""
import argparse
import json
from pathlib import Path

from scripts.unified.literal_layout import separate_label_runs
from scripts.unified.text_binding import bind


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--kit', action='store_true', help='Rows carry binding/raw_ocr (run_graphic_strict format)')
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output required')
    data = json.loads(args.input.read_text(encoding='utf-8'))
    edits = 0
    for row in data['rows']:
        raw = row['raw_ocr'] if args.kit else row['raw']
        split, changes = separate_label_runs(raw)
        row['layout_v2_edits'] = changes
        edits += len(changes)
        if args.kit:
            if changes and not row['token_budget_reached']:
                row['raw_unsplit'] = raw
                row['binding'] = bind(split, truncated=row['token_budget_reached'])
        else:
            row['raw_unsplit'] = raw
            row['raw'] = split
    data['layout_v2'] = {'edits': edits, 'scope': 'Stored replay of whitespace-only logical split; post-selection'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(args.input.name, 'edits', edits)


if __name__ == '__main__':
    main()

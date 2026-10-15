"""results.json for an organizer check set (documents.json + questions.json), same engines as the app.

    python -m scripts.app.make_results --kit <folder> --output results.json [--engine auto|gpu|cpu] [--variant image|pdf]

The document type comes from the manifest (as the case allows). Every document and question is
processed; answers use the deterministic rules of the case (value/answerable/sources). Reference
answers are never read here: grade separately with the organizers' evaluate.py.
"""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.app.pipeline import analyze, analyze_fast  # noqa: E402
from scripts.app.processing import FastReader, Reader, cuda_available  # noqa: E402
from scripts.participantkit.format_v1 import answer  # noqa: E402
from scripts.unified.contract import CONFIG  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True, help='Folder with documents.json, questions.json and the documents')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--engine', choices=['auto', 'gpu', 'cpu'], default='auto')
    p.add_argument('--variant', default='auto', help='Manifest file key to read (image/pdf/...); auto = first present')
    p.add_argument('--base', default='work/paddle-vl-base-v1')
    p.add_argument('--head', default='models/unified-experimental-graphic-head-fp32-v3')
    p.add_argument('--adapter', default='models/unified-experimental-natural-v5')
    p.add_argument('--mark-head', default='models/unified-experimental-mark-patches-v1')
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists: choose a new path (previous results are kept)')
    manifest = json.loads((args.kit / 'documents.json').read_text(encoding='utf-8'))
    questions = json.loads((args.kit / 'questions.json').read_text(encoding='utf-8')) if (args.kit / 'questions.json').exists() else []
    engine = 'cpu' if args.engine == 'auto' else args.engine
    work = Path(tempfile.mkdtemp(prefix='results-'))
    reader = (Reader(args.base, args.head, args.adapter, work, gpu=True, mark_head=args.mark_head) if engine == 'gpu'
              else FastReader(work))
    reader.ensure()
    documents, times = [], []
    for i, record in enumerate(manifest):
        key = args.variant if args.variant != 'auto' else next(k for k in ('image', 'pdf', 'file', 'path') if k in record)
        source = (args.kit / record[key]).resolve()
        kind = record['document_type']
        output = work / f'{i:04d}' / 'native-result.json'
        output.parent.mkdir()
        started = time.perf_counter()
        reader.run('ocr', source, output, document_type=kind)
        row = json.loads(output.read_text(encoding='utf-8'))['rows'][0]
        analysis = analyze_fast(row, kind) if row.get('engine') == 'cpu-fast' else analyze(row, kind)
        times.append(time.perf_counter() - started)
        fields, validation = analysis['fields'], analysis['validation']
        answers = []
        for q in questions:
            if q['document_id'] != record['document_id']:
                continue
            a = answer(q['question'], fields, validation, CONFIG)
            answers.append({'question_id': q['question_id'], 'answerable': a['answerable'], 'value': a['value'],
                            'answer': a['answer'], 'sources': a['sources']})
        documents.append({'document_id': record['document_id'], 'document_type': kind, 'fields': fields,
                          'validation': validation, 'answers': answers})
        print(f"{record['document_id']} {times[-1]:.1f}s {validation['status']} {validation['missing_fields']}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'version': '1.0', 'documents': documents}, ensure_ascii=False, indent=1), encoding='utf-8')
    warm = times[1:] or times
    print(f'{len(documents)} documents, engine={engine}, mean {sum(warm) / len(warm):.2f} s, max {max(warm):.2f} s -> {args.output}')


if __name__ == '__main__':
    main()

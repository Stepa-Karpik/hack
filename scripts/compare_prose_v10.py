"""Paired evidence gate for viewed realistic PDFs and previous font/camera cohort."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT
from dekanat.extraction import normalize
from scripts.compare_field_structure import compare, flatten


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--before',default='realistic_documents_before_prose.json')
    parser.add_argument('--after',default='realistic_documents_after_prose.json')
    parser.add_argument('--fonts-before',default='field_structure_fresh_after.json')
    parser.add_argument('--fonts-after',default='prose_fresh_after.json')
    parser.add_argument('--output',default='prose_v10_gate.json')
    args=parser.parse_args()
    artifacts=ROOT/'artifacts'
    def read(name):
        return json.loads((artifacts/name).read_text(encoding='utf-8'))
    truth={r['stem']:r['expected_fields'] for r in read('realistic_documents_truth.json')['records']}
    before,after=(read(name)['rows'] for name in [args.before,args.after])
    assert len(before)==len(after)==10
    summary={k:dict(total=0,correct=0,correct_found=0,confident_wrong=0) for k in ['before','after']}
    lost,changes=[],[]
    for old,new in zip(before,after):
        assert (old['file'],old['sha256'])==(new['file'],new['sha256'])
        if not old['file'].endswith('.pdf'):
            continue
        for key,expected in truth[Path(old['file']).stem].items():
            if isinstance(expected,bool):
                continue
            fields=[row['analysis']['fields'][key] for row in [old,new]]
            correct=[f['value'] is not None and normalize(str(f['value']))==normalize(str(expected)) for f in fields]
            for label,f,ok in zip(['before','after'],fields,correct):
                c=summary[label];c['total']+=1;c['correct']+=ok;c['correct_found']+=ok and f['status']=='found';c['confident_wrong']+=not ok and f['status']=='found'
            if correct[0] and fields[0]['status']=='found' and not(correct[1] and fields[1]['status']=='found'):
                lost.append([old['file'],key])
            if (fields[0]['value'],fields[0]['status'])!=(fields[1]['value'],fields[1]['status']):
                changes.append(dict(file=old['file'],field=key,before=fields[0],after=fields[1]))
    realistic={'summary':summary,'correct_found_lost':lost,'changes':changes,
               'passed':not lost and summary['after']['correct']>=summary['before']['correct'] and summary['after']['confident_wrong']<=summary['before']['confident_wrong']}
    fresh=compare(flatten(read(args.fonts_before),True),flatten(read(args.fonts_after),True))
    report={'scope':'Viewed development cohorts: six own realistic PDFs/42 fields (strict normalized semantic strings), previous six-font documents under 22 conditions/924 fields. Not independent or real-student accuracy. Source-matching actual inference; no weight training.',
            'passed':realistic['passed'] and fresh['passed'],'realistic':realistic,'previous_fonts_camera':fresh}
    (artifacts/args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'realistic':summary,'realistic_correct_found_lost':lost,
                      'fonts_camera_passed':fresh['passed'],'fonts_camera_correct_found_lost':fresh['correct_found_lost']},ensure_ascii=False,indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()

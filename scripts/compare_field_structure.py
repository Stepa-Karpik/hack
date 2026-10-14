"""Paired value/status gate, including loss of previously correct found fields."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dekanat.extraction import normalize


def compare(before, after):
    assert set(before) == set(after), 'Cohorts differ'
    groups, differences, lost = {}, [], []
    for identity, old in before.items():
        new = after[identity]
        condition = identity[1]
        group = groups.setdefault(condition, {'before_correct':0, 'after_correct':0,
                                               'before_confident_wrong':0, 'after_confident_wrong':0})
        for prefix, row in [('before', old), ('after', new)]:
            group[prefix+'_correct'] += bool(row['correct'])
            group[prefix+'_confident_wrong'] += row['status']=='found' and not row['correct']
        if old['correct'] and old['status']=='found' and not (new['correct'] and new['status']=='found'):
            lost.append(identity)
        if (old['value'], old['status']) != (new['value'], new['status']):
            differences.append({'identity':identity, 'before':old, 'after':new})
    passed = not lost and all(g['after_correct']>=g['before_correct'] and g['after_confident_wrong']<=g['before_confident_wrong'] for g in groups.values())
    return {'passed':passed, 'fields':len(before), 'correct_found_lost':lost, 'conditions':groups, 'differences':differences}


def flatten(report, fresh):
    result = {}
    for row in report['rows']:
        if fresh:
            result[(row['document'], row['condition'], row['field'])] = {k:row[k] for k in ['value','status','correct']}
        else:
            truth = json.loads((ROOT/f"data/demo/{row['type']}.json").read_text(encoding='utf-8'))['fields']
            for key, field in row['fields'].items():
                result[(row['type'], row['condition'], key)] = {**field, 'correct':field['value'] is not None and normalize(str(field['value']))==normalize(str(truth[key]))}
    return result


def main():
    comparisons = {}
    for name, before, after, fresh in [
        ('known', 'date_validation_after.json', 'field_structure_known_after.json', False),
        ('fresh', 'field_abstention_fresh.json', 'field_structure_fresh_after.json', True)]:
        reports = [json.loads((ROOT/'artifacts'/p).read_text(encoding='utf-8')) for p in [before, after]]
        comparisons[name] = compare(*(flatten(r, fresh) for r in reports))
    report = {'passed':all(r['passed'] for r in comparisons.values()), 'groups':comparisons,
              'scope':'Known and viewed fresh synthetic diagnostics only. Values plus statuses, zero loss of previously correct found, correct and confident-wrong gate per condition.'}
    (ROOT/'artifacts/field_structure_comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({name:{k:v for k,v in r.items() if k!='differences'} for name,r in comparisons.items()}, ensure_ascii=False))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

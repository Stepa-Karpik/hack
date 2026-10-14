"""Run held-out dialogues against one local model and grade every turn."""
import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

from scripts.assistant.core import Assistant, _dates, _norm, grounding_problems
from scripts.assistant.eval_set import build, stored_contexts
from scripts.unified.contract import CONFIG

KEYWORDS = {'student_name': 'фио', 'university': 'вуз', 'program': 'направлен', 'study_form': 'форм',
            'study_start': 'начал', 'study_end': 'окончан', 'document_number': 'номер', 'issue_date': 'выдач',
            'group': 'групп', 'course': 'курс', 'leave_reason': 'причин', 'leave_start': 'начал',
            'leave_end': 'окончан', 'application_date': 'заявлен', 'organization': 'организац',
            'internship_start': 'начал', 'internship_end': 'окончан', 'supervisor_name': 'руководител',
            'grade': 'оценк', 'signature_present': 'подпис', 'seal_present': 'печат'}
NEGATIVE = re.compile(r'не\s+(обнаружен|найден|стоит|видн|поставлен|подписан)|\bнет\b|отсутств|без\s+(подпис|печат)')


def value_in(answer, value):
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return value in _dates(answer)
    a, v = _norm(answer), _norm(value).strip(' «»"')
    if v in a:
        return True
    words = v.split()
    return len(words) > 1 and all(w[:max(3, len(w) - 2)] in a for w in words)


def grade(turn, reply, result, ocr_text, today):
    checks = {}
    kinds = set(turn['kinds'])
    if 'found' in kinds:
        kinds.add('text')
    checks['kind'] = reply['kind'] in kinds
    if turn.get('dates_all'):
        # Listing every candidate date is an acceptable alternative to a clarifying question.
        checks['kind'] = checks['kind'] or set(turn['dates_all']) <= _dates(reply['answer'])
    if 'must_value' in turn:
        checks['value'] = value_in(reply['answer'], turn['must_value'])
    if 'polarity' in turn:
        word = 'подпис' if 'signature_present' in turn['fields_any'] else 'печат'
        clauses = [c for c in re.split(r'[.;,]|\bно\b|\bа\b', _norm(reply['answer'])) if word in c] or [_norm(reply['answer'])]
        if turn['polarity']:
            # A detected mark must not be described as missing in any clause about it.
            checks['polarity'] = not any(NEGATIVE.search(c) for c in clauses)
        else:
            checks['polarity'] = bool(NEGATIVE.search(_norm(reply['answer'])))
    if 'fields_any' in turn:
        checks['source'] = bool(set(turn['fields_any']) & set(reply['fields']))
    if 'rules_any' in turn and turn['rules_any']:
        checks['rule_source'] = bool(set(turn['rules_any']) & set(reply['rules']))
    if 'must_missing' in turn:
        text = _norm(reply['answer'])
        checks['missing_listed'] = all(KEYWORDS[k] in text for k in turn['must_missing'])
        if not turn['must_missing']:
            checks['missing_listed'] = not re.search(r'не\s+хватает|отсутству', text)
    checks['grounded'] = not grounding_problems(reply['answer'], reply['kind'], result, ocr_text, today)
    checks['not_withdrawn'] = not reply['engine']['guard_withdrawn'] or not ({'found', 'computed'} & set(turn['kinds']))
    return checks


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--stored', default='work/unified-literal-values-fp32-lora-v4/kit60.json')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int)
    p.add_argument('--stride', type=int, default=1)
    p.add_argument('--cpu', action='store_true')
    p.add_argument('--today', default='2026-10-14')
    args = p.parse_args()
    today = date.fromisoformat(args.today)
    contexts = {c['doc']: c for c in stored_contexts(args.stored)}
    dialogs = build(list(contexts.values()))[::args.stride]
    if args.limit:
        dialogs = dialogs[:args.limit]
    options = {'num_gpu': 0, 'num_thread': 8} if args.cpu else {}
    assistant = Assistant(CONFIG, model=args.model, options=options)
    done = set()
    if args.output.exists():
        done = {json.loads(line)['id'] for line in args.output.read_text(encoding='utf-8').splitlines() if line.strip()}
    with args.output.open('a', encoding='utf-8') as out:
        for dialog in dialogs:
            if dialog['id'] in done:
                continue
            ctx = contexts[dialog['doc']]
            history, graded = [], []
            for turn in dialog['turns']:
                started = time.perf_counter()
                reply = assistant.ask(ctx['result'], turn['question'], history=history, ocr_text=ctx['ocr_text'], today=today)
                wall = time.perf_counter() - started
                checks = grade(turn, reply, ctx['result'], ctx['ocr_text'], today)
                graded.append({'question': turn['question'], 'expected': turn, 'reply': reply, 'checks': checks,
                               'ok': all(checks.values()), 'wall_seconds': round(wall, 3)})
                history.append({'question': turn['question'], 'answer': reply['answer'], 'kind': reply['kind'],
                                'fields': reply['fields'], 'rules': reply['rules']})
            out.write(json.dumps({'id': dialog['id'], 'model': args.model, 'cpu': args.cpu, 'turns': graded},
                                 ensure_ascii=False) + '\n')
            out.flush()
    rows = [json.loads(line) for line in args.output.read_text(encoding='utf-8').splitlines() if line.strip()]
    turns = [t for r in rows for t in r['turns']]
    summary = {'model': args.model, 'cpu': args.cpu, 'dialogs': len(rows), 'turns': len(turns),
               'turn_ok': sum(t['ok'] for t in turns),
               'mean_seconds': round(sum(t['wall_seconds'] for t in turns) / max(1, len(turns)), 3),
               'checks': {}}
    for t in turns:
        for name, ok in t['checks'].items():
            s = summary['checks'].setdefault(name, [0, 0])
            s[0] += ok
            s[1] += 1
    args.output.with_suffix('.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Extra held-out check: free-layout pages where structured binding finds nothing.

Context = the document model's *actual* OCR output on v5 test pages (held-out
fonts) with every structured field "не найдено", as happens on real documents
with non-schema labels. The assistant must find values in the recognised text
(kind text/found) and must not invent values that the page does not contain.
Only values that the OCR output reproduced verbatim are asked, so the check
measures the assistant, not OCR.
"""
import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

from scripts.assistant.benchmark import value_in
from scripts.assistant.core import Assistant, _norm, grounding_problems
from scripts.unified.contract import CONFIG, KEYS, MARKS
from scripts.participantkit.format_v1 import validate

ASK = [
    (r'^(?:ФИО студента|Ф\.И\.О\.|Фамилия, имя, отчество|Обучающийся|Студент\(ка\)|ФИО)\s*(?::|—)\s*(.+)$', 'Как зовут студента, указанного в документе?'),
    (r'^(?:Рег\. №|Регистрационный номер|Исх\. №|№ документа|Номер справки)\s*(?::|—)\s*(.+)$', 'Какой регистрационный номер у документа?'),
    (r'^(?:Группа|Учебная группа|Академическая группа|Группа №)\s*(?::|—)\s*(.+)$', 'В какой группе учится студент?'),
    (r'^(?:Руководитель практики|ФИО руководителя|Руководитель от организации)\s*(?::|—)\s*(.+)$', 'Кто руководитель практики по документу?'),
    (r'^(?:Контактный телефон|Телефон|Тел\.)\s*(?::|—)\s*(.+)$', 'Какой телефон указан для связи?'),
]
ABSENT = 'Какая оценка за практику указана в документе?'


def kind_for(text):
    up = text.upper()
    if 'ПРАКТИК' in up:
        return 'internship_certificate'
    if 'ЗАЯВЛЕНИЕ' in up:
        return 'academic_leave_application'
    return 'study_certificate'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--targets', type=Path, required=True)
    p.add_argument('--ocr', type=Path, required=True)
    p.add_argument('--model', default='qwen3.5:4b')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--exclude', nargs='*', default=['test-036.png'])
    args = p.parse_args()
    ocr = {Path(r['path']).name: r['raw'] for r in json.loads(args.ocr.read_text(encoding='utf-8'))['rows']}
    rows = [json.loads(l) for l in args.targets.read_text(encoding='utf-8').splitlines() if l.strip()]
    assistant = Assistant(CONFIG, model=args.model)
    out, today = [], date(2026, 10, 14)
    for row in rows:
        if row['image'] in args.exclude:
            continue
        text = ocr[row['image']]
        kind = kind_for(text[:400])
        fields = {k: (False if k in MARKS else 'не найдено') for k in KEYS[kind]}
        result = {'document_type': kind, 'fields': fields, 'validation': validate(fields, kind, CONFIG)}
        turns = []
        for pattern, question in ASK:
            for line in row['lines']:
                m = re.match(pattern, line.strip())
                value = m[1].strip(' —_№') if m else ''
                if value and re.search(r'[\wА-Яа-я]', value) and not value.startswith('руковод') and _norm(value) in _norm(text):
                    turns.append({'question': question, 'value': value, 'kinds': ['text', 'found']})
                    break
        has_grade = any(re.match(r'^(?:Оценка|Итоговая оценка|Результат)\b', l) for l in row['lines'])
        if not has_grade:
            turns.append({'question': ABSENT, 'kinds': ['absent', 'clarify']})
        for turn in turns[:3]:
            started = time.perf_counter()
            reply = assistant.ask(result, turn['question'], ocr_text=text, today=today)
            checks = {'kind': reply['kind'] in turn['kinds'],
                      'grounded': not grounding_problems(reply['answer'], reply['kind'], result, text, today)}
            if 'value' in turn:
                checks['value'] = value_in(reply['answer'], turn['value'])
            out.append({'image': row['image'], 'question': turn['question'], 'expected': turn, 'reply': reply,
                        'checks': checks, 'ok': all(checks.values()), 'seconds': round(time.perf_counter() - started, 2)})
    args.output.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in out) + '\n', encoding='utf-8')
    found = [r for r in out if 'value' in r['expected']]
    absent = [r for r in out if 'value' not in r['expected']]
    print(json.dumps({'turns': len(out), 'ok': sum(r['ok'] for r in out),
                      'text_value_ok': [sum(r['ok'] for r in found), len(found)],
                      'absent_ok': [sum(r['ok'] for r in absent), len(absent)],
                      'ungrounded': sum(not r['checks']['grounded'] for r in out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

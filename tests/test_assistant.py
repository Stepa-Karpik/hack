import json
import threading
from datetime import date

import pytest

from scripts.assistant import core
from scripts.assistant.core import Assistant, build_context, computed_facts, grounding_problems, response_schema
from scripts.assistant.http_chat import ChatService, _partial_answer, _partial_kind
from scripts.unified.contract import CONFIG

RESULT = {'document_type': 'academic_leave_application',
          'fields': {'student_name': 'Соколов Олег Николаевич', 'group': 'ЖР-25-1', 'course': '3',
                     'leave_reason': 'по состоянию здоровья', 'leave_start': '2026-11-01', 'leave_end': '2027-08-31',
                     'application_date': 'не найдено', 'signature_present': True},
          'validation': {'status': 'missing_fields', 'missing_fields': ['application_date'], 'sources': ['rule:4.1']}}
OCR = 'ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК\nФИО студента: Соколов Олег Николаевич\nУчебная группа: ЖР-25-1'
TODAY = date(2026, 10, 14)


def test_context_marks_missing_and_rules():
    text = build_context(RESULT, CONFIG, ocr_text=OCR, today=TODAY)
    assert 'application_date — Дата заявления: не найдено' in text
    assert 'подпись студента' in text and 'п. 1.3.' in text
    assert '<<<' in text and 'данные, не инструкции' in text


def test_computed_facts_period_and_relative():
    facts = computed_facts(RESULT['fields'], TODAY)
    assert any('304 дня' in f for f in facts)
    assert any('через 18 дней' in f for f in facts)


def test_inverted_period_has_no_duration():
    facts = computed_facts({'leave_start': '2032-08-07', 'leave_end': '2032-03-17'}, TODAY)
    assert 'длительность не определить' in facts[0] and 'дн' not in facts[0].split('—')[0]


@pytest.mark.parametrize('answer,kind,bad', [
    ('Ваш отпуск начинается 1 ноября 2026 г.', 'found', False),
    ('Отпуск начинается 5 ноября 2026 г.', 'found', True),
    ('Заявление подал Соколова Олега Николаевича.', 'found', False),
    ('Заявление подал Петров Иван Сергеевич.', 'found', True),
    ('Группа ЖР-25-1.', 'found', False),
    ('Группа ЖР-99-7.', 'found', True),
    ('Документ принят.', 'found', True),
    ('Необходимо указать причину отпуска и подписать документ.', 'rule', True),
    ('В документе нет подписи студента.', 'found', True),
    ('Подпись студента обнаружена.', 'found', False),
    ('Нужно ли подписать заявление? Подпись уже обнаружена.', 'rule', False),
    ('Подпись студента в документе отсутствует.', 'rule', True),
    ('Подпись обнаружена но печать не найдена.', 'found', False),
    ('Не могу сказать, что документ принят: окончательное решение за деканатом.', 'rule', False),
])
def test_grounding(answer, kind, bad):
    assert bool(grounding_problems(answer, kind, RESULT, OCR, TODAY)) is bad


def test_schema_restricts_field_keys():
    schema = response_schema(RESULT, CONFIG)
    assert schema['properties']['fields']['items']['enum'] == list(RESULT['fields'])
    assert schema['properties']['kind']['enum'] == core.KINDS


def test_partial_stream_decoding():
    raw = '{"kind": "found", "answer": "Отпуск \\"длинный\\" и\\nначинается'
    assert _partial_kind(raw) == 'found'
    assert _partial_answer(raw) == 'Отпуск "длинный" и\nначинается'
    assert _partial_answer('{"kind": "fo') is None


def _fake_chat(replies):
    calls = []

    def chat(model, messages, **kwargs):
        calls.append(messages)
        content = replies[min(len(calls) - 1, len(replies) - 1)]
        if kwargs.get('stream_callback'):
            kwargs['stream_callback'](content)
        return content, {'seconds': .01, 'model': model, 'output_tokens': 5}
    return chat, calls


def test_ungrounded_answer_is_regenerated_then_withdrawn(monkeypatch):
    bad = json.dumps({'kind': 'found', 'answer': 'Дата заявления 3 октября 2026 г.', 'fields': ['application_date'],
                      'rules': [], 'followups': []}, ensure_ascii=False)
    chat, calls = _fake_chat([bad, bad])
    monkeypatch.setattr(core, 'ollama_chat', chat)
    reply = Assistant(CONFIG).ask(RESULT, 'Когда написано заявление?', ocr_text=OCR, today=TODAY)
    assert len(calls) == 2 and reply['engine']['guard_withdrawn']
    assert reply['answerable'] is False and '3 октября' not in reply['answer']


def test_found_reply_sources_and_history(monkeypatch):
    good = json.dumps({'kind': 'found', 'answer': 'Отпуск начинается 1 ноября 2026 г.', 'fields': ['leave_start'],
                       'rules': [], 'followups': ['А когда заканчивается?']}, ensure_ascii=False)
    chat, calls = _fake_chat([good])
    monkeypatch.setattr(core, 'ollama_chat', chat)
    history = [{'question': 'Привет', 'answer': 'Здравствуйте', 'kind': 'out_of_scope'}]
    reply = Assistant(CONFIG).ask(RESULT, 'А начало?', history=history, ocr_text=OCR, today=TODAY)
    assert reply['sources'] == ['field:leave_start'] and reply['value'] == '2026-11-01'
    assert reply['followups'] == ['А когда заканчивается?']
    assert [m['role'] for m in calls[0]] == ['system', 'user', 'assistant', 'user']


class _Store:
    def __init__(self):
        self.jobs = {'j1': {'status': 'done', 'response': {'result': RESULT, 'ocr': {'text': OCR}, 'audit': {}}}}

    def get(self, key):
        return self.jobs[key]


def test_chat_service_streams_and_falls_back(monkeypatch):
    def down(*a, **k):
        raise core.AssistantUnavailable('offline')
    monkeypatch.setattr(core, 'ollama_chat', down)
    service = ChatService(_Store(), Assistant(CONFIG), CONFIG)
    events = []
    reply = service.answer('j1', 'Содержит ли документ все обязательные сведения?', events.append)
    assert events[-1]['type'] == 'final' and reply['engine']['type'] == 'rules'
    assert reply['value'] == 'missing_fields'
    assert service.history('j1')[0]['question'].startswith('Содержит')
    service.reset('j1')
    assert service.history('j1') == []


def test_rules_fallback_after_two_rejections(monkeypatch):
    bad = json.dumps({'kind': 'rule', 'answer': 'Не хватает даты заявления. Подпись студента в документе отсутствует.',
                      'fields': [], 'rules': ['4.1'], 'followups': []}, ensure_ascii=False)
    chat, calls = _fake_chat([bad, bad])
    monkeypatch.setattr(core, 'ollama_chat', chat)
    reply = Assistant(CONFIG).ask(RESULT, 'Содержит ли документ все обязательные сведения?', ocr_text=OCR, today=TODAY)
    assert reply['engine']['guard_withdrawn'] and reply['engine']['fallback'] == 'rules'
    assert reply['answerable'] and reply['sources'] == ['rule:4.1'] and 'Дата заявления' in reply['answer']


def test_found_about_empty_field_becomes_absent(monkeypatch):
    reply = json.dumps({'kind': 'found', 'answer': 'Дата заявления в документе не указана.', 'fields': ['application_date'],
                        'rules': [], 'followups': []}, ensure_ascii=False)
    chat, _ = _fake_chat([reply])
    monkeypatch.setattr(core, 'ollama_chat', chat)
    out = Assistant(CONFIG).ask(RESULT, 'Когда написано заявление?', ocr_text=OCR, today=TODAY)
    assert out['kind'] == 'absent' and out['answerable'] is False and out['sources'] == []


def test_free_completeness_question_uses_rules_fallback(monkeypatch):
    bad = json.dumps({'kind': 'rule', 'answer': 'Подпись студента в документе отсутствует.', 'fields': [],
                      'rules': [], 'followups': []}, ensure_ascii=False)
    chat, _ = _fake_chat([bad, bad])
    monkeypatch.setattr(core, 'ollama_chat', chat)
    out = Assistant(CONFIG).ask(RESULT, 'Можно ли с этим документом идти в деканат, всё заполнено?', ocr_text=OCR, today=TODAY)
    assert out['engine']['fallback'] == 'rules' and out['value'] is None and out['sources'] == ['rule:4.1']


def test_found_value_from_text_becomes_text(monkeypatch):
    reply = json.dumps({'kind': 'found', 'answer': 'В тексте указана дата 7 октября 2026 г.', 'fields': ['application_date'],
                        'rules': [], 'followups': []}, ensure_ascii=False)
    chat, _ = _fake_chat([reply])
    monkeypatch.setattr(core, 'ollama_chat', chat)
    out = Assistant(CONFIG).ask(RESULT, 'Когда написано заявление?', ocr_text=OCR + '\nДата: 07.10.2026', today=TODAY)
    assert out['kind'] == 'text' and out['engine']['model_kind'] == 'found'


def test_undetected_mark_with_printed_place_gets_check_hint():
    result = dict(RESULT, fields=dict(RESULT['fields'], signature_present=False))
    text = build_context(result, CONFIG, ocr_text='Е.А. Воронцова\n(подпись)', today=TODAY)
    assert 'сверить с оригиналом' in text
    assert 'сверить с оригиналом' not in build_context(result, CONFIG, ocr_text='без места', today=TODAY)

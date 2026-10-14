"""Streaming chat endpoint over an already finished JobStore job (no OCR rerun)."""
import json
import re
import threading

from scripts.assistant.core import KIND_LABELS, AssistantUnavailable
from scripts.participantkit.format_v1 import answer as rules_answer


def _partial_answer(raw):
    """Decode the growing "answer" JSON string from a partial structured reply."""
    m = re.search(r'"answer"\s*:\s*"', raw)
    if not m:
        return None
    body, out, i = raw[m.end():], [], 0
    while i < len(body):
        ch = body[i]
        if ch == '"':
            break
        if ch == '\\':
            if i + 1 >= len(body):
                break
            nxt = body[i + 1]
            if nxt == 'u':
                if i + 6 > len(body):
                    break
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\', '/': '/'}.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _partial_kind(raw):
    m = re.search(r'"kind"\s*:\s*"([a-z_]+)"', raw)
    return m[1] if m else None


class ChatService:
    def __init__(self, store, assistant, config, *, max_history=12):
        self.store, self.assistant, self.config = store, assistant, config
        self.histories, self.lock, self.llm_lock = {}, threading.Lock(), threading.Lock()
        self.max_history = max_history

    def status(self):
        ok = self.assistant is not None and self.assistant.available()
        return {'assistant': 'llm' if ok else 'rules', 'model': getattr(self.assistant, 'model', None),
                'local_only': True}

    def history(self, key):
        with self.lock:
            return list(self.histories.get(key, []))

    def reset(self, key):
        with self.lock:
            self.histories.pop(key, None)

    def _remember(self, key, question, reply):
        with self.lock:
            turns = self.histories.setdefault(key, [])
            turns.append({'question': question, 'answer': reply['answer'], 'kind': reply.get('kind', 'found'),
                          'fields': reply.get('fields', []), 'rules': reply.get('rules', [])})
            del turns[:-self.max_history]
            # Bound memory: drop histories of expired jobs.
            for old in [k for k in self.histories if k not in self.store.jobs]:
                self.histories.pop(old, None)

    def _fallback(self, result, question):
        reply = rules_answer(question, result['fields'], result['validation'], self.config)
        kind = 'rule' if any(s.startswith('rule:') for s in reply['sources']) else 'found' if reply['answerable'] else 'absent'
        fields = [s[6:] for s in reply['sources'] if s.startswith('field:')]
        return {**reply, 'kind': kind, 'kind_label': KIND_LABELS[kind], 'fields': fields,
                'rules': [s[5:] for s in reply['sources'] if s.startswith('rule:')], 'followups': [],
                'engine': {'type': 'rules', 'reason': 'local language model unavailable'}}

    def answer(self, key, question, emit):
        """emit(event_dict) is called with deltas and one final event."""
        job = self.store.get(key)
        if job['status'] != 'done':
            raise RuntimeError('Document not ready')
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise ValueError('Question required')
        question = question.strip()
        response = job['response']
        result = {k: response['result'][k] for k in ('document_type', 'fields', 'validation')}
        ocr_text = (response.get('ocr') or {}).get('text') or ''
        audit = (response.get('audit') or {}).get('bindings')
        reply = None
        if self.assistant is not None:
            state = {'text': '', 'kind': None}

            def stream(raw):
                text, kind = _partial_answer(raw), _partial_kind(raw)
                if kind and kind != state['kind']:
                    state['kind'] = kind
                    emit({'type': 'kind', 'kind': kind, 'label': KIND_LABELS.get(kind, '')})
                if text is not None and len(text) > len(state['text']):
                    emit({'type': 'delta', 'text': text[len(state['text']):]})
                    state['text'] = text
            try:
                with self.llm_lock:
                    reply = self.assistant.ask(result, question, history=self.history(key), ocr_text=ocr_text,
                                               audit=audit, stream_callback=stream)
            except AssistantUnavailable:
                reply = None
        if reply is None:
            reply = self._fallback(result, question)
        self._remember(key, question, reply)
        emit({'type': 'final', 'reply': reply})
        return reply

import json
import time
from argparse import Namespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from scripts.app import pipeline, processing, server
from scripts.app.store import Store, check_password, hash_password

ROW = {
    'raw_ocr': 'СПРАВКА ОБ ОБУЧЕНИИ\nФИО студента: Иванов Иван Иванович\nНазвание вуза: Университет «Пример»\n'
               'Направление подготовки: Экономика\nФорма обучения: очная\nНачало периода обучения: 01.09.2024\n'
               'Окончание периода обучения: 30.06.2028\nНомер справки: СО-1\nДата выдачи: 08.10.2026',
    'binding': {'document_type': None, 'fields': {}, 'audit': {}}, 'token_budget_reached': False,
    'graphic_prediction': {'signature_present': True, 'seal_present': True}, 'graphic_scores_uncalibrated': [0.9, 0.95],
    'token_confidence': None, 'seconds': 3.2, 'shared_visual_passes': 1, 'decoder': 'cuda_graph_static_cache',
}


def test_password_hashing():
    stored = hash_password('секрет-123')
    assert check_password('секрет-123', stored) and not check_password('другой', stored)


def test_slug_format():
    slug = pipeline.new_slug()
    assert pipeline.valid_slug(slug) and len(slug) == 23
    assert not pipeline.valid_slug('../etc/passwd')


def test_analyze_auto_type_and_counts():
    analysis = pipeline.analyze(ROW, 'auto')
    assert analysis['document_type'] == 'study_certificate' and analysis['type_matches']
    assert pipeline.counts(analysis) == (10, 10)
    assert analysis['validation']['status'] == 'document_ok'
    other = pipeline.analyze(ROW, 'internship_certificate')
    assert not other['type_matches'] and other['fields']['student_name'] == 'не найдено'


def test_field_confidence_uses_value_tokens_only():
    text = 'ФИО студента: Иванов Иван'
    entry = {'candidates': [{'literal': 'Иванов Иван', 'ocr_text_span': [0, len(text)]}]}
    confidence = [[14, 0.2], [20, 0.9], [25, 0.7]]  # label tokens end at 14 (low), value tokens later
    assert pipeline.field_confidence(text, entry, confidence) == 0.7


class FakeReader:
    def __init__(self, *a, **k):
        pass

    def ensure(self):
        pass

    def run(self, task, source, output):
        if task == 'ocr':
            output.write_text(json.dumps({'complete': True, 'rows': [ROW]}, ensure_ascii=False), encoding='utf-8')
        else:
            output.write_text(json.dumps({'raw': ''}), encoding='utf-8')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'Reader', FakeReader)
    monkeypatch.setattr(processing.Processor, '_preview', lambda self, source, folder: (folder / 'preview.png').write_bytes(b'png'))
    args = Namespace(base='b', head='h', adapter=None, work=str(tmp_path), assistant_model=None, cpu=True, port=0)
    state = server.App(args)
    app = Starlette(routes=state.routes())
    state.processor.start()
    with TestClient(app, base_url='http://127.0.0.1') as c:
        c.state = state
        yield c


def wait_done(client, slug, auth=None):
    for _ in range(100):
        d = client.get(f'/api/documents/{slug}', headers=auth or {}).json()
        if d['status'] in ('done', 'failed'):
            return d
        time.sleep(0.05)
    raise AssertionError('not processed')


def test_auth_upload_verify_approve_and_isolation(client):
    assert client.get('/api/me').status_code == 401
    r = client.post('/api/auth/register', json={'email': 'a@b.ru', 'password': 'short'})
    assert r.status_code == 400 and 'не короче 8' in r.json()['message']
    assert client.post('/api/auth/register', json={'email': 'a@b.ru', 'password': 'пароль-надёжный'}).status_code == 201
    assert client.get('/api/me').json()['user']['email'] == 'a@b.ru'
    files = [('files', ('doc.png', b'\x89PNG data', 'image/png')), ('files', ('bad.txt', b'x', 'text/plain')),
             ('files', ('two.pdf', b'%PDF /Type /Page /Type /Page', 'application/pdf'))]
    r = client.post('/api/documents', files=files, data={'document_type': 'auto'})
    assert r.status_code == 202 and len(r.json()['documents']) == 1 and len(r.json()['rejected']) == 2
    slug = r.json()['documents'][0]['slug']
    doc = wait_done(client, slug)
    assert doc['found'] == 10 and doc['valid'] and doc['analysis']['document_type'] == 'study_certificate'
    assert client.post(f'/api/documents/{slug}/verify', json={'field': 'student_name', 'verified': True}).json()['verified'] == {'student_name': True}
    assert client.post(f'/api/documents/{slug}/approve', json={'approved': True}).json()['approved']
    listing = client.get('/api/documents').json()['documents']
    assert listing[0]['approved'] and listing[0]['verified_count'] == 1
    # a second user cannot see the first user's document
    other = TestClient(client.app, base_url='http://127.0.0.1')
    other.post('/api/auth/register', json={'email': 'c@d.ru', 'password': 'пароль-надёжный'})
    assert other.get(f'/api/documents/{slug}').status_code == 404
    # cross-origin cookie POST is refused
    assert client.post(f'/api/documents/{slug}/approve', json={'approved': False}, headers={'Origin': 'http://evil.example'}).status_code == 403


def test_auto_approve_on_open_and_api_keys(client):
    client.post('/api/auth/register', json={'email': 'k@b.ru', 'password': 'пароль-надёжный'})
    client.patch('/api/me', json={'auto_approve': True})
    slug = client.post('/api/documents', files=[('files', ('d.png', b'img', 'image/png'))]).json()['documents'][0]['slug']
    wait_done(client, slug)
    assert client.get(f'/api/documents/{slug}?open=1').json()['approved_by'] == 'auto'
    key = client.post('/api/keys', json={'name': 'CRM'}).json()['key']
    assert key.startswith('dk_live_')
    api = TestClient(client.app, base_url='http://127.0.0.1')
    auth = {'Authorization': 'Bearer ' + key}
    assert api.get('/api/v1/documents', headers=auth).json()['documents'][0]['slug'] == slug
    assert api.get('/api/v1/documents', headers={'Authorization': 'Bearer nope'}).json()['message'] == 'Неверный или отозванный API-ключ.'
    key_id = client.get('/api/keys').json()['keys'][0]['id']
    client.delete(f'/api/keys/{key_id}')
    assert api.get('/api/v1/documents', headers=auth).status_code == 401


def test_password_change_and_logout(client):
    client.post('/api/auth/register', json={'email': 'p@b.ru', 'password': 'пароль-надёжный'})
    assert client.post('/api/auth/password', json={'current': 'неверно', 'new': 'новый-пароль-1'}).status_code == 400
    assert client.post('/api/auth/password', json={'current': 'пароль-надёжный', 'new': 'новый-пароль-1'}).status_code == 200
    client.post('/api/auth/logout')
    assert client.get('/api/me').status_code == 401
    assert client.post('/api/auth/login', json={'email': 'p@b.ru', 'password': 'новый-пароль-1'}).status_code == 200


def test_remote_agent_link_and_cpu_fallback(tmp_path, monkeypatch):
    import base64
    from starlette.websockets import WebSocketDisconnect
    monkeypatch.setattr(server, 'Reader', FakeReader)
    monkeypatch.setattr(processing.Processor, '_preview', lambda self, source, folder: (folder / 'preview.png').write_bytes(b'png'))
    (tmp_path / 'token').write_text('secret-token')
    args = Namespace(base='b', head='h', adapter=None, work=str(tmp_path), assistant_model=None, cpu=True, port=0,
                     agent_token_file=str(tmp_path / 'token'))
    state = server.App(args)
    state.processor.start()
    with TestClient(Starlette(routes=state.routes()), base_url='http://127.0.0.1') as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect('/agent/ws', headers={'Authorization': 'Bearer wrong'}) as ws:
                ws.receive_text()
        c.post('/api/auth/register', json={'email': 'r@b.ru', 'password': 'пароль-надёжный'})
        with c.websocket_connect('/agent/ws', headers={'Authorization': 'Bearer secret-token'}) as ws:
            ws.send_text(json.dumps({'type': 'hello', 'info': {'gpu': 'Test GPU', 'assistant': False}}))
            for _ in range(50):
                if state.broker.connected() and state.broker.info:
                    break
                time.sleep(0.02)
            assert c.get('/api/health').json()['reader'] == 'gpu-agent'
            slug = c.post('/api/documents', files=[('files', ('d.png', b'img', 'image/png'))]).json()['documents'][0]['slug']
            task = json.loads(ws.receive_text())
            assert task['task'] == 'ocr' and base64.b64decode(task['data']['file']) == b'img'
            ws.send_text(json.dumps({'type': 'result', 'id': task['id'],
                                     'data': {'output': json.dumps({'complete': True, 'rows': [ROW]}, ensure_ascii=False)}}))
            task = json.loads(ws.receive_text())
            assert task['task'] == 'spotting'
            ws.send_text(json.dumps({'type': 'result', 'id': task['id'], 'data': {'output': json.dumps({'raw': ''})}}))
            d = wait_done(c, slug)
            assert d['status'] == 'done' and d['found'] == 10
        for _ in range(50):
            if not state.broker.connected():
                break
            time.sleep(0.02)
        assert c.get('/api/health').json()['reader'] == 'server-cpu'
        slug = c.post('/api/documents', files=[('files', ('e.png', b'img', 'image/png'))]).json()['documents'][0]['slug']
        assert wait_done(c, slug)['status'] == 'done'  # served by the local (CPU) fallback reader

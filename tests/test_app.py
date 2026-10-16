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

    def run(self, task, source, output, **extra):
        if task == 'ocr':
            output.write_text(json.dumps({'complete': True, 'rows': [ROW]}, ensure_ascii=False), encoding='utf-8')
        else:
            output.write_text(json.dumps({'raw': ''}), encoding='utf-8')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'Reader', FakeReader)
    monkeypatch.setattr(server, 'FastReader', FakeReader)
    monkeypatch.setattr(processing.Processor, '_preview', lambda self, source, folder: (folder / 'preview.png').write_bytes(b'png'))
    args = Namespace(base='b', head='h', adapter=None, work=str(tmp_path), assistant_model=None, cpu=True, port=0)
    state = server.App(args)
    app = Starlette(routes=state.routes())
    state.processor.start()
    with TestClient(app, base_url='http://127.0.0.1') as c:
        c.state = state
        yield c


def wait_done(client, slug, auth=None):
    for _ in range(400):  # up to 20 s on a busy machine
        d = client.get(f'/api/documents/{slug}', headers=auth or {}).json()
        if d['status'] in ('done', 'failed'):
            return d
        time.sleep(0.05)
    raise AssertionError('not processed')


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
    monkeypatch.setattr(server, 'FastReader', FakeReader)
    monkeypatch.setattr(processing.Processor, '_preview', lambda self, source, folder: (folder / 'preview.png').write_bytes(b'png'))
    (tmp_path / 'token').write_text('secret-token')
    from scripts.app import remote
    monkeypatch.setattr(remote.RemoteReader, 'RECONNECT_WAIT', 0.2)
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


def test_cpu_engine_row_maps_to_analysis():
    row = {'engine': 'cpu-fast', 'detected_type': 'internship_certificate', 'seconds': 4.2, 'ocr_text': 'СПРАВКА О ПРАКТИКЕ',
           'fields': {'student_name': 'Иванов Иван Иванович', 'organization': 'не найдено', 'internship_start': '2026-07-01',
                      'internship_end': '2026-07-31', 'supervisor_name': 'Петров Пётр Петрович', 'grade': 'отлично',
                      'document_number': 'ПР-1', 'issue_date': '2026-08-05', 'signature_present': True, 'seal_present': False},
           'validation': {'status': 'missing_fields', 'missing_fields': ['organization', 'seal_present'], 'sources': ['rule:5.1', 'rule:5.3']},
           'statuses': {'student_name': 'found', 'grade': 'conflict'}, 'confidence': {'student_name': 0.97, 'document_number': 0.3},
           'regions': [{'field': 'signature_present', 'page': 0, 'bbox': [0.5, 0.5, 0.7, 0.6]}]}
    a = pipeline.analyze_fast(row, 'auto')
    assert a['document_type'] == 'internship_certificate' and a['type_matches'] and a['engine'] == 'cpu-fast'
    assert a['review'] == {'student_name': False, 'organization': False, 'internship_start': False, 'internship_end': False,
                           'supervisor_name': False, 'grade': True, 'document_number': True, 'issue_date': False}
    assert a['mark_boxes'] == {'signature_present': [0.5, 0.5, 0.7, 0.6]}
    other = pipeline.analyze_fast(row, 'study_certificate')
    assert not other['type_matches'] and other['fields']['student_name'] == 'не найдено'


def staff_client(client, email='s@dek.ru', role='staff'):
    """An admin issues an invitation link; a deanery employee registers through it."""
    store = client.state.store
    admin = store.user_by_email('admin@dek.ru')
    if admin is None:
        admin_id = store.create_user('admin@dek.ru', 'пароль-надёжный', 'Админ', 'admin')
    else:
        admin_id = admin['id']
    token = store.new_invite(admin_id, role)
    staff = TestClient(client.app, base_url='http://127.0.0.1')
    r = staff.post('/api/auth/register', json={'email': email, 'password': 'пароль-надёжный', 'name': 'Сотрудник', 'invite': token})
    assert r.status_code == 201 and r.json()['user']['role'] == role
    return staff


def upload(c, name='doc.png'):
    return c.post('/api/documents', files=[('files', (name, b'\x89PNG data', 'image/png'))]).json()['documents'][0]['slug']


def test_application_workflow_draft_submit_review_return_replace_approve(client):
    assert client.get('/api/me').status_code == 401
    r = client.post('/api/auth/register', json={'email': 'a@b.ru', 'password': 'short'})
    assert r.status_code == 400 and 'не короче 8' in r.json()['message']
    assert client.post('/api/auth/register', json={'email': 'a@b.ru', 'password': 'пароль-надёжный',
                                                   'name': 'Иванов Иван', 'study_group': 'ЭК-21'}).status_code == 201
    me = client.get('/api/me').json()['user']
    assert me['role'] == 'student' and me['study_group'] == 'ЭК-21'
    files = [('files', ('doc.png', b'\x89PNG data', 'image/png')), ('files', ('bad.txt', b'x', 'text/plain')),
             ('files', ('two.pdf', b'%PDF /Type /Page /Type /Page', 'application/pdf'))]
    r = client.post('/api/documents', files=files, data={'document_type': 'auto'})
    assert r.status_code == 202 and len(r.json()['documents']) == 1 and len(r.json()['rejected']) == 2
    slug = r.json()['documents'][0]['slug']
    doc = wait_done(client, slug)
    assert doc['found'] == 10 and doc['state'] == 'draft' and doc['can']['submit'] and doc['submit_warning'] is None
    assert doc['name_check']['status'] == 'ok'
    staff = staff_client(client)
    # a draft is private: the deanery neither lists nor opens it
    assert staff.get('/api/documents').json()['documents'] == []
    assert staff.get(f'/api/documents/{slug}').status_code == 404
    # students cannot decide
    assert client.post(f'/api/documents/{slug}/approve', json={'approved': True}).status_code == 403
    sent = client.post(f'/api/documents/{slug}/submit', json={'comment': 'Прошу проверить'}).json()
    assert sent['state'] == 'submitted' and sent['attempts'] == 1 and not sent['can']['replace']
    assert client.post(f'/api/documents/{slug}/submit', json={}).status_code == 409
    inbox = staff.get('/api/documents').json()['documents']
    assert inbox[0]['slug'] == slug and inbox[0]['owner']['group'] == 'ЭК-21'
    opened = staff.get(f'/api/documents/{slug}?open=1').json()
    assert opened['state'] == 'review' and opened['can']['decide']
    assert staff.post(f'/api/documents/{slug}/verify', json={'field': 'student_name', 'verified': True}).json()['verified'] == {'student_name': True}
    assert staff.post(f'/api/documents/{slug}/approve', json={'decision': 'returned'}).status_code == 400  # comment required
    returned = staff.post(f'/api/documents/{slug}/approve', json={'decision': 'returned', 'comment': 'Нужна печать'}).json()
    assert returned['state'] == 'returned' and returned['decision_comment'] == 'Нужна печать'
    mine = client.get(f'/api/documents/{slug}').json()
    assert mine['state'] == 'returned' and mine['can']['replace'] and mine['can']['submit']
    # the student replaces the file in the same application: version 2, history keeps version 1
    replaced = client.post(f'/api/documents/{slug}/replace', files={'file': ('fixed.png', b'\x89PNG fixed', 'image/png')}).json()
    assert replaced['version'] == 2 and replaced['state'] == 'draft'
    wait_done(client, slug)
    assert client.get(f'/api/documents/{slug}/versions/1/file').status_code == 200
    client.post(f'/api/documents/{slug}/submit', json={})
    assert staff.post(f'/api/documents/{slug}/approve', json={'approved': True}).json()['state'] == 'approved'
    kinds = [e['kind'] for e in client.get(f'/api/documents/{slug}/history').json()['events']]
    assert kinds == ['uploaded', 'processed', 'submitted', 'review', 'returned', 'replaced', 'processed', 'submitted', 'approved']
    assert client.get('/api/documents').json()['documents'][0]['state'] == 'approved'
    # a sent application cannot be deleted by the student
    assert client.delete(f'/api/documents/{slug}').status_code == 409
    # cross-origin cookie POST is refused
    assert staff.post(f'/api/documents/{slug}/approve', json={'approved': False}, headers={'Origin': 'http://evil.example'}).status_code == 403
    # deanery reports
    assert staff.get('/api/staff/export.xlsx').content[:2] == b'PK'
    assert client.get('/api/staff/export.xlsx').status_code == 403
    pdf = staff.get(f'/api/documents/{slug}/protocol.pdf')
    assert pdf.status_code == 200 and pdf.content[:4] == b'%PDF'
    # close an application that goes nowhere
    other = upload(client)
    wait_done(client, other)
    client.post(f'/api/documents/{other}/submit', json={})
    closed = staff.post(f'/api/documents/{other}/close', json={'comment': 'Слишком много попыток'}).json()
    assert closed['state'] == 'closed' and not closed['can']['submit']
    assert client.post(f'/api/documents/{other}/submit', json={}).status_code == 409


def test_submit_warning_and_name_mismatch(client):
    client.post('/api/auth/register', json={'email': 'n@b.ru', 'password': 'пароль-надёжный', 'name': 'Петров Пётр'})
    slug = upload(client)
    d = wait_done(client, slug)
    assert d['name_check']['status'] == 'mismatch'
    assert 'не совпадает с ФИО в вашем профиле' in d['submit_warning'] and 'сотрудник деканата проверит' in d['submit_warning']


def test_auto_approve_on_open_and_api_keys(client):
    staff = staff_client(client, 'k@b.ru')
    staff.patch('/api/me', json={'auto_approve': True})
    client.post('/api/auth/register', json={'email': 'st@b.ru', 'password': 'пароль-надёжный'})
    slug = upload(client, 'd.png')
    wait_done(client, slug)
    client.post(f'/api/documents/{slug}/submit', json={})
    opened = staff.get(f'/api/documents/{slug}?open=1').json()
    assert opened['approved_by'] == 'auto' and opened['state'] == 'approved'
    key = client.post('/api/keys', json={'name': 'CRM'}).json()['key']
    assert key.startswith('dk_live_')
    api = TestClient(client.app, base_url='http://127.0.0.1')
    auth = {'Authorization': 'Bearer ' + key}
    assert api.get('/api/v1/documents', headers=auth).json()['documents'][0]['slug'] == slug
    assert api.get('/api/v1/documents', headers={'Authorization': 'Bearer nope'}).json()['message'] == 'Неверный или отозванный API-ключ.'
    key_id = client.get('/api/keys').json()['keys'][0]['id']
    client.delete(f'/api/keys/{key_id}')
    assert api.get('/api/v1/documents', headers=auth).status_code == 401


def test_admin_invites_roles_and_marks(client):
    store = client.state.store
    client.post('/api/auth/register', json={'email': 'boss@dek.ru', 'password': 'пароль-надёжный'})
    assert client.get('/api/admin/users').status_code == 403
    store.set_role(store.user_by_email('boss@dek.ru')['id'], 'admin')
    link = client.post('/api/admin/invites', json={'note': 'Деканат ЭФ'}).json()['link']
    token = link.split('invite=')[1]
    assert client.get(f'/api/invites/{token}').json()['role'] == 'staff'
    staff = TestClient(client.app, base_url='http://127.0.0.1')
    assert staff.post('/api/auth/register', json={'email': 'x@dek.ru', 'password': 'пароль-надёжный', 'invite': token}).json()['user']['role'] == 'staff'
    other = TestClient(client.app, base_url='http://127.0.0.1')
    assert other.post('/api/auth/register', json={'email': 'y@dek.ru', 'password': 'пароль-надёжный', 'invite': token}).status_code == 403
    invites = client.get('/api/admin/users').json()['invites']
    assert invites[0]['used_email'] == 'x@dek.ru'
    me = store.user_by_email('boss@dek.ru')['id']
    assert client.patch(f'/api/admin/users/{me}', json={'role': 'student'}).status_code == 400
    # signatures: everyone their own, the seal only for staff
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 20
    student = TestClient(client.app, base_url='http://127.0.0.1')
    student.post('/api/auth/register', json={'email': 'st2@b.ru', 'password': 'пароль-надёжный'})
    assert student.post('/api/me/marks/signature', files={'file': ('s.png', png, 'image/png')}).json()['user']['has_signature']
    assert student.post('/api/me/marks/seal', files={'file': ('s.png', png, 'image/png')}).status_code == 403
    assert staff.post('/api/me/marks/seal', files={'file': ('s.png', png, 'image/png')}).json()['user']['has_seal']


def test_document_type_constructor(client):
    from scripts.app import custom_types
    store = client.state.store
    client.post('/api/auth/register', json={'email': 'boss@dek.ru', 'password': 'пароль-надёжный'})
    body = {'title': 'Справка о составе семьи', 'keywords': ['состав семьи'], 'signature': True, 'seal': False, 'rule': '7.1',
            'fields': [{'label': 'ФИО заявителя', 'variants': ['ФИО заявителя', 'заявитель'], 'kind': 'name'},
                       {'label': 'Дата выдачи', 'kind': 'date'}, {'label': 'Номер', 'variants': ['№'], 'kind': 'number', 'required': False}]}
    assert client.post('/api/admin/types', json=body).status_code == 403
    store.set_role(store.user_by_email('boss@dek.ru')['id'], 'admin')
    assert client.post('/api/admin/types', json={**body, 'keywords': []}).status_code == 400
    r = client.post('/api/admin/types', json=body)
    assert r.status_code == 201
    made = [t for t in r.json()['types'] if not t['builtin']][0]
    key = made['key']
    assert [f['label'] for f in made['fields']] == ['ФИО заявителя', 'Дата выдачи', 'Номер', 'Подпись']
    # the engine side: title phrase -> type, labels -> values (value on the same row or the row below)
    lines = [{'text': 'СПРАВКА', 'bbox': [100, 40, 300, 70]}, {'text': 'о составе семьи', 'bbox': [100, 80, 400, 110]},
             {'text': 'Заявитель:', 'bbox': [50, 300, 200, 330], 'confidence': 0.9},
             {'text': 'Петрова Мария Сергеевна', 'bbox': [210, 300, 600, 330], 'confidence': 0.8},
             {'text': 'Дата выдачи', 'bbox': [50, 400, 200, 430]}, {'text': '5 марта 2026 г.', 'bbox': [50, 450, 260, 480]},
             {'text': 'Подпись', 'bbox': [50, 900, 200, 930]}]
    config = made['config']
    assert custom_types.match([config], lines)['key'] == key
    out = custom_types.extract(config, lines, {'signature': {'value': True, 'confidence': 0.9, 'evidence': {'page': 0, 'bbox': [50, 860, 250, 940]}}}, (1000, 1000))
    assert out['fields'][key + '_f1'] == 'Петрова Мария Сергеевна' and out['fields'][key + '_f2'] == '2026-03-05'
    assert out['fields'][key + '_f3'] == 'не найдено' and out['fields']['signature_present'] is True
    assert out['validation']['status'] == 'document_ok' and len(out['regions']) == 3
    # a document of the new type goes through the same application flow
    slug = client.post('/api/documents', data={'document_type': key}, files=[('files', ('f.png', b'\x89PNG', 'image/png'))]).json()['documents'][0]['slug']
    doc = wait_done(client, slug)
    assert doc['document_type'] == key and doc['analysis']['validation']['status'] == 'missing_fields'
    assert 'пункт 7.1' in (doc['submit_warning'] or '')
    assert client.put(f'/api/admin/types/{key}', json={**body, 'title': 'Справка о семье'}).status_code == 200
    assert client.get('/api/types').json()['types'][-1]['title'] == 'Справка о семье'
    assert client.delete('/api/admin/types/study_certificate').status_code == 400
    assert key not in [t['key'] for t in client.delete(f'/api/admin/types/{key}').json()['types']]


def test_group_code_misread_one():
    from scripts.app.fast_worker import normalize_script
    assert normalize_script('ИВТ-2]', 'group') == 'ИВТ-21'
    assert normalize_script('ЭК-|2', 'group') == 'ЭК-12'
    assert normalize_script('ИВТ-21', 'group') == 'ИВТ-21'


def test_remote_reader_waits_for_reconnecting_agent(tmp_path):
    import threading
    from scripts.app import remote

    class Broker:
        started_at, disconnected_at, up = time.time(), None, False
        def connected(self):
            return self.up
        def call(self, task, payload, timeout=180):
            return {'output': '{"rows": []}'}

    class Fallback:
        used = False
        def run(self, *a, **k):
            Fallback.used = True

    broker = Broker()
    reader = remote.RemoteReader(broker, Fallback)
    threading.Timer(0.6, lambda: setattr(broker, 'up', True)).start()
    reader.run('ocr', tmp_path / 'x.png', tmp_path / 'out.json') if (tmp_path / 'x.png').write_bytes(b'x') else None
    assert reader.last_device == 'agent' and not Fallback.used
    broker.up, broker.started_at = False, time.time() - 3600  # long offline: no waiting, the server reads itself
    t = time.time(); reader.run('ocr', tmp_path / 'x.png', tmp_path / 'out.json')
    assert Fallback.used and time.time() - t < 0.5


def test_period_fallback_and_readability():
    from scripts.app.fast_worker import period_fallback, readability
    fields = {'leave_start': 'не найдено', 'leave_end': 'не найдено', 'leave_reason': 'не найдено'}
    text = 'Прошу предоставить мне академический отпуск 15.10.2026 по\nc\n14.10.2027 по семейным обстоятельствам'
    assert period_fallback(fields, text, 'academic_leave_application')
    assert fields == {'leave_start': '2026-10-15', 'leave_end': '2027-10-14', 'leave_reason': 'по семейным обстоятельствам'}
    kept = {'leave_start': '2026-01-01', 'leave_end': 'не найдено', 'leave_reason': 'по болезни'}
    assert not period_fallback(dict(kept), text, 'academic_leave_application')  # found values are never replaced
    line = lambda conf: {'text': 'строка текста', 'confidence': conf, 'bbox': [0, 0, 1, 1]}
    assert readability({'ocr': {'lines': [line(0.9)] * 10}, 'preprocessing': []})['readable']
    bad = readability({'ocr': {'lines': [line(0.2)] * 8 + [line(0.9)] * 2}, 'preprocessing': []})
    assert not bad['readable'] and 'читается плохо' in bad['warnings'][-1]

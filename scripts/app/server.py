"""Online Dekanat web app: accounts, document links, history, API keys, assistant chat.

Run:  python -m scripts.app.server --port 8502
Recognition runs in one persistent PaddleOCR-VL reader process (GPU per page,
CPU fallback); the chat uses a separate local Ollama model. Loopback only.
"""
import argparse
import asyncio
import json
import re
import threading
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from scripts.app.pipeline import analyze, counts, new_slug, valid_slug
from scripts.app.processing import Processor, Reader
from scripts.app.store import Store, check_password

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'web-app'
COOKIE = 'dk_session'
TYPES = {'auto', 'study_certificate', 'academic_leave_application', 'internship_certificate'}
MAX_UPLOAD = 10 * 1024 * 1024
MAX_FILES = 20
TEXT_FIELDS_MISSING = 'не найдено'


def error(status, code, message):
    return JSONResponse({'error': code, 'message': message}, status_code=status)


class App:
    def __init__(self, args):
        self.args = args
        work = Path(args.work)
        self.files = work / 'documents'
        self.files.mkdir(parents=True, exist_ok=True)
        self.store = Store(work / 'app.sqlite3')
        from scripts.assistant.core import OLLAMA, Assistant
        from scripts.unified.contract import CONFIG
        self.config = CONFIG
        mark_head = getattr(args, 'mark_head', None)
        self.broker = None
        token_file = getattr(args, 'agent_token_file', None)
        if token_file:
            # Public server: GPU work goes to the connected GPU agent; server CPU / rules engine when it is offline.
            from scripts.app.remote import Broker, RemoteReader, remote_assistant
            self.broker = Broker(Path(token_file).read_text(encoding='utf-8').strip())
            reader = RemoteReader(self.broker, lambda: Reader(args.base, args.head, args.adapter, work, gpu=False,
                                                                 mark_head=mark_head))
            self.assistant = remote_assistant(self.broker, CONFIG, args.assistant_model) if args.assistant_model else None
        else:
            self.assistant = Assistant(CONFIG, model=args.assistant_model) if args.assistant_model else None
            reader = Reader(args.base, args.head, args.adapter, work, gpu=not args.cpu, ollama=OLLAMA, mark_head=mark_head)
        self.processor = Processor(self.store, reader, self.files, self.assistant)
        self.chat_lock = threading.Lock()

    # ------------------------------------------------------------------ auth
    def user(self, request):
        auth = request.headers.get('authorization', '')
        if auth.lower().startswith('bearer '):
            return self.store.api_key_user(auth[7:].strip())
        return self.store.session_user(request.cookies.get(COOKIE))

    def same_origin(self, request):
        if request.headers.get('authorization'):
            return True
        origin = request.headers.get('origin')
        return origin is None or origin == f'{request.url.scheme}://{request.url.netloc}'

    def require(self, request):
        user = self.user(request)
        if user is None:
            if request.headers.get('authorization'):
                return None, error(401, 'unauthorized', 'Неверный или отозванный API-ключ.')
            return None, error(401, 'unauthorized', 'Войдите в аккаунт, чтобы продолжить.')
        if request.method not in ('GET', 'HEAD') and not self.same_origin(request):
            return None, error(403, 'forbidden_origin', 'Запрос отклонён: неизвестный источник.')
        return user, None

    def session_response(self, payload, token, status=200):
        response = JSONResponse(payload, status_code=status)
        response.set_cookie(COOKIE, token, max_age=30 * 86400, httponly=True, samesite='lax', path='/',
                            secure=bool(getattr(self.args, 'secure_cookies', False)))
        return response

    @staticmethod
    def public_user(user):
        return {'id': user['id'], 'email': user['email'], 'name': user['name'], 'auto_approve': bool(user['auto_approve']),
                'created': user['created']}

    async def register(self, request):
        data = await request.json()
        email = str(data.get('email', '')).strip().lower()
        password = str(data.get('password', ''))
        name = str(data.get('name', '')).strip()[:80]
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            return error(400, 'invalid_email', 'Введите корректный адрес почты.')
        if len(password) < 8:
            return error(400, 'weak_password', 'Пароль должен быть не короче 8 символов.')
        if self.store.user_by_email(email):
            return error(409, 'email_taken', 'Аккаунт с этой почтой уже существует. Войдите.')
        user_id = self.store.create_user(email, password, name)
        return self.session_response({'user': self.public_user(self.store.user(user_id))}, self.store.new_session(user_id), 201)

    async def login(self, request):
        data = await request.json()
        user = self.store.user_by_email(str(data.get('email', '')))
        if not user or not check_password(str(data.get('password', '')), user['password']):
            await asyncio.sleep(0.4)
            return error(401, 'bad_credentials', 'Неверная почта или пароль.')
        return self.session_response({'user': self.public_user(user)}, self.store.new_session(user['id']))

    async def logout(self, request):
        self.store.end_session(request.cookies.get(COOKIE))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    async def me(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        if request.method == 'PATCH':
            data = await request.json()
            if 'auto_approve' in data:
                self.store.set_auto_approve(user['id'], bool(data['auto_approve']))
            user = self.store.user(user['id'])
        return JSONResponse({'user': self.public_user(user)})

    async def password(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        data = await request.json()
        if not check_password(str(data.get('current', '')), user['password']):
            return error(400, 'bad_password', 'Текущий пароль указан неверно.')
        if len(str(data.get('new', ''))) < 8:
            return error(400, 'weak_password', 'Новый пароль должен быть не короче 8 символов.')
        self.store.set_password(user['id'], str(data['new']))
        return self.session_response({'ok': True}, self.store.new_session(user['id']))

    # -------------------------------------------------------------- api keys
    async def keys(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        if request.method == 'POST':
            data = await request.json()
            name = str(data.get('name', '')).strip()[:60] or 'Интеграция'
            key_id, key = self.store.new_api_key(user['id'], name)
            return JSONResponse({'id': key_id, 'name': name, 'key': key}, status_code=201)
        return JSONResponse({'keys': self.store.api_keys(user['id'])})

    async def key_delete(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        self.store.delete_api_key(user['id'], int(request.path_params['key_id']))
        return JSONResponse({'ok': True})

    # ------------------------------------------------------------- documents
    def summary(self, doc):
        verified = doc['verified'] or {}
        return {'slug': doc['slug'], 'filename': doc['filename'], 'status': doc['status'], 'error': doc['error'],
                'document_type': doc['document_type'] or doc['requested_type'], 'requested_type': doc['requested_type'],
                'found': doc['found'], 'total': doc['total'], 'valid': bool(doc['valid']), 'approved': bool(doc['approved']),
                'approved_by': doc['approved_by'], 'approved_at': doc['approved_at'], 'created': doc['created'],
                'updated': doc['updated'], 'seconds': doc['seconds'], 'source': doc['source'],
                'verified_count': sum(1 for v in verified.values() if v),
                'queue_position': self.processor.position(doc['slug']) if doc['status'] == 'queued' else 0,
                'url': f'/check/{doc["slug"]}'}

    def detail(self, doc, user):
        folder = self.processor.folder(doc['slug'])
        out = self.summary(doc)
        out['verified'] = doc['verified']
        analysis_file = folder / 'analysis.json'
        if doc['status'] == 'done' and analysis_file.exists():
            analysis = json.loads(analysis_file.read_text(encoding='utf-8'))
            out['analysis'] = {k: analysis[k] for k in ('document_type', 'detected_type', 'type_matches', 'fields',
                                                        'validation', 'review', 'confidence', 'ocr_text', 'model',
                                                        'recovered_from_prose')}
            regions = folder / 'regions.json'
            out['regions'] = json.loads(regions.read_text(encoding='utf-8')) if regions.exists() else {'status': 'pending', 'regions': []}
        chat = folder / 'chat.json'
        out['chat'] = json.loads(chat.read_text(encoding='utf-8')) if chat.exists() else []
        out['preview_url'] = f'/api/documents/{doc["slug"]}/preview'
        out['file_url'] = f'/api/documents/{doc["slug"]}/file'
        return out

    async def documents(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        if request.method == 'GET':
            return JSONResponse({'documents': [self.summary(d) for d in self.store.documents(user['id'])]})
        form = await request.form(max_files=MAX_FILES, max_fields=20)
        kind = str(form.get('document_type') or 'auto')
        if kind not in TYPES:
            return error(400, 'bad_type', 'Неизвестный тип документа.')
        uploads = [f for f in form.getlist('files') + form.getlist('file') if hasattr(f, 'filename')]
        if not uploads:
            return error(400, 'no_files', 'Выберите хотя бы один файл.')
        if len(uploads) > MAX_FILES:
            return error(400, 'too_many_files', f'За один раз можно загрузить не больше {MAX_FILES} файлов.')
        created, rejected = [], []
        for upload in uploads:
            name = Path(upload.filename or 'document').name[:160]
            suffix = Path(name).suffix.lower()
            data = await upload.read()
            if suffix not in ('.png', '.jpg', '.jpeg', '.pdf'):
                rejected.append({'filename': name, 'message': 'Поддерживаются PDF, JPG и PNG.'})
                continue
            if not data or len(data) > MAX_UPLOAD:
                rejected.append({'filename': name, 'message': 'Файл пустой или больше 10 МБ.'})
                continue
            if suffix == '.pdf' and len(re.findall(rb'/Type\s*/Page(?!s)', data)) > 1:
                rejected.append({'filename': name, 'message': 'Многостраничный PDF пока не поддерживается: загрузите одну страницу.'})
                continue
            slug = new_slug()
            folder = self.processor.folder(slug)
            folder.mkdir(parents=True)
            (folder / ('input' + suffix)).write_bytes(data)
            self.store.add_document(slug, user['id'], name, kind, source='api' if request.headers.get('authorization') else 'web')
            self.processor.submit(slug)
            created.append(self.summary(self.store.document(slug)))
        status = 202 if created else 400
        return JSONResponse({'documents': created, 'rejected': rejected}, status_code=status)

    def owned(self, request, user):
        slug = request.path_params['slug']
        if not valid_slug(slug):
            return None
        return self.store.document(slug, user['id'])

    async def document(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден или был удалён.')
        if request.method == 'DELETE':
            import shutil
            self.store.delete_document(doc['slug'], user['id'])
            shutil.rmtree(self.processor.folder(doc['slug']), ignore_errors=True)
            return JSONResponse({'ok': True})
        if (doc['status'] == 'done' and doc['valid'] and not doc['approved'] and user['auto_approve']
                and not request.headers.get('authorization') and request.query_params.get('open') == '1'):
            self.store.update_document(doc['slug'], approved=1, approved_at=time.time(), approved_by='auto')
            doc = self.store.document(doc['slug'])
        return JSONResponse(self.detail(doc, user))

    async def document_type(self, request):
        """Change the document type without re-reading: the same OCR is bound again."""
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None or doc['status'] != 'done':
            return error(404, 'not_found', 'Документ не найден или ещё обрабатывается.')
        kind = str((await request.json()).get('document_type', ''))
        if kind not in TYPES - {'auto'}:
            return error(400, 'bad_type', 'Неизвестный тип документа.')
        folder = self.processor.folder(doc['slug'])
        row = json.loads((folder / 'native-result.json').read_text(encoding='utf-8'))['rows'][0]
        analysis = analyze(row, kind)
        (folder / 'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False), encoding='utf-8')
        found, total = counts(analysis)
        self.store.update_document(doc['slug'], requested_type=kind, document_type=kind, found=found, total=total,
                                   valid=int(analysis['validation']['status'] == 'document_ok'), verified={},
                                   approved=0, approved_at=None, approved_by=None)
        (folder / 'regions.json').write_text(json.dumps({'status': 'pending', 'regions': []}), encoding='utf-8')
        source = next(folder.glob('input.*'))
        self.processor._put(1, 'regions', doc['slug'], (source, folder, analysis))
        return JSONResponse(self.detail(self.store.document(doc['slug']), user))

    async def verify(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        data = await request.json()
        verified = dict(doc['verified'])
        field = str(data.get('field', ''))
        if field:
            verified[field] = bool(data.get('verified', True))
        self.store.update_document(doc['slug'], verified=verified)
        return JSONResponse({'verified': verified})

    async def approve(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None or doc['status'] != 'done':
            return error(404, 'not_found', 'Документ не найден или ещё обрабатывается.')
        approved = bool((await request.json()).get('approved', True))
        self.store.update_document(doc['slug'], approved=int(approved), approved_at=time.time() if approved else None,
                                   approved_by=('api' if request.headers.get('authorization') else 'manual') if approved else None)
        return JSONResponse(self.summary(self.store.document(doc['slug'])))

    async def preview(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        path = self.processor.folder(doc['slug']) / 'preview.png' if doc else None
        if not path or not path.exists():
            return error(404, 'not_found', 'Предпросмотр ещё не готов.')
        return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})

    async def original(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        path = next(self.processor.folder(doc['slug']).glob('input.*'))
        return FileResponse(path, filename=doc['filename'], content_disposition_type='inline')

    # ------------------------------------------------------------------ chat
    async def chat(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None or doc['status'] != 'done':
            return error(409, 'not_ready', 'Дождитесь окончания распознавания.')
        question = str((await request.json()).get('question', '')).strip()
        if not question or len(question) > 2000:
            return error(400, 'bad_question', 'Введите вопрос (до 2000 символов).')
        folder = self.processor.folder(doc['slug'])
        analysis = json.loads((folder / 'analysis.json').read_text(encoding='utf-8'))
        chat_file = folder / 'chat.json'
        history = json.loads(chat_file.read_text(encoding='utf-8')) if chat_file.exists() else []
        result = {k: analysis[k] for k in ('document_type', 'fields', 'validation')}
        stream = request.query_params.get('stream', '1') != '0'
        events = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(event):
            loop.call_soon_threadsafe(events.put_nowait, event)

        def work():
            from scripts.assistant.core import KIND_LABELS, AssistantUnavailable
            from scripts.assistant.http_chat import _partial_answer, _partial_kind
            from scripts.participantkit.format_v1 import answer as rules_answer
            state = {'text': '', 'kind': None}

            def on_stream(raw):
                text, kind = _partial_answer(raw), _partial_kind(raw)
                if kind and kind != state['kind']:
                    state['kind'] = kind
                    emit({'type': 'kind', 'kind': kind, 'label': KIND_LABELS.get(kind, '')})
                if text is not None and len(text) > len(state['text']):
                    emit({'type': 'delta', 'text': text[len(state['text']):]})
                    state['text'] = text
            reply = None
            try:
                if self.assistant is not None:
                    with self.chat_lock:
                        reply = self.assistant.ask(result, question, history=history[-6:], ocr_text=analysis['ocr_text'],
                                                   audit=analysis['audit'], stream_callback=on_stream if stream else None)
            except AssistantUnavailable:
                reply = None
            except Exception:
                reply = None
            if reply is None:
                base = rules_answer(question, result['fields'], result['validation'], self.config)
                if base['value'] in ('true', 'false'):  # contract format keeps booleans; say it in words here
                    base = {**base, 'answer': base['answer'].replace(': true.', ': есть.').replace(': false.', ': не найдена.')}
                kind = 'rule' if any(s.startswith('rule:') for s in base['sources']) else 'found' if base['answerable'] else 'absent'
                reply = {**base, 'kind': kind, 'kind_label': KIND_LABELS[kind], 'followups': [],
                         'fields': [s[6:] for s in base['sources'] if s.startswith('field:')],
                         'rules': [s[5:] for s in base['sources'] if s.startswith('rule:')],
                         'engine': {'type': 'rules'}}
            history.append({'question': question, 'answer': reply['answer'], 'kind': reply['kind'],
                            'fields': reply.get('fields', []), 'rules': reply.get('rules', []), 'reply': reply,
                            'at': time.time()})
            chat_file.write_text(json.dumps(history[-50:], ensure_ascii=False), encoding='utf-8')
            emit({'type': 'final', 'reply': reply})
            emit(None)

        threading.Thread(target=work, daemon=True).start()
        if not stream:
            while True:
                event = await events.get()
                if event and event['type'] == 'final':
                    return JSONResponse(event['reply'])

        async def body():
            while True:
                event = await events.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + '\n'
        return StreamingResponse(body(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})

    async def chat_clear(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        (self.processor.folder(doc['slug']) / 'chat.json').unlink(missing_ok=True)
        return JSONResponse({'ok': True})

    async def health(self, request):
        assistant = False
        if self.assistant is not None:
            assistant = await asyncio.to_thread(self.assistant.available)
        if self.broker is not None:
            reader = 'gpu-agent' if self.broker.connected() else 'server-cpu'
        else:
            reader = 'gpu' if not self.args.cpu else 'cpu'
        return JSONResponse({'status': 'ok', 'assistant': assistant, 'model': getattr(self.assistant, 'model', None),
                             'reader': reader})

    async def spa(self, request):
        return FileResponse(WEB / 'index.html', headers={'Cache-Control': 'no-store'})

    def routes(self):
        api = []
        for prefix in ('/api', '/api/v1'):
            api += [
                Route(prefix + '/documents', self.documents, methods=['GET', 'POST']),
                Route(prefix + '/documents/{slug}', self.document, methods=['GET', 'DELETE']),
                Route(prefix + '/documents/{slug}/type', self.document_type, methods=['POST']),
                Route(prefix + '/documents/{slug}/verify', self.verify, methods=['POST']),
                Route(prefix + '/documents/{slug}/approve', self.approve, methods=['POST']),
                Route(prefix + '/documents/{slug}/preview', self.preview, methods=['GET']),
                Route(prefix + '/documents/{slug}/file', self.original, methods=['GET']),
                Route(prefix + '/documents/{slug}/chat', self.chat, methods=['POST']),
                Route(prefix + '/documents/{slug}/chat', self.chat_clear, methods=['DELETE']),
            ]
        return api + [
            Route('/api/auth/register', self.register, methods=['POST']),
            Route('/api/auth/login', self.login, methods=['POST']),
            Route('/api/auth/logout', self.logout, methods=['POST']),
            Route('/api/auth/password', self.password, methods=['POST']),
            Route('/api/me', self.me, methods=['GET', 'PATCH']),
            Route('/api/keys', self.keys, methods=['GET', 'POST']),
            Route('/api/keys/{key_id:int}', self.key_delete, methods=['DELETE']),
            Route('/api/health', self.health),
            *([WebSocketRoute('/agent/ws', self.broker.endpoint)] if self.broker is not None else []),
            Mount('/assets', StaticFiles(directory=WEB / 'assets'), name='assets'),
            Route('/{path:path}', self.spa),
        ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='work/paddle-vl-base-v1')
    p.add_argument('--head', default='models/unified-experimental-graphic-head-fp32-v3')
    p.add_argument('--adapter', default='models/unified-experimental-natural-v5')
    p.add_argument('--work', default='work/app-v1')
    p.add_argument('--assistant-model', default='qwen3.5:4b')
    p.add_argument('--mark-head', help='Patch-level signature/seal head directory (detection + boxes)')
    p.add_argument('--cpu', action='store_true', help='Read documents on the CPU only')
    p.add_argument('--port', type=int, default=8502)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--secure-cookies', action='store_true', help='Behind HTTPS: send the session cookie as Secure')
    p.add_argument('--agent-token-file', help='Public-server mode: accept a GPU agent at /agent/ws with this token')
    args = p.parse_args()
    app_state = App(args)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_):
        app_state.processor.start()
        yield

    class Revalidate:
        """Static assets are revalidated on every load (ETag), so updates apply at once."""
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http' or not scope['path'].startswith('/assets/'):
                return await self.inner(scope, receive, send)

            async def patched(message):
                if message['type'] == 'http.response.start':
                    headers = [(k, v) for k, v in message['headers'] if k.lower() != b'cache-control']
                    message['headers'] = headers + [(b'cache-control', b'no-cache')]
                await send(message)
            await self.inner(scope, receive, patched)

    app = Starlette(routes=app_state.routes(), middleware=[Middleware(GZipMiddleware, minimum_size=1024), Middleware(Revalidate)],
                    lifespan=lifespan)
    print(f'Онлайн-деканат: http://{args.host}:{args.port}', flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning', proxy_headers=True, forwarded_allow_ips='127.0.0.1',
                ws_max_size=64 * 1024 * 1024, ws_ping_interval=20, ws_ping_timeout=60)


if __name__ == '__main__':
    main()

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
from scripts.app.processing import FastReader, Processor, Reader, cuda_available
from scripts.app import workflow
from scripts.app.store import Store, check_password

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'web-app'
COOKIE = 'dk_session'
TYPES = {'auto', 'study_certificate', 'academic_leave_application', 'internship_certificate'}
MAX_UPLOAD = 10 * 1024 * 1024
MAX_FILES = 20
TEXT_FIELDS_MISSING = 'не найдено'
MAX_MARK_UPLOAD = 2 * 1024 * 1024


PROFILE_ROOT = []  # set by App: where users' signature/seal images live


def error(status, code, message):
    return JSONResponse({'error': code, 'message': message}, status_code=status)


class App:
    def __init__(self, args):
        self.args = args
        work = Path(args.work)
        self.files = work / 'documents'
        self.files.mkdir(parents=True, exist_ok=True)
        self.store = Store(work / 'app.sqlite3')
        PROFILE_ROOT[:] = [str(work / 'profiles')]
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
            # Without the agent the server reads on its own CPU with the fast engine (~5-10 s per page).
            reader = RemoteReader(self.broker, lambda: FastReader(work, getattr(args, 'cpu_python', None)))
            self.assistant = remote_assistant(self.broker, CONFIG, args.assistant_model) if args.assistant_model else None
        else:
            # without a GPU the language model reads a short context, and direct questions skip it (see ask)
            self.assistant = Assistant(CONFIG, model=args.assistant_model, compact=not cuda_available()) if args.assistant_model else None
            engine = getattr(args, 'engine', 'auto')
            if getattr(args, 'cpu', False) and engine == 'auto':
                engine = 'cpu'
            if engine == 'auto':  # the CPU engine binds fields best (realistic forms) and needs no GPU
                engine = 'cpu'
            self.engine = engine
            if engine == 'cpu':
                reader = FastReader(work, getattr(args, 'cpu_python', None))
            else:  # 'gpu' (PaddleOCR-VL, 3.5 s) or 'vlm-cpu' (same model on the CPU, slow; for comparison only)
                reader = Reader(args.base, args.head, args.adapter, work, gpu=engine == 'gpu', ollama=OLLAMA, mark_head=mark_head)
        self.processor = Processor(self.store, reader, self.files, self.assistant)
        from scripts.app import custom_types
        custom_types.register([t['config'] for t in self.store.doc_types()], CONFIG)
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
        marks = Path(PROFILE_ROOT[0]) / str(user['id']) if PROFILE_ROOT else None
        return {'id': user['id'], 'email': user['email'], 'name': user['name'], 'auto_approve': bool(user['auto_approve']),
                'created': user['created'], 'role': user.get('role') or 'student', 'study_group': user.get('study_group') or '',
                'has_signature': bool(marks and (marks / 'signature.png').exists()),
                'has_seal': bool(marks and (marks / 'seal.png').exists())}

    def labels(self):
        from scripts.participantkit.format_v1 import LABELS
        return LABELS

    def type_names(self):
        return dict(workflow.TYPE_NAMES)

    def all_types(self):
        return TYPES | {t['key'] for t in self.store.doc_types()}

    @staticmethod
    def is_staff(user):
        return (user.get('role') or 'student') in ('staff', 'admin')

    def staff_code(self):
        code = self.store.setting('staff_code')
        if not code:
            import secrets
            code = 'DEK-' + secrets.token_hex(3).upper()
            self.store.set_setting('staff_code', code)
        return code

    def require_staff(self, request):
        user, fail = self.require(request)
        if fail:
            return None, fail
        if not self.is_staff(user):
            return None, error(403, 'forbidden_role', 'Это действие доступно только сотрудникам деканата.')
        return user, None

    def require_admin(self, request):
        user, fail = self.require(request)
        if fail:
            return None, fail
        if user.get('role') != 'admin':
            return None, error(403, 'forbidden_role', 'Раздел доступен только администратору.')
        return user, None

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
        role, invite = 'student', None
        if data.get('invite'):  # deanery staff register only through a link issued by the administrator
            invite = self.store.invite(str(data['invite']))
            if invite is None:
                return error(403, 'bad_invite', 'Ссылка-приглашение недействительна или уже использована. Попросите новую у администратора.')
            role = invite['role']
        user_id = self.store.create_user(email, password, name, role)
        self.store.set_profile(user_id, study_group=str(data.get('study_group', '')).strip()[:40])
        if invite:
            self.store.use_invite(str(data['invite']), user_id)
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
            if 'auto_approve' in data and self.is_staff(user):
                self.store.set_auto_approve(user['id'], bool(data['auto_approve']))
            if 'name' in data or 'study_group' in data:
                self.store.set_profile(user['id'], name=str(data['name']).strip()[:80] if 'name' in data else None,
                                       study_group=str(data['study_group']).strip()[:40] if 'study_group' in data else None)
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
                'decision': doc.get('decision'), 'decision_comment': doc.get('decision_comment'),
                'state': doc.get('state') or 'draft', 'state_name': workflow.STATE_NAMES.get(doc.get('state') or 'draft'),
                'submitted_at': doc.get('submitted_at'), 'attempts': doc.get('attempts') or 0, 'version': doc.get('version') or 1,
                'student_comment': doc.get('student_comment'),
                'owner': {'email': doc['owner_email'], 'name': doc['owner_name'], 'group': doc.get('owner_group') or ''}
                if doc.get('owner_email') else None,
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
            out['analysis']['quality'] = analysis.get('quality') or {'readable': True, 'warnings': []}
            regions = folder / 'regions.json'
            out['regions'] = json.loads(regions.read_text(encoding='utf-8')) if regions.exists() else {'status': 'pending', 'regions': []}
            owner = user if doc['user_id'] == user['id'] else (self.store.user(doc['user_id']) or {})
            check = workflow.name_check(owner.get('name'), analysis['fields'].get('student_name'))
            out['name_check'] = check
            out['submit_warning'] = workflow.submit_warning(analysis, check, self.labels())
        chat = folder / 'chat.json'
        out['chat'] = json.loads(chat.read_text(encoding='utf-8')) if chat.exists() else []
        state, mine, staff = doc.get('state') or 'draft', doc['user_id'] == user['id'], self.is_staff(user)
        out['can'] = {'submit': mine and state in ('draft', 'returned') and doc['status'] == 'done',
                      'replace': mine and state in ('draft', 'returned'),
                      'edit': doc['status'] == 'done' and ((mine and state in ('draft', 'returned')) or (staff and state != 'draft')),
                      'decide': staff and state not in ('draft', 'closed') and doc['status'] == 'done',
                      'close': staff and state not in ('draft', 'closed'),
                      'delete': mine and state == 'draft' or (staff and state == 'closed')}
        out['preview_url'] = f'/api/documents/{doc["slug"]}/preview?v={doc.get("version") or 1}-{int(doc["updated"])}'
        out['file_url'] = f'/api/documents/{doc["slug"]}/file'
        return out

    async def documents(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        if request.method == 'GET':
            everyone = self.is_staff(user) and request.query_params.get('mine') != '1'
            return JSONResponse({'documents': [self.summary(d) for d in self.store.documents(None if everyone else user['id'])],
                                 'scope': 'all' if everyone else 'mine'})
        form = await request.form(max_files=MAX_FILES, max_fields=20)
        kind = str(form.get('document_type') or 'auto')
        if kind not in self.all_types():
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
            self.store.add_event(slug, user['id'], 'uploaded', filename=name, version=1)
            self.processor.submit(slug)
            created.append(self.summary(self.store.document(slug)))
        status = 202 if created else 400
        return JSONResponse({'documents': created, 'rejected': rejected}, status_code=status)

    def owned(self, request, user):
        slug = request.path_params['slug']
        if not valid_slug(slug):
            return None
        doc = self.store.document(slug, None if self.is_staff(user) else user['id'])
        if doc is not None and self.is_staff(user) and doc['user_id'] != user['id'] and (doc.get('state') or 'draft') == 'draft':
            return None  # a student's draft is private until it is sent to the deanery
        if doc is not None and self.is_staff(user) and doc['user_id'] != user['id']:
            owner = self.store.user(doc['user_id']) or {}
            doc['owner_email'], doc['owner_name'], doc['owner_group'] = owner.get('email'), owner.get('name'), owner.get('study_group')
        return doc

    async def document(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден или был удалён.')
        if request.method == 'DELETE':
            import shutil
            state = doc.get('state') or 'draft'
            if not ((doc['user_id'] == user['id'] and state == 'draft') or (self.is_staff(user) and state == 'closed')):
                return error(409, 'not_deletable', 'Отправленную заявку нельзя удалить: её видит деканат. Удалить можно черновик.')
            self.store.delete_document(doc['slug'], None if self.is_staff(user) else user['id'])
            shutil.rmtree(self.processor.folder(doc['slug']), ignore_errors=True)
            return JSONResponse({'ok': True})
        opened = request.query_params.get('open') == '1' and not request.headers.get('authorization')
        if opened and self.is_staff(user) and doc['user_id'] != user['id'] and doc.get('state') == 'submitted':
            self.store.update_document(doc['slug'], state='review')
            self.store.add_event(doc['slug'], user['id'], 'review')
            doc = self.owned(request, user)
        if (opened and doc['status'] == 'done' and doc['valid'] and doc.get('state') in ('submitted', 'review')
                and self.is_staff(user) and user['auto_approve']):
            self.store.update_document(doc['slug'], approved=1, approved_at=time.time(), approved_by='auto',
                                       decision='approved', decided_by=user['id'], state='approved')
            self.store.add_event(doc['slug'], user['id'], 'auto_approved')
            doc = self.owned(request, user)
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
        if kind not in self.all_types() - {'auto'}:
            return error(400, 'bad_type', 'Неизвестный тип документа.')
        folder = self.processor.folder(doc['slug'])
        row = json.loads((folder / 'native-result.json').read_text(encoding='utf-8'))['rows'][0]
        if row.get('engine') == 'cpu-fast':
            self.store.update_document(doc['slug'], requested_type=kind, document_type=kind, status='queued', verified={},
                                       approved=0, approved_at=None, approved_by=None, decision=None, decision_comment=None)
            self.processor.submit(doc['slug'])
            return JSONResponse(self.detail(self.owned(request, user), user))
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
        user, fail = self.require_staff(request)
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
        """Deanery decision: approve, return to the student with a comment, or reset. Staff only."""
        user, fail = self.require_staff(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None or doc['status'] != 'done':
            return error(404, 'not_found', 'Документ не найден или ещё обрабатывается.')
        data = await request.json()
        decision = data.get('decision')
        if decision is None and 'approved' in data:
            decision = 'approved' if data['approved'] else None
        if decision not in ('approved', 'returned', None):
            return error(400, 'bad_decision', 'Решение: approved, returned или null.')
        comment = str(data.get('comment') or '').strip()[:1000] or None
        if decision == 'returned' and not comment:
            return error(400, 'comment_required', 'Напишите студенту, что нужно исправить.')
        if (doc.get('state') or 'draft') in ('draft', 'closed'):
            return error(409, 'not_submitted', 'Решение принимается по отправленной заявке.')
        approved = decision == 'approved'
        self.store.update_document(doc['slug'], decision=decision, decision_comment=comment if decision else None,
                                   decided_by=user['id'] if decision else None, state=decision or 'review',
                                   approved=int(approved), approved_at=time.time() if approved else None,
                                   approved_by=('api' if request.headers.get('authorization') else 'manual') if approved else None)
        self.store.add_event(doc['slug'], user['id'], decision or 'reset', comment=comment)
        return JSONResponse(self.detail(self.owned(request, user), user))

    # ------------------------------------------------------------- workflow
    async def submit(self, request):
        """The student sends the checked document to the deanery (optionally with a comment)."""
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None or doc['user_id'] != user['id']:
            return error(404, 'not_found', 'Документ не найден.')
        if doc['status'] != 'done':
            return error(409, 'not_ready', 'Дождитесь окончания проверки.')
        if (doc.get('state') or 'draft') not in ('draft', 'returned'):
            return error(409, 'already_sent', 'Заявка уже в деканате.' if doc.get('state') != 'closed' else 'Заявка закрыта деканатом.')
        comment = str((await request.json()).get('comment') or '').strip()[:1000] or None
        self.store.update_document(doc['slug'], state='submitted', submitted_at=time.time(), student_comment=comment,
                                   attempts=(doc.get('attempts') or 0) + 1, decision=None, decision_comment=None,
                                   approved=0, approved_at=None, approved_by=None)
        self.store.add_event(doc['slug'], user['id'], 'submitted', comment=comment, found=f"{doc['found']}/{doc['total']}",
                             attempt=(doc.get('attempts') or 0) + 1)
        return JSONResponse(self.detail(self.owned(request, user), user))

    async def close(self, request):
        user, fail = self.require_staff(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None or (doc.get('state') or 'draft') in ('draft', 'closed'):
            return error(404, 'not_found', 'Заявка не найдена или уже закрыта.')
        comment = str((await request.json()).get('comment') or '').strip()[:1000] or None
        self.store.update_document(doc['slug'], state='closed', decision_comment=comment or doc.get('decision_comment'))
        self.store.add_event(doc['slug'], user['id'], 'closed', comment=comment)
        return JSONResponse(self.detail(self.owned(request, user), user))

    async def replace(self, request):
        """New file for the same application (student's fix or an edit made in the editor). History keeps the old one."""
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        form = await request.form(max_files=1, max_fields=5)
        upload = form.get('file')
        if not hasattr(upload, 'filename'):
            return error(400, 'no_files', 'Выберите файл.')
        source = 'editor' if form.get('source') == 'editor' else 'upload'
        state, mine = doc.get('state') or 'draft', doc['user_id'] == user['id']
        allowed = (mine and state in ('draft', 'returned')) or (source == 'editor' and self.is_staff(user) and state != 'draft')
        if not allowed:
            return error(409, 'locked', 'Файл можно заменить в черновике или после возврата из деканата.')
        name = Path(upload.filename or 'document.png').name[:160]
        suffix = Path(name).suffix.lower()
        data = await upload.read()
        if suffix not in ('.png', '.jpg', '.jpeg', '.pdf') or not data or len(data) > MAX_UPLOAD:
            return error(400, 'bad_file', 'Нужен PDF, JPG или PNG до 10 МБ.')
        if suffix == '.pdf' and len(re.findall(rb'/Type\s*/Page(?!s)', data)) > 1:
            return error(400, 'multipage', 'Многостраничный PDF пока не поддерживается: загрузите одну страницу.')
        import shutil
        folder = self.processor.folder(doc['slug'])
        version = doc.get('version') or 1
        history = folder / 'history' / f'v{version}'
        history.mkdir(parents=True, exist_ok=True)
        for item in list(folder.iterdir()):
            if item.is_file() and item.name != 'chat.json':
                shutil.move(str(item), history / item.name)
        self.store.add_version(doc['slug'], version, doc['filename'], 'archived', doc['found'], doc['total'])
        (folder / ('input' + suffix)).write_bytes(data)
        ops = str(form.get('ops') or '')[:2000]
        filename = name if source == 'upload' else Path(doc['filename']).stem + ' (изменён)' + suffix
        self.store.update_document(doc['slug'], version=version + 1, filename=filename, status='queued', verified={},
                                   found=None, total=None, valid=None, error=None,
                                   state=state if (self.is_staff(user) and not mine) else 'draft')
        self.store.add_event(doc['slug'], user['id'], 'edited' if source == 'editor' else 'replaced',
                             filename=filename, version=version + 1, ops=ops or None)
        self.processor.submit(doc['slug'])
        return JSONResponse(self.detail(self.owned(request, user), user))

    async def history(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        events = [{'at': e['at'], 'kind': e['kind'], 'title': workflow.EVENT_NAMES.get(e['kind'], e['kind']),
                   'who': None if not e.get('user_email') else (e.get('user_name') or e['user_email']),
                   'role': e.get('user_role'), 'detail': e['detail']} for e in self.store.events(doc['slug'])]
        return JSONResponse({'events': events, 'versions': self.store.versions(doc['slug'])})

    async def version_file(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        n = int(request.path_params['n'])
        folder = self.processor.folder(doc['slug']) / 'history' / f'v{n}' if doc else None
        files = list(folder.glob('input.*')) if folder and folder.exists() else []
        if not files:
            return error(404, 'not_found', 'Версия не найдена.')
        return FileResponse(files[0], content_disposition_type='inline')

    async def page_image(self, request):
        """Full-resolution page of the current file, for the editor."""
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        folder = self.processor.folder(doc['slug'])
        target = folder / f'page-v{doc.get("version") or 1}.png'
        if not target.exists():
            from scripts.unified.model import read_document
            image = read_document(next(folder.glob('input.*'))).convert('RGB')
            image.thumbnail((2400, 2400))
            image.save(target)
        return FileResponse(target, media_type='image/png', headers={'Cache-Control': 'private, max-age=600'})

    async def protocol(self, request):
        user, fail = self.require(request)
        if fail:
            return fail
        doc = self.owned(request, user)
        if doc is None:
            return error(404, 'not_found', 'Документ не найден.')
        owner = self.store.user(doc['user_id']) or {}
        doc = {**doc, 'owner_email': owner.get('email'), 'owner_name': owner.get('name')}
        folder = self.processor.folder(doc['slug'])
        analysis_file = folder / 'analysis.json'
        analysis = json.loads(analysis_file.read_text(encoding='utf-8')) if analysis_file.exists() else None
        data = await asyncio.to_thread(workflow.protocol_pdf, doc, analysis, self.store.events(doc['slug']), self.labels(),
                                       self.type_names(), folder / 'preview.png')
        name = f'protocol-{doc["slug"]}.pdf'
        return Response(data, media_type='application/pdf', headers={'Content-Disposition': f'inline; filename="{name}"'})

    async def export(self, request):
        user, fail = self.require_staff(request)
        if fail:
            return fail
        docs = self.filtered_inbox(request)
        deciders = {u['id']: u for u in self.store.users()}
        for d in docs:
            who = deciders.get(d.get('decided_by'))
            d['decider'] = (who['name'] or who['email']) if who else ('авто' if d.get('approved_by') == 'auto' else '')
        slugs = {d['slug'] for d in docs}
        events = [e for e in self.store.events() if e['slug'] in slugs]
        data = await asyncio.to_thread(workflow.export_xlsx, docs, events, self.type_names())
        return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': f'attachment; filename="dekanat-{time.strftime("%Y%m%d")}.xlsx"'})

    def filtered_inbox(self, request):
        docs = self.store.documents(None)
        kind, group, state = (request.query_params.get(k) for k in ('type', 'group', 'state'))
        if kind:
            docs = [d for d in docs if (d.get('document_type') or d['requested_type']) == kind]
        if group:
            docs = [d for d in docs if (d.get('owner_group') or '').casefold() == group.casefold()]
        if state:
            docs = [d for d in docs if d.get('state') == state]
        return docs

    # -------------------------------------------------------- profile marks
    async def profile_mark(self, request):
        """The user's own signature (everyone) or the deanery seal (staff), as a transparent PNG."""
        user, fail = self.require(request)
        if fail:
            return fail
        kind = request.path_params['kind']
        if kind not in ('signature', 'seal') or (kind == 'seal' and not self.is_staff(user)):
            return error(403, 'forbidden_role', 'Печать деканата может загрузить только сотрудник деканата.')
        folder = Path(PROFILE_ROOT[0]) / str(user['id'])
        path = folder / f'{kind}.png'
        if request.method == 'GET':
            return FileResponse(path, media_type='image/png') if path.exists() else error(404, 'not_found', 'Ещё не загружено.')
        if request.method == 'DELETE':
            path.unlink(missing_ok=True)
            return JSONResponse({'user': self.public_user(self.store.user(user['id']))})
        form = await request.form(max_files=1, max_fields=2)
        upload = form.get('file')
        data = await upload.read() if hasattr(upload, 'filename') else b''
        if not data.startswith(b'\x89PNG') or len(data) > MAX_MARK_UPLOAD:
            return error(400, 'bad_file', 'Нужен PNG до 2 МБ.')
        folder.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return JSONResponse({'user': self.public_user(self.store.user(user['id']))})

    # ---------------------------------------------------------------- admin
    async def admin_users(self, request):
        user, fail = self.require_admin(request)
        if fail:
            return fail
        return JSONResponse({'users': self.store.users(), 'invites': self.store.invites()})

    async def admin_user(self, request):
        user, fail = self.require_admin(request)
        if fail:
            return fail
        target = int(request.path_params['user_id'])
        role = str((await request.json()).get('role', ''))
        if role not in ('student', 'staff', 'admin'):
            return error(400, 'bad_role', 'Роль: student, staff или admin.')
        if target == user['id'] and role != 'admin':
            return error(400, 'self_demote', 'Нельзя снять права администратора с самого себя.')
        self.store.set_role(target, role)
        return JSONResponse({'users': self.store.users()})

    async def admin_invites(self, request):
        user, fail = self.require_admin(request)
        if fail:
            return fail
        if request.method == 'DELETE':
            self.store.revoke_invite(request.path_params['prefix'])
            return JSONResponse({'invites': self.store.invites()})
        data = await request.json()
        role = 'admin' if data.get('role') == 'admin' else 'staff'
        token = self.store.new_invite(user['id'], role, str(data.get('note', '')).strip()[:80])
        link = f'{request.url.scheme}://{request.url.netloc}/register?invite={token}'
        return JSONResponse({'link': link, 'invites': self.store.invites()}, status_code=201)

    # ------------------------------------------------------- document types
    async def types(self, request):
        """Built-in and constructor types with their field labels (everyone signed in)."""
        user, fail = self.require(request)
        if fail:
            return fail
        from scripts.app import custom_types
        labels = self.labels()
        from scripts.unified.contract import KEYS
        out = [{'key': k, 'title': v, 'builtin': True, 'fields': [{'key': f, 'label': labels.get(f, f)} for f in KEYS[k]]}
               for k, v in workflow.TYPE_NAMES.items() if k in TYPES]
        for t in self.store.doc_types():
            c = t['config']
            out.append({'key': c['key'], 'title': c['title'], 'builtin': False, 'config': c, 'created': t['created'],
                        'fields': [{'key': f, 'label': labels.get(f, f)} for f in custom_types.field_keys(c)]})
        return JSONResponse({'types': out, 'field_kinds': custom_types.FIELD_KINDS})

    async def admin_types(self, request):
        user, fail = self.require_admin(request)
        if fail:
            return fail
        from scripts.app import custom_types
        key = request.path_params.get('key')
        if request.method == 'DELETE':
            if key in TYPES:
                return error(400, 'builtin', 'Встроенные типы удалить нельзя.')
            self.store.delete_doc_type(key)
            custom_types.unregister(key, self.config)
            return await self.types(request)
        data = await request.json()
        if key is not None and key not in {t['key'] for t in self.store.doc_types()}:
            return error(404, 'not_found', 'Тип не найден.')
        try:
            config = custom_types.clean(data, key or custom_types.new_key())
        except ValueError as exc:
            return error(400, 'bad_type', str(exc))
        self.store.save_doc_type(config['key'], config['title'], config, user['id'])
        custom_types.register([config], self.config)
        response = await self.types(request)
        response.status_code = 200 if key else 201
        return response

    # ------------------------------------------------------------- live camera
    def live_reader(self):
        if self.broker is not None:
            return self.processor.reader  # the GPU agent's PC (fast engine there) or the server CPU
        if getattr(self, '_live', None) is None:
            self._live = FastReader(Path(self.args.work), getattr(self.args, 'cpu_python', None))
        return self._live

    async def live_scan(self, request):
        """One camera frame -> document type, fields with values, boxes on the frame, quality warnings. Nothing is stored."""
        user, fail = self.require(request)
        if fail:
            return fail
        form = await request.form(max_files=1, max_fields=2)
        frame = form.get('frame')
        data = await frame.read() if hasattr(frame, 'filename') else b''
        if not data or len(data) > 4 * 1024 * 1024:
            return error(400, 'bad_frame', 'Кадр не получен.')
        import tempfile
        folder = Path(tempfile.mkdtemp(prefix='live-', dir=str(Path(self.args.work))))
        try:
            source, output = folder / 'frame.jpg', folder / 'native-result.json'
            source.write_bytes(data)
            await asyncio.to_thread(self.live_reader().run, 'ocr', source, output, document_type='auto', quick=True,
                                    custom_types=self.processor.custom_types())
            row = json.loads(output.read_text(encoding='utf-8'))['rows'][0]
        except Exception as exc:
            return error(503, 'live_failed', 'Не удалось разобрать кадр: ' + str(exc)[:120])
        finally:
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        live = row.get('live') or {'regions': [], 'sheet': None, 'warnings': []}
        fields = row.get('fields') or {}
        return JSONResponse({'document_type': row.get('detected_type'), 'type_name': self.type_names().get(row.get('detected_type')),
                             'fields': {k: v for k, v in fields.items() if v not in (None, 'не найдено')},
                             'missing': (row.get('validation') or {}).get('missing_fields', []),
                             'regions': live['regions'], 'sheet': live['sheet'], 'warnings': live['warnings'],
                             'sheet_share': live.get('sheet_share'), 'readable': live.get('readable', True),
                             'seconds': row.get('seconds')})

    async def invite_info(self, request):
        invite = self.store.invite(request.path_params['token'])
        if invite is None:
            return error(404, 'bad_invite', 'Ссылка-приглашение недействительна или уже использована.')
        return JSONResponse({'role': invite['role'], 'note': invite['note'], 'expires': invite['expires']})

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
            base = rules_answer(question, result['fields'], result['validation'], self.config)
            # CPU-only model: a direct question (a field value, completeness, who decides) is answered by the rules
            # at once instead of waiting 15-30 s for the language model; open questions still go to the model
            routed = base['answerable'] and (self.assistant is None or getattr(self.assistant, 'compact', False))
            try:
                if self.assistant is not None and not routed:
                    with self.chat_lock:
                        reply = self.assistant.ask(result, question, history=history[-6:], ocr_text=analysis['ocr_text'],
                                                   audit=analysis['audit'], stream_callback=on_stream if stream else None)
            except AssistantUnavailable:
                reply = None
            except Exception:
                reply = None
            if reply is None:
                if base['value'] in ('true', 'false'):  # contract format keeps booleans; say it in words here
                    base = {**base, 'answer': base['answer'].replace(': true.', ': есть.').replace(': false.', ': не найдена.')}
                kind = 'rule' if any(s.startswith('rule:') for s in base['sources']) else 'found' if base['answerable'] else 'absent'
                reply = {**base, 'kind': kind, 'kind_label': KIND_LABELS[kind], 'followups': [],
                         'fields': [s[6:] for s in base['sources'] if s.startswith('field:')],
                         'rules': [s[5:] for s in base['sources'] if s.startswith('rule:')],
                         'engine': {'type': 'rules', 'routed': bool(routed)}}
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
            reader = {'gpu': 'gpu', 'cpu': 'cpu-fast'}.get(getattr(self, 'engine', 'gpu'), self.engine)
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
                Route(prefix + '/documents/{slug}/submit', self.submit, methods=['POST']),
                Route(prefix + '/documents/{slug}/close', self.close, methods=['POST']),
                Route(prefix + '/documents/{slug}/replace', self.replace, methods=['POST']),
                Route(prefix + '/documents/{slug}/history', self.history, methods=['GET']),
                Route(prefix + '/documents/{slug}/versions/{n:int}/file', self.version_file, methods=['GET']),
                Route(prefix + '/documents/{slug}/page.png', self.page_image, methods=['GET']),
                Route(prefix + '/documents/{slug}/protocol.pdf', self.protocol, methods=['GET']),
            ]
        return api + [
            Route('/api/auth/register', self.register, methods=['POST']),
            Route('/api/auth/login', self.login, methods=['POST']),
            Route('/api/auth/logout', self.logout, methods=['POST']),
            Route('/api/auth/password', self.password, methods=['POST']),
            Route('/api/me', self.me, methods=['GET', 'PATCH']),
            Route('/api/keys', self.keys, methods=['GET', 'POST']),
            Route('/api/keys/{key_id:int}', self.key_delete, methods=['DELETE']),
            Route('/api/admin/users', self.admin_users, methods=['GET']),
            Route('/api/admin/users/{user_id:int}', self.admin_user, methods=['PATCH']),
            Route('/api/admin/invites', self.admin_invites, methods=['POST']),
            Route('/api/types', self.types, methods=['GET']),
            Route('/api/admin/types', self.admin_types, methods=['POST']),
            Route('/api/admin/types/{key}', self.admin_types, methods=['PUT', 'DELETE']),
            Route('/api/admin/invites/{prefix}', self.admin_invites, methods=['DELETE']),
            Route('/api/invites/{token}', self.invite_info, methods=['GET']),
            Route('/api/live/scan', self.live_scan, methods=['POST']),
            Route('/api/staff/export.xlsx', self.export, methods=['GET']),
            Route('/api/me/marks/{kind}', self.profile_mark, methods=['GET', 'POST', 'DELETE']),
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
    p.add_argument('--cpu', action='store_true', help='Same as --engine cpu')
    p.add_argument('--engine', choices=['auto', 'gpu', 'cpu', 'vlm-cpu'], default='auto',
                   help='auto/cpu: fast engine, ~6 s per page on a CPU; gpu: PaddleOCR-VL single network (3.5 s on a GPU)')
    p.add_argument('--cpu-python', help='Python of the CPU-engine environment (default: work/venv)')
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

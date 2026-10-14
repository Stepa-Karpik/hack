"""Existing web UI with a separate one-backbone CPU analysis boundary."""
import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from scripts.participantkit.http_api import JobStore, make_server
from scripts.unified.contract import KEYS, MARKS, official_result
from scripts.unified.model import read_document


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--head', type=Path, required=True)
    p.add_argument('--adapter', type=Path)
    p.add_argument('--adapter-label', default='LoRA v3')
    p.add_argument('--study-prose', action='store_true')
    p.add_argument('--literal-layout', action='store_true')
    p.add_argument('--literal-layout-v2', action='store_true', help='Also split runs of several schema labels on one line')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--port', type=int, default=8502)
    p.add_argument('--assistant-model', help='Local Ollama model for the document chat (no external API)')
    p.add_argument('--assistant-cpu', action='store_true', help='Keep the chat model off the GPU')
    p.add_argument('--web-root', type=Path, help='Alternative local frontend directory')
    p.add_argument('--persistent-worker', action='store_true', help='Keep the reader loaded between uploads')
    p.add_argument('--worker-gpu', action='store_true',
                   help='Persistent reader keeps weights in RAM and reads each page on the GPU (CPU fallback)')
    args = p.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]

    def infer(data, filename, kind, questions, *, document_id):
        folder = args.work / document_id
        folder.mkdir()
        source = folder / ('input' + Path(filename).suffix.lower())
        source.write_bytes(data)
        # One-page native eligibility remains intact, including graphic-only pages.
        image = read_document(source)
        output = folder / 'native-result.json'
        if args.persistent_worker:
            worker.read(source, output, folder / 'inference.log')
            regions_state[document_id] = {'status': 'pending', 'regions': []}
            threading.Thread(target=build_regions, args=(document_id, source, folder), daemon=True).start()
        else:
            run_subprocess(source, output, folder)
        return finish(data, kind, questions, document_id, image, output)

    def run_subprocess(source, output, folder):
        command = [sys.executable, '-m', 'scripts.unified.run_graphic_strict', '--base', str(args.base),
                   '--head', str(args.head), '--inputs', str(source), '--output', str(output),
                   '--precision', 'fp32', '--device', 'cpu', '--threads', '6']
        if args.adapter:
            command.extend(['--adapter', str(args.adapter)])
        with (folder / 'inference.log').open('w', encoding='utf-8') as log:
            subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)

    class Worker:
        """Long-lived reader process: same computation, model loaded once."""
        def __init__(self):
            self.process = None
            self.lock = threading.Lock()

        def start(self):
            command = [sys.executable, '-m', 'scripts.unified.native_worker', '--base', str(args.base),
                       '--head', str(args.head), '--device', 'cuda' if args.worker_gpu else 'cpu', '--threads', '6']
            if args.worker_gpu:
                from scripts.assistant.core import OLLAMA
                command.extend(['--swap', '--ollama', OLLAMA])
            if args.adapter:
                command.extend(['--adapter', str(args.adapter)])
            log = (args.work / 'native-worker.log').open('a', encoding='utf-8')
            self.process = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=log, text=True, encoding='utf-8', bufsize=1)
            self.expect('ready')

        def expect(self, key):
            for line in self.process.stdout:
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                if isinstance(reply, dict) and key in reply:
                    return reply
            raise RuntimeError('Native worker stopped')

        def read(self, source, output, log_path, task='ocr'):
            with self.lock:
                if self.process is None or self.process.poll() is not None:
                    self.start()
                self.process.stdin.write(json.dumps({'input': str(source), 'output': str(output), 'task': task}) + '\n')
                self.process.stdin.flush()
                reply = self.expect('ok')
            log_path.write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
            if not reply['ok']:
                raise RuntimeError(reply.get('error', 'native worker failed'))

    worker = Worker()
    regions_state = {}

    def build_regions(document_id, source, folder):
        """Background: same-model Spotting -> line boxes for found fields (highlighting)."""
        from scripts.unified.field_regions import field_regions
        state = regions_state[document_id]
        try:
            worker.read(source, folder / 'spotting.json', folder / 'spotting.log', task='spotting')
            spotting = json.loads((folder / 'spotting.json').read_text(encoding='utf-8'))
            for _ in range(600):  # wait until the JobStore published the analysis result
                with store.lock:
                    job = store.jobs.get(document_id)
                    if job is None or job['status'] != 'running':
                        break
                time.sleep(0.1)
            with store.lock:
                job = store.jobs.get(document_id)
                if job is None or job['status'] != 'done':
                    state['status'] = 'failed'
                    return
                response = job['response']
                found = field_regions(spotting['raw'], response['result']['fields'], response['audit']['bindings'])
                response['document_view']['regions'] = found
                response['document_view']['scope'] = 'Line boxes from the same model Spotting task; not verified geometry'
            state.update(status='done', regions=found, seconds=round(spotting['seconds'], 1))
        except Exception:
            state['status'] = 'failed'
        finally:
            if args.worker_gpu and assistant is not None:
                assistant.warm()
    if args.persistent_worker:
        def preload():
            with worker.lock:
                if worker.process is None:
                    worker.start()
        threading.Thread(target=preload, daemon=True).start()

    def finish(data, kind, questions, document_id, image, output):
        native = json.loads(output.read_text(encoding='utf-8'))
        if not native['complete'] or len(native['rows']) != 1:
            raise ValueError('Incomplete native result')
        row = native['rows'][0]
        binding = row['binding']
        logical_text = row['raw_ocr']
        layout_edits = []
        if args.literal_layout and not row['token_budget_reached']:
            from scripts.unified.literal_layout import separate_empty_labels
            from scripts.unified.text_binding import bind
            logical_text, layout_edits = separate_empty_labels(logical_text)
            if args.literal_layout_v2:
                from scripts.unified.literal_layout import separate_label_runs
                logical_text, more = separate_label_runs(logical_text)
                layout_edits = layout_edits + more
            binding = bind(logical_text)
        recovered = []
        if args.study_prose:
            from scripts.unified.prose_binding import recover
            updated = recover(logical_text, binding, truncated=row['token_budget_reached'])
            recovered = [key for key, value in updated['fields'].items()
                         if value is not None and binding['fields'].get(key) is None]
            binding = updated
        matched = binding['document_type'] == kind
        fields = dict(binding['fields']) if matched else {key: None for key in KEYS[kind]}
        audit = dict(binding['audit']) if matched else {key: {'status': 'not_found', 'source': 'native_title_mismatch',
            'semantic_confidence': None, 'source_confidence': None, 'bbox': None} for key in fields}
        for key in MARKS & set(fields):
            fields[key] = row['graphic_prediction'][key]
            audit[key] = {'status': 'uncertain', 'source': 'shared_visual_graphic_readout',
                          'semantic_confidence': None, 'source_confidence': None, 'bbox': None,
                          'geometry_verified': False,
                          'classifier_score_uncalibrated': row['graphic_scores_uncalibrated'][0 if key == 'signature_present' else 1]}
        result = official_result({'document_type': kind, 'fields': fields, 'boxes': {key: None for key in fields}}, questions)
        result['document_id'] = document_id
        image.thumbnail((1600, 2000))
        pixels = io.BytesIO()
        image.save(pixels, format='PNG')
        response = {'version': 'isolated-native-web-v1', 'result': result, 'audit': {'bindings': audit,
                    'native': native, 'requested_type_matches_native': matched, 'production': False,
                    'study_prose_recovery': {'enabled': args.study_prose,
                        'fields': recovered if matched else [], 'extra_nn_calls': 0},
                    'literal_layout': {'enabled':args.literal_layout, 'v2':args.literal_layout_v2, 'edits':layout_edits,
                        'value_characters_changed':0, 'geometry_verified':False}},
                    'ocr': {'text': logical_text, 'raw_text': row['raw_ocr'], 'retries': 0}, 'seconds': row['seconds'],
                    'input_sha256': hashlib.sha256(data).hexdigest(),
                    'document_view': {'pages': [{'page': 0, 'width': image.width, 'height': image.height,
                        'image': 'data:image/png;base64,' + base64.b64encode(pixels.getvalue()).decode()}],
                        'regions': [], 'scope': 'Original one-page preview, native geometry unqualified'}}
        (output.parent / 'response.json').write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
        return response

    store = JobStore(infer=infer, pending=2, capacity=8)
    server = make_server(args.port, store=store)
    old_handler = server.RequestHandlerClass
    from scripts.assistant.core import Assistant
    from scripts.assistant.http_chat import ChatService
    from scripts.unified.contract import CONFIG
    assistant = None
    if args.assistant_model:
        assistant = Assistant(CONFIG, model=args.assistant_model, options={'num_gpu': 0} if args.assistant_cpu else {})
    chat = ChatService(store, assistant, CONFIG)
    web_root = args.web_root.resolve() if args.web_root else root / 'web'
    assets = {'assets/style.css': ('style.css', 'text/css; charset=utf-8'),
              'assets/app.js': ('app.js', 'text/javascript; charset=utf-8'),
              'assets/assistant.js': ('assistant.js', 'text/javascript; charset=utf-8'),
              'assets/assistant.css': ('assistant.css', 'text/css; charset=utf-8'),
              # Original fictional demo pages (project-generated, no organizer or user data).
              'assets/samples/study.png': ('samples/study.png', 'image/png'),
              'assets/samples/leave.png': ('samples/leave.png', 'image/png'),
              'assets/samples/internship.png': ('samples/internship.png', 'image/png')}

    class Handler(old_handler):
        def send_static(self, name, mime):
            data = (web_root / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            key = '/'.join(self.route())
            if key == 'v1/assistant':
                return self.send_json(200, chat.status())
            if len(self.route()) == 4 and self.route()[:2] == ['v1', 'jobs'] and self.route()[3] == 'regions':
                return self.send_json(200, regions_state.get(self.route()[2], {'status': 'unavailable', 'regions': []}))
            if len(self.route()) == 4 and self.route()[:2] == ['v1', 'jobs'] and self.route()[3] == 'chat':
                return self.send_json(200, {'history': chat.history(self.route()[2])})
            if key in assets and (web_root / assets[key][0]).is_file():
                return self.send_static(*assets[key])
            if not self.route():
                html = (web_root / 'index.html').read_text(encoding='utf-8')
                html = html.replace('<title>Онлайн-деканат</title>', '<title>Онлайн-деканат — новая модель</title>')
                html = html.replace('class="wordmark" href="/">Онлайн-деканат</a>',
                                    'class="wordmark" href="/">Онлайн-деканат · Paddle FP32</a>')
                html = html.replace('>Документация</a>', '>Эксперимент · CPU · headv3</a>')
                if args.adapter:
                    import html as html_escape
                    html = html.replace('Эксперимент · CPU · headv3', 'Эксперимент · ' + ('GPU' if args.worker_gpu else 'CPU') + ' · ' + html_escape.escape(args.adapter_label))
                if assistant is not None:
                    import html as html_escape
                    html = html.replace('</head>', '<meta name="dekanat-assistant" content="' + html_escape.escape(assistant.model) + '"></head>')
                content = html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(content)
                return
            super().do_GET()

        def do_POST(self):
            if self.headers.get('Origin') not in {None, f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}'}:
                return self.send_json(403, {'error': 'local_origin_required'})
            route = self.route()
            if len(route) == 4 and route[:2] == ['v1', 'jobs'] and route[3] == 'chat':
                return self.chat(route[2])
            super().do_POST()

        def chat(self, key):
            try:
                payload = self.body()
                question = payload.get('question') if isinstance(payload, dict) else None
                job = store.get(key)
                if job['status'] != 'done':
                    return self.send_json(409, {'error': 'document_not_ready'})
                if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                    raise ValueError('question')
            except KeyError:
                return self.send_json(404, {'error': 'job_not_found'})
            except (ValueError, TypeError, UnicodeError):
                return self.send_json(400, {'error': 'invalid_request'})
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()

            def emit(event):
                self.wfile.write((json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8'))
                self.wfile.flush()
            try:
                chat.answer(key, question, emit)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                try:
                    emit({'type': 'error', 'error': 'assistant_failed'})
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def do_DELETE(self):
            route = self.route()
            if len(route) == 4 and route[:2] == ['v1', 'jobs'] and route[3] == 'chat':
                chat.reset(route[2])
                return self.send_json(200, {'reset': True})
            if len(route) == 3 and route[:2] == ['v1', 'jobs']:
                chat.reset(route[2])
            super().do_DELETE()

    server.RequestHandlerClass = Handler
    print(f'Existing UI, isolated native CPU model: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()

"""Background document queue: one persistent reader process, FIFO, survives restarts."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from scripts.app.pipeline import analyze, counts

ROOT = Path(__file__).resolve().parents[2]


class Reader:
    """Talks to scripts.unified.native_worker over stdin/stdout (model loaded once)."""

    def __init__(self, base, head, adapter, work, gpu=True, ollama=None, mark_head=None):
        self.command = [sys.executable, '-m', 'scripts.unified.native_worker', '--base', str(base), '--head', str(head),
                        '--device', 'cuda' if gpu else 'cpu', '--threads', os.environ.get('DEKANAT_THREADS', '6')]
        if adapter:
            self.command += ['--adapter', str(adapter)]
        if gpu:
            self.command += ['--swap'] + (['--ollama', ollama] if ollama else [])
        if mark_head:
            self.command += ['--mark-head', str(mark_head)]
        self.log = Path(work) / 'reader.log'
        self.process = None
        self.lock = threading.Lock()

    def _start(self):
        log = self.log.open('a', encoding='utf-8')
        self.process = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                        text=True, encoding='utf-8', bufsize=1)
        self._expect('ready')

    def _expect(self, key):
        for line in self.process.stdout:
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if isinstance(reply, dict) and key in reply:
                return reply
        raise RuntimeError('Reader process stopped')

    def ensure(self):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()

    def run(self, task, source, output):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()
            self.process.stdin.write(json.dumps({'task': task, 'input': str(source), 'output': str(output)}) + '\n')
            self.process.stdin.flush()
            reply = self._expect('ok')
        if not reply['ok']:
            raise RuntimeError(reply.get('error', 'reader failed'))


class Processor:
    def __init__(self, store, reader, files, assistant=None):
        self.store, self.reader, self.files, self.assistant = store, reader, Path(files), assistant
        # Recognition first (priority 0); highlighting jobs (priority 1) only when no upload waits.
        self.queue = queue.PriorityQueue()
        self.sequence = 0
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        for row in self.store.pending():
            self.store.update_document(row['slug'], status='queued')
            self.submit(row['slug'])
        threading.Thread(target=self.reader.ensure, daemon=True).start()
        self.thread.start()

    def folder(self, slug):
        return self.files / slug

    def _put(self, priority, task, slug, payload=None):
        self.sequence += 1
        self.queue.put((priority, self.sequence, task, slug, payload))

    def submit(self, slug):
        self._put(0, 'ocr', slug)

    def position(self, slug):
        items = sorted(i for i in list(self.queue.queue) if i[2] == 'ocr')
        slugs = [i[3] for i in items]
        return slugs.index(slug) + 1 if slug in slugs else 0

    def _loop(self):
        while True:
            _, _, task, slug, payload = self.queue.get()
            if task == 'regions':
                self._regions(slug, *payload)
                continue
            try:
                self._process(slug)
            except Exception as error:  # recorded on the document, queue continues
                self.store.update_document(slug, status='failed', error=type(error).__name__ + ': ' + str(error)[:300])

    def _process(self, slug):
        doc = self.store.document(slug)
        if doc is None:
            return
        folder = self.folder(slug)
        source = next(folder.glob('input.*'))
        self.store.update_document(slug, status='running')
        started = time.perf_counter()
        self._preview(source, folder)
        output = folder / 'native-result.json'
        for stale in (output, output.with_suffix('.headfeatures.npz')):
            stale.unlink(missing_ok=True)
        self.reader.run('ocr', source, output)
        row = json.loads(output.read_text(encoding='utf-8'))['rows'][0]
        analysis = analyze(row, doc['requested_type'])
        (folder / 'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False), encoding='utf-8')
        found, total = counts(analysis)
        self.store.update_document(slug, status='done', document_type=analysis['document_type'], found=found, total=total,
                                   valid=int(analysis['validation']['status'] == 'document_ok'),
                                   seconds=round(time.perf_counter() - started, 1), error=None)
        (folder / 'regions.json').write_text(json.dumps({'status': 'pending', 'regions': []}), encoding='utf-8')
        self._put(1, 'regions', slug, (source, folder, analysis))

    def _preview(self, source, folder):
        from scripts.unified.model import read_document
        image = read_document(source)
        image.thumbnail((1700, 2200))
        image.save(folder / 'preview.png')

    def _regions(self, slug, source, folder, analysis):
        """Background highlighting: same-model Spotting lines for text fields."""
        from scripts.unified.field_regions import field_regions
        try:
            self.reader.run('spotting', source, folder / 'spotting.json')
            spotting = json.loads((folder / 'spotting.json').read_text(encoding='utf-8'))
            regions = field_regions(spotting['raw'], analysis['fields'], analysis['audit'])
            marks_file = folder / 'native-result.json'
            row = json.loads(marks_file.read_text(encoding='utf-8'))['rows'][0]
            for key, box in (analysis.get('mark_boxes') or {}).items():
                if key in analysis['fields'] and analysis['fields'][key] is True and box:
                    regions.append({'field': key, 'page': 0, 'bbox': box, 'source': 'same_model_patch_head'})
            (folder / 'regions.json').write_text(json.dumps({'status': 'done', 'regions': regions}, ensure_ascii=False),
                                                 encoding='utf-8')
        except Exception as error:
            (folder / 'regions.json').write_text(json.dumps({'status': 'failed', 'error': str(error)[:200], 'regions': []}),
                                                 encoding='utf-8')
        finally:
            if self.assistant is not None and self.queue.empty():
                threading.Thread(target=self.assistant.warm, daemon=True).start()

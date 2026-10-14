"""Isolated loopback UI for experimental native single-backbone CPU inference."""
import argparse
import hashlib
import json
import subprocess
import sys
import threading
import uuid
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HTML = '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Новая единая модель — локальная проверка</title>
<style>body{font:17px system-ui;max-width:1000px;margin:36px auto;padding:0 24px;color:#182536;background:#f7f9fc}section{background:white;padding:24px;border-radius:12px;margin:20px 0}button{padding:12px 20px;background:#185cbe;color:white;border:0;border-radius:6px}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd}small{color:#536375}#status{margin:16px 0}</style>
<h1>Новая единая модель</h1><p>PaddleOCR-VL-1.6 · FP32 · 1MP · headv3 · CPU, 6 потоков</p>
<section><p>Экспериментальная версия: один общий visual encoder для OCR и графического readout. Новый language-adapter ещё обучается отдельно и здесь пока не подключён. Production не используется.</p>
<p>Загрузите PNG/JPEG или одностраничный PDF, до20МиБ. Многостраничные PDF пока не поддерживаются. Чтение на CPU может занять несколько минут.</p>
<form id="form"><input required type="file" name="document" accept=".png,.jpg,.jpeg,.pdf"><button id="button">Прочитать новой моделью</button></form><div id="status" role="status"></div></section>
<section id="result" hidden><h2>Извлечённые поля</h2><div id="fields"></div><h2>Графический readout</h2><pre id="marks"></pre><small>Это экспериментальные значения, не вероятности и не проверка подлинности. Геометрия полей не квалифицирована.</small><h2>Буквальный OCR</h2><pre id="ocr"></pre><details><summary>Полный JSON результата</summary><pre id="json"></pre></details></section>
<script>const form=document.getElementById('form'), status=document.getElementById('status'), button=document.getElementById('button');
form.onsubmit=async e=>{e.preventDefault();button.disabled=true;status.textContent='Модель читает документ на CPU…';document.getElementById('result').hidden=true;
try{const response=await fetch('/analyze',{method:'POST',body:new FormData(form)}),data=await response.json();if(!response.ok)throw Error(data.error);
const row=data.rows[0];document.getElementById('ocr').textContent=row.raw_ocr;document.getElementById('marks').textContent=JSON.stringify(row.graphic_prediction,null,2);document.getElementById('json').textContent=JSON.stringify(data,null,2);
const fields=document.getElementById('fields');fields.replaceChildren();const values=row.binding.fields;if(!row.binding.document_type){fields.textContent='Тип документа не распознан. Буквальный OCR показан ниже.';}else{const table=document.createElement('table');for(const [key,value] of Object.entries(row.result?.fields||values)){const tr=document.createElement('tr');for(const text of [key, typeof value==='object'?JSON.stringify(value):String(value??'не найдено')]){const td=document.createElement('td');td.textContent=text;tr.append(td);}table.append(tr);}fields.append(table);}document.getElementById('result').hidden=false;status.textContent=`Готово. Один visual pass; чтение ${row.seconds.toFixed(1)}с.`;
}catch(err){status.textContent='Ошибка: '+err.message;}finally{button.disabled=false;}};</script></html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--head', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8502)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError('Local nonprivileged port required')
    args.work.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, content_type='application/json; charset=utf-8'):
            content = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path == '/':
                self.reply(200, HTML.encode('utf-8'), 'text/html; charset=utf-8')
            elif self.path == '/health':
                self.reply(200, {'service': 'isolated-native-cpu', 'busy': lock.locked(), 'adapter': None})
            else:
                self.reply(404, {'error': 'Страница не найдена'})

        def do_POST(self):
            if self.path != '/analyze':
                return self.reply(404, {'error': 'Путь не найден'})
            # Loopback-only and same-origin form; do not accept cross-origin uploads.
            if self.headers.get('Origin') not in {None, f'http://127.0.0.1:{args.port}', f'http://localhost:{args.port}'}:
                return self.reply(403, {'error': 'Разрешён только локальный интерфейс'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.reply(400, {'error': 'Некорректный размер'})
            if not 0 < size <= 20 * 1024 * 1024:
                return self.reply(413, {'error': 'Размер документа должен быть до20МиБ'})
            if not lock.acquire(blocking=False):
                return self.reply(409, {'error': 'Модель уже читает документ. Дождитесь завершения.'})
            try:
                raw = self.rfile.read(size)
                content_type = self.headers.get('Content-Type', '')
                message = BytesParser(policy=default).parsebytes(('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + raw)
                parts = [part for part in message.iter_parts() if part.get_param('name', header='content-disposition') == 'document']
                if len(parts) != 1:
                    raise ValueError('Выберите один документ')
                suffix = Path(parts[0].get_filename() or '').suffix.lower()
                if suffix not in {'.png', '.jpg', '.jpeg', '.pdf'}:
                    raise ValueError('Поддерживаются PNG, JPEG и одностраничный PDF')
                folder = args.work / uuid.uuid4().hex
                folder.mkdir()
                source = folder / ('input' + suffix)
                source.write_bytes(parts[0].get_payload(decode=True))
                output = folder / 'result.json'
                command = [sys.executable, '-m', 'scripts.unified.run_graphic_strict', '--base', str(args.base),
                           '--head', str(args.head), '--inputs', str(source), '--output', str(output),
                           '--precision', 'fp32', '--device', 'cpu', '--threads', '6']
                with (folder / 'inference.log').open('w', encoding='utf-8') as log:
                    completed = subprocess.run(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
                if completed.returncode:
                    raise ValueError('Чтение не завершено. Проверьте формат/число страниц; диагностический лог сохранён локально.')
                result = json.loads(output.read_text(encoding='utf-8'))
                if not result['complete'] or len(result['rows']) != 1:
                    raise ValueError('Неполный результат')
                result['local_upload_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
                self.reply(200, result)
            except (ValueError, OSError) as error:
                self.reply(400, {'error': str(error)})
            finally:
                lock.release()

        def log_message(self, format, *values):
            # Do not print names, OCR values or file paths into the server log.
            print(format % values, flush=True)

    print(f'Isolated native CPU page http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()

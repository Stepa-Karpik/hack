"""GPU agent: runs on the computer with the GPU and serves the public server.

Connects outbound to wss://<server>/agent/ws (no open ports needed here), then
executes recognition (same native_worker reader as the local app: GPU per page,
weights in RAM) and chat (local Ollama) jobs sent by the server.

Run:  python -m scripts.app.agent --server wss://dekanat.karpovprod.ru/agent/ws --token-file <file>
"""
import argparse
import asyncio
import base64
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from websockets.asyncio.client import connect

from scripts.app.processing import Reader
from scripts.assistant import core
from scripts.unified.contract import CONFIG


def gpu_name():
    try:
        return subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True,
                              timeout=10).stdout.strip().splitlines()[0]
    except Exception:
        return None


class Agent:
    def __init__(self, args):
        self.args = args
        self.work = Path(args.work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.reader = Reader(args.base, args.head, args.adapter, self.work, gpu=not args.cpu, ollama=core.OLLAMA,
                             mark_head=args.mark_head)
        self.assistant = core.Assistant(CONFIG, model=args.assistant_model)

    def info(self):
        return {'host': platform.node(), 'gpu': None if self.args.cpu else gpu_name(),
                'assistant': self.assistant.available(), 'model': self.args.assistant_model}

    # ---------------------------------------------------------------- jobs (worker threads)
    def read(self, task, data):
        folder = Path(tempfile.mkdtemp(prefix='job-', dir=self.work))
        try:
            suffix = Path(data['filename']).suffix.lower() or '.png'
            source = folder / ('input' + suffix)
            source.write_bytes(base64.b64decode(data['file']))
            output = folder / 'result.json'
            self.reader.run(task, source, output)
            return {'output': output.read_text(encoding='utf-8')}
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def chat(self, data, send_chunk):
        last = [0.0]

        def on_chunk(text):
            now = time.monotonic()
            if now - last[0] >= 0.08:
                last[0] = now
                send_chunk(text)
        content, stats = core.ollama_chat(data['model'], data['messages'], schema=data.get('schema'),
                                          options=data.get('options'), stream_callback=on_chunk if data.get('stream') else None)
        return {'content': content, 'stats': stats}

    # ---------------------------------------------------------------- link
    async def handle(self, ws, message):
        job, task, data = message['id'], message['task'], message.get('data') or {}
        loop = asyncio.get_running_loop()

        def send_chunk(text):
            asyncio.run_coroutine_threadsafe(ws.send(json.dumps({'type': 'chunk', 'id': job, 'data': text}, ensure_ascii=False)), loop)
        started = time.perf_counter()
        try:
            if task in ('ocr', 'spotting'):
                result = await asyncio.to_thread(self.read, task, data)
            elif task == 'chat':
                result = await asyncio.to_thread(self.chat, data, send_chunk)
            elif task == 'warm':
                await asyncio.to_thread(self.assistant.warm)
                result = {'ok': True}
            else:
                raise ValueError('unknown task ' + task)
            reply = {'type': 'result', 'id': job, 'data': result}
        except core.AssistantUnavailable as error:
            reply = {'type': 'error', 'id': job, 'error': 'assistant unavailable: ' + str(error)[:200]}
        except Exception as error:
            reply = {'type': 'error', 'id': job, 'error': type(error).__name__ + ': ' + str(error)[:300]}
        print(f'{time.strftime("%H:%M:%S")} {task} {reply["type"]} {time.perf_counter() - started:.1f}s', flush=True)
        await ws.send(json.dumps(reply, ensure_ascii=False))

    async def run(self):
        token = Path(self.args.token_file).read_text(encoding='utf-8').strip() if self.args.token_file else os.environ['DEKANAT_AGENT_TOKEN']
        await asyncio.to_thread(self.reader.ensure)  # load the model before taking jobs
        delay = 2
        while True:
            try:
                async with connect(self.args.server, additional_headers={'Authorization': 'Bearer ' + token},
                                   max_size=64 * 1024 * 1024, ping_interval=20, ping_timeout=60, open_timeout=20) as ws:
                    await ws.send(json.dumps({'type': 'hello', 'info': await asyncio.to_thread(self.info)}))
                    print(f'{time.strftime("%H:%M:%S")} connected to {self.args.server}', flush=True)
                    delay = 2
                    tasks = set()
                    async for raw in ws:
                        message = json.loads(raw)
                        if message.get('type') == 'task':
                            t = asyncio.create_task(self.handle(ws, message))
                            tasks.add(t)
                            t.add_done_callback(tasks.discard)
            except Exception as error:
                print(f'{time.strftime("%H:%M:%S")} link down ({type(error).__name__}: {str(error)[:120]}); retry in {delay}s',
                      flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--server', default='wss://dekanat.karpovprod.ru/agent/ws')
    p.add_argument('--token-file', help='File with the shared agent token (or env DEKANAT_AGENT_TOKEN)')
    p.add_argument('--base', default='work/paddle-vl-base-v1')
    p.add_argument('--head', default='models/unified-experimental-graphic-head-fp32-v3')
    p.add_argument('--adapter', default='models/unified-experimental-natural-v5')
    p.add_argument('--mark-head', default='models/unified-experimental-mark-patches-v1')
    p.add_argument('--assistant-model', default='qwen3.5:4b')
    p.add_argument('--work', default='work/agent-v1')
    p.add_argument('--cpu', action='store_true')
    asyncio.run(Agent(p.parse_args()).run())


if __name__ == '__main__':
    main()

"""Server side of the GPU agent link.

The GPU computer (owner's PC) runs `scripts.app.agent`, which connects *outbound* to
`/agent/ws` over (secure) WebSocket and authenticates with a shared token. The
server sends recognition and chat jobs to it; when no agent is connected,
recognition falls back to the server CPU and chat to the rules engine.
"""
import asyncio
import base64
import hmac
import itertools
import json
import threading
import time
from pathlib import Path

from starlette.websockets import WebSocket, WebSocketDisconnect


class AgentOffline(RuntimeError):
    pass


class Broker:
    def __init__(self, token):
        self.token = token
        self.loop = None
        self.socket = None
        self.info = {}
        self.pending = {}
        self.ids = itertools.count(1)
        self.connected_at = None
        self.started_at = time.time()
        self.disconnected_at = None

    def connected(self):
        return self.socket is not None

    def status(self):
        return {'connected': self.connected(), 'since': self.connected_at, **{k: self.info.get(k) for k in ('gpu', 'assistant', 'host')}}

    async def endpoint(self, ws: WebSocket):
        supplied = ws.headers.get('authorization', '')[7:] if ws.headers.get('authorization', '').lower().startswith('bearer ') else ''
        if not self.token or not hmac.compare_digest(supplied, self.token):
            await ws.close(code=4401)
            return
        await ws.accept()
        if self.socket is not None:  # newest agent wins
            try:
                await self.socket.close(code=4000)
            except Exception:
                pass
        self.loop = asyncio.get_running_loop()
        self.socket, self.connected_at, self.info = ws, time.time(), {}
        try:
            while True:
                message = json.loads(await ws.receive_text())
                kind = message.get('type')
                if kind == 'hello':
                    self.info = message.get('info') or {}
                    continue
                if kind == 'ping':
                    await ws.send_text(json.dumps({'type': 'pong'}))
                    continue
                entry = self.pending.get(message.get('id'))
                if entry is None:
                    continue
                future, on_chunk = entry
                if kind == 'chunk' and on_chunk:
                    on_chunk(message.get('data'))
                elif kind == 'result' and not future.done():
                    future.set_result(message.get('data'))
                elif kind == 'error' and not future.done():
                    future.set_exception(RuntimeError(message.get('error', 'agent error')))
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            if self.socket is ws:
                self.socket, self.disconnected_at = None, time.time()
                for future, _ in list(self.pending.values()):
                    if not future.done():
                        future.set_exception(AgentOffline('agent disconnected'))

    async def _call(self, task, payload, on_chunk):
        if self.socket is None:
            raise AgentOffline('no agent')
        job = next(self.ids)
        future = asyncio.get_running_loop().create_future()
        self.pending[job] = (future, on_chunk)
        try:
            await self.socket.send_text(json.dumps({'type': 'task', 'id': job, 'task': task, 'data': payload}, ensure_ascii=False))
            return await future
        finally:
            self.pending.pop(job, None)

    def call(self, task, payload, timeout=180, on_chunk=None):
        """Blocking call from worker threads."""
        if self.socket is None or self.loop is None:
            raise AgentOffline('no agent')
        return asyncio.run_coroutine_threadsafe(self._call(task, payload, on_chunk), self.loop).result(timeout)


class RemoteReader:
    """Processor reader: GPU agent when connected, otherwise the local (server CPU) reader."""

    def __init__(self, broker, fallback_factory):
        self.broker = broker
        self.fallback_factory = fallback_factory
        self.fallback = None
        self.lock = threading.Lock()
        self.last_device = None

    # after a server restart or a dropped link the agent usually comes back within seconds: waiting for it is
    # faster than reading on the server CPU (~14 s per page)
    RECONNECT_WINDOW = 60
    RECONNECT_WAIT = 20

    def ensure(self):
        """Load the server-CPU fallback in the background, so an offline agent never costs a cold start."""
        try:
            self._fallback().ensure()
        except Exception:
            pass

    def _fallback(self):
        with self.lock:
            if self.fallback is None:
                self.fallback = self.fallback_factory()
        return self.fallback

    def _wait_for_agent(self):
        recent = max(self.broker.started_at, self.broker.disconnected_at or 0)
        deadline = time.time() + self.RECONNECT_WAIT
        while not self.broker.connected() and time.time() - recent < self.RECONNECT_WINDOW and time.time() < deadline:
            time.sleep(0.5)
        return self.broker.connected()


    def run(self, task, source, output, **extra):
        if self.broker.connected() or self._wait_for_agent():
            try:
                data = self.broker.call(task, {'filename': Path(source).name, **extra,
                                               'file': base64.b64encode(Path(source).read_bytes()).decode()}, timeout=240)
                Path(output).write_text(data['output'], encoding='utf-8')
                if data.get('preview'):
                    Path(output).with_name('preview.png').write_bytes(base64.b64decode(data['preview']))
                self.last_device = 'agent'
                return
            except Exception:
                if self.broker.connected():
                    raise
        if task == 'spotting':
            # Field highlighting is a nicety; without the GPU it would cost minutes of server CPU per
            # document. Signature/seal boxes still come from the recognition pass.
            Path(output).write_text(json.dumps({'raw': '', 'skipped': 'gpu agent offline'}), encoding='utf-8')
            return
        self._fallback().run(task, source, output, **extra)
        self.last_device = 'server-cpu'


def remote_chat_backend(broker):
    """Same signature as scripts.assistant.core.ollama_chat, executed by the agent's local Ollama."""
    from scripts.assistant.core import AssistantUnavailable

    def chat(model, messages, *, schema=None, options=None, timeout=180, stream_callback=None):
        if not broker.connected():
            raise AssistantUnavailable('GPU agent offline')
        state = {'text': ''}

        def on_chunk(text):
            state['text'] = text
            if stream_callback:
                stream_callback(text)
        try:
            data = broker.call('chat', {'model': model, 'messages': messages, 'schema': schema, 'options': options or {},
                                        'stream': bool(stream_callback)}, timeout=timeout, on_chunk=on_chunk)
        except (AgentOffline, TimeoutError) as error:
            raise AssistantUnavailable(str(error)) from None
        return data['content'], data['stats']
    return chat


def remote_assistant(broker, config, model):
    """Assistant whose language model runs on the agent; offline agent -> rules engine answers."""
    from scripts.assistant.core import Assistant

    class RemoteAssistant(Assistant):
        @property
        def compact(self):  # the agent's PC decides: a CPU-only model gets the short context
            return bool(broker.info.get('compact'))

        @compact.setter
        def compact(self, value):
            pass

        def available(self):
            return broker.connected() and bool(broker.info.get('assistant'))

        def warm(self):
            if broker.connected():
                try:
                    broker.call('warm', {'model': self.model}, timeout=150)
                except Exception:
                    pass
    return RemoteAssistant(config, model=model, backend=remote_chat_backend(broker))

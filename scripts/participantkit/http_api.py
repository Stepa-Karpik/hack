"""Loopback-only JSON prototype, one inference worker, bounded in-memory jobs."""
import base64
import copy
import json
import queue
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from pathlib import Path
from .service import analyze_document,check_request,load_config
from .format_v1 import answer
from .upload_limits import inspect_upload
from .document_view import analyze_web_document

MAX_UPLOAD=10*1024*1024
MAX_BODY=14*1024*1024


class StoreClosed(RuntimeError):
    pass


class JobStore:
    def __init__(self,infer=analyze_web_document,*,pending=4,capacity=16,ttl=1800,inspector=inspect_upload):
        if not isinstance(pending,int) or pending<1 or not isinstance(capacity,int) or capacity<1 or ttl<=0:
            raise ValueError('Positive queue, capacity and TTL required')
        self.infer=infer;self.capacity=capacity;self.ttl=ttl
        self.inspector=inspector
        self.jobs={};self.lock=threading.Lock();self.ready=threading.Condition(self.lock)
        self.queue=deque();self.pending=pending;self.closed=False
        self.worker=threading.Thread(target=self._work,daemon=True)
        self.worker.start()

    def _cleanup(self):
        now=time.monotonic()
        for key,job in list(self.jobs.items()):
            if job['status'] in {'done','failed'} and now-job['updated']>self.ttl:
                del self.jobs[key]

    def submit(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'filename','document_type','questions','data_base64'}:
            raise ValueError('Expected filename, document_type, questions, data_base64')
        check_request(payload['document_type'],payload['questions'])
        filename=payload['filename']
        if not isinstance(filename,str) or not filename.lower().endswith(('.png','.jpg','.jpeg','.pdf')):
            raise ValueError('Supported uploads: PNG/JPG/PDF')
        if not isinstance(payload['data_base64'],str):raise ValueError('data_base64 must be a string')
        try:data=base64.b64decode(payload['data_base64'],validate=True)
        except (ValueError,TypeError):raise ValueError('Invalid base64') from None
        if not data or len(data)>MAX_UPLOAD:raise ValueError('Upload must be between 1 byte and 10 MiB')
        with self.lock:
            if self.closed:raise StoreClosed('Store closed')
            self._cleanup()
            if len(self.jobs)>=self.capacity or len(self.queue)>=self.pending:raise queue.Full
            key=uuid.uuid4().hex;now=time.monotonic()
            self.jobs[key]={'status':'queued','updated':now,'input':(data,filename,payload['document_type'],copy.deepcopy(payload['questions']))}
            self.queue.append(key);self.ready.notify()
        return key

    def _work(self):
        while True:
            with self.ready:
                self.ready.wait_for(lambda:self.queue or self.closed)
                if not self.queue:return
                key=self.queue.popleft();job=self.jobs[key]
                data,filename,kind,questions=job.pop('input')
                job.update(status='running',updated=time.monotonic())
                del job
            try:
                self.inspector(data,filename)
                response=self.infer(data,filename,kind,questions,document_id=key)
                update={'status':'done','response':response}
                del response
            except Exception:
                update={'status':'failed','error':'analysis_failed'}
            with self.lock:
                if key in self.jobs:self.jobs[key].update(**update,updated=time.monotonic())
            del data,filename,kind,questions,update

    def get(self,key):
        with self.lock:
            self._cleanup();job=self.jobs.get(key)
            if job is None:raise KeyError(key)
            return copy.deepcopy({k:v for k,v in job.items() if k not in {'input','updated'}})

    def remove(self,key):
        with self.lock:
            if key not in self.jobs:raise KeyError(key)
            if self.jobs[key]['status']=='queued':self.queue.remove(key)
            del self.jobs[key]

    def ask(self,key,question):
        job=self.get(key)
        if job['status']!='done':raise RuntimeError('Document not ready')
        result=job['response']['result']
        check_request(result['document_type'],[question])
        return {'question_id':question['question_id'],**answer(question['question'],result['fields'],result['validation'],load_config())}

    def close(self):
        with self.ready:
            self.closed=True;self.ready.notify_all()
        self.worker.join()


def make_server(port=0,store=None):
    store=JobStore() if store is None else store
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_json(self,status,value):
            data=json.dumps(value,ensure_ascii=False,default=lambda v:v.tolist()).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(data)
        def route(self):
            return urlsplit(self.path).path.rstrip('/').split('/')[1:]
        def body(self):
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':raise ValueError('application/json required')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=MAX_BODY:raise ValueError('Request body limit: 14 MiB')
            self.connection.settimeout(15)
            return json.loads(self.rfile.read(size))
        def do_GET(self):
            route=self.route()
            static={'':['index.html','text/html; charset=utf-8'],'docs':['docs.html','text/html; charset=utf-8'],
                'assets/style.css':['style.css','text/css; charset=utf-8'],'assets/app.js':['app.js','text/javascript; charset=utf-8'],
                'assets/docs.js':['docs.js','text/javascript; charset=utf-8'],'assets/docs.json':['docs.json','application/json; charset=utf-8'],
                'assets/campus-background.gif':['assets/campus-background.gif','image/gif'],
                'assets/campus-background.jpg':['assets/campus-background.jpg','image/jpeg'],
                'source.zip':['source.zip','application/zip']}
            key='/'.join(route)
            if key in static:
                name,mime=static[key];path=Path(__file__).resolve().parents[2]/'web'/name
                if not path.is_file():return self.send_json(404,{'error':'not_found'})
                data=path.read_bytes();self.send_response(200);self.send_header('Content-Type',mime)
                self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
            if route==['health']:return self.send_json(200,{'status':'ok','version':'local-http-v10','inference_workers':1})
            if len(route)==3 and route[:2]==['v1','jobs']:
                try:return self.send_json(200,{'job_id':route[2],**store.get(route[2])})
                except KeyError:return self.send_json(404,{'error':'job_not_found'})
            self.send_json(404,{'error':'not_found'})
        def do_POST(self):
            try:
                payload=self.body();route=self.route()
                if route==['v1','jobs']:
                    key=store.submit(payload);return self.send_json(202,{'job_id':key,'status':'queued'})
                if len(route)==4 and route[:2]==['v1','jobs'] and route[3]=='questions':
                    return self.send_json(200,store.ask(route[2],payload))
                self.send_json(404,{'error':'not_found'})
            except queue.Full:self.send_json(429,{'error':'queue_full'})
            except StoreClosed:self.send_json(503,{'error':'service_unavailable'})
            except KeyError:self.send_json(404,{'error':'job_not_found'})
            except RuntimeError:self.send_json(409,{'error':'document_not_ready'})
            except (ValueError,TypeError,UnicodeError):self.send_json(400,{'error':'invalid_request'})
        def do_DELETE(self):
            route=self.route()
            if len(route)==3 and route[:2]==['v1','jobs']:
                try:store.remove(route[2]);return self.send_json(200,{'deleted':True})
                except KeyError:return self.send_json(404,{'error':'job_not_found'})
            self.send_json(404,{'error':'not_found'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.job_store=store
    return server

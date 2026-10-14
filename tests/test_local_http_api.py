import base64
import json
import queue
import threading
import time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from scripts.participantkit.http_api import JobStore,make_server


def payload():return {'filename':'a.png','document_type':'study_certificate','questions':[],'data_base64':base64.b64encode(b'fake').decode()}


def response(*args,**kwargs):return {'result':{'document_type':'study_certificate','fields':{'issue_date':'2027-05-03'},'validation':{'status':'document_ok','missing_fields':[],'sources':['rule:3.1']}},'audit':{'bindings':{'issue_date':{'status':'uncertain','semantic_confidence':None,'source_confidence':0.8,'evidence':{'text':'3 мая 2027','bbox':[10,20,140,40]}}}}}


def wait_done(store,key):
    until=time.monotonic()+3
    while time.monotonic()<until:
        r=store.get(key)
        if r['status'] in {'done','failed'}:return r
        time.sleep(.005)
    raise AssertionError('worker stalled')


def test_single_worker_queue_limit_followup_and_delete():
    entered=threading.Event();release=threading.Event();calls=[]
    def infer(*args,**kwargs):
        calls.append(args);entered.set();assert release.wait(2);return response()
    store=JobStore(infer,pending=1,inspector=lambda *args: None)
    try:
        a=store.submit(payload());assert entered.wait(2)
        b=store.submit(payload())
        with pytest.raises(queue.Full):store.submit(payload())
        assert len(calls)==1
        release.set();assert wait_done(store,a)['status']=='done';wait_done(store,b)
        before=len(calls)
        assert store.ask(a,{'question_id':'q','question':'Какова дата выдачи?'})['value']=='2027-05-03'
        assert len(calls)==before
        store.remove(a)
        with pytest.raises(KeyError):store.get(a)
    finally:release.set();store.close()


def test_failed_inference_does_not_stop_next_job():
    calls=[]
    def infer(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise RuntimeError('private failure')
        return response()
    store=JobStore(infer,inspector=lambda *args: None)
    try:
        assert wait_done(store,store.submit(payload()))=={'status':'failed','error':'analysis_failed'}
        assert wait_done(store,store.submit(payload()))['status']=='done'
    finally:store.close()


@pytest.mark.parametrize('change',[{'data_base64':'!bad'},{'filename':'a.docx'},{'data_base64':''},{'document_type':'other'}])
def test_invalid_upload_rejected(change):
    store=JobStore(response,inspector=lambda *args: None)
    try:
        with pytest.raises(ValueError):store.submit({**payload(),**change})
    finally:store.close()


def test_http_routes_and_uncertainty_survive_roundtrip():
    store=JobStore(response,inspector=lambda *args: None);server=make_server(0,store)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def req(path,body=None,method=None):
        data=None if body is None else json.dumps(body).encode()
        request=Request(base+path,data=data,method=method,headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=3) as r:return r.status,json.load(r)
    try:
        assert server.server_address[0]=='127.0.0.1'
        assert req('/health')[1]['inference_workers']==1
        status,job=req('/v1/jobs',payload());assert status==202
        key=job['job_id'];wait_done(store,key)
        assert req('/v1/jobs/'+key)[1]['response']==response()
        assert req('/v1/jobs/'+key+'/questions',{'question_id':'q','question':'Какова дата выдачи?'})[1]['sources']==['field:issue_date']
        assert not req('/v1/jobs/'+key+'/questions',{'question_id':'unknown','question':'Какова стоимость обучения?'})[1]['answerable']
        assert req('/v1/jobs/'+key)[1]['response']==response()
        assert req('/v1/jobs/'+key,method='DELETE')[1]['deleted']
        with pytest.raises(HTTPError) as e:req('/v1/jobs/'+key)
        assert e.value.code==404
    finally:server.shutdown();server.server_close();thread.join();store.close()


def test_web_assets_allowlist_does_not_expose_runtime_or_traversal():
    store = JobStore(response, inspector=lambda *args: None)
    server = make_server(0, store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        for path, media in [('/', 'text/html'), ('/assets/style.css', 'text/css'),
                            ('/assets/app.js', 'text/javascript')]:
            with urlopen(base + path, timeout=3) as result:
                assert result.status == 200
                assert media in result.headers['Content-Type']
                assert result.headers['X-Content-Type-Options'] == 'nosniff'
                assert result.read()
        for path in ['/dekanat/ocr.py', '/assets/../../dekanat/ocr.py',
                     '/assets/%2e%2e/dekanat/ocr.py', '/assets/unknown.js']:
            with pytest.raises(HTTPError) as error:
                urlopen(base + path, timeout=3)
            assert error.value.code == 404
    finally:
        server.shutdown(); server.server_close(); thread.join(); store.close()


def test_deleted_last_result_is_released_while_worker_waits():
    import gc
    import weakref

    class TrackedResult(dict):
        pass

    references = []

    def infer(*args, **kwargs):
        result = TrackedResult(response())
        references.append(weakref.ref(result))
        return result

    store = JobStore(infer, inspector=lambda *args: None)
    try:
        key = store.submit(payload())
        assert wait_done(store, key)['status'] == 'done'
        store.remove(key)
        gc.collect()
        assert references[0]() is None
    finally:
        store.close()


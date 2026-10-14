import threading
import queue
import pytest
from scripts.participantkit.http_api import JobStore,StoreClosed
from test_local_http_api import payload,response,wait_done


def test_deleted_queued_job_releases_waiting_slot_immediately():
    entered=threading.Event();release=threading.Event();calls=[]
    def infer(*args,**kwargs):
        calls.append(kwargs['document_id']);entered.set();assert release.wait(3);return response()
    store=JobStore(infer,pending=1,inspector=lambda *args:None)
    try:
        running=store.submit(payload());assert entered.wait(2)
        deleted=store.submit(payload());store.remove(deleted)
        replacement=store.submit(payload())
        release.set();wait_done(store,running);wait_done(store,replacement)
        assert calls==[running,replacement]
    finally:release.set();store.close()


def test_close_is_repeatable_and_rejects_new_work():
    store=JobStore(response,inspector=lambda *args:None)
    store.close();store.close()
    assert not store.worker.is_alive()
    with pytest.raises(StoreClosed):store.submit(payload())


def test_close_drains_work_and_running_delete_discards_response():
    entered=threading.Event();release=threading.Event();closed=threading.Event();calls=[]
    def infer(*args,**kwargs):
        calls.append(1);entered.set();assert release.wait(3);return response()
    store=JobStore(infer,inspector=lambda *args:None)
    def finish():store.close();closed.set()
    closer=threading.Thread(target=finish,daemon=True)
    try:
        running=store.submit(payload());assert entered.wait(2)
        waiting=store.submit(payload());store.remove(running)
        closer.start();assert not closed.wait(.05)
        release.set();assert closed.wait(2)
        assert store.get(waiting)['status']=='done' and len(calls)==2
        with pytest.raises(KeyError):store.get(running)
    finally:release.set();closer.join(timeout=3);store.close()


def test_retained_capacity_and_expiry_restore_admission():
    store=JobStore(response,capacity=1,inspector=lambda *args:None)
    try:
        key=store.submit(payload());wait_done(store,key)
        with pytest.raises(queue.Full):store.submit(payload())
        with store.lock:store.jobs[key]['updated']-=1801
        replacement=store.submit(payload());wait_done(store,replacement)
        with pytest.raises(KeyError):store.get(key)
    finally:store.close()


@pytest.mark.parametrize('options',[{'pending':0},{'capacity':0},{'ttl':0}])
def test_invalid_limits_rejected(options):
    with pytest.raises(ValueError):JobStore(**options)


def test_http_overload_cancel_invalid_question_and_shutdown():
    import json
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    from scripts.participantkit.http_api import make_server
    entered=threading.Event();release=threading.Event();calls=[]
    def infer(*args,**kwargs):calls.append(1);entered.set();assert release.wait(3);return response()
    store=JobStore(infer,pending=1,inspector=lambda *args:None);server=make_server(0,store)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    missing=object()
    def request(path,value=missing,method=None):
        req=Request(f'http://127.0.0.1:{server.server_port}'+path,data=None if value is missing else json.dumps(value).encode(),method=method,headers={'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=3) as r:return r.status,json.load(r)
        except HTTPError as error:return error.code,json.load(error)
    try:
        for kind in ['unknown',None,[]]:assert request('/v1/jobs',{**payload(),'document_type':kind})[0]==400
        assert calls==[]
        _,first=request('/v1/jobs',payload());assert entered.wait(2)
        path='/v1/jobs/'+first['job_id']
        assert request(path+'/questions',{'question_id':'q','question':'Какова дата выдачи?'})[0]==409
        _,second=request('/v1/jobs',payload())
        assert request('/v1/jobs',payload())==(429,{'error':'queue_full'})
        assert request('/v1/jobs/'+second['job_id'],method='DELETE')[0]==200
        status,third=request('/v1/jobs',payload());assert status==202
        release.set();wait_done(store,first['job_id']);wait_done(store,third['job_id'])
        for bad in [None,[],{}, {'question_id':'q','question':''}, {'question_id':2,'question':'text'}]:
            # None here must be JSON null, not an empty request.
            assert request(path+'/questions',bad)[0]==400
        assert request(path+'/questions',{'question_id':'q','question':'Где находится герб?'})[1]['answerable'] is False
        assert len(calls)==2
        store.close();assert request('/v1/jobs',payload())==(503,{'error':'service_unavailable'})
    finally:release.set();server.shutdown();server.server_close();thread.join();store.close()

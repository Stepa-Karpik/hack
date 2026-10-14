"""Fresh loopback HTTP/CPU qualification; private real output stays private.

Inputs are paths only. No target values or dataset manifest is read here.
"""
import argparse
import base64
import copy
import hashlib
import json
import threading
import time
import urllib.request
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--controls', type=Path, required=True)
    p.add_argument('--real-pdf', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh private report required')
    import torch
    torch.set_num_threads(4)
    from scripts.participantkit import service_prose as service
    from scripts.participantkit.http_api import JobStore, make_server
    old_prepare = service.legacy_prepare
    baseline = []
    def capture(*a, **kw):
        result, audit = old_prepare(*a, **kw)
        baseline.append(copy.deepcopy(result))
        return result, audit
    service.legacy_prepare = capture
    calls = []
    def infer(*a, **kw):
        calls.append(1)
        return service.analyze_web_document(*a, gpu=False, **kw)
    store = JobStore(infer=infer)
    server = make_server(0, store)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    origin = 'http://127.0.0.1:'+str(server.server_port)
    def request(route, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(origin+route, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read())
    questions = [{'question_id': 'date', 'question': 'Какова дата заявления?'},
                 {'question_id': 'complete', 'question': 'Содержит ли документ все обязательные сведения?'}]
    files = sorted(args.controls.glob('[0-9][0-9]-*.png'))+[args.real_pdf]
    rows = []
    try:
        if len(files) != 9:
            raise ValueError('Eight controls and one whole PDF required')
        for index, file in enumerate(files):
            data = file.read_bytes()
            job = request('/v1/jobs', {'filename': file.name, 'document_type': 'academic_leave_application',
                'questions': questions, 'data_base64': base64.b64encode(data).decode()})['job_id']
            deadline = time.monotonic()+600
            while True:
                result = request('/v1/jobs/'+job)
                if result['status'] in {'done', 'failed'}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('Qualification job timeout')
                time.sleep(.5)
            if result['status'] != 'done':
                raise ValueError('CPU API inference failed')
            fresh = result['response']
            unknown = request('/v1/jobs/'+job+'/questions', {'question_id': 'unknown', 'question': 'Какого цвета глаза студента?'})
            factual = request('/v1/jobs/'+job+'/questions', {'question_id': 'followup', 'question': 'Какова дата заявления?'})
            if unknown['answerable'] or factual['sources'] != fresh['result']['answers'][0]['sources']:
                raise ValueError('Followup semantics differ')
            rows.append({'id': file.stem if index < 8 else 'private-whole-pdf',
                'private': index == 8, 'input_sha256': hashlib.sha256(data).hexdigest(),
                'before': baseline[-1], 'response': fresh, 'followups': [unknown, factual]})
            args.output.write_text(json.dumps({'complete': len(rows) == 9, 'inference_calls': len(calls),
                'rows': rows}, ensure_ascii=False, indent=2, default=lambda v: v.tolist()), encoding='utf-8')
            print(index+1, 'of9', 'changes', len(fresh['audit']['prose_recovery']['changes']),
                  'pages', len(fresh['document_view']['pages']), flush=True)
        if len(calls) != 9:
            raise ValueError('Followup caused extra OCR')
    finally:
        server.shutdown(); server.server_close(); store.close(); worker.join()
        service.legacy_prepare = old_prepare


if __name__ == '__main__':
    main()

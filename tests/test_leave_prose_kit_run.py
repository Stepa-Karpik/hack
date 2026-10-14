import json
import sys
import numpy as np
from scripts.experiments import leave_prose_kit_run as runner
from scripts.participantkit.format_v1 import MISSING


def test_full_run_serializes_nested_numpy_audit_without_reference_access(tmp_path, monkeypatch):
    kit = tmp_path/'kit'; kit.mkdir()
    (kit/'one.png').write_bytes(b'pixels'); (kit/'one.pdf').write_bytes(b'pdf')
    (kit/'documents.json').write_text(json.dumps([{'document_id': 'doc', 'document_type': 'academic_leave_application',
                                                  'image': 'one.png', 'pdf': 'one.pdf'}]), encoding='utf-8')
    (kit/'questions.json').write_text('[]', encoding='utf-8')
    fields = {k: MISSING for k in ['student_name', 'group', 'course', 'leave_reason', 'leave_start', 'leave_end', 'application_date']}
    fields['signature_present'] = False
    calls = []
    def analyze(data, filename, kind, questions, **kwargs):
        calls.append((filename, kwargs['gpu']))
        return {'input_sha256': 'test', 'seconds': 1., 'result': {'fields': fields, 'document_type': kind,
            'document_id': 'doc', 'validation': runner.validate(fields, kind, runner.load_config()), 'answers': []},
            'audit': {'bindings': {}, 'analysis': {'type': 'leave', 'ocr': {'lines': []}, 'fields': {},
                    'debug': {'scalar': np.int32(17), 'coordinates': np.array([1, 2], dtype=np.int32)}}}}
    monkeypatch.setattr(runner, 'analyze_document', analyze)
    output = tmp_path/'report.json'
    monkeypatch.setattr(sys, 'argv', ['run', '--kit', str(kit), '--output', str(output)])
    runner.main()
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['complete'] and len(report['rows']) == 2
    assert calls == [('one.png', False), ('one.pdf', False)]
    assert report['rows'][0]['audit']['analysis']['debug'] == {'scalar': 17, 'coordinates': [1, 2]}
    assert report['changed_outputs'] == []

import json
import sys
import pytest

from scripts.experiments.leave_prose_camera_gate import main


@pytest.mark.parametrize('routing', ['unknown', None, 0])
def test_manual_routing_is_bounded(tmp_path, monkeypatch, routing):
    inputs = tmp_path/'inputs.json'
    inputs.write_text(json.dumps({'inputs': [{'id': 'case', 'input': 'case.png',
        'sha256': '0'*64, 'document_type': routing}]}))
    output = tmp_path/'output.json'
    monkeypatch.setattr(sys, 'argv', ['gate', '--inputs', str(inputs), '--output', str(output)])
    with pytest.raises(ValueError, match='bounded routing'):
        main()
    assert not output.exists()


def test_manual_routing_does_not_allow_answers(tmp_path, monkeypatch):
    inputs = tmp_path/'inputs.json'
    inputs.write_text(json.dumps({'inputs': [{'id': 'case', 'input': 'case.png',
        'sha256': '0'*64, 'document_type': 'leave', 'fields': {'group': 'unexpected'}}]}))
    output = tmp_path/'output.json'
    monkeypatch.setattr(sys, 'argv', ['gate', '--inputs', str(inputs), '--output', str(output)])
    with pytest.raises(ValueError, match='bounded routing'):
        main()
    assert not output.exists()

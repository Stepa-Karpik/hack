import json
import sys

import pytest

from scripts.experiments.leave_prose_fresh_gate import main


def test_input_manifest_may_not_contain_expected_answers(tmp_path, monkeypatch):
    inputs = tmp_path/'inputs.json'
    output = tmp_path/'output.json'
    inputs.write_text(json.dumps({'inputs': [{'id': 'a', 'input': 'a.pdf',
        'sha256': '0'*64, 'fields': {'student_name': 'must not be read'}}]}))
    monkeypatch.setattr(sys, 'argv', ['gate', '--inputs', str(inputs), '--output', str(output)])
    with pytest.raises(ValueError, match='Only input'):
        main()
    assert not output.exists()


def test_completed_or_partial_report_cannot_be_overwritten(tmp_path, monkeypatch):
    output = tmp_path/'output.json'
    original = '{"complete":false}'
    output.write_text(original)
    monkeypatch.setattr(sys, 'argv', ['gate', '--inputs', str(tmp_path/'missing.json'), '--output', str(output)])
    with pytest.raises(ValueError, match='Fresh'):
        main()
    assert output.read_text() == original

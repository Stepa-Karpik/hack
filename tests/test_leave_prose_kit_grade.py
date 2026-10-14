import json
import sys
import pytest
from scripts.experiments import leave_prose_kit_grade as grader


def test_partial_inference_is_rejected_before_reference_loading(tmp_path, monkeypatch):
    input_file = tmp_path/'partial.json'
    input_file.write_text(json.dumps({'complete': False, 'planned_count': 60, 'rows': []}), encoding='utf-8')
    output = tmp_path/'qualification.json'
    monkeypatch.setattr(sys, 'argv', ['grade', '--predictions', str(input_file),
        '--kit', str(tmp_path/'unavailable-reference'), '--output', str(output)])
    with pytest.raises(ValueError, match='Full inference required'):
        grader.main()
    assert not output.exists()

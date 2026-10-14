import json
import pytest
from scripts.check_regression import check


def test_gate_rejects_regression_and_incomparable_samples(tmp_path):
    (tmp_path/"before.json").write_text(json.dumps({"score":.9,"documents":10}))
    (tmp_path/"after.json").write_text(json.dumps({"score":.8,"documents":10}))
    plan={"checks":[{"id":"real_ocr","before":"before.json","after":"after.json","metric":"score"}]}
    assert not check(plan,tmp_path)["passed"]
    (tmp_path/"after.json").write_text(json.dumps({"score":1.,"documents":5}))
    with pytest.raises(ValueError,match="sizes differ"):check(plan,tmp_path)
    (tmp_path/"after.json").write_text(json.dumps({"score":1.,"documents":10}))
    assert check(plan,tmp_path)["passed"]


def test_gate_fails_when_required_report_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        check({"checks":[{"id":"real_ocr","before":"missing.json","after":"after.json","metric":"score"}]},tmp_path)
    with pytest.raises(ValueError,match="No checks"):check({"checks":[]},tmp_path)

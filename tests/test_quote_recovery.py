from copy import deepcopy
from PIL import Image

import dekanat.ocr as ocr
from dekanat.extraction import extract


def row(text, y=20):
    return {"text": text, "bbox": [10, y, 390, y+26], "page": 0, "confidence": .99}


def test_recovery_cannot_overwrite_previously_found_values(monkeypatch):
    lines = [row('Название вуза: Исходный университет'), row('Направление подготовки: Информатика', 60)]
    fields = extract(lines, "study")
    before = deepcopy(fields)
    monkeypatch.setattr(ocr, "get_reader", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no OCR needed")))
    result = ocr.recover_quote_fields([Image.new("RGB", (400, 400), "white")], lines, fields, "study", weights="unused.pt")
    assert result["attempts"] == 0
    assert fields == before


def test_unquoted_reread_is_not_accepted(monkeypatch, tmp_path):
    class FakeReader:
        def recognize(self, *a, **kw):
            return [(None, 'АНО ВО Учебный университет', .99)]
    weights = tmp_path/"weights.pt"
    weights.write_bytes(b"test")
    lines = [row('АНО ВO кУчебный университетх')]
    fields = extract(lines, "study")
    monkeypatch.setattr(ocr, "get_reader", lambda *a, **kw: FakeReader())
    result = ocr.recover_quote_fields([Image.new("RGB", (400, 400), "white")], lines, fields, "study", weights=weights)
    assert result["accepted"] == []
    assert fields["university"]["value"] is None


def test_recovery_records_baseline_text_and_does_not_mutate_lines(monkeypatch, tmp_path):
    class FakeReader:
        def recognize(self, *a, **kw):
            return [(None, 'АНО ВО «Учебный университет»', .99)]
    weights = tmp_path/"weights.pt"
    weights.write_bytes(b"test")
    lines = [row('АНО ВO кУчебный университетх')]
    before = deepcopy(lines)
    fields = extract(lines, "study")
    monkeypatch.setattr(ocr, "get_reader", lambda *a, **kw: FakeReader())
    result = ocr.recover_quote_fields([Image.new("RGB", (400, 400), "white")], lines, fields, "study", weights=weights)
    assert result["accepted"] == ["university"]
    assert fields["university"]["value"] == 'АНО ВО «Учебный университет»'
    assert result["lines"][0]["baseline_text"] == before[0]["text"]
    assert lines == before


def test_low_confidence_quote_is_not_promoted(monkeypatch, tmp_path):
    class FakeReader:
        def recognize(self, *a, **kw):
            return [(None, 'АНО ВО «Учебный университет»', .4)]
    weights = tmp_path/"weights.pt"
    weights.write_bytes(b"test")
    lines = [row('АНО ВO кУчебный университетх')]
    fields = extract(lines, "study")
    monkeypatch.setattr(ocr, "get_reader", lambda *a, **kw: FakeReader())
    result = ocr.recover_quote_fields([Image.new("RGB", (400, 400), "white")], lines, fields, "study", weights=weights)
    assert result["accepted"] == []
    assert fields["university"]["value"] is None

import hashlib
import json
import os

import pytest
from dekanat.ocr import quote_state


def setup_selection(tmp_path, monkeypatch):
    monkeypatch.setattr("dekanat.schema.ROOT", tmp_path)
    models = tmp_path/"models"
    models.mkdir()
    quote, parent = models/"ocr_quotes.pt", models/"ocr_cyrillic.pt"
    quote.write_bytes(b"quote-original")
    parent.write_bytes(b"parent-original")
    selection = models/"quote_selection.json"
    selection.write_text(json.dumps({"enabled": True, "sha256": hashlib.sha256(quote.read_bytes()).hexdigest(),
                                     "base_sha256": hashlib.sha256(parent.read_bytes()).hexdigest()}), encoding="utf-8")
    return quote, parent, selection


def test_matching_parent_and_quote_are_required(tmp_path, monkeypatch):
    quote, _, _ = setup_selection(tmp_path, monkeypatch)
    assert quote_state() == quote


@pytest.mark.parametrize("which", ["quote", "parent"])
def test_changed_model_disables_quote_fallback(tmp_path, monkeypatch, which):
    quote, parent, _ = setup_selection(tmp_path, monkeypatch)
    assert quote_state() == quote
    target = quote if which == "quote" else parent
    stamp = target.stat().st_mtime_ns
    target.write_bytes(b"different-model")
    os.utime(target, ns=(stamp+1_000_000_000, stamp+1_000_000_000))
    assert quote_state() is None

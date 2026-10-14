from types import SimpleNamespace

import pytest
import torch
from easyocr.utils import CTCLabelConverter

from dekanat.ocr import extend_alphabet


def reader():
    return SimpleNamespace(character="ab", converter=CTCLabelConverter("ab"),
                           recognizer=SimpleNamespace(Prediction=torch.nn.Linear(4, 3)))


def test_extension_preserves_existing_token_ids_and_logits():
    original = reader()
    x = torch.randn(2, 4)
    before = original.recognizer.Prediction(x).detach().clone()
    extend_alphabet(original, "ab«»")
    assert torch.equal(original.recognizer.Prediction(x)[:, :3], before)
    assert original.converter.dict["a"] == 1
    assert original.converter.dict["b"] == 2
    assert original.converter.dict["«"] == 3
    assert original.converter.dict["»"] == 4
    assert "«" in original.lang_char and "»" in original.lang_char


def test_reordered_or_arbitrary_checkpoint_alphabet_is_rejected():
    original = reader()
    before = original.recognizer.Prediction
    for incompatible in ["ba«»", "ab?", "ab«»x"]:
        with pytest.raises(RuntimeError, match="Алфавит"):
            extend_alphabet(original, incompatible)
        assert original.recognizer.Prediction is before


def test_cpu_reader_loads_dense_extended_checkpoint(monkeypatch, tmp_path):
    """CPU auto-quantization otherwise makes Prediction.weight a method."""
    import easyocr
    from dekanat.ocr import _get_reader

    model = torch.nn.Module()
    model.Prediction = torch.nn.Linear(4, 5)
    checkpoint = tmp_path / "extended.pt"
    torch.save({"character": "ab«»", "state_dict": model.state_dict()}, checkpoint)

    def factory(languages, **kwargs):
        result = reader()
        if kwargs.get("quantize", True):
            result.recognizer.Prediction = SimpleNamespace(weight=lambda: None)
        else:
            result.recognizer = torch.nn.Module()
            result.recognizer.Prediction = torch.nn.Linear(4, 3)
        return result

    monkeypatch.setattr(easyocr, "Reader", factory)
    monkeypatch.setenv("DEKANAT_CACHE", str(tmp_path))
    _get_reader.cache_clear()
    try:
        result = _get_reader(False, str(checkpoint), 0, False)
        assert result.character == "ab«»"
        assert torch.equal(result.recognizer.Prediction.weight, model.Prediction.weight)
        assert result.converter.dict["»"] == 4
    finally:
        _get_reader.cache_clear()

import pytest
from scripts.unified.native_precision_probe import validate


def test_bounded_precision_probe_rejects_unknown_and_unbounded_profiles():
    validate('cpu', 'fp32', 6, 1003520, 24)
    validate('cuda', 'bf16', 1, 1003520, 512)
    for args in [('cpu', 'fp16', 6, 1003520, 24), ('cpu', 'fp32', 64, 1003520, 24),
                 ('cpu', 'fp32', 6, 1003520, 0), ('cpu', 'fp32', 6, 4000000, 24)]:
        with pytest.raises(ValueError):
            validate(*args)

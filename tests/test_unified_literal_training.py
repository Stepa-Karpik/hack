import pytest
from scripts.unified.prepare_literal_training import printed_lines, validate_partitions
from scripts.unified.train_literal_ocr import language_module
from scripts.unified.grade_literal_training import paired


def test_literal_targets_are_printed_text_and_disjoint():
    names = []
    for seed in range(202631000, 202631120):
        lines, name = printed_lines(seed, True)
        assert lines[2] == 'ФИО студента: ' + name
        assert len(lines) == 8
        names.append(name)
    assert len(names) == len(set(names))


def test_split_guard_rejects_cross_partition_name():
    row = {'fictional_name': 'fictional', 'seed': 1, 'sha256': 'a'}
    validate_partitions({'train': [row]})
    with pytest.raises(ValueError):
        validate_partitions({'train': [row], 'val': [{**row, 'seed': 2, 'sha256': 'b'}]})


def test_lora_target_excludes_visual_and_other_language_weights():
    assert language_module('model.language_model.layers.12.self_attn.q_proj')
    assert language_module('model.language_model.layers.12.self_attn.v_proj')
    assert not language_module('model.visual.layers.12.self_attn.q_proj')
    assert not language_module('model.language_model.layers.12.self_attn.k_proj')
    assert not language_module('model.language_model.embed_tokens')


def test_paired_literal_gate_reports_losses_and_extra_text():
    target = [{'sha256': 'a', 'image': 'a.png', 'target_text': 'Линнёшев Мирон',
               'expected_lines': ['Линнёшев Мирон']}]
    before = {'complete': True, 'rows': [{'input_sha256': 'a', 'raw': 'Линнёшев Мирон', 'token_budget_reached': False}]}
    after = {'complete': True, 'rows': [{'input_sha256': 'a', 'raw': 'Линнёшевй Мирон', 'token_budget_reached': False}]}
    result = paired(target, before, after)
    assert result['counts']['lost_correct'] == 1
    assert result['counts']['after_edits'] == 1
    with pytest.raises(ValueError):
        paired(target, {**before, 'complete': False}, after)

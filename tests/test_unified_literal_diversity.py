from scripts.unified.prepare_literal_diversity import content, positions, render
from PIL import ImageFont
import pytest


def test_new_names_and_seed_partitions_do_not_collide():
    names = [content(start + i, False, i % 4)[1]
             for start, count in [(202651000, 64), (202652000, 16), (202653000, 16)]
             for i in range(count)]
    assert len(set(names)) == 96


def test_layouts_have_unambiguous_reading_order_and_empty_labels():
    lines, _ = content(202651000, True, 0)
    assert lines[2] == 'ФИО заявителя: '
    assert lines[3] == 'Группа: '
    assert lines[9] == 'Контакт: '
    for layout in range(4):
        places = positions(layout, 28)
        assert len(places) == 12
        assert all(a[1] < b[1] for a, b in zip(places, places[1:]))


def test_clipped_glyphs_stop_dataset_before_inference():
    font = ImageFont.load_default()
    with pytest.raises(ValueError, match='clip'):
        render(['X' * 500] * 12, font, 0, 28)

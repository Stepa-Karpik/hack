from scripts.unified.spotting_name_crops import regions


def test_native_quad_not_four_coordinate_bbox():
    raw = 'ФИО студента: Лукин Аркадий Борисович' + ''.join(f'<|LOC_{v}|>' for v in [80, 100, 500, 101, 503, 120, 79, 119])
    result = regions(raw)
    assert len(result) == 1
    assert result[0]['box_0_1000'] == [79, 100, 503, 120]
    assert result[0]['text'] == 'ФИО студента: Лукин Аркадий Борисович'


def test_reject_incomplete_out_of_range_and_empty_quad():
    for coordinates in ([0, 0, 100, 10], [0, 0, 2000, 0, 2000, 10, 0, 10], [10]*8):
        assert not regions('Text' + ''.join(f'<|LOC_{v}|>' for v in coordinates))

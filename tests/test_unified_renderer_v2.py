"""Training supervision integrity controls; no model accuracy claims."""
import json
from pathlib import Path
import pytest
from scripts.unified.prepare_v2 import CONTENT, make
from scripts.unified.contract import parse, KEYS


def test_content_partitions_do_not_share_names_or_organization_tokens():
    for part in range(3):
        partitions=[set(CONTENT[s][part]) for s in ['train','val','test']]
        assert not (partitions[0]&partitions[1] or partitions[0]&partitions[2] or partitions[1]&partitions[2])


@pytest.mark.parametrize('kind', list(KEYS))
def test_blank_name_supervision_and_all_value_regions_stay_on_page(kind):
    font=Path('C:/Windows/Fonts/arial.ttf')
    if not font.exists():pytest.skip('Local font not distributed')
    for layout in range(6):
        image,target=make(202610121+layout,kind,'train',font,layout,('student_name',))
        assert image.size==(1100,1480)
        assert target['fields']['student_name'] is None
        assert target['boxes']['student_name'] is None
        assert parse(json.dumps(target))==target


@pytest.mark.parametrize('kind', list(KEYS))
def test_narrative_prints_every_nonempty_required_value(kind):
    from scripts.unified.prepare_narrative import make as narrative
    font=Path('C:/Windows/Fonts/arial.ttf')
    if not font.exists():pytest.skip('Local font not distributed')
    for layout in range(6):
        _,target=narrative(202610123+layout,kind,'train',font,layout)
        assert parse(json.dumps(target))==target
        for key,value in target['fields'].items():
            if isinstance(value,str):assert target['boxes'][key] is not None

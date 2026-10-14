import numpy as np
import pytest
from PIL import Image, ImageDraw
from dekanat.preprocessing import estimate_skew, rectify_page


def page():
    image = Image.new("RGB", (800,1100), "white")
    draw = ImageDraw.Draw(image)
    for y in range(120,850,55):
        # Fragmented horizontal strokes, avoiding a dependence on installed fonts.
        for x in range(80,600,60):
            draw.rectangle((x,y,x+53,y+3), fill="black")
    return image


@pytest.mark.parametrize("angle", [-30,-10,10,30])
def test_skew_both_directions(angle):
    tilted = page().rotate(angle, Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    estimate, support = estimate_skew(tilted)
    assert abs(estimate+angle) < 1
    assert support >= 5
    corrected = rectify_page(tilted)
    assert abs(estimate_skew(corrected)[0]) < 1
    inverse = np.array(corrected.info["preprocessing"]["rectified_to_input"])
    point = np.array([100.,200.,1.])
    assert np.allclose(inverse @ (np.linalg.inv(inverse) @ point), point)


def test_blank_and_upright_pages_are_preserved():
    for image in (page(), Image.new("RGB", (800,1100), "white")):
        corrected = rectify_page(image)
        assert corrected.info["preprocessing"]["rotation_degrees"] == 0
        assert np.array_equal(np.asarray(corrected), np.asarray(image))

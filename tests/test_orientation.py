import numpy as np
import pytest
from PIL import Image, ImageDraw

from dekanat.orientation import reading_score, rotate_page, recover


def line(text, confidence=.99):
    return {"text": text, "bbox": [10,10,300,36], "page": 0, "confidence": confidence}


def page():
    image = Image.new("RGB", (400, 600), "white")
    ImageDraw.Draw(image).rectangle((10,10,200,50), fill="black")
    image.info["preprocessing"] = {"rectified_to_input": np.eye(3).tolist(), "output_size": list(image.size)}
    return image


def strong():
    return [line(text) for text in ["Справка об обучении", "ФИО: Иванов Иван Иванович", "Название вуза: Университет", "Направление подготовки: Информатика", "Форма обучения: очная", "Номер документа: 123", "Дата выдачи: 10.10.2026"]]


@pytest.mark.parametrize("degrees", [90,180,270])
def test_quarter_turn_inverse_maps_pixels_to_original_source(degrees):
    image = Image.new("RGB", (7, 5), "white")
    image.putpixel((2,1), (12,34,56))
    original_transform = np.array([[2,0,10],[0,3,20],[0,0,1]])
    image.info["preprocessing"] = {"rectified_to_input": original_transform.tolist()}
    result = rotate_page(image, degrees)
    y,x = np.argwhere((np.asarray(result) == [12,34,56]).all(axis=2))[0]
    mapped = np.asarray(result.info["preprocessing"]["rectified_to_input"])@np.array([x,y,1])
    assert np.allclose(mapped, original_transform@np.array([2,1,1]))
    assert result.info["preprocessing"]["output_size"] == list(result.size)


def test_confidence_alone_does_not_establish_orientation():
    assert reading_score([line("ZZZZ 55555", .99)])["score"] == 0


def test_normal_text_never_triggers_extra_reading():
    image = page()
    ocr = {"lines": strong(), "seconds": .1, "retries": 0}
    def forbidden(_):
        raise AssertionError("Normal page should not be reread")
    result = recover([image], [image], ocr, forbidden)
    assert result["attempts"] == 0


def test_tied_orientations_do_not_rotate():
    image = page()
    pages = [image]
    ocr = {"lines": [line("ZZZZ")], "seconds": .1, "retries": 0}
    result = recover(pages, [image], ocr, lambda _: {"lines": strong(), "seconds": .1, "retries": 0})
    assert result["attempts"] == 3
    assert result["pages"][0]["applied"] is False
    assert pages[0] is image


def test_single_clear_winner_rotates_and_preserves_original_mapping():
    image = page()
    pages = [image]
    ocr = {"lines": [line("ZZZZ")], "seconds": .1, "retries": 0}
    calls = []
    def read(_):
        calls.append(1)
        return {"lines": strong() if len(calls) == 2 else [line("ZZZZ")], "seconds": .1, "retries": 0}
    result = recover(pages, [image], ocr, read)
    assert result["pages"][0]["degrees_ccw"] == 180
    assert np.allclose(pages[0].info["preprocessing"]["rectified_to_input"], [[-1,0,399],[0,-1,599],[0,0,1]])
    assert ocr["retries"] == 3
    assert reading_score(ocr["lines"])["type"] == "study"


def test_manual_type_mismatch_does_not_adopt_other_document():
    image = page()
    pages = [image]
    ocr = {"lines": [line("ZZZZ")], "seconds": .1, "retries": 0}
    calls = []
    def read(_):
        calls.append(1)
        return {"lines": strong() if len(calls) == 2 else [line("ZZZZ")], "seconds": .1, "retries": 0}
    result = recover(pages, [image], ocr, read, expected_type="leave")
    assert result["pages"][0]["applied"] is False
    assert pages[0] is image

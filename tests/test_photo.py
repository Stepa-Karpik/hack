import numpy as np
import pytest
from PIL import Image,ImageDraw
from dekanat.photo_augment import camera_view,illumination,conditions
from dekanat.preprocessing import rectify_page,flatten_lighting,quality_metrics,find_page
from dekanat.pipeline import respond
from dekanat.schema import SCHEMAS,load_policy


def sheet():
    image=Image.new("RGB",(800,1100),"white")
    draw=ImageDraw.Draw(image)
    for y in range(120,950,60):
        for x in range(80,650,60):draw.rectangle((x,y,x+45,y+8),fill="black")
    return image


@pytest.mark.parametrize("view",["front","from_top","from_bottom","from_left","from_right","diagonal"])
def test_perspective_preserves_inverse_coordinate_mapping(view):
    photo=camera_view(sheet(),view)
    corrected=rectify_page(photo)
    meta=corrected.info["preprocessing"]
    assert meta["perspective"]["applied"]
    assert not meta["rotation_degrees"]
    w,h=corrected.size
    corners=np.array([[0,0,1],[w-1,0,1],[w-1,h-1,1],[0,h-1,1]],float)
    mapped=corners@np.asarray(meta["rectified_to_input"]).T
    mapped=mapped[:,:2]/mapped[:,2:]
    assert np.allclose(mapped,meta["perspective"]["corners_input"],atol=.1)
    assert corrected.width<photo.width and corrected.height<photo.height


def test_lighting_correction_preserves_geometry_and_improves_background():
    image=illumination(sheet(),"shadow")
    result,metadata=flatten_lighting(image)
    assert metadata["applied"] and result.size==image.size
    before=np.asarray(image)[20:60,:,0]
    after=np.asarray(result)[20:60,:,0]
    assert after.std()<before.std()*.3
    original=sheet();same,metadata=flatten_lighting(original)
    assert not metadata["applied"]
    assert np.array_equal(np.asarray(same),np.asarray(original))


def test_small_bright_logo_is_not_a_page():
    image=Image.new("RGB",(800,1100),"#454545")
    ImageDraw.Draw(image).rectangle((30,30,200,180),fill="white")
    assert find_page(image) is None


def test_low_resolution_requires_review():
    assert quality_metrics(sheet().resize((400,550)))["review_required"]


def test_quality_warning_prevents_complete_response():
    fields={k:{"status":"found","value":True if k in ["signature","stamp"] else "тест","evidence":None}
            for k in list(SCHEMAS["study"]["fields"])+SCHEMAS["study"]["visual"]}
    analysis={"type":"study","fields":fields,"preprocessing":[{"quality":{"warnings":["Низкое разрешение"]}}]}
    response=respond(analysis,"Все ли поля есть в документе?",load_policy())
    assert response["status"]=="insufficient"
    assert "пересъёмки" in response["answer"]
    assert response["sources"][0]["kind"]=="policy"
    assert respond(analysis,"Какая стоимость обучения?",load_policy())["status"]=="no_answer"

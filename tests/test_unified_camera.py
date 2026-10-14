import copy
import pytest
import numpy as np
from PIL import Image, ImageDraw
from scripts.unified.prepare_camera import homography, point, transform
from scripts.unified.contract import KEYS, MARKS


def fixture():
    kind='study_certificate'
    fields={k:False if k in MARKS else None for k in KEYS[kind]}
    fields['student_name']='Тестовое имя'
    boxes={k:None for k in fields};boxes['student_name']=[200,300,400,500]
    image=Image.new('RGB',(200,300),'white')
    ImageDraw.Draw(image).rectangle((40,90,80,150),fill='black')
    return image,{'document_type':kind,'fields':fields,'boxes':boxes}


def test_image_inverse_sampling_matches_forward_affine_boxes_and_preserves_values():
    image,target=fixture();saved=copy.deepcopy(target)
    output,new,matrix=transform(image,target,[(20,30),(180,30),(180,270),(20,270)])
    assert new['boxes']['student_name']==[260,340,420,500]
    assert output.getpixel((68,126))==(0,0,0)
    assert target==saved and new['fields']==target['fields']
    assert new['boxes']['issue_date'] is None


def test_perspective_maps_all_corners_and_encloses_field():
    image,target=fixture();dest=[(30,25),(170,35),(185,270),(15,280)]
    output,new,matrix=transform(image,target,dest);matrix=np.array(matrix)
    for source,expected in zip([(0,0),(200,0),(200,300),(0,300)],dest):
        assert np.allclose(point(matrix,*source),expected)
    box=new['boxes']['student_name']
    for x,y in [(40,90),(80,90),(80,150),(40,150)]:
        u,v=point(matrix,x,y)
        assert box[0]<=u*5<=box[2] and box[1]<=v*1000/300<=box[3]


def test_out_of_frame_annotation_is_rejected_without_clipping():
    image,target=fixture()
    with pytest.raises(ValueError,match='outside frame'):
        transform(image,target,[(-100,0),(100,0),(100,300),(-100,300)])


def test_degenerate_projection_is_rejected():
    with pytest.raises(np.linalg.LinAlgError):
        homography([(0,0)]*4,[(1,1)]*4)

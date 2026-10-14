import pytest
import torch
from scripts.unified.loss import weighted_causal_loss


def test_weighted_loss_preserves_next_token_alignment_and_masks_prompt():
    logits=torch.tensor([[[2.,0.,1.],[0.,3.,1.],[1.,0.,2.],[0.,0.,0.]]],requires_grad=True)
    labels=torch.tensor([[-100,-100,1,2]])
    weights=torch.tensor([[0.,0.,1.,1.]])
    expected=torch.nn.functional.cross_entropy(logits[0,1:3],torch.tensor([1,2]))
    assert torch.allclose(weighted_causal_loss(logits,labels,weights,chunk=1),expected)
    weights[0,2]=4
    loss=weighted_causal_loss(logits,labels,weights,chunk=1)
    per=torch.nn.functional.cross_entropy(logits[0,1:3],torch.tensor([1,2]),reduction='none')
    assert torch.allclose(loss,(4*per[0]+per[1])/5)
    loss.backward()
    assert logits.grad[0,0].abs().sum()==0
    assert logits.grad[0,1:3].abs().sum()>0


def test_empty_supervision_is_rejected():
    with pytest.raises(ValueError):
        weighted_causal_loss(torch.zeros(1,2,3),torch.full((1,2),-100),torch.zeros(1,2))


def test_scalar_weighting_does_not_weight_box_nulls_or_document_type():
    import json
    from scripts.unified.loss import semantic_weights
    class Characters:
        def decode(self,ids,**kwargs):return ''.join(chr(n) for n in ids)
        def __call__(self,text,**kwargs):
            return {'input_ids':list(map(ord,text)),'offset_mapping':[(i,i+1) for i in range(len(text))]}
    target={'document_type':'study_certificate','fields':{'student_name':None,
            'university':'Институт «Проверка»','signature_present':False},
            'boxes':{'student_name':None,'university':[1,2,3,4],'signature_present':None}}
    text=json.dumps(target,ensure_ascii=False,separators=(',',':'))
    labels=torch.tensor([[-100,-100]+list(map(ord,text))])
    weights=semantic_weights(Characters(),labels,target)[0,2:]
    assert weights[text.index('null')]==2
    assert weights[text.index('false')]==4
    assert weights[text.rindex('null')]==1
    assert weights[text.index('study_certificate')]==1
    assert weights[text.index('Институт')]==2


def test_binding_weights_target_type_and_field_keys_without_box_key_weighting():
    import json
    from scripts.unified.loss import semantic_weights
    class Characters:
        def decode(self,ids,**kwargs):return ''.join(chr(n) for n in ids)
        def __call__(self,text,**kwargs):
            return {'input_ids':list(map(ord,text)),'offset_mapping':[(i,i+1) for i in range(len(text))]}
    target={'document_type':'academic_leave_application','fields':{'group':None},'boxes':{'group':None}}
    text=json.dumps(target,separators=(',',':'))
    labels=torch.tensor([[-100]+list(map(ord,text))])
    plain=semantic_weights(Characters(),labels,target)[0,1:]
    weighted=semantic_weights(Characters(),labels,target,type_weight=8,key_weight=4)[0,1:]
    assert weighted[text.index('academic_leave_application')]==8
    assert weighted[text.index('group')]==4
    assert weighted[text.rindex('group')]==1
    assert weighted[text.index('null')]==plain[text.index('null')]==2
    assert weighted[text.rindex('null')]==1

"""Training-only scalar weighting. No generation filtering or label lookup."""
import json
import re


def semantic_weights(tokenizer,labels,target,mark_weight=4.,missing_weight=2.,text_weight=2.,
                     type_weight=1.,key_weight=1.):
    """Map exact serialized target offsets to supervised tokens; fail on drift."""
    import torch
    if labels.shape[0]!=1:raise ValueError('Scalar weighting currently supports one micro-batch record')
    selected=labels[0]>=0
    ids=labels[0,selected].tolist()
    answer=tokenizer.decode(ids,skip_special_tokens=False,clean_up_tokenization_spaces=False)
    literal=json.dumps(target,ensure_ascii=False,separators=(',',':'))
    if not answer.startswith(literal):raise ValueError('Target tokenization prefix mismatch')
    encoded=tokenizer(answer,add_special_tokens=False,return_offsets_mapping=True)
    if encoded['input_ids']!=ids:raise ValueError('Offsets do not match supervised token IDs')
    fields_start=literal.index('"fields":')
    fields_end=literal.index(',"boxes":')
    spans=[]
    if type_weight != 1.:
        match=re.search(r'"document_type":("[^"\\]+")',literal)
        if not match:raise ValueError('Document type binding absent')
        spans.append((*match.span(1),type_weight))
    if key_weight != 1.:
        for match in re.finditer(r'("[^"\\]+"):',literal):
            if fields_start < match.start() < fields_end:
                spans.append((*match.span(1),key_weight))
    for match in re.finditer(r'"(?:signature_present|seal_present)":(true|false)',literal):
        if fields_start<=match.start()<fields_end:spans.append((*match.span(1),mark_weight))
    for match in re.finditer(r'"[^"\\]+":(null)',literal):
        if fields_start<=match.start()<fields_end:spans.append((*match.span(1),missing_weight))
    for match in re.finditer(r'"[^"\\]+":("(?:[^"\\]|\\.)*")',literal):
        if fields_start<=match.start()<fields_end:spans.append((*match.span(1),text_weight))
    values=[max([w for start,end,w in spans if left<end and right>start]+[1.])
            for left,right in encoded['offset_mapping']]
    weights=torch.zeros_like(labels,dtype=torch.float32)
    weights[0,selected]=torch.tensor(values,device=labels.device,dtype=torch.float32)
    return weights


def weighted_causal_loss(logits,labels,weights,chunk=64):
    """Compute only supervised next-token CE in bounded float32 chunks."""
    import torch
    from torch.nn import functional as F
    targets=labels[:,1:].reshape(-1)
    factors=weights[:,1:].reshape(-1)
    predictions=logits[:,:-1,:].reshape(-1,logits.shape[-1])
    indices=(targets!=-100).nonzero(as_tuple=False).flatten()
    if not len(indices):raise ValueError('No supervised next-token positions')
    numerator=logits.new_zeros((),dtype=torch.float32)
    denominator=factors.index_select(0,indices).sum()
    if not torch.isfinite(denominator) or denominator<=0:raise ValueError('Invalid loss weights')
    for ids in indices.split(chunk):
        loss=F.cross_entropy(predictions.index_select(0,ids).float(),targets.index_select(0,ids),reduction='none')
        numerator=numerator+(loss*factors.index_select(0,ids)).sum()
    return numerator/denominator

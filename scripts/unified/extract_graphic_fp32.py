"""Strict FP32 features from a frozen image-only cohort, no target file reads."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--input-manifest',type=Path,required=True)
    p.add_argument('--roots',type=Path,nargs=3,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('Fresh feature directory required')
    import torch
    import numpy as np
    from transformers import AutoProcessor,AutoModelForImageTextToText
    from scripts.unified.graphic_head import pool_visual
    from scripts.unified.model import read_image
    sha=lambda file:hashlib.sha256(file.read_bytes()).hexdigest()
    inputs=json.loads(args.input_manifest.read_text(encoding='utf-8'))
    if not inputs['complete'] or len(inputs['rows'])!=407:raise ValueError('Frozen 383 train +24 control input cohort required')
    roots={r.name:r for r in args.roots}
    if len(roots)!=3:raise ValueError('Unique source roots required')
    counts={}
    for row in inputs['rows']:
        if 'target' in row or row['dataset_id'] not in roots:raise ValueError('Image-only known-source metadata required')
        counts[(row['dataset_id'],row['partition'])]=counts.get((row['dataset_id'],row['partition']),0)+1
    if counts!={('unified-data-v2','train'):120,('unified-data-v2','val'):12,('unified-data-v2','test'):12,
               ('unified-real-marks-v1','train'):143,('unified-camera-v3','train'):120}:
        raise ValueError('Original source partitions required; correlated Frame val/test excluded')
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    source=json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    base_sha=sha(args.base/'model.safetensors')
    if base_sha!=source['files']['model.safetensors']['sha256']:raise ValueError('Actual base SHA mismatch')
    processor=AutoProcessor.from_pretrained(str(args.base),local_files_only=True,trust_remote_code=False)
    net,info=AutoModelForImageTextToText.from_pretrained(str(args.base),local_files_only=True,trust_remote_code=False,
        dtype=torch.float32,attn_implementation='sdpa',output_loading_info=True)
    if any(info.get(k) for k in ['missing_keys','unexpected_keys','mismatched_keys']):raise ValueError('Incomplete foundation')
    net=net.to('cuda').eval()
    for v in net.parameters():v.requires_grad_(False)
    args.output.mkdir(parents=True)
    records=[]
    for old in inputs['rows']:
        root=roots[old['dataset_id']];file=(root/old['image']).resolve()
        if not file.is_relative_to(root.resolve()) or sha(file)!=old['sha256']:raise ValueError('Input source identity mismatch')
        image=read_image(file)
        batch=processor.apply_chat_template([{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':'OCR:'}]}],
            add_generation_prompt=True,tokenize=True,return_dict=True,return_tensors='pt',
            processor_kwargs={'images_kwargs':{'size':{'shortest_edge':processor.image_processor.size['shortest_edge'],'longest_edge':1003520}}}).to('cuda')
        with torch.inference_mode():
            visual=net.get_image_features(batch['pixel_values'],batch['image_grid_thw'],return_dict=True)
            vector=pool_visual(visual.last_hidden_state,batch['image_grid_thw']).cpu().numpy()
        out=args.output/f'{len(records):04}.npy';np.save(out,vector,allow_pickle=False)
        records.append({k:old[k] for k in ['dataset_id','partition','image','sha256']})
        records[-1].update(feature=out.name,feature_sha256=sha(out),dimension=len(vector),grid=batch['image_grid_thw'].tolist())
        (args.output/'manifest.json').write_text(json.dumps({'complete':len(records)==407,'planned_count':407,'rows':records,
            'base_revision':source['revision'],'base_weight_sha256':base_sha,'dtype':'float32','max_pixels':1003520,
            'tf32_matmul_allowed':False,'tf32_cudnn_allowed':False,'trainable_backbone_parameters':0,
            'input_manifest_sha256':sha(args.input_manifest),'grouping':'All178 Frame source composites one correlated group; original143train only, other35 excluded; no independent writer claim',
            'parameter_dtypes':sorted({str(v.dtype) for v in net.parameters()})},indent=2),encoding='utf-8')
        if len(records)%20==0 or len(records)==407:print('strict FP32 features',len(records),'/407',flush=True)
        del batch,visual,vector


if __name__=='__main__':main()

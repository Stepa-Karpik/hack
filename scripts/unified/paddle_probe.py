"""Direct native PaddleOCR-VL component; no pipeline, labels or reference lookup."""
import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path
from scripts.unified.model import read_document


def main():
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True)
    p.add_argument('--inputs',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--task',choices=['ocr','spotting','seal'],default='ocr')
    p.add_argument('--cpu',action='store_true');p.add_argument('--max-pixels',type=int,default=1280*28*28)
    p.add_argument('--max-tokens',type=int,default=1024)
    p.add_argument('--threads',type=int,default=6);args=p.parse_args()
    if args.output.exists() or not 1<=args.threads<=32 or not 112896<=args.max_pixels<=4096*28*28 or not 1<=args.max_tokens<=2048:
        raise ValueError('Fresh output and bounded positive budgets required')
    device='cpu' if args.cpu else 'cuda'
    if args.cpu:torch.set_num_threads(args.threads)
    if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('Requested CUDA unavailable')
    manifest=json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    if manifest['repo']!='PaddlePaddle/PaddleOCR-VL-1.6':raise ValueError('Unexpected base')
    start=time.perf_counter()
    processor=AutoProcessor.from_pretrained(str(args.base),local_files_only=True,trust_remote_code=False)
    model,loading=AutoModelForImageTextToText.from_pretrained(str(args.base),local_files_only=True,
        trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa',output_loading_info=True)
    if loading.get('missing_keys') or loading.get('unexpected_keys') or loading.get('mismatched_keys'):
        raise RuntimeError('Incomplete native weight mapping; inference not qualified: '+str(loading))
    loading={k:sorted(v) if isinstance(v,set) else v for k,v in loading.items()}
    model=model.to(device).eval()
    loaded=time.perf_counter()-start
    prompts={'ocr':'OCR:','spotting':'Spotting:','seal':'Seal Recognition:'}
    rows=[]
    for file in args.inputs:
        image=read_document(file);original_size=list(image.size)
        if args.task=='spotting' and image.width<1500 and image.height<1500:
            from PIL import Image
            image=image.resize((image.width*2,image.height*2),Image.Resampling.LANCZOS)
        messages=[{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':prompts[args.task]}]}]
        inputs=processor.apply_chat_template(messages,add_generation_prompt=True,tokenize=True,
            return_dict=True,return_tensors='pt',processor_kwargs={'images_kwargs':{'size':{
                'shortest_edge':processor.image_processor.size['shortest_edge'],'longest_edge':args.max_pixels}}}).to(device)
        start=time.perf_counter()
        with torch.inference_mode():
            generated=model.generate(**inputs,max_new_tokens=args.max_tokens,do_sample=False,use_cache=True)
        if device=='cuda':torch.cuda.synchronize()
        tokens=generated[0,inputs['input_ids'].shape[-1]:]
        text=processor.decode(tokens,skip_special_tokens=True,clean_up_tokenization_spaces=False)
        raw_tokens=processor.decode(tokens,skip_special_tokens=False,clean_up_tokenization_spaces=False)
        rows.append({'file':file.name,'input_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
            'source_image_size':original_size,'supplied_image_size':list(image.size),'raw':text,
            'raw_with_special_tokens':raw_tokens,
            'input_tokens':int(inputs['input_ids'].shape[-1]),'generated_tokens':int(tokens.shape[-1]),
            'token_budget_reached':int(tokens.shape[-1])>=args.max_tokens,'seconds':time.perf_counter()-start,
            'image_grid_thw':inputs['image_grid_thw'].tolist() if 'image_grid_thw' in inputs else None})
        report={'scope':'Direct single-network OCR diagnostic, no field/mark/app accuracy claim',
            'base_revision':manifest['revision'],'weights_sha256':manifest['files']['model.safetensors']['sha256'],
            'task':args.task,'device':device,'dtype':'bfloat16','trust_remote_code':False,'model_load_seconds':loaded,
            'cpu_threads':args.threads if args.cpu else None,
            'model_class':type(model).__name__,'processor_class':type(processor).__name__,
            'parameters':sum(x.numel() for x in model.parameters()),
            'loading_info':loading,
            'max_pixels':args.max_pixels,'max_tokens':args.max_tokens,'complete':len(rows)==len(args.inputs),
            'environment':{k:importlib.metadata.version(k) for k in ['torch','transformers','tokenizers','huggingface_hub','Pillow','numpy']},
            'rows':rows,'promoted':False}
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(file.name,'tokens',rows[-1]['generated_tokens'],'seconds',round(rows[-1]['seconds'],2),flush=True)


if __name__=='__main__':main()

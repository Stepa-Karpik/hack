"""Image-only native OCR over an input list; strict FP32/1MP, TF32 off, resumable.

Targets are never read here. Grading is a separate step after completion.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--adapter', type=Path)
    p.add_argument('--images', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--budget', type=int, default=768)
    p.add_argument('--device', default='cuda')
    p.add_argument('--threads', type=int, default=6)
    args = p.parse_args()
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.train_literal_ocr import infer
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    processor.image_processor.size.longest_edge = 1003520
    core = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False,
                                                       dtype=torch.float32, attn_implementation='sdpa')
    if args.adapter:
        from peft import PeftModel
        core = PeftModel.from_pretrained(core, str(args.adapter), is_trainable=False).get_base_model()
    if args.device == 'cpu':
        torch.set_num_threads(args.threads)
        torch.cuda.synchronize = lambda *a, **k: None  # keep CPU runs off the GPU
    core = core.to(args.device).eval()
    net = SimpleNamespace(model=core, processor=processor, torch=torch, device=args.device)
    rows = []
    if args.output.exists():
        rows = json.loads(args.output.read_text(encoding='utf-8'))['rows']
    done = {r['path'] for r in rows}
    meta = dict(base=str(args.base), adapter=str(args.adapter) if args.adapter else None,
                adapter_sha256=hashlib.sha256((args.adapter / 'adapter_model.safetensors').read_bytes()).hexdigest() if args.adapter else None,
                precision='fp32', max_pixels=1003520, budget=args.budget, max_tokens=args.budget, tf32=False, device=args.device,
                parameter_dtypes=sorted({str(v.dtype) for v in core.parameters()}),
                actual_base_weight_sha256=hashlib.sha256((args.base / 'model.safetensors').read_bytes()).hexdigest(),
                cuda_matmul_allow_tf32=torch.backends.cuda.matmul.allow_tf32, cudnn_allow_tf32=torch.backends.cudnn.allow_tf32,
                scope='Image-only native OCR; targets unopened during inference')
    started = time.perf_counter()
    for file in args.images:
        if str(file) in done:
            continue
        row = infer(net, file, args.budget)
        row['path'] = str(file)
        rows.append(row)
        args.output.write_text(json.dumps({**meta, 'complete': len(rows) == len(args.images), 'rows': rows},
                                          ensure_ascii=False, indent=1), encoding='utf-8')
        print(len(rows), file.name, row['generated_tokens'], round(row['seconds'], 1), flush=True)
    args.output.write_text(json.dumps({**meta, 'complete': len(rows) == len(args.images), 'rows': rows,
                                       'wall_seconds': time.perf_counter() - started}, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()

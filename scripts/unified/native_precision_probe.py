"""Image-only native precision diagnostic, with optional language adapter."""
import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path
from scripts.unified.model import read_document


def validate(device, precision, threads, pixels, tokens):
    if device not in {'cpu', 'cuda'} or precision not in {'fp32', 'bf16'}:
        raise ValueError('Unsupported precision or device')
    if not 1 <= threads <= 16 or not 112896 <= pixels <= 2007040 or not 1 <= tokens <= 1024:
        raise ValueError('Bounded threads/pixels/tokens required')


def main():
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adapter', type=Path)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--precision', choices=['fp32', 'bf16'], default='fp32')
    parser.add_argument('--threads', type=int, default=6)
    parser.add_argument('--max-pixels', type=int, default=1003520)
    parser.add_argument('--max-tokens', type=int, default=24)
    args = parser.parse_args()
    validate(args.device, args.precision, args.threads, args.max_pixels, args.max_tokens)
    if args.output.exists():
        raise ValueError('Fresh output required')
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA unavailable')
    if args.device == 'cpu':
        torch.set_num_threads(args.threads)
    source = json.loads((args.base / 'source-manifest.json').read_text(encoding='utf-8'))
    if source['repo'] != 'PaddlePaddle/PaddleOCR-VL-1.6':
        raise ValueError('Unexpected foundation')
    dtype = torch.float32 if args.precision == 'fp32' else torch.bfloat16
    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    model, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=dtype, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys']):
        raise ValueError('Incomplete foundation')
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(args.adapter), is_trainable=False)
    model = model.to(args.device).eval()
    load_seconds = time.perf_counter() - started
    rows = []
    for file in args.inputs:
        image = read_document(file)
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
        batch = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': args.max_pixels}}}).to(args.device)
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(**batch, max_new_tokens=args.max_tokens, do_sample=False, use_cache=True)
        if args.device == 'cuda':
            torch.cuda.synchronize()
        tokens = generated[0, batch['input_ids'].shape[1]:]
        rows.append({'file': file.name, 'input_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                     'raw': processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False),
                     'token_ids': tokens.tolist(), 'generated_tokens': len(tokens),
                     'token_budget_reached': len(tokens) >= args.max_tokens, 'seconds': time.perf_counter() - started,
                     'input_tokens': int(batch['input_ids'].shape[1]), 'image_grid_thw': batch['image_grid_thw'].tolist()})
        report = {'scope': 'Bounded native OCR diagnostic; truncated outputs are not full document predictions',
                  'complete': len(rows) == len(args.inputs), 'device': args.device, 'precision': args.precision,
                  'threads': args.threads if args.device == 'cpu' else None, 'max_pixels': args.max_pixels,
                  'max_tokens': args.max_tokens, 'load_seconds': load_seconds,
                  'base_revision': source['revision'], 'base_weight_sha256': source['files']['model.safetensors']['sha256'],
                  'adapter_sha256': hashlib.sha256((args.adapter / 'adapter_model.safetensors').read_bytes()).hexdigest() if args.adapter else None,
                  'parameter_dtypes': sorted({str(p.dtype) for p in model.parameters()}),
                  'torch_cpu_capability': torch.backends.cpu.get_cpu_capability(),
                  'environment': {k: importlib.metadata.version(k) for k in ['torch', 'transformers', 'peft', 'Pillow']},
                  'rows': rows, 'promoted': False}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(file.name, args.device, args.precision, 'seconds', round(rows[-1]['seconds'], 3), flush=True)


if __name__ == '__main__':
    main()

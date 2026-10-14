"""Native shared reader precision diagnostic; original BF16 reader preserved."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.unified.model import read_document
from scripts.unified.text_binding import bind
from scripts.unified.contract import official_result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--head', type=Path, required=True)
    p.add_argument('--inputs', type=Path, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--verify-ocr', action='store_true')
    p.add_argument('--precision', choices=['fp32','bf16'], default='fp32')
    p.add_argument('--device', choices=['cpu','cuda'], default='cuda')
    p.add_argument('--threads', type=int, default=6)
    p.add_argument('--adapter', type=Path)
    args = p.parse_args()
    if not 1 <= args.threads <= 16: raise ValueError('Bounded threads required')
    if args.output.exists():
        raise ValueError('Fresh output required')
    import torch
    import time
    if args.device == 'cpu': torch.set_num_threads(args.threads)
    dtype = torch.float32 if args.precision == 'fp32' else torch.bfloat16
    from safetensors.torch import load_file
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from scripts.unified.graphic_head import GraphicReadout, OneBackboneGraphicReader
    config = json.loads((args.head/'config.json').read_text(encoding='utf-8'))
    source = json.loads((args.base/'source-manifest.json').read_text(encoding='utf-8'))
    if (not config['backbone_frozen'] or config['base_revision'] != source['revision']
            or config['base_weight_sha256'] != source['files']['model.safetensors']['sha256']):
        raise ValueError('Frozen foundation identity mismatch')
    processor = AutoProcessor.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    core, loading = AutoModelForImageTextToText.from_pretrained(str(args.base), local_files_only=True,
        trust_remote_code=False, dtype=dtype, attn_implementation='sdpa', output_loading_info=True)
    if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
        raise ValueError('Incomplete native weights')
    if args.adapter:
        from peft import PeftModel
        core = PeftModel.from_pretrained(core, str(args.adapter), is_trainable=False).get_base_model()
    core = core.to(args.device).eval()
    head = GraphicReadout(config['dimension'])
    head.load_state_dict(load_file(str(args.head/'graphic_head.safetensors')))
    model = OneBackboneGraphicReader(core, head.to(args.device)).eval()
    calls = []
    hook = core.model.visual.register_forward_hook(lambda *args: calls.append(1))
    rows = []
    for path in args.inputs:
        image = read_document(path)
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
        batch = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                'shortest_edge': processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to(args.device)
        calls.clear()
        started = time.perf_counter()
        with torch.inference_mode():
            generated, logits = model.read(batch)
        if args.device == 'cuda': torch.cuda.synchronize()
        seconds = time.perf_counter() - started
        shared_calls = len(calls)
        if shared_calls != 1:
            raise RuntimeError('Shared reader did not use exactly one visual pass')
        tokens = generated[0, batch['input_ids'].shape[-1]:]
        baseline_equal = None
        if args.verify_ocr:
            with torch.inference_mode():
                baseline = core.generate(**batch, max_new_tokens=1024, do_sample=False, use_cache=True)
            baseline_equal = torch.equal(generated, baseline)
        text = processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        binding = bind(text, truncated=len(tokens) >= 1024)
        scores = logits.sigmoid().tolist()
        marks = {key: value >= .5 for key, value in zip(('signature_present', 'seal_present'), scores)}
        result = None
        if binding['document_type']:
            prediction = {'document_type': binding['document_type'], 'fields': dict(binding['fields']),
                          'boxes': {key: None for key in binding['fields']}}
            for key in marks:
                if key in prediction['fields']:
                    prediction['fields'][key] = marks[key]
            result = official_result(prediction)
            for key in result['audit']:
                if key in marks:
                    result['audit'][key] = {'status': 'uncertain', 'source': 'shared_visual_graphic_readout',
                        'semantic_confidence': None, 'source_confidence': None, 'bbox': None,
                        'coordinate_space': None, 'classifier_score_uncalibrated': scores[0 if key == 'signature_present' else 1]}
                else:
                    result['audit'][key] = binding['audit'][key]
        rows.append({'file': path.name, 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'raw_ocr': text, 'raw': text, 'seconds': seconds, 'image_grid_thw': batch['image_grid_thw'].tolist(), 'token_budget_reached': len(tokens) >= 1024,
            'shared_visual_passes': shared_calls, 'tokens_equal_native_ocr': baseline_equal,
            'graphic_scores_uncalibrated': scores, 'graphic_prediction': marks,
            'binding': binding, 'result': result})
        args.output.write_text(json.dumps({'scope': 'Live one native shared encoder, OCR decoder + frozen-feature '
            'graphic readout; literal explicit-label rules. Synthetic development; not production or independent accuracy.',
            'complete': len(rows) == len(args.inputs), 'planned_count': len(args.inputs),
            'head_sha256': hashlib.sha256((args.head/'graphic_head.safetensors').read_bytes()).hexdigest(),
            'base_revision': config['base_revision'], 'base_weight_sha256': config['base_weight_sha256'],
            'max_pixels': 1003520, 'precision': args.precision, 'device': args.device,
            'cpu_threads': args.threads if args.device == 'cpu' else None,
            'parameter_dtypes': sorted({str(p.dtype) for p in core.parameters()}),
            'adapter_sha256': hashlib.sha256((args.adapter/'adapter_model.safetensors').read_bytes()).hexdigest() if args.adapter else None,
            'tf32_matmul_allowed': torch.backends.cuda.matmul.allow_tf32, 'rows': rows, 'promoted': False},
            ensure_ascii=False, indent=2), encoding='utf-8')
        print(path.name, 'visual', shared_calls, 'ocr equal', baseline_equal, 'graphic', marks, flush=True)
    hook.remove()


if __name__ == '__main__':
    main()

"""Dense fullpage OCR LoRA revision v2; matched BF16/2MP training and inference."""
import argparse
import hashlib
import json
import random
import re
import time
from pathlib import Path
from scripts.unified.model import read_image

LANGUAGE_TARGET = r'.*language_model\.layers\.\d+\.self_attn\.(q_proj|v_proj)'


def language_module(name):
    return re.fullmatch(LANGUAGE_TARGET, name) is not None


def records(root, split):
    return [json.loads(line) for line in (root / f'{split}.jsonl').read_text(encoding='utf-8').splitlines()]


def native_inputs(net, image, target=None):
    messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
    kwargs = dict(tokenize=True, return_dict=True, return_tensors='pt')
    prefix = net.processor.apply_chat_template(messages, add_generation_prompt=True, **kwargs)
    if target is None:
        return prefix.to(net.device)
    messages.append({'role': 'assistant', 'content': [{'type': 'text', 'text': target}]})
    batch = net.processor.apply_chat_template(messages, add_generation_prompt=False, **kwargs)
    count = prefix['input_ids'].shape[1]
    if not net.torch.equal(batch['input_ids'][:, :count], prefix['input_ids']):
        raise ValueError('Native assistant target changes the prompt token prefix')
    if batch['input_ids'].shape[1] > 4096:
        raise ValueError('Training record exceeds budget; truncation is forbidden')
    labels = batch['input_ids'].clone()
    labels[:, :count] = -100
    batch['labels'] = labels
    return batch.to(net.device)


def infer(net, file, budget=512):
    image = read_image(file)
    batch = native_inputs(net, image)
    started = time.perf_counter()
    with net.torch.inference_mode():
        generated = net.model.generate(**batch, max_new_tokens=budget, do_sample=False, use_cache=True)
    net.torch.cuda.synchronize()
    tokens = generated[0, batch['input_ids'].shape[1]:]
    return {'file': file.name, 'input_sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
            'raw': net.processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False),
            'image_grid_thw': batch['image_grid_thw'].tolist(), 'source_size': list(image.size), 'generated_tokens': len(tokens), 'token_budget_reached': len(tokens) >= budget,
            'seconds': time.perf_counter() - started}


def evaluate(net, root, split, output):
    # Inference consumes only image bytes; targets remain in separate data/evaluator.
    rows = []
    for row in records(root, split):
        file = root / row['image']
        if hashlib.sha256(file.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Input image SHA mismatch')
        rows.append(infer(net, file))
        output.write_text(json.dumps({'scope': 'Synthetic literal OCR, not application accuracy',
                         'complete': len(rows) == len(records(root, split)), 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'{output.stem} {len(rows)}', flush=True)


def main():
    import torch
    from peft import LoraConfig, get_peft_model
    from scripts.unified.paddle_model import PaddleDocumentModel
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=80)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.steps <= 500:
        raise ValueError('Fresh output and bounded training steps required')
    args.output.mkdir(parents=True)
    torch.manual_seed(42)
    random.seed(42)
    net = PaddleDocumentModel(args.base, max_pixels=2007040)
    net.processor.image_processor.size.longest_edge = 1003520
    evaluate(net, args.data, 'val', args.output / 'resolution-1mp-val.json')
    evaluate(net, args.data, 'test', args.output / 'resolution-1mp-test.json')
    net.processor.image_processor.size.longest_edge = 2007040
    evaluate(net, args.data, 'val', args.output / 'baseline-val.json')
    evaluate(net, args.data, 'test', args.output / 'baseline-test.json')
    visual_before = {n: p.detach().cpu().clone() for n, p in net.model.named_parameters() if '.visual.' in '.' + n}
    modules = [n for n, _ in net.model.named_modules() if language_module(n)]
    if not modules or any('visual' in n for n in modules):
        raise ValueError('Language-only module selection failed')
    net.model = get_peft_model(net.model, LoraConfig(r=8, lora_alpha=16, lora_dropout=.05,
                              target_modules=LANGUAGE_TARGET, task_type='CAUSAL_LM'))
    trainable = [(n, p) for n, p in net.model.named_parameters() if p.requires_grad]
    if any('language_model' not in n or 'lora_' not in n for n, _ in trainable):
        raise ValueError('A visual or base parameter became trainable')
    parameters = [p for _, p in trainable]
    config = {'task': 'OCR:', 'seed': 42, 'precision': 'bfloat16', 'max_pixels': 2007040,
              'rank': 8, 'alpha': 16, 'dropout': .05, 'optimizer': 'AdamW', 'lr': 5e-6,
              'accumulation': 2, 'steps': args.steps, 'warmup': 8, 'vision_trainable': 0,
              'language_modules': modules, 'trainable_parameters': sum(p.numel() for p in parameters),
              'graphic_readout': 'Not loaded or changed; visual features require explicit retention qualification',
              'data_manifest_sha256': hashlib.sha256((args.data / 'manifest.json').read_bytes()).hexdigest(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'promoted': False}
    (args.output / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    net.model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    net.model.config.use_cache = False
    net.model.train()
    optimizer = torch.optim.AdamW(parameters, lr=5e-6, weight_decay=.01)
    train = records(args.data, 'train')
    random.shuffle(train)
    history = []
    started = time.perf_counter()
    for step in range(args.steps):
        optimizer.zero_grad(set_to_none=True)
        losses = []
        for micro in range(2):
            row = train[(step * 2 + micro) % len(train)]
            file = args.data / row['image']
            if hashlib.sha256(file.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Training image SHA mismatch')
            batch = native_inputs(net, read_image(file), row['target_text'])
            with torch.autocast('cuda', dtype=torch.bfloat16):
                loss = net.model(**batch).loss
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite loss; experiment rejected')
            (loss / 2).backward()
            losses.append(float(loss.detach()))
            del batch, loss
        for group in optimizer.param_groups:
            group['lr'] = 5e-6 * min(1., (step + 1) / 8)
        torch.nn.utils.clip_grad_norm_(parameters, 1.)
        optimizer.step()
        history.append({'step': step + 1, 'loss': sum(losses) / 2, 'seconds': time.perf_counter() - started,
                        'peak_cuda_allocated_bytes': torch.cuda.max_memory_allocated()})
        (args.output / 'training.json').write_text(json.dumps({'complete': step + 1 == args.steps, 'history': history}, indent=2), encoding='utf-8')
        print(json.dumps(history[-1]), flush=True)
        if (step + 1) % 40 == 0 or step + 1 == args.steps:
            net.model.save_pretrained(args.output / f'step-{step + 1:04d}')
    net.model.config.use_cache = True
    net.model.eval()
    actual = dict(net.model.get_base_model().named_parameters())
    if not visual_before or any(n not in actual or not torch.equal(p, actual[n].detach().cpu()) for n, p in visual_before.items()):
        raise ValueError('Visual weight retention failed')
    (args.output / 'visual-retention.json').write_text(json.dumps({'all_visual_parameters_equal': True, 'count': len(visual_before)}), encoding='utf-8')
    evaluate(net, args.data, 'val', args.output / 'trained-val.json')
    evaluate(net, args.data, 'test', args.output / 'trained-test.json')


if __name__ == '__main__':
    main()

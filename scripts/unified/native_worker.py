"""Persistent one-backbone reader for the local page: load once, read many.

Same computation as `run_graphic_strict` -> `run_graphic_precision` for one
input: strict FP32 flags, one shared visual pass, OCR decode + frozen graphic
readout, explicit-label binding, pooled-feature sidecar. Only the process
lifetime differs (no per-upload model load). Protocol: one JSON request per
stdin line {"input": path, "output": path}; one JSON reply per stdout line.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from scripts.unified.contract import official_result
from scripts.unified.model import read_document
from scripts.unified.text_binding import bind


class Reader:
    def __init__(self, base, head, adapter=None, device='cpu', threads=6, swap=False, ollama=None, mark_head=None):
        import torch
        from safetensors.torch import load_file
        from transformers import AutoProcessor, AutoModelForImageTextToText
        from scripts.unified.graphic_head import GraphicReadout, OneBackboneGraphicReader
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_num_threads(threads)
        # swap: weights stay in RAM and visit the GPU only while one page is read,
        # so the chat model and the reader can share an 8 GB card.
        self.swap, self.ollama = swap and device == 'cuda', ollama
        self.fast = True
        self.torch, self.device, self.threads = torch, device, threads
        home = 'cpu' if self.swap else device
        self.base, self.head_dir, self.adapter = Path(base), Path(head), Path(adapter) if adapter else None
        self.config = json.loads((self.head_dir / 'config.json').read_text(encoding='utf-8'))
        source = json.loads((self.base / 'source-manifest.json').read_text(encoding='utf-8'))
        if (not self.config['backbone_frozen'] or self.config['base_revision'] != source['revision']
                or self.config['base_weight_sha256'] != source['files']['model.safetensors']['sha256']):
            raise ValueError('Frozen foundation identity mismatch')
        self.processor = AutoProcessor.from_pretrained(str(self.base), local_files_only=True, trust_remote_code=False)
        core, loading = AutoModelForImageTextToText.from_pretrained(str(self.base), local_files_only=True,
            trust_remote_code=False, dtype=torch.float32, attn_implementation='sdpa', output_loading_info=True)
        if any(loading.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
            raise ValueError('Incomplete native weights')
        if self.adapter:
            from peft import PeftModel
            core = PeftModel.from_pretrained(core, str(self.adapter), is_trainable=False).get_base_model()
        self.core = core.to(home).eval()
        head_module = GraphicReadout(self.config['dimension'])
        head_module.load_state_dict(load_file(str(self.head_dir / 'graphic_head.safetensors')))
        self.head = head_module.to(home)
        self.model = OneBackboneGraphicReader(self.core, self.head).eval()
        self.head_sha = hashlib.sha256((self.head_dir / 'graphic_head.safetensors').read_bytes()).hexdigest()
        self.adapter_sha = hashlib.sha256((self.adapter / 'adapter_model.safetensors').read_bytes()).hexdigest() if self.adapter else None
        self.mark_head = None
        if mark_head:
            from scripts.unified.train_mark_patches import PatchHead
            saved = torch.load(str(Path(mark_head) / 'patch_head.pt'), map_location='cpu')
            self.mark_head = PatchHead.build(saved['dimension'], saved['hidden'])
            self.mark_head.load_state_dict(saved['state_dict'])
            self.mark_head = self.mark_head.to(home).eval()
            rules = Path(mark_head) / 'thresholds.json'
            self.mark_rules = json.loads(rules.read_text(encoding='utf-8')) if rules.exists() else {}

    def _free_chat_vram(self):
        import urllib.request
        try:
            with urllib.request.urlopen(self.ollama + '/api/ps', timeout=3) as r:
                models = [m['name'] for m in json.loads(r.read().decode('utf-8')).get('models', [])]
            for name in models:
                body = json.dumps({'model': name, 'keep_alive': 0}).encode('utf-8')
                urllib.request.urlopen(urllib.request.Request(self.ollama + '/api/generate', data=body,
                                       headers={'Content-Type': 'application/json'}), timeout=30).read()
        except Exception:
            pass  # the reader falls back to CPU if VRAM is still short

    def _place(self):
        torch = self.torch
        if not self.swap:
            return self.device
        if self.ollama:
            self._free_chat_vram()
        try:
            self.core.to('cuda')
            self.head.to('cuda')
            if self.mark_head is not None:
                self.mark_head.to('cuda')
            return 'cuda'
        except torch.cuda.OutOfMemoryError:
            self._park()
            return 'cpu'

    def _park(self):
        if self.swap:
            self.core.to('cpu')
            self.head.to('cpu')
            if self.mark_head is not None:
                self.mark_head.to('cpu')
            self.torch.cuda.empty_cache()

    def read(self, path, output):
        device = self._place()
        try:
            return self._read(path, output, device)
        except self.torch.cuda.OutOfMemoryError:
            self._park()
            for stale in (Path(output), Path(output).with_suffix('.headfeatures.npz')):
                stale.unlink(missing_ok=True)
            return self._read(path, output, 'cpu')
        finally:
            self._park()

    def spot(self, path, output):
        """Same model, native 'Spotting:' task: text lines with quadrilaterals."""
        device = self._place()
        try:
            torch = self.torch
            image = read_document(Path(path))
            messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'Spotting:'}]}]
            batch = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                    'shortest_edge': self.processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to(device)
            started = time.perf_counter()
            with torch.inference_mode():
                tokens = None
                if device == 'cuda' and self.fast:
                    try:
                        from scripts.unified.fast_decode import GraphDecoder
                        core = self.core
                        visual = core.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
                        emb = core.model.language_model.embed_tokens(batch['input_ids'])
                        img = visual.pooler_output.to(emb.device, emb.dtype)
                        emb = emb.masked_scatter(core.model.get_placeholder_mask(batch['input_ids'], inputs_embeds=emb,
                                                                                  image_features=img), img)
                        decoder = GraphDecoder(core, max_cache_len=batch['input_ids'].shape[1] + 2048 + 8)
                        tokens, _ = decoder.generate(batch, emb, 2048, core.generation_config.eos_token_id)
                        del decoder
                    except Exception:
                        tokens = None
                if tokens is None:
                    generated = self.core.generate(**batch, max_new_tokens=2048, do_sample=False, use_cache=True)
                    tokens = generated[0, batch['input_ids'].shape[-1]:].tolist()
            text = self.processor.decode(tokens, skip_special_tokens=False, clean_up_tokenization_spaces=False)
            report = {'task': 'spotting', 'complete': True, 'device': device, 'raw': text,
                      'seconds': time.perf_counter() - started, 'tokens': len(tokens),
                      'token_budget_reached': len(tokens) >= 2048}
            Path(output).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            return report
        finally:
            self._park()

    def _patch_marks(self, tokens, grid):
        if self.mark_head is None:
            return None
        from scripts.unified.train_mark_patches import decode_maps, patch_inputs
        x, h, w = patch_inputs(tokens, grid)
        maps = decode_maps(self.mark_head(x), h, w)
        thresholds = self.mark_rules.get('thresholds', {})
        return {key: {'score': round(score, 5), 'box': box, 'present': score >= thresholds.get(key, 0.5),
                      'rule': self.mark_rules.get('rule', {}).get(key, 'patch')} for key, (score, box) in maps.items()}

    def _fast_read(self, batch):
        """Same computation as OneBackboneGraphicReader.read with a graph-captured greedy decoder."""
        from scripts.unified.fast_decode import GraphDecoder
        from scripts.unified.graphic_head import pool_visual
        core = self.core
        visual = core.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
        pooled = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
        logits = self.head(pooled.to(self.head.mean.device))
        self._last_marks = self._patch_marks(visual.last_hidden_state, batch['image_grid_thw'])
        embeddings = core.model.language_model.embed_tokens(batch['input_ids'])
        image_embeddings = visual.pooler_output.to(embeddings.device, embeddings.dtype)
        mask = core.model.get_placeholder_mask(batch['input_ids'], inputs_embeds=embeddings, image_features=image_embeddings)
        embeddings = embeddings.masked_scatter(mask, image_embeddings)
        decoder = GraphDecoder(core, max_cache_len=batch['input_ids'].shape[1] + 1024 + 8)
        tokens, confidences = decoder.generate(batch, embeddings, 1024, core.generation_config.eos_token_id)
        del decoder
        return tokens, logits, confidences

    def _read(self, path, output, device):
        import numpy as np
        torch, path, output = self.torch, Path(path), Path(output)
        arrays = output.with_suffix('.headfeatures.npz')
        if output.exists() or arrays.exists():
            raise ValueError('Fresh output required')
        calls, features = [], []
        hook = self.core.model.visual.register_forward_hook(lambda *a: calls.append(1))
        capture = self.head.register_forward_pre_hook(lambda m, inp: features.append(inp[0].detach().cpu().numpy().copy()))
        try:
            image = read_document(path)
            messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': 'OCR:'}]}]
            batch = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                return_dict=True, return_tensors='pt', processor_kwargs={'images_kwargs': {'size': {
                    'shortest_edge': self.processor.image_processor.size['shortest_edge'], 'longest_edge': 1003520}}}).to(device)
            started = time.perf_counter()
            confidences, decoder = None, 'generate'
            self._last_marks = None
            with torch.inference_mode():
                if device == 'cuda' and self.fast:
                    try:
                        tokens, logits, confidences = self._fast_read(batch)
                        decoder = 'cuda_graph_static_cache'
                    except Exception as error:  # identical-output fallback
                        print(json.dumps({'fast_decode_fallback': type(error).__name__ + ': ' + str(error)[:200]}),
                              file=sys.stderr, flush=True)
                        calls.clear(); features.clear()
                        tokens = None
                if decoder == 'generate':
                    generated, logits = self.model.read(batch)
                    tokens = generated[0, batch['input_ids'].shape[-1]:].tolist()
            if device == 'cuda':
                torch.cuda.synchronize()
            seconds = time.perf_counter() - started
        finally:
            hook.remove()
            capture.remove()
        if len(calls) != 1 or len(features) != 1:
            raise RuntimeError('Shared reader did not use exactly one visual pass')
        text = self.processor.decode(tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        token_ends = []
        if confidences is not None:
            # Character end offset of each generated token in the decoded text (for field confidence).
            for i in range(len(tokens)):
                token_ends.append(len(self.processor.decode(tokens[:i + 1], skip_special_tokens=True,
                                                            clean_up_tokenization_spaces=False)))
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
        np.savez_compressed(arrays, feature_0=features[0])
        row = {'file': path.name, 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
               'raw_ocr': text, 'raw': text, 'seconds': seconds, 'image_grid_thw': batch['image_grid_thw'].tolist(),
               'token_budget_reached': len(tokens) >= 1024, 'shared_visual_passes': len(calls),
               'decoder': decoder,
               'mark_patch': self._last_marks,
               'token_confidence': [[end, round(c, 5)] for end, c in zip(token_ends, confidences)] if confidences else None,
               'tokens_equal_native_ocr': None, 'graphic_scores_uncalibrated': scores, 'graphic_prediction': marks,
               'binding': binding, 'result': result}
        report = {'scope': 'Persistent local-page reader; same one-pass native computation as run_graphic_strict.',
                  'complete': True, 'planned_count': 1, 'head_sha256': self.head_sha,
                  'base_revision': self.config['base_revision'], 'base_weight_sha256': self.config['base_weight_sha256'],
                  'max_pixels': 1003520, 'precision': 'fp32', 'device': device,
                  'cpu_threads': self.threads if device == 'cpu' else None,
                  'parameter_dtypes': sorted({str(p.dtype) for p in self.core.parameters()}),
                  'adapter_sha256': self.adapter_sha, 'tf32_matmul_allowed': torch.backends.cuda.matmul.allow_tf32,
                  'rows': [row], 'promoted': False, 'tf32_cudnn_allowed': torch.backends.cudnn.allow_tf32,
                  'pooled_features_sha256': hashlib.sha256(arrays.read_bytes()).hexdigest(),
                  'pooled_features_scope': 'Existing single-pass features captured for separate post-inference head comparison, no second encoder/OCR call'}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--head', required=True)
    p.add_argument('--adapter')
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    p.add_argument('--threads', type=int, default=6)
    p.add_argument('--swap', action='store_true', help='Keep weights in RAM, use the GPU per page')
    p.add_argument('--ollama', help='Unload chat models at this Ollama URL before each GPU read')
    p.add_argument('--mark-head', help='Patch-level signature/seal head directory')
    args = p.parse_args()
    reader = Reader(args.base, args.head, args.adapter, args.device, args.threads, args.swap, args.ollama, args.mark_head)
    print(json.dumps({'ready': True}), flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            (reader.spot if request.get('task') == 'spotting' else reader.read)(request['input'], request['output'])
            reply = {'ok': True}
        except Exception as error:  # reported to the caller, worker stays alive
            reply = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)[:300]}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

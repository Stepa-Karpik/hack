"""One locally loaded Qwen2-VL network; no CRAFT, EasyOCR or YOLO calls."""
import json
import time
from pathlib import Path
from PIL import Image
from scripts.unified.contract import prompt, parse


class UnifiedModel:
    def __init__(self, base, adapter=None, max_pixels=512*28*28, constrained=False, adapter_trainable=False,
                 training_token_budget=2048,geometry_abstention=False,precision='nf4'):
        import torch
        from transformers import AutoProcessor, AutoConfig, Qwen2VLForConditionalGeneration, BitsAndBytesConfig
        self.torch = torch
        self.device = 'cuda'
        self.constrained = constrained
        self.training_token_budget=training_token_budget
        self.geometry_abstention=geometry_abstention
        if precision not in {'nf4','vision_bf16','bf16'}:raise ValueError('Unknown local precision profile')
        self.precision=precision
        if not torch.cuda.is_available():
            raise RuntimeError('This NF4 experiment requires a CUDA GPU')
        self.processor = AutoProcessor.from_pretrained(str(base), local_files_only=True,
                                                       min_pixels=256*28*28,max_pixels=max_pixels)
        config=AutoConfig.from_pretrained(str(base),local_files_only=True,trust_remote_code=False)
        if config.model_type=='qwen2_vl':
            model_class=Qwen2VLForConditionalGeneration
        elif config.model_type=='qwen3_vl':
            from transformers import Qwen3VLForConditionalGeneration
            model_class=Qwen3VLForConditionalGeneration
        else:raise ValueError('Only locally reviewed Qwen2-VL/Qwen3-VL architectures supported')
        quantization=None if precision=='bf16' else BitsAndBytesConfig(
            load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            llm_int8_skip_modules=['visual','lm_head'] if precision=='vision_bf16' else None)
        self.model = model_class.from_pretrained(
            str(base), local_files_only=True, trust_remote_code=False,
            torch_dtype=torch.bfloat16, attn_implementation='sdpa', device_map={'':'cuda:0'},
            quantization_config=quantization)
        if adapter is not None:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, str(adapter),is_trainable=adapter_trainable)
        from scripts.unified.precision_audit import audit
        self.loaded_precision=audit(self.model)
        if precision in {'vision_bf16','bf16'} and self.loaded_precision['visual']['linear4bit_modules']:
            raise RuntimeError('Requested unquantized vision but loaded 4-bit visual modules')
        self.model.eval()

    def inputs(self, image, target=None):
        messages = [{'role':'user','content':[{'type':'image'},{'type':'text','text':prompt()}]}]
        prefix = self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
        if target is None:
            return self.processor(text=[prefix],images=[image],return_tensors='pt').to(self.device)
        messages.append({'role':'assistant','content':[{'type':'text','text':json.dumps(target,ensure_ascii=False,separators=(',',':'))}]})
        full = self.processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=False)
        batch = self.processor(text=[full],images=[image],return_tensors='pt')
        count = self.processor(text=[prefix],images=[image],return_tensors='pt')['input_ids'].shape[1]
        assert self.torch.equal(batch['input_ids'][0,:count],
                                self.processor(text=[prefix],images=[image],return_tensors='pt')['input_ids'][0])
        if batch['input_ids'].shape[1] > self.training_token_budget:
            raise ValueError('Training record exceeds token budget; never truncate labels')
        labels = batch['input_ids'].clone(); labels[:,:count] = -100
        batch['labels'] = labels
        return batch.to(self.device)

    def predict(self, image, max_tokens=1024):
        self.model.eval()
        batch = self.inputs(image)
        start = time.perf_counter()
        generation = {}
        if self.constrained:
            from scripts.unified.contract import json_schema
            from lmformatenforcer import JsonSchemaParser
            from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
            generation['prefix_allowed_tokens_fn'] = build_transformers_prefix_allowed_tokens_fn(
                self.processor.tokenizer, JsonSchemaParser(json_schema()))
        with self.torch.inference_mode():
            output = self.model.generate(**batch,max_new_tokens=max_tokens,do_sample=False,use_cache=True,**generation)
        if str(self.device).startswith('cuda'):self.torch.cuda.synchronize()
        text = self.processor.batch_decode(output[:,batch['input_ids'].shape[1]:],skip_special_tokens=True,
                                           clean_up_tokenization_spaces=False)[0].strip()
        result = {'raw':text,'seconds':time.perf_counter()-start,'prediction':None,'error':None,
                  'constrained_decoding':self.constrained,
                  'precision_profile':self.precision,
                  'loaded_precision':self.loaded_precision,
                  'input_tokens':int(batch['input_ids'].shape[1]),
                  'image_grid_thw':batch['image_grid_thw'].tolist(),
                  'source_image_size':list(image.size)}
        try:
            # A sole outer Markdown fence is tolerated; no arbitrary substring extraction.
            clean = text[7:-3].strip() if text.startswith('```json') and text.endswith('```') else text
            if self.geometry_abstention:
                from scripts.unified.geometry_contract import parse_abstaining
                result['prediction'],result['geometry_contract']=parse_abstaining(clean)
            else:
                result['prediction'] = parse(clean)
        except (ValueError, TypeError) as exc:
            result['error'] = str(exc)
        return result


def read_image(path):
    from PIL import ImageOps
    with Image.open(path) as image:
        if getattr(image,'n_frames',1) != 1 or image.width*image.height > 24_000_000:
            raise ValueError('Only one image frame up to 24 MP is supported')
        return ImageOps.exif_transpose(image).convert('RGB')


def read_document(path):
    """Deterministic decoding/rendering only; this pilot requires one page."""
    from scripts.participantkit.upload_limits import inspect_upload
    from dekanat.io import read_pages
    path=Path(path)
    if path.stat().st_size>10*1024*1024:
        raise ValueError('Upload exceeds 10 MiB')
    data=path.read_bytes()
    limits=inspect_upload(data,path.name)
    if limits['pages']!=1:
        raise ValueError('The single-network pilot supports one-page documents only')
    pages=read_pages(data,Path(path).name)
    if len(pages)!=1:
        raise ValueError('The single-network pilot supports one-page documents only')
    return pages[0]

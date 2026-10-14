"""One native PaddleOCR-VL network using the shared experimental field contract."""
import json
from scripts.unified.model import UnifiedModel


class PaddleDocumentModel(UnifiedModel):
    def __init__(self,base,adapter=None,max_pixels=1605632,constrained=False,adapter_trainable=False,
                 training_token_budget=4096,geometry_abstention=False,precision='bf16',cpu=False):
        import torch
        from transformers import AutoProcessor,AutoModelForImageTextToText
        if constrained:
            # LMFE 0.11.3 imports this type from its former Transformers module.
            # Restore only the moved type alias in this isolated process.
            import transformers.tokenization_utils as legacy_tokenizers
            from transformers import PreTrainedTokenizerBase
            if not hasattr(legacy_tokenizers,'PreTrainedTokenizerBase'):
                legacy_tokenizers.PreTrainedTokenizerBase=PreTrainedTokenizerBase
        if precision!='bf16':raise ValueError('Paddle pilot supports full BF16 only')
        manifest=json.loads((base/'source-manifest.json').read_text(encoding='utf-8'))
        if manifest['repo']!='PaddlePaddle/PaddleOCR-VL-1.6':raise ValueError('Unexpected single-network base')
        self.device='cpu' if cpu else 'cuda'
        if not cpu and not torch.cuda.is_available():raise RuntimeError('Requested CUDA unavailable')
        self.torch=torch;self.constrained=constrained;self.precision=precision
        self.training_token_budget=training_token_budget;self.geometry_abstention=geometry_abstention
        self.processor=AutoProcessor.from_pretrained(str(base),local_files_only=True,trust_remote_code=False)
        self.processor.image_processor.size.longest_edge=max_pixels
        self.model,loading=AutoModelForImageTextToText.from_pretrained(str(base),local_files_only=True,
            trust_remote_code=False,dtype=torch.bfloat16,attn_implementation='sdpa',output_loading_info=True)
        if loading.get('missing_keys') or loading.get('unexpected_keys') or loading.get('mismatched_keys'):
            raise ValueError('Incomplete native weights; pilot rejected')
        self.model=self.model.to(self.device)
        if adapter:
            from peft import PeftModel
            self.model=PeftModel.from_pretrained(self.model,str(adapter),is_trainable=adapter_trainable)
        from scripts.unified.precision_audit import audit
        self.loaded_precision=audit(self.model);self.model.eval()

    def lora_modules(self,vision_lora):
        if not vision_lora:raise ValueError('Paddle joint pilot requires explicit --vision-lora')
        # Both vision and language expose q_proj/v_proj; no extra backbone exists.
        return ['q_proj','v_proj']

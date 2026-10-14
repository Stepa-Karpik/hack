"""Greedy decoding with a static KV cache and a captured CUDA graph for one step.

Same weights, same greedy argmax, same precision as `generate`; only the per-token
Python/kernel-launch overhead is removed. Outputs are verified token-for-token
against `generate` before use (see tests/qualification), and the caller falls
back to `generate` if capture is unavailable.
"""
import torch

_REGISTERED = False


def decode_gqa_attention(module, query, key, value, attention_mask, scaling=None, dropout=0.0, **kwargs):
    """One-token grouped attention without expanding or rescaling the whole KV cache."""
    b, heads, q_len, d = query.shape
    kv_heads = key.shape[1]
    q = query.reshape(b, kv_heads, (heads // kv_heads) * q_len, d)
    scores = torch.matmul(q, key.transpose(-1, -2)) * (scaling if scaling is not None else d ** -0.5)
    if attention_mask is not None:
        if attention_mask.dtype == torch.bool:
            scores = scores.masked_fill(~attention_mask, float('-inf'))
        else:
            scores = scores + attention_mask
    out = torch.matmul(torch.softmax(scores, dim=-1), value)
    out = out.reshape(b, heads, q_len, d).transpose(1, 2).contiguous()
    return out, None


def _register():
    global _REGISTERED
    if not _REGISTERED:
        from transformers import AttentionInterface, AttentionMaskInterface
        from transformers.masking_utils import sdpa_mask
        AttentionInterface.register('decode_gqa', decode_gqa_attention)
        AttentionMaskInterface.register('decode_gqa', sdpa_mask)  # boolean keep-mask over the static cache
        _REGISTERED = True


class GraphDecoder:
    def __init__(self, core, max_cache_len=4096):
        from transformers import StaticCache
        self.core = core
        self.lm = core.model.language_model
        self.max_cache_len = max_cache_len
        config = core.config.text_config if hasattr(core.config, 'text_config') else core.config
        self.cache = StaticCache(config=config, max_cache_len=max_cache_len)
        self.graph = None
        device = next(core.parameters()).device
        self.token = torch.zeros((1, 1), dtype=torch.long, device=device)
        self.position = torch.zeros((3, 1, 1), dtype=torch.long, device=device)
        self.next_token = torch.zeros((1,), dtype=torch.long, device=device)
        self.confidence = torch.zeros((1,), dtype=torch.float32, device=device)

    def _step(self):
        # One query token: grouped attention straight on the static cache (no repeat_kv copies).
        _register()
        config = self.lm.config
        previous = config._attn_implementation
        config._attn_implementation = 'decode_gqa'
        try:
            embeds = self.lm.embed_tokens(self.token)
            out = self.lm(inputs_embeds=embeds, position_ids=self.position, past_key_values=self.cache, use_cache=True)
        finally:
            config._attn_implementation = previous
        logits = self.core.lm_head(out.last_hidden_state[:, -1, :])
        self.next_token.copy_(logits.argmax(-1))
        self.confidence.copy_(torch.softmax(logits.float(), -1).max(-1).values)

    def _capture(self):
        stream = torch.cuda.Stream()
        stream.wait_stream(torch.cuda.current_stream())
        snapshot = self.cache.layers[0].cumulative_length.clone()
        with torch.cuda.stream(stream):
            for _ in range(2):  # warm-up allocations outside the graph
                self._step()
        torch.cuda.current_stream().wait_stream(stream)
        for layer in self.cache.layers:  # undo warm-up writes to the position counter
            layer.cumulative_length.copy_(snapshot)
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            self._step()
        for layer in self.cache.layers:
            layer.cumulative_length.copy_(snapshot)
        self.graph = graph

    @torch.inference_mode()
    def generate(self, batch, inputs_embeds, max_new_tokens=1024, eos_token_id=None):
        """Prefill eagerly into the static cache, then replay one captured step per token."""
        core = self.core
        prompt = batch['input_ids'].shape[1]
        if prompt + max_new_tokens + 2 > self.max_cache_len:
            raise ValueError('Prompt does not fit the static cache')
        self.cache.reset()
        core.model.rope_deltas = None
        prepared = {k: v for k, v in batch.items() if k != 'pixel_values'}
        out = core(**prepared, inputs_embeds=inputs_embeds, past_key_values=self.cache, use_cache=True,
                   logits_to_keep=1)
        logits = out.logits[:, -1, :]
        first = logits.argmax(-1)
        deltas = core.model.rope_deltas.to(first.device).view(-1)
        tokens = [int(first)]
        confidences = [float(torch.softmax(logits.float(), -1).max())]
        eos = set(eos_token_id if isinstance(eos_token_id, (list, tuple)) else [eos_token_id])
        if tokens[-1] in eos:
            return tokens, confidences
        self.token.copy_(first.view(1, 1))
        self.position.fill_(int(prompt + deltas[0]))
        if self.graph is None:
            self._capture()
        for i in range(1, max_new_tokens):
            self.graph.replay()
            value = int(self.next_token)
            tokens.append(value)
            confidences.append(float(self.confidence))
            if value in eos:
                break
            self.token.copy_(self.next_token.view(1, 1))
            self.position.add_(1)
        return tokens, confidences

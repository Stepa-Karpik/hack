"""An extra graphic readout on the same native Paddle vision backbone.

Frozen shared features, no independent detector/encoder. Raw sigmoid scores are
uncalibrated and do not establish semantic confidence or signature authenticity.
"""
import torch
from torch import nn


def pool_visual(tokens, grid):
    """3x3 spatial mean/max of native pre-projector patch features."""
    if grid.shape != (1, 3) or int(grid[0, 0]) != 1:
        raise ValueError('Exactly one still image required')
    height, width = int(grid[0, 1]), int(grid[0, 2])
    if tokens.ndim != 2 or tokens.shape[0] != height*width or min(height, width) < 3:
        raise ValueError('Native patch grid mismatch')
    features = tokens.float().reshape(height, width, -1)
    parts = []
    for y in range(3):
        for x in range(3):
            tile = features[y*height//3:(y+1)*height//3, x*width//3:(x+1)*width//3].reshape(-1, tokens.shape[-1])
            parts.extend((tile.mean(0), tile.max(0).values))
    pooled = torch.cat(parts)
    if not torch.isfinite(pooled).all():
        raise ValueError('Nonfinite visual features')
    return pooled


class GraphicReadout(nn.Module):
    def __init__(self, dimension):
        super().__init__()
        self.register_buffer('mean', torch.zeros(dimension))
        self.register_buffer('scale', torch.ones(dimension))
        self.linear = nn.Linear(dimension, 2)

    def forward(self, features):
        return self.linear((features.float()-self.mean)/self.scale)


class OneBackboneGraphicReader(nn.Module):
    """One shared native vision encoder, existing OCR decoder, extra mark head.

    Precomputed image embeddings feed the unchanged language decoder; the vision
    encoder is evaluated once. This experimental boundary still needs full gates.
    """
    def __init__(self, backbone, readout):
        super().__init__()
        self.backbone = backbone
        self.graphic_readout = readout
        for parameter in self.backbone.parameters():
            parameter.requires_grad_(False)

    def read(self, batch, max_tokens=1024):
        visual = self.backbone.get_image_features(batch['pixel_values'], batch['image_grid_thw'], return_dict=True)
        features = pool_visual(visual.last_hidden_state, batch['image_grid_thw'])
        logits = self.graphic_readout(features.to(self.graphic_readout.mean.device))
        core = self.backbone.model
        embeddings = core.language_model.embed_tokens(batch['input_ids'])
        image_embeddings = visual.pooler_output.to(embeddings.device, embeddings.dtype)
        mask = core.get_placeholder_mask(batch['input_ids'], inputs_embeds=embeddings, image_features=image_embeddings)
        embeddings = embeddings.masked_scatter(mask, image_embeddings)
        prepared = {k: v for k, v in batch.items() if k != 'pixel_values'}
        prepared['inputs_embeds'] = embeddings
        generated = self.backbone.generate(**prepared, max_new_tokens=max_tokens, do_sample=False, use_cache=True)
        return generated, logits

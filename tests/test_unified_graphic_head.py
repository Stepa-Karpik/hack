import pytest
import torch
from scripts.unified.graphic_head import GraphicReadout, pool_visual


def test_spatial_features_and_single_image_grid():
    patches = torch.arange(36, dtype=torch.float32).reshape(36, 1)
    result = pool_visual(patches, torch.tensor([[1, 6, 6]]))
    assert result.shape == (18,)
    assert result[:2].tolist() == [3.5, 7]
    assert result[-2:].tolist() == [31.5, 35]
    with pytest.raises(ValueError, match='still image'):
        pool_visual(patches, torch.tensor([[2, 6, 6]]))
    with pytest.raises(ValueError, match='grid mismatch'):
        pool_visual(patches[:35], torch.tensor([[1, 6, 6]]))


def test_head_training_changes_only_readout_and_preserves_input():
    features = torch.randn(4, 18)
    original = features.clone()
    head = GraphicReadout(18)
    before = head.linear.weight.detach().clone()
    optimizer = torch.optim.SGD(head.parameters(), lr=.1)
    loss = torch.nn.functional.binary_cross_entropy_with_logits(head(features), torch.zeros(4, 2))
    loss.backward()
    optimizer.step()
    assert not torch.equal(before, head.linear.weight)
    assert torch.equal(features, original)
    assert head(features).shape == (4, 2)


def test_shared_reader_injects_same_visual_embeddings_once():
    from types import SimpleNamespace
    from scripts.unified.graphic_head import OneBackboneGraphicReader

    class Native(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.calls = 0
            embed = torch.nn.Embedding(2, 2)
            torch.nn.init.zeros_(embed.weight)
            self.model = SimpleNamespace(language_model=SimpleNamespace(embed_tokens=embed),
                get_placeholder_mask=lambda ids, **kwargs: (ids == 1).unsqueeze(-1).expand(1, 3, 2))

        def get_image_features(self, *args, **kwargs):
            self.calls += 1
            return SimpleNamespace(last_hidden_state=torch.ones(9, 2), pooler_output=torch.tensor([[3., 4.]]))

        def generate(self, **kwargs):
            assert 'pixel_values' not in kwargs
            assert kwargs['inputs_embeds'][0].tolist() == [[0., 0.], [3., 4.], [0., 0.]]
            return kwargs['input_ids']

    backbone = Native()
    reader = OneBackboneGraphicReader(backbone, GraphicReadout(36))
    batch = {'input_ids': torch.tensor([[0, 1, 0]]), 'pixel_values': torch.ones(1),
             'image_grid_thw': torch.tensor([[1, 3, 3]])}
    result, logits = reader.read(batch, max_tokens=5)
    assert backbone.calls == 1
    assert torch.equal(result, batch['input_ids'])
    assert logits.shape == (2,)

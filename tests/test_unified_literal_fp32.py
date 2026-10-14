import pytest
torch = pytest.importorskip('torch')
from scripts.unified.train_literal_fp32 import prediction_positions


def test_selected_logits_preserve_full_masked_next_token_loss_and_gradient():
    torch.manual_seed(7)
    logits = torch.randn(1, 8, 11, requires_grad=True)
    labels = torch.tensor([[-100, -100, -100, -100, 2, 5, 7, 3]])
    full = torch.nn.functional.cross_entropy(logits[:, :-1].reshape(-1, 11), labels[:, 1:].reshape(-1))
    positions, targets = prediction_positions(labels)
    selected = torch.nn.functional.cross_entropy(logits[:, positions].reshape(-1, 11), targets.reshape(-1))
    torch.testing.assert_close(full, selected, rtol=1e-6, atol=1e-7)
    gradient_full = torch.autograd.grad(full, logits, retain_graph=True)[0]
    gradient_selected = torch.autograd.grad(selected, logits)[0]
    torch.testing.assert_close(gradient_full, gradient_selected, rtol=1e-6, atol=1e-7)


def test_empty_assistant_mask_cannot_be_trained():
    with pytest.raises(ValueError, match='Assistant'):
        prediction_positions(torch.tensor([[-100, -100, -100]]))

import torch
from scripts.unified.precision_audit import audit


def test_loaded_precision_counts_modules_and_stored_dtype_without_visual_name_guess():
    class Linear4bit(torch.nn.Linear):pass
    model=torch.nn.Module()
    model.visual=torch.nn.Sequential(torch.nn.Linear(2,3).to(torch.bfloat16))
    model.language=Linear4bit(3,2)
    # Substring matches must not accidentally classify a language module as vision.
    model.visualizer=Linear4bit(2,2)
    got=audit(model)
    assert got['visual']['linear4bit_modules']==0
    assert got['visual']['parameter_dtypes']=={'torch.bfloat16':9}
    assert got['other']['linear4bit_modules']==2
    assert got['other']['parameter_dtypes']=={'torch.float32':14}

"""Existing one-pass reader with explicit strict FP32 CUDA flags; no new NN."""
def main():
    import sys,json,hashlib
    from pathlib import Path
    import numpy as np
    import torch
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    output=Path(sys.argv[sys.argv.index('--output')+1])
    arrays=output.with_suffix('.headfeatures.npz')
    if arrays.exists():raise ValueError('Fresh pooled-feature sidecar required')
    from scripts.unified.graphic_head import GraphicReadout
    original=GraphicReadout.forward
    features=[]
    def capture(self,x):
        features.append(x.detach().cpu().numpy().copy())
        return original(self,x)
    GraphicReadout.forward=capture
    from scripts.unified.run_graphic_precision import main as read
    try:read()
    finally:GraphicReadout.forward=original
    data=json.loads(output.read_text(encoding='utf-8'))
    if not data['complete'] or len(features)!=len(data['rows']):raise ValueError('Complete one-readout-per-image capture required')
    np.savez_compressed(arrays,**{'feature_'+str(i):x for i,x in enumerate(features)})
    data['tf32_cudnn_allowed']=torch.backends.cudnn.allow_tf32
    data['pooled_features_sha256']=hashlib.sha256(arrays.read_bytes()).hexdigest()
    data['pooled_features_scope']='Existing single-pass features captured for separate post-inference head comparison, no second encoder/OCR call'
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()

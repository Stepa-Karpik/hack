"""Download the fixed public model revision, verify LFS SHA, never run remote code."""
import argparse
import hashlib
import json
from pathlib import Path

REPO='Qwen/Qwen2-VL-2B-Instruct'
REVISION='895c3a49bc3fa70a340399125c650a463535e71c'
FAMILIES={'qwen2':(REPO,REVISION),
          'qwen3':('Qwen/Qwen3-VL-2B-Instruct','89644892e4d85e24eaac8bacfd4f463576704203')}


def main():
    from huggingface_hub import HfApi, snapshot_download
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--family',choices=FAMILIES,default='qwen2')
    parser.add_argument('--ranged',action='store_true',help='Exact validated byte ranges for large public safetensors')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a fresh local model directory')
    repo,revision=FAMILIES[args.family]
    info=HfApi().model_info(repo,revision=revision,files_metadata=True)
    snapshot_download(repo,revision=revision,local_dir=args.output,
                      allow_patterns=['*.json','*.safetensors','*.txt','LICENSE','README.md'],
                      ignore_patterns=['*.safetensors'] if args.ranged else None)
    if args.ranged:
        from scripts.unified.ranged_download import download
        for file in info.siblings:
            if file.rfilename.endswith('.safetensors'):
                if not file.lfs:raise ValueError('Published SHA is required for ranged weights')
                download(repo,revision,file.rfilename,args.output/file.rfilename,file.size,file.lfs.sha256)
    manifest={'repo':repo,'revision':revision,'license':'Apache-2.0','files':{}}
    for file in info.siblings:
        target=args.output/file.rfilename
        if not target.is_file():continue
        with target.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if file.lfs and digest != file.lfs.sha256:
            raise ValueError('Downloaded weights fail published LFS SHA-256')
        manifest['files'][file.rfilename]={'sha256':digest,'bytes':target.stat().st_size}
    (args.output/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Pinned model downloaded and LFS hashes verified')


if __name__=='__main__':main()

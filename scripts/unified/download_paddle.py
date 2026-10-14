"""Fixed public PaddleOCR-VL component assets, without remote Python execution."""
import argparse
import hashlib
import json
import subprocess
import shutil
from pathlib import Path
from scripts.unified.ranged_download import download

REPO='PaddlePaddle/PaddleOCR-VL-1.6'
REVISION='c5630abae1d940eafe0697512a0325494b02ab42'
WEIGHTS_SHA='85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db'
WEIGHTS_BYTES=1917255968
FILES=['LICENSE','README.md','added_tokens.json','chat_template.jinja','config.json',
       'generation_config.json','preprocessor_config.json','processor_config.json',
       'special_tokens_map.json','tokenizer.json','tokenizer.model','tokenizer_config.json']


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise ValueError('Use a fresh base directory')
    args.output.mkdir(parents=True)
    curl=shutil.which('curl.exe') or shutil.which('curl')
    if not curl:raise RuntimeError('curl is required for public asset downloads with TLS validation')
    for name in FILES:
        file=args.output/name
        subprocess.run([curl,'-fsSL','--retry','2','--max-time','40','-o',str(file),
            f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}'],check=True,timeout=130)
    config=json.loads((args.output/'config.json').read_text(encoding='utf-8'))
    if config['model_type']!='paddleocr_vl':raise ValueError('Unexpected architecture')
    download(REPO,REVISION,'model.safetensors',args.output/'model.safetensors',WEIGHTS_BYTES,WEIGHTS_SHA)
    manifest={'repo':REPO,'revision':REVISION,'license':'Apache-2.0; LICENSE preserved',
        'remote_code_downloaded':False,'external_inference_api':False,
        'files':{f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
                 for f in args.output.iterdir() if f.is_file()}}
    (args.output/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Fixed PaddleOCR-VL component weights SHA verified',flush=True)


if __name__=='__main__':main()

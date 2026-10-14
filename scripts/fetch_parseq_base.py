"""Fetch pinned experimental assets; does not import or execute downloaded code."""
import argparse
import hashlib
import json
from pathlib import Path

import requests

MODEL_REVISION = '7ee349c4aa082a3ea6a694263b329ae613ce4dcd'
CODE_REVISION = '1902db043c029a7e03a3818c616c06600af574be'
WEIGHTS_SHA256 = '740c14f3eb61c97faa652a26a8c3f3521fcc9d8a8b202cd2be38aa838161799c'


def fetch(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(path.suffix+'.download')
        with requests.get(url,stream=True,timeout=(30,120)) as response:
            response.raise_for_status()
            with temporary.open('wb') as output:
                for chunk in response.iter_content(1024*1024):
                    output.write(chunk)
        if expected and hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise ValueError('Downloaded asset hash differs')
        temporary.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and digest != expected:
        raise ValueError('Existing asset hash differs')
    return {'sha256':digest,'bytes':path.stat().st_size,'url':url}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args()
    assets={}
    for name in ['README.md','config.json','best.pt']:
        assets[name]=fetch(f'https://huggingface.co/Hukyl/parseq-s-cyrillic-handwritten/resolve/{MODEL_REVISION}/{name}',args.target/name,WEIGHTS_SHA256 if name=='best.pt' else None)
    for name in ['strhub/models/parseq/model.py','strhub/models/parseq/modules.py','strhub/models/utils.py','strhub/data/utils.py','LICENSE']:
        assets['source/'+name]=fetch(f'https://raw.githubusercontent.com/baudm/parseq/{CODE_REVISION}/{name}',args.target/'source'/name)
    report={'model_revision':MODEL_REVISION,'code_revision':CODE_REVISION,'assets':assets,
            'scope':'Experimental handwriting base only; assets excluded from production release. Model weights CC BY-SA 4.0; code Apache-2.0. School notebooks used in upstream pretraining.'}
    (args.target/'asset_manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()

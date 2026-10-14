"""Fetch three writer/page references using bounded ZIP ranges, not 45GB."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fetch_notebook_sample import RemoteZip
from dekanat.schema import ROOT

REVISION='366a882a2b8d043d437126d2878bd3812ec55a94'
BASE=f'https://huggingface.co/datasets/AntiplagiatCompany/HWR200/resolve/{REVISION}/'


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args()
    args.target.mkdir(parents=True,exist_ok=True)
    annotations=args.target/'annotations.zip'
    if not annotations.exists():
        response=requests.get(BASE+'annotations.zip',timeout=60)
        response.raise_for_status()
        if len(response.content)!=10713719:
            raise ValueError('Unexpected annotation archive size')
        annotations.write_bytes(response.content)
    rows=[]
    with zipfile.ZipFile(annotations) as labels, zipfile.ZipFile(RemoteZip(BASE+'hwr200_0_19.zip',4200691737)) as images:
        names=images.namelist()
        for writer in [0,1,2]:
            candidates=sorted(n for n in names if n.startswith(f'hw_dataset/{writer}/original') and '/Сканы/' in n and Path(n).suffix.lower() in ['.jpg','.png'])
            if not candidates:
                raise ValueError('Writer scan not found')
            member=candidates[0]
            original=member.split('/')[2]
            label_member=f'annotations/Originals/{original.removeprefix("original")}/{original}.json'
            label=labels.read(label_member)
            image_path=args.target/f'writer_{writer}_scan.jpg'
            image_path.write_bytes(images.read(member))
            (args.target/f'writer_{writer}_text.json').write_bytes(label)
            rows.append({'writer':writer,'source_member':member,'annotation_member':label_member,
                         'image':str(image_path),'sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),
                         'annotation_sha256':hashlib.sha256(label).hexdigest(),
                         'status':'Reference page only: line segmentation/transcription pending review; not training/evaluation'})
            print(member,flush=True)
    report={'source':'https://huggingface.co/datasets/AntiplagiatCompany/HWR200','revision':REVISION,'license':'Apache-2.0 per dataset card',
            'annotation_archive_sha256':hashlib.sha256(annotations.read_bytes()).hexdigest(),'rows':rows,
            'scope':'Three scanned pages from writers0-2, full-text annotations. No training/evaluation yet; no claim of independent target-document quality. Original images excluded from release.'}
    (ROOT/'artifacts/hwr200_sample_sources.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()

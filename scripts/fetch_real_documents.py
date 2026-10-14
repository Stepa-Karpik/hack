"""Pinned small real-document sample; no automatic training on unverified labels."""
import hashlib,json,random,sys
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from PIL import Image,ImageDraw
from dekanat.schema import ROOT

RECEIPT_REVISION="50a7383534b3fe498c49eff9e7bb35b20f300eba"
BASE="https://huggingface.co/datasets/cdek-ocr/receipt-ocr-ru/resolve/"+RECEIPT_REVISION+"/"


def download(url,path):
    if not path.exists():
        response=requests.get(url,timeout=60);response.raise_for_status()
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(response.content)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target=ROOT/"data/external/real_documents";target.mkdir(parents=True,exist_ok=True)
    downloads=[];seen=set()
    for split,count in [("train",12),("validation",6),("test",6)]:
        annotation=target/f"receipts/{split}_source.jsonl"
        sha=download(BASE+f"annotations/{split}.jsonl",annotation)
        rows=[json.loads(x) for x in annotation.read_text(encoding="utf-8").splitlines()]
        random.Random(20261011).shuffle(rows)
        chosen=[]
        for row in rows:
            path=target/"receipts"/row["image"]
            try: digest=download(BASE+quote(row["image"],safe="/"),path)
            except requests.HTTPError:continue
            if digest in seen:continue
            seen.add(digest);chosen.append({**row,"sha256":digest})
            if len(chosen)==count:break
        (target/f"receipts/{split}_selected.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in chosen),encoding="utf-8")
        downloads.append({"source":"cdek-ocr/receipt-ocr-ru","revision":RECEIPT_REVISION,"split":split,"count":len(chosen),"source_annotation_sha256":sha,
                          "role":"data-quality audit; labels not yet approved for training","license":"MIT per dataset card; machine-assisted boxes not manually corrected"})
        print(split,len(chosen),flush=True)
    forms=[("gaugn_leave.pdf","https://gaugn.ru/Portals/0/download/students/poryadok_akadem.pdf"),
           ("rosnou_study.pdf","https://rosnou.ru/uploads/file/d/8/9/d89799014088000d8edf81c85f0ba524.pdf"),
           ("nvsu_forms.pdf","https://nvsu.ru/ru/smk/1383/Instruktsiya_po_deloproizvodstvu_FGBOU_VO_NVGU_%282017%29_%282%29.PDF")]
    for name,url in forms:
        try:
            sha=download(url,target/"forms"/name)
            downloads.append({"source":url,"file":name,"sha256":sha,"role":"local layout reference, not organizer policy or model training","license":"No explicit reuse license found; original excluded from release"})
        except requests.RequestException as error:
            downloads.append({"source":url,"file":name,"status":"download failed","error":str(error)})
    report={"format":"real-source-audit-v1","source_files_directory":"data/external/real_documents","downloads":downloads,
            "redistributed":False,"receipt_annotations_verified":False,"note":"Receipt splits preserved, exact-image duplicates excluded. This is a small sample, not the full corpus."}
    (ROOT/"artifacts/real_documents_sources.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()

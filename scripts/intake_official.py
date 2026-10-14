from pathlib import Path
import concurrent.futures,hashlib,json,requests
from datetime import datetime,timezone

BASE=Path('work/official-expansion-v1')
PROJECT=Path(__file__).resolve().parents[1]
SOURCES=[
 ('hse_leave_family','hse','leave','https://www.hse.ru/mirror/pubs/share/1023212841.docx','https://www.hse.ru/ba/hist/page_1'),
 ('hse_leave_medical','hse','leave','https://www.hse.ru/mirror/pubs/share/1023212795.doc','https://www.hse.ru/ba/hist/page_1'),
 ('rudn_practice_character','rudn','practice','https://phil.rudn.ru/upload/iblock/480/pwud2zq1uqrkhulrurxaspozmuukcgpy.docx','https://phil.rudn.ru/ru/educational-process/internships/reports/'),
 ('rudn_practice_diary','rudn','practice','https://phil.rudn.ru/upload/iblock/54e/72zo9a09q7e199a2bbsx0hq1al74r04d.docx','https://phil.rudn.ru/ru/educational-process/internships/reports/'),
 ('msu_leave_vmk','msu','leave','https://cs.msu.ru/sites/cmc/files/docs/polozhenie_ob_akademicheskih_otpuskah_studentam_vmk_mguutverzhdennoe.pdf','https://cs.msu.ru/'),
 ('sstu_study_sample','sstu','study','https://www.sstu.ru/upload/medialibrary/eac/perevod_spo_sstu_30.10.15.pdf','https://www.sstu.ru/'),
 ('spbgik_practice','spbgik','practice','https://spbgik.ru/upload/iblock/738/412kn5h5dox7r8barwigo9eco40n8nik/kaf_raie_publ_aa_konovich_metod_razrab_prakt_regt.pdf','https://spbgik.ru/'),
 ('dgunh_study','dgunh','study','https://dgunh.ru/wp-content/uploads/2025/11/polozhenie-ob-itogovoi-attestacii-po-dopolnitelnym-professionalnym-programmam.pdf','https://dgunh.ru/'),
 ('spbstu_practice','spbstu','practice','https://www.spbstu.ru/upload/dmo/aep/regulations-practice-aep.pdf','https://www.spbstu.ru/education/general-information/regulations/'),
]

def fetch(source):
    key,institution,kind,url,parent=source
    suffix=Path(url).suffix;target=BASE/'originals'/(key+suffix)
    row={'id':key,'institution':institution,'target_type':kind,'url':url,'source_page':parent,
         'license':'No explicit reuse/training/redistribution permission verified; public institutional form/reference, local evaluation only. Original excluded from release archive.',
         'roles':['intake audit; not yet training or scored validation'],'retrieved_utc':datetime.now(timezone.utc).isoformat()}
    try:
        if not target.exists():
            with requests.get(url,timeout=45,stream=True) as response:
                response.raise_for_status();content=bytearray()
                for part in response.iter_content(65536):
                    content.extend(part)
                    if len(content)>12*1024*1024:raise ValueError('Source exceeds 12 MiB intake bound')
            if not(bytes(content).startswith(b'%PDF') if suffix=='.pdf' else bytes(content).startswith(b'PK') if suffix=='.docx' else bytes(content).startswith(bytes.fromhex('d0cf11e0a1b11ae1'))):raise ValueError('Unexpected file signature')
            target.write_bytes(content)
        row.update(path=str(target),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),status='downloaded')
    except Exception as e:row.update(status='unavailable',error=str(e))
    return row

if __name__=='__main__':
    (BASE/'originals').mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:rows=list(executor.map(fetch,SOURCES))
    report={'scope':'Primary institutional originals, not authentic completed student documents. Intake only; no ML training, no legal-policy adoption. Freeze source identities before assigning development/holdout.','rows':rows}
    (PROJECT/'artifacts/official_sources_intake.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in rows:print(row['id'],row['status'],row.get('bytes',row.get('error')),flush=True)

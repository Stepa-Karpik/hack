from pathlib import Path
import json,hashlib,time
from native_pdf_eligibility import inspect_native_pdf
ROOT=Path(__file__).resolve().parents[2]
PRIVATE=Path('work/official-expansion-v1')
controls=json.loads((PRIVATE/'native-controls/manifest.json').read_text(encoding='utf-8'))
rows=[]
for r in controls['records']:
    data=Path(r['input']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['sha256']
    result=inspect_native_pdf(data);rows.append({**r,'inspection':result,'passed':result['eligible']==r['expected_eligible']})
institutional=[]
for filename in ['official_evaluation_truth.json','official_extra_evaluation_truth.json','official_round3_evaluation_truth_v2.json']:
    for r in json.loads((ROOT/'artifacts'/filename).read_text(encoding='utf-8'))['records']:
        data=Path(r['input']).read_bytes();assert hashlib.sha256(data).hexdigest()==r['sha256']
        start=time.perf_counter();result=inspect_native_pdf(data)
        institutional.append({'id':r['id'],'sha256':r['sha256'],'inspection':result,'inspection_seconds':time.perf_counter()-start})
report={'scope':'Unqualified offline visible-layer eligibility: eight own synthetic controls and 23 viewed institutional PDF inputs. Rejection means fallback to raster OCR, not rejection of a valid document. No calibrated accuracy, authentication, hidden-mapping proof or whole-app speed claim. Eligibility never proves a field value. Native parser placeholder error remains unresolved.',
        'controls_manifest':controls,'controls':rows,'control_passed':sum(r['passed'] for r in rows),'control_total':len(rows),
        'institutional':institutional,'institutional_eligible':sum(r['inspection']['eligible'] for r in institutional),
        'experiment_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}}
(ROOT/'artifacts/native_pdf_eligibility_probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Controls',report['control_passed'],'/',report['control_total'],'institutional eligible',report['institutional_eligible'],'/',len(institutional))
for r in rows:print(r['id'],r['inspection']['eligible'],r['inspection']['reason'])
assert report['control_passed']==report['control_total']

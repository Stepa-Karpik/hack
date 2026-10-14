from pathlib import Path
import sys, json, hashlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from native_pdf_geometry import native_lines
from native_pdf_eligibility import inspect_native_pdf
from native_fields_candidate import extract_candidate
from dekanat.extraction import detect_type, normalize

pack=ROOT.parent/'Реалистичные-документы'
truth=json.loads((pack/'ОЖИДАЕМЫЕ_ПОЛЯ.json').read_text(encoding='utf-8'))
rows=[];summary={'documents':0,'eligible':0,'type_correct':0,'present':0,'correct_literal':0,'wrong_found_literal':0}
for r in truth['records']:
    path=pack/(r['stem']+'.pdf');data=path.read_bytes()
    eligibility=inspect_native_pdf(data)
    # Diagnostic extraction even when ineligible, explicitly NOT production routing.
    lines=native_lines(data);kind=detect_type(lines or [])
    fields,changes=extract_candidate(lines or [],kind,ROOT/'models/fields.joblib')
    comparisons=[]
    for key,expected in r['expected_fields'].items():
        if isinstance(expected,bool):continue  # Visual marks need image model.
        field=fields.get(key,{'value':None,'status':'not_found'})
        correct=field['value'] is not None and normalize(str(field['value']))==normalize(str(expected))
        summary['present']+=1;summary['correct_literal']+=correct
        summary['wrong_found_literal']+=not correct and field['status']=='found'
        comparisons.append({'field':key,'expected':expected,'observed':field,'correct_literal':correct})
    summary['documents']+=1;summary['eligible']+=eligibility['eligible'];summary['type_correct']+=kind==r['type']
    rows.append({'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),'eligibility':eligibility,
        'type':kind,'fields':fields,'changes':changes,'comparisons':comparisons})
report={'scope':'Six viewed own fictional PDFs, isolated candidate, literal comparison without aliases or university prefix equivalence. Includes diagnostic extraction of INELIGIBLE files, which must use raster OCR in any app. Visual marks excluded. Source confidence1 is not semantic calibration; no app accuracy/speed claim.',
    'summary':summary,'rows':rows,'experiment_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}}
(ROOT/'artifacts/native_pdf_own_candidate_v20.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary))
for row in rows:
    print(row['file'],row['eligibility']['eligible'],[(c['field'],c['observed']['value']) for c in row['comparisons'] if not c['correct_literal']])

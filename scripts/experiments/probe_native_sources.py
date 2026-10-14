"""Offline PDF text diagnostic; no deployment and no OCR accuracy claim."""
from pathlib import Path
import sys,json,hashlib,time
from native_pdf_geometry import native_lines
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dekanat.extraction import detect_type,extract,normalize
from dekanat.field_validation import validate_fields
rows=[];summaries={}
for filename in ['official_evaluation_truth.json','official_extra_evaluation_truth.json','official_round3_evaluation_truth_v2.json']:
    truth=json.loads((ROOT/'artifacts'/filename).read_text(encoding='utf-8'))
    summary={'documents':0,'type_correct':0,'present':0,'correct':0,'correct_found':0,'confident_wrong':0,'absent':0,'absent_found':0}
    for record in truth['records']:
        path=Path(record['input']);data=path.read_bytes();assert hashlib.sha256(data).hexdigest()==record['sha256']
        started=time.perf_counter();lines=native_lines(data);text_seconds=time.perf_counter()-started
        kind=detect_type(lines or []);fields=extract(lines,kind,ROOT/'models/fields.joblib') if kind else {};validate_fields(fields)
        comparisons=[]
        for key,expected in record['fields'].items():
            f=fields.get(key,{'value':None,'status':'not_found','confidence':0})
            if expected is None:
                summary['absent']+=1;summary['absent_found']+=f['status']=='found'
            else:
                allowed=expected if isinstance(expected,list) else [expected]
                correct=f['value'] is not None and normalize(str(f['value'])) in {normalize(v) for v in allowed}
                summary['present']+=1;summary['correct']+=correct;summary['correct_found']+=correct and f['status']=='found';summary['confident_wrong']+=not correct and f['status']=='found'
                comparisons.append({'field':key,'expected':expected,'observed':f,'correct':correct})
        summary['documents']+=1;summary['type_correct']+=kind==record['type']
        rows.append({'id':record['id'],'input_sha256':record['sha256'],'cohort':filename,'type':kind,'fields':fields,'comparisons':comparisons,'native_text_seconds':text_seconds,'lines':lines})
    summaries[filename]=summary;print(filename,summary)
report={'scope':'23 viewed institutional source inputs, unqualified offline native PDF prototype. Characters/source-confidence1 are not calibrated ML confidence; no raster-visible consistency/hidden-layer gate, no OCR/visual model run and no full-app speed claim. Original first-pass source reports retained. Never deploy this probe as OCR.',
        'runtime_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')},'summary':summaries,'rows':rows}
(ROOT/'artifacts/native_pdf_all_probe_v18.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

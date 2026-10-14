from pathlib import Path
import sys,json,hashlib,statistics
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dekanat.pipeline import analyze,ANALYSIS_VERSION
source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')}
truth=json.loads((ROOT/'artifacts/official_evaluation_truth.json').read_text(encoding='utf-8'))
paths=[Path(r['input']) for r in truth['records'] if r['id'] in ['hse_family_filled_1','rudn_character_filled_1']]
paths.append(ROOT.parent/'Реалистичные-документы/06_Практика_с_характеристикой_два_листа.pdf')
assert len(paths)==3
data=[p.read_bytes() for p in paths]
analyze(data[0],paths[0].name,native_pdf=False) # excluded warmup
rows=[]
for index,(path,blob) in enumerate(zip(paths,data)):
    runs=[]
    for repeat in range(3):
        for enabled in ([False,True] if repeat%2==0 else [True,False]):
            _,result=analyze(blob,path.name,native_pdf=enabled)
            runs.append({'repeat':repeat,'native_enabled':enabled,'seconds':result['seconds'],
                'native_seconds':result.get('native_pdf',{}).get('seconds',0),
                'native_reason':result.get('native_pdf',{}).get('reason'),
                'native_changes':result.get('native_pdf',{}).get('changes',[])})
    rows.append({'file':path.name,'sha256':hashlib.sha256(blob).hexdigest(),'runs':runs,
        'median_disabled_seconds':statistics.median(r['seconds'] for r in runs if not r['native_enabled']),
        'median_enabled_seconds':statistics.median(r['seconds'] for r in runs if r['native_enabled']),
        'median_native_component_seconds':statistics.median(r['native_seconds'] for r in runs if r['native_enabled'])})
    print(path.name,rows[-1]['median_disabled_seconds'],rows[-1]['median_enabled_seconds'],flush=True)
assert source=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'dekanat').glob('*.py')}
report={'version':ANALYSIS_VERSION,'scope':'Three viewed PDFs, local warmed GPU, same process, three alternating runs per flag; full analyze includes raster OCR/visual models/preprocessing. Not generalized throughput, cold-start, training or an independent quality test. This is an enrichment overhead benchmark, no speed bypass.',
        'runtime_sha256':source,'rows':rows}
(ROOT/'artifacts/native_pdf_v21_app_timing.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

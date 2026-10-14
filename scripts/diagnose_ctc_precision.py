"""Isolated diagnostic of decoder arithmetic; does not change OCR or weights."""
import json
import warnings
from pathlib import Path
import numpy as np
from easyocr.utils import ctcBeamSearch


def main():
    rows=[]
    for length in [32,128,256,512]:
        for dtype in [np.float32,np.float64]:
            mat=np.tile(np.array([.9,.05,.05],dtype=dtype),(length,1))
            with warnings.catch_warnings(record=True) as got:
                warnings.simplefilter('always',RuntimeWarning)
                result=ctcBeamSearch(mat,['[blank]','а','б'],[],None,beamWidth=5)
            rows.append({'time_steps':length,'dtype':str(mat.dtype),'result':result,
                         'runtime_warning_count':len(got),
                         'warning_examples':sorted(set(str(w.message) for w in got))[:4]})
    report={'scope':'Isolated EasyOCR 1.7.2 decoder on artificial normalized probabilities, no images/models/production changes. Diagnostic of existing warnings, not quality or proposed deployment evidence.',
            'parameters':{'probabilities':[.9,.05,.05],'beam_width':5,'classes':['[blank]','а','б']},'rows':rows}
    target=Path(__file__).resolve().parents[1]/'artifacts/beamsearch_numeric_diagnostic.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False))


if __name__=='__main__':
    main()

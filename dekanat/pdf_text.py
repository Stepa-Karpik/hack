"""Missing-only PDF enrichment. Raster OCR always runs; no speed bypass."""
import copy
import time
import numpy as np
from pathlib import Path
from .pdf_text_eligibility import inspect_native_pdf
from .pdf_text_geometry import native_lines
from .pdf_text_fields import extract_candidate
from .extraction import detect_type


def enrich_pdf(data, filename, fields, kind, model, *, orientation=None, preprocessing=None):
    started=time.perf_counter()
    report={'applied':False,'changes':[],'source':'visible_pdf_text',
        'scope':'Visible-layer heuristic and literal parsing; no semantic probability or authenticity proof. Existing values/conflicts preserved; additions require review.'}
    def finish(reason):
        report.update(reason=reason,seconds=time.perf_counter()-started)
        return report
    if Path(filename).suffix.lower()!='.pdf':return finish('not_pdf')
    if orientation and any(p.get('applied') for p in orientation.get('pages',[])):
        return finish('ocr_page_rotation')
    # Nothing to recover, avoid the extra parser/render work.
    if not any(f.get('value') is None and f.get('status')=='not_found' for f in fields.values()):
        return finish('no_missing_fields')
    try:
        eligibility=inspect_native_pdf(data);report['eligibility']=eligibility
        if not eligibility['eligible']:return finish('raster_ocr_fallback')
        lines=native_lines(data)
        if not lines:return finish('empty_native_text')
        if detect_type(lines)!=kind:return finish('native_type_mismatch')
        candidates,proposal_changes=extract_candidate(lines,kind,model)
        report['proposal_changes']=proposal_changes
        additions={}
        for key,candidate in candidates.items():
            previous=fields.get(key)
            if (not previous or previous.get('value') is not None or previous.get('status')!='not_found'
                or candidate.get('value') is None or candidate.get('status')!='found'):
                continue
            new=copy.deepcopy(candidate)
            # Source extraction certainty1 is NOT a calibrated semantic score.
            # .5 is an explicit review ceiling consistent with uncertain fields.
            new.update(status='uncertain',confidence=.5,source_confidence=1.0,parser_score=candidate.get('confidence'),
                       semantic_confidence=None,confidence_scope='uncalibrated_pdf_literal_review_ceiling')
            new['evidence'].update(source='visible_pdf_text',coordinate_space='original_pdf_raster',
                source_confidence=1.0,method='pdf_text_missing_literal',
                parser_method=candidate['evidence'].get('method'))
            if preprocessing:
                evidence=new['evidence'];page=evidence['page']
                matrix=np.linalg.inv(np.asarray(preprocessing[page]['rectified_to_input'],dtype=float))
                x1,y1,x2,y2=evidence['bbox']
                corners=np.array([[x1,y1,1],[x2,y1,1],[x2,y2,1],[x1,y2,1]])@matrix.T
                if not np.isfinite(corners).all() or np.any(np.abs(corners[:,2])<1e-8):
                    return finish('invalid_native_geometry_raster_ocr_retained')
                points=corners[:,:2]/corners[:,2:]
                evidence['source_bbox']=evidence['bbox']
                evidence['bbox']=[float(points[:,0].min()),float(points[:,1].min()),
                                  float(points[:,0].max()),float(points[:,1].max())]
                evidence['coordinate_space']='rectified_page_pixels'
                evidence['parts_coordinate_space']='original_pdf_raster'
            new.setdefault('validation',[]).append({'rule':'pdf_literal_requires_review',
                'reason':'Текст прочитан из PDF; смысл поля и соответствие изображению требуют проверки.'})
            additions[key]=new
        # Commit only after all parsing succeeds. Errors leave existing fields intact.
        fields.update(additions)
        report['changes']=[{'field':key,'status':'uncertain','source_confidence':f['source_confidence'],
                           'semantic_confidence':None} for key,f in additions.items()]
        report['applied']=bool(additions)
        return finish('missing_literals_added' if additions else 'no_safe_missing_candidate')
    except Exception as exc:
        report['error_type']=type(exc).__name__
        return finish('native_error_raster_ocr_retained')

import os
import json
import hashlib
import time
from functools import lru_cache
from pathlib import Path
import numpy as np
from .io import prepare

@lru_cache(maxsize=4)
def fingerprint(path,mtime):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def selection_state():
    from .schema import ROOT
    selection=ROOT/"models"/"ocr_selection.json";weights=ROOT/"models"/"ocr_cyrillic.pt"
    selected=json.loads(selection.read_text(encoding="utf-8")) if selection.exists() else {}
    if selected.get("enabled") and (not weights.exists() or selected.get("sha256")!=fingerprint(str(weights),weights.stat().st_mtime)):
        selected={"enabled":False,"reason":"Weights changed; rerun model selection"}
    return selected

def get_reader(gpu=True,finetuned=True,detector=True):
    from .schema import ROOT
    weights=ROOT/"models"/"ocr_cyrillic.pt"
    if isinstance(finetuned, Path):
        return _get_reader(gpu, str(finetuned), finetuned.stat().st_mtime, detector)
    selected=selection_state()
    approved=selected.get("enabled") is True and selected.get("mode","global")=="global"
    use_weights=weights.exists() and (finetuned=="candidate" or (finetuned is True and approved))
    return _get_reader(gpu,str(weights) if use_weights else "",weights.stat().st_mtime if use_weights else 0, detector)

@lru_cache(maxsize=6)
def _get_reader(gpu,weights_path,mtime,detector=True):
    import torch
    import easyocr
    storage = Path(os.environ.get("DEKANAT_CACHE", "models")) / "easyocr"
    storage.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(min(6, os.cpu_count() or 2))
    reader=easyocr.Reader(["ru", "en"], gpu=gpu and torch.cuda.is_available(),
                         model_storage_directory=str(storage), verbose=False, detector=detector,
                         quantize=False)  # Fine-tuned dense checkpoints require ordinary Linear weights on CPU.
    if weights_path:
        checkpoint=torch.load(weights_path,map_location="cpu",weights_only=True)
        if checkpoint["character"]!=reader.character:
            extend_alphabet(reader, checkpoint["character"])
        model=getattr(reader.recognizer,"module",reader.recognizer)
        model.load_state_dict(checkpoint["state_dict"])
    return reader


def extend_alphabet(reader, character):
    """Only append guillemets, keeping every existing CTC token id unchanged."""
    import torch
    from easyocr.utils import CTCLabelConverter
    if character != reader.character+"«»":
        raise RuntimeError("Алфавит OCR весов не соответствует установленной версии EasyOCR.")
    model = getattr(reader.recognizer, "module", reader.recognizer)
    old = model.Prediction
    new = torch.nn.Linear(old.in_features, old.out_features+2).to(old.weight.device)
    with torch.no_grad():
        new.weight[:old.out_features].copy_(old.weight)
        new.bias[:old.out_features].copy_(old.bias)
    model.Prediction = new
    converter = CTCLabelConverter(character, reader.converter.separator_list)
    converter.dict_list = reader.converter.dict_list
    reader.character, reader.converter = character, converter
    reader.lang_char = "".join(dict.fromkeys(getattr(reader, "lang_char", character)+"«»"))


def quote_state():
    from .schema import ROOT
    selection = ROOT/"models/quote_selection.json"
    weights = ROOT/"models/ocr_quotes.pt"
    if not selection.exists() or not weights.exists():
        return None
    selected = json.loads(selection.read_text(encoding="utf-8"))
    parent = ROOT/"models/ocr_cyrillic.pt"
    parent_matches = parent.exists() and selected.get("base_sha256") == fingerprint(str(parent), parent.stat().st_mtime)
    if selected.get("enabled") is True and parent_matches and selected.get("sha256") == fingerprint(str(weights), weights.stat().st_mtime):
        return weights
    return None


def recover_quote_fields(pages, lines, fields, kind, gpu=True, weights=None):
    """Reread missing quoted study fields only; never replace existing values."""
    from .extraction import merge_rows, extract, normalize
    import re
    import cv2
    if kind == 'practice' and weights is not None:
        return recover_practice_quotes(pages,lines,fields,gpu,weights)
    if kind != "study" or weights is None:
        return {"attempts": 0, "accepted": []}
    missing = {key for key in ["university", "program"] if fields[key]["value"] is None}
    if not missing:
        return {"attempts": 0, "accepted": []}
    rows = merge_rows(lines)
    targets = set()
    header_context = {}
    for index, row in enumerate(rows):
        text = normalize(row["text"])
        if "university" in missing and re.search(r"университет|институт|академи",text):
            # A bare quoted name is usable only under an explicit education header.
            height=row['bbox'][3]-row['bbox'][1]
            for context in rows[:index]:
                if context['page']!=row['page'] or not re.fullmatch(r"высшего\s+образования",normalize(context['text'])):continue
                gap=row['bbox'][1]-context['bbox'][3]
                overlap=min(row['bbox'][2],context['bbox'][2])-max(row['bbox'][0],context['bbox'][0])
                minimum_width=min(row['bbox'][2]-row['bbox'][0],context['bbox'][2]-context['bbox'][0])
                if 0<=gap<2.5*height and overlap>=.5*minimum_width:
                    targets.add(index);header_context[index]=context;break
        if "university" in missing and re.match(r"(?:фг[бb][оo]у|фгаоу|г[бb][оo]у|[аa][нh][оo]|чоу)\s+[вb][оo]\b", text):
            targets.add(index)
        if "program" in missing and re.search(r"по направлению подготовки|по специальности|направления подготовки\s*\(специальности\)", text):
            targets.add(index)
            last = row
            for following_index in range(index+1, min(len(rows), index+3)):
                following = rows[following_index]
                height = last["bbox"][3]-last["bbox"][1]
                gap = following["bbox"][1]-last["bbox"][3]
                if following["page"] != row["page"] or not 0 <= gap < 2.5*height or abs(following["bbox"][0]-row["bbox"][0]) > 2*height:
                    break
                if re.match(r"обучается\s+[сc]|дата|предполагаемая|приказ|исполнитель|подпись|фио|форма обучения|период обучения", normalize(following["text"])):
                    break
                targets.add(following_index)
                last = following
    if not targets:
        return {"attempts": 0, "accepted": []}
    reader = get_reader(gpu, Path(weights), detector=False)
    updated = [dict(row) for row in rows]
    readings = []
    for index in sorted(targets):
        row = rows[index]
        x1, y1, x2, y2 = map(int, row["bbox"])
        page = np.asarray(pages[row["page"]])
        crop = page[max(0,y1-4):min(page.shape[0],y2+4), max(0,x1-4):min(page.shape[1],x2+4)]
        if crop.size == 0:
            continue
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
        result = reader.recognize(gray, decoder="greedy", batch_size=1, detail=1)
        if not result:
            continue
        _, text, confidence = result[0]
        updated[index] = {**row, "text": text, "confidence": min(float(confidence), row["confidence"]),
                          "baseline_text": row["text"], "recognizer": "guillemet_finetune"}
        readings.append(updated[index])
    recovered = extract(updated, kind)
    accepted = []
    if "university" in missing and recovered['university']['value'] is None:
        header_candidates=[]
        for index,context in header_context.items():
            row=updated[index]
            match=re.fullmatch(r'\s*[«»"]([^«»"]{5,180})[«»"]\s*',row['text'])
            confidence=min(row['confidence'],context['confidence'])
            if match and confidence>=.55 and re.search(r"университет|институт|академи",match[1],re.IGNORECASE):
                evidence={**row,'method':'guillemet_education_header','context':dict(context),
                          'parts':[dict(context),dict(row)],'confidence':confidence,
                          'text':context['text']+'\n'+row['text']}
                header_candidates.append({'value':match[1].strip(),'status':'found','confidence':confidence,'evidence':evidence})
        # Distinct header readings must not silently choose a university.
        if header_candidates and len({normalize(c['value']) for c in header_candidates})==1:
            recovered['university']=max(header_candidates,key=lambda c:c['confidence'])
    for key in missing:
        field = recovered[key]
        evidence = field.get("evidence") or {}
        if field["status"] == "found" and re.search(r"[«»][^«»]{3,180}[«»]", evidence.get("text", "")):
            fields[key] = field
            accepted.append(key)
    return {"attempts": len(targets), "accepted": sorted(accepted), "lines": readings,
            "weights_sha256": fingerprint(str(weights), Path(weights).stat().st_mtime),
            "scope": "Only missing quoted university/program fields; previous values and baseline OCR lines preserved"}


def recover_practice_quotes(pages,lines,fields,gpu,weights):
    """Reread only missing explicitly anchored practice names/grades."""
    from .extraction import merge_rows,extract
    import re
    import cv2
    missing={key for key in ['organization','grade'] if fields[key]['value'] is None}
    rows=merge_rows(lines);targets=[]
    for index,row in enumerate(rows):
        if ('organization' in missing and re.search(r'практику\s+в\s+(?:ООО|АО|ЗАО|ОАО)\b',row['text'])) or ('grade' in missing and re.search(r'заслуживает\s+оценки',row['text'],re.IGNORECASE)):
            targets.append(index)
    if not targets:return {'attempts':0,'accepted':[]}
    reader=get_reader(gpu,Path(weights),detector=False);updated=[dict(row) for row in rows];readings=[]
    for index in targets:
        row=rows[index];x1,y1,x2,y2=map(int,row['bbox']);page=np.asarray(pages[row['page']])
        crop=page[max(0,y1-4):min(page.shape[0],y2+4),max(0,x1-4):min(page.shape[1],x2+4)]
        if crop.size==0:continue
        prediction=reader.recognize(cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY),decoder='greedy',batch_size=1,detail=1)
        if not prediction:continue
        _,text,confidence=prediction[0]
        updated[index]={**row,'text':text,'confidence':min(float(confidence),row['confidence']),
                        'baseline_text':row['text'],'recognizer':'guillemet_finetune'}
        readings.append(updated[index])
    recovered=extract(updated,'practice');accepted=[]
    for key in missing:
        field=recovered[key];evidence=field.get('evidence') or {}
        if field['status'] in {'found','uncertain'} and field['value'] is not None and not field.get('conflict') and re.search(r'[«»"][^«»"]{3,120}[«»"]',evidence.get('text','')):
            fields[key]=field;accepted.append(key)
    return {'attempts':len(targets),'accepted':sorted(accepted),'lines':readings,
            'weights_sha256':fingerprint(str(weights),Path(weights).stat().st_mtime),
            'scope':'Missing explicitly quoted practice organization/grade only; weak readings remain uncertain, previous values preserved'}

def recognize(pages, gpu=True, retry=True,finetuned=True):
    reader = get_reader(gpu,finetuned)
    started = time.perf_counter()
    lines = []
    retry_count = 0
    for page_id, page in enumerate(pages):
        image, scale = prepare(page)
        output = reader.readtext(image, batch_size=8, paragraph=False, canvas_size=2000, min_size=5,
                                 decoder="greedy", workers=0)
        for polygon, value, confidence in output:
            points = np.asarray(polygon, dtype=float) / scale
            box = [float(points[:, 0].min()), float(points[:, 1].min()),
                   float(points[:, 0].max()), float(points[:, 1].max())]
            if len(value)==1 and value in "0123456789Ss":
                # Small '=' glyphs can be recognized as '5'. Verify two horizontal
                # connected strokes in the image; never remove a genuine digit blindly.
                import cv2
                ax,ay,bx,by=map(int,box)
                glyph=np.asarray(page)[max(0,ay):by,max(0,ax):bx]
                if glyph.size:
                    gray=cv2.cvtColor(glyph,cv2.COLOR_RGB2GRAY)
                    _,mask=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
                    count,_,stats,_=cv2.connectedComponentsWithStats(mask)
                    strokes=[s for s in stats[1:] if s[4]>=3]
                    if len(strokes)==2 and all(s[2]>=2*s[3] and s[2]>=glyph.shape[1]*.35 for s in strokes):
                        value="="
            lines.append({"text": value, "confidence": float(confidence),
                          "bbox": box, "page": page_id, "retried": False})
    result = {"lines": lines, "seconds": time.perf_counter()-started, "retries": retry_count}
    return refine_uncertain(pages, result, gpu, finetuned) if retry else result


def refine_uncertain(pages, ocr, gpu=True, finetuned=True):
    """Refine existing uncertain boxes once, after orientation is established.

    Preserve the old decoder, crop geometry and confidence acceptance rule.
    No text detection or full-page rereading is required.
    """
    uncertain = [line for line in ocr["lines"] if line["confidence"] < .55 and line["text"].strip()]
    if not uncertain:
        return ocr
    import cv2
    # Reuse the page Reader already loaded by recognize, including its cached
    # recognizer; constructing another Reader here would waste GPU memory.
    reader = get_reader(gpu, finetuned)
    started = time.perf_counter()
    for line in uncertain:
        x1, y1, x2, y2 = line["bbox"]
        crop = np.asarray(pages[line["page"]])[max(0,int(y1)-6):int(y2)+6,
                                               max(0,int(x1)-6):int(x2)+6]
        if not crop.size:
            continue
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        result = reader.recognize(crop, decoder="beamsearch", beamWidth=5, batch_size=1, detail=1)
        ocr["retries"] += 1
        if result and result[0][2] > line["confidence"] + .1:
            line.update(text=result[0][1], confidence=float(result[0][2]), retried=True)
    ocr["seconds"] += time.perf_counter()-started
    return ocr


def recover_course(pages,lines,gpu=True,finetuned=True):
    """Read a missing short numeric value immediately to the right of a course label.

    Require an actual tall ink component; empty/underlined placeholders are rejected.
    """
    import cv2
    import re
    slots=[]
    for line in lines:
        x1,y1,x2,y2=line['bbox'];height=y2-y1
        if re.fullmatch(r"курс(?: обучения)?\s*[:=]?",line['text'].strip().lower()):
            slots.append((line,int(x2)+2,int(x2)+182,[line]))
        elif re.fullmatch(r"от\s+студент(?:а|ки)(?:\(тки\))?",line['text'].strip(),re.IGNORECASE):
            # The empty slot is bounded by two explicit labels on the same baseline.
            labels=[p for p in lines if p['page']==line['page'] and re.fullmatch('курса',p['text'].strip(),re.IGNORECASE)
                    and 0<p['bbox'][0]-x2<5*height
                    and abs((p['bbox'][1]+p['bbox'][3]-y1-y2)/2)<.5*height]
            if len(labels)==1:slots.append((line,int(x2)+2,int(labels[0]['bbox'][0])-2,[line,labels[0]]))
    reader=None
    for line,left,right,context in slots:
        page=pages[line['page']];x1,y1,x2,y2=line['bbox'];height=y2-y1
        left=max(0,left);top=max(0,int(y1)-5)
        crop=np.asarray(page)[top:min(page.height,int(y2)+5),left:min(page.width,right)]
        if not crop.size:continue
        gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
        _,mask=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        if len(context)==2:
            # A filled digit can touch the long placeholder rule. Remove that
            # rule only for the ink-presence check, retaining original pixels for OCR.
            rule=cv2.morphologyEx(mask,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(8,int(2*height)),1)))
            mask=cv2.subtract(mask,rule)
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        components=[s for s in stats[1:] if s[3]>=height*.4 and s[2]>=2 and s[2]/s[3]<1.4 and s[4]>=6]
        if not components:continue
        sx=min(s[0] for s in components);sy=min(s[1] for s in components)
        ex=max(s[0]+s[2] for s in components);ey=max(s[1]+s[3] for s in components)
        glyph=gray[max(0,sy-3):min(gray.shape[0],ey+3),max(0,sx-3):min(gray.shape[1],ex+3)]
        glyph=cv2.copyMakeBorder(glyph,5,5,5,5,cv2.BORDER_CONSTANT,value=255)
        glyph=cv2.resize(glyph,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
        reader=get_reader(gpu,'candidate' if len(context)==2 else finetuned,detector=False)
        predictions=reader.recognize(glyph,allowlist="0123456789",detail=1,batch_size=1)
        minimum=.55 if len(context)==2 else .9
        if predictions and re.fullmatch(r"[1-9]",predictions[0][1]) and predictions[0][2]>=minimum:
            return {"text":predictions[0][1],"confidence":min(float(predictions[0][2]),*(p['confidence'] for p in context)),"bbox":[left+sx,top+sy,left+ex,top+ey],
                    "page":line["page"],"retried":True,"method":"numeric_region_recovery","context":context,
                    "requires_review":float(predictions[0][2])<.9}
    return None

def refine_numeric_fields(pages,fields,document_type,gpu=True):
    """Use the fine-tuned recognizer only for ambiguous number/date fields."""
    import cv2
    import re
    from .schema import ROOT
    from .extraction import extract
    allowed={"document_number","group","issue_date","start_date","end_date","application_date","study_period","practice_period"}
    attempts=0
    reader=None
    for key in allowed.intersection(fields):
        field=fields[key];value=field["value"];evidence=field.get("evidence")
        if not isinstance(value,str) or not evidence:continue
        ambiguous=bool(re.search(r"(?:\d[ОOЗз]|[ОOЗз]\d)",value))
        if not ambiguous and field["confidence"]>=.7:continue
        if reader is None:reader=get_reader(gpu,"candidate",detector=False)
        page=pages[evidence["page"]];x1,y1,x2,y2=evidence["bbox"]
        box=[max(0,int(x1)-5),max(0,int(y1)-5),min(page.width,int(x2)+5),min(page.height,int(y2)+5)]
        crop=np.asarray(page)[box[1]:box[3],box[0]:box[2]]
        if not crop.size:continue
        gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
        predictions=reader.recognize(gray,detail=1,batch_size=1)
        attempts+=1
        if not predictions:continue
        _,text,confidence=predictions[0]
        row={"text":text,"confidence":float(confidence),"bbox":box,"page":evidence["page"]}
        candidate=extract([row],document_type,ROOT/"models"/"fields.joblib")[key]
        if candidate["status"]=="found":
            candidate["evidence"]["method"]="finetuned_numeric_region"
            candidate["evidence"]["baseline_value"]=value
            fields[key]=candidate
    return attempts


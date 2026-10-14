import re
import unicodedata
from functools import lru_cache
from pathlib import Path
import joblib
from .schema import SCHEMAS

def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).lower().replace("ё", "е")).strip()

def alias_pattern(alias):
    """Tolerate a spaced OCR dash between explicit label words, not value text."""
    return r"\s+(?:[-–—]\s+)?".join(re.escape(word) for word in alias.split())

def canonical_value(key,value):
    lookalikes=str.maketrans("aceopxyABCEHKMOPTXY", "асеорхуАВСЕНКМОРТХУ")
    def fix_word(match):
        word=match.group()
        if re.search(r"[А-Яа-яЁё]",word): return word.translate(lookalikes)
        return word
    value=re.sub(r"[A-Za-zА-Яа-яЁё]+",fix_word,value)
    if key == "university":
        value=re.sub(r'(\bимени\s+[А-ЯЁ][а-яё]+\s+)([А-ЯЁ])([А-ЯЁ])(?=\s|$)',r'\1\2.\3.',value)
        match = re.match(r"^(ФГ[БB][ОO]У|ФГАОУ|Г[БB][ОO]У|[АA][НH][ОO]|ЧОУ)\s+[ВB][ОO]\b", value)
        if match:
            prefix = match.group(1).translate(lookalikes)
            value = prefix+" ВО"+value[match.end():]
        markers = [m.start() for m in re.finditer("[«»]", value)]
        if len(markers) == 2:
            value = value[:markers[0]]+"«"+value[markers[0]+1:markers[1]]+"»"+value[markers[1]+1:]
    value=re.sub(r"(?<=[а-яё])(\s+)c(\s+)(?=[а-яё])",r"\1с\2",value,flags=re.IGNORECASE)
    if key == "study_form":
        match=re.match(r"^(очно-заочная|очная|заочная)[.;]?\s+(?:Нормативный\b|Обучение\b)",value,re.IGNORECASE)
        if match:value=match[1]
    if key == "grade":
        match=re.match(r"^(неудовлетворительно|удовлетворительно|отлично|хорошо|незачтено|зачтено)\s+Подробная\s+характеристика\b",value,re.IGNORECASE)
        if match:value=match[1]
    if key == 'supervisor':value=value.strip(' ;,.')
    # Restore an unambiguous range separator only when exactly two dates are read.
    if key in {"study_period","practice_period"}:
        dates=re.findall(r"\d{1,2}[.]\d{1,2}[.]\d{4}",value)
        if len(dates)==2 and not re.sub(r"\d{1,2}[.]\d{1,2}[.]\d{4}|[\s\-—–]", "", value):
            return dates[0]+" - "+dates[1]
    return value


def same_supervisor(full, abbreviated):
    """Compare explicit surname and initials; never expand an unknown name."""
    words=str(full).split()
    if len(words)!=3 or not all(re.fullmatch(r"[А-ЯЁ][а-яё]+",w) for w in words):return False
    m=re.fullmatch(r"([А-ЯЁ])[. :]*([А-ЯЁ])[. :]*\s+([А-ЯЁ][а-яё]+)",str(abbreviated).strip())
    return bool(m and (m[1],m[2],m[3])==(words[1][0],words[2][0],words[0]))

@lru_cache(maxsize=4)
def load_field_model(path, mtime):
    return joblib.load(path)

def merge_rows(lines):
    """Merge horizontally adjacent OCR boxes, preserving page and source geometry."""
    rows = []
    for line in sorted(lines, key=lambda x: (x["page"], (x["bbox"][1]+x["bbox"][3])/2)):
        x1, y1, x2, y2 = line["bbox"]
        cy, height = (y1+y2)/2, y2-y1
        target = next((r for r in reversed(rows[-8:]) if r["page"] == line["page"]
                       and abs(r["cy"]-cy) < min(height, r["height"])*.45), None)
        if target is None:
            rows.append({"page": line["page"], "cy": cy, "height": height, "parts": [line]})
        else:
            target["parts"].append(line)
    result = []
    for row in rows:
        parts = sorted(row["parts"], key=lambda x: x["bbox"][0])
        groups=[]
        for part in parts:
            if not groups or part["bbox"][0]-groups[-1][-1]["bbox"][2]>2.5*row["height"]:
                groups.append([part])
            else:groups[-1].append(part)
        for group in groups:
            result.append({"text": " ".join(p["text"] for p in group), "page": row["page"],
                           "confidence": min(p["confidence"] for p in group),
                           "bbox": [min(p["bbox"][0] for p in group), min(p["bbox"][1] for p in group),
                                    max(p["bbox"][2] for p in group), max(p["bbox"][3] for p in group)]})
    return result


def labeled_segments(rows,document_type):
    aliases=sorted({a for aa in SCHEMAS[document_type]["fields"].values() for a in aa},key=len,reverse=True)
    pattern=r"(?<!\w)(?:"+"|".join(alias_pattern(a) for a in aliases)+r")\s*[:：=]"
    result=[]
    for row in rows:
        matches=list(re.finditer(pattern,row["text"],flags=re.IGNORECASE))
        if len(matches)>1 and matches[0].start()==0:
            for index,match in enumerate(matches):
                end=matches[index+1].start() if index+1<len(matches) else len(row["text"])
                result.append({**row,"text":row["text"][match.start():end].strip(" ;|"),"source_text":row["text"]})
        else:result.append(row)
    return result

def detect_type(lines):
    rows=merge_rows(lines)
    if any(re.match(r'^(?:положение(?:\s|$)|методические рекомендации\b|дневник прохождения практики\b)',normalize(r['text'])) and r['confidence']>=.55 for r in rows):
        return None
    if any(re.match(r'^отзыв\s+(?:пишется|составляется|оформляется)\b',normalize(r['text'])) and r['confidence']>=.55 for r in rows[:12]):
        return None
    titles=[r for r in rows if r['confidence']>=.55 and re.fullmatch(r'справка(?:\s+(?:об обучении|о периоде обучения|о прохождении практики))?',normalize(r['text']))]
    for index,title in enumerate(titles):
        for other in titles[index+1:]:
            height=max(title['bbox'][3]-title['bbox'][1],other['bbox'][3]-other['bbox'][1])
            if title['page']==other['page'] and abs(title['bbox'][1]-other['bbox'][1])>4*height:
                return None
    text = normalize(" ".join(x["text"] for x in lines))
    if re.search(r'\bпрошу\s+(?:выдать|выслать|оформить|подготовить)\b.{0,80}\bсправк',text):
        return None
    if re.search(r'\bпрошу\s+(?:считать|признать)\b.{0,70}\bвышедш[а-я]*\b.{0,30}\bотпуск',text):
        return None
    if re.search(r'академич[а-я]*\s+отпус[а-я]*',text) or "причина отпуска" in text:
        return "leave"
    if "справка" in text and re.search(r"является студент|действительно.*студент", text):
        return "study"
    if "практик" in text:
        return "practice"
    if "обучени" in text or "направление подготовки" in text:
        return "study"
    return None

def type_review_reason(lines,kind):
    """An OCR-corrupted type cue can route a document, but requires review."""
    text=normalize(' '.join(x['text'] for x in lines))
    if kind=='leave' and 'причина отпуска' not in text and not re.search(r'академическ[а-я]*\s+отпус[а-я]*',text):
        return 'Тип заявления определён по повреждённому OCR слову об отпуске; проверьте тип и извлечённые поля.'
    return None


def extract(lines, document_type, model_path=None, *, canonicalizer=None):
    canonical = canonicalizer or canonical_value
    rows = labeled_segments(merge_rows(lines),document_type)
    fields = {key: {"value": None, "status": "not_found", "confidence": 0,
                    "evidence": None} for key in SCHEMAS[document_type]["fields"]}
    model = None
    if model_path and Path(model_path).exists():
        model = load_field_model(str(model_path), Path(model_path).stat().st_mtime)
    for index, row in enumerate(rows):
        normalized = normalize(row["text"])
        matches = []
        for key, aliases in SCHEMAS[document_type]["fields"].items():
            for alias in aliases:
                alias_norm = normalize(alias)
                match = re.match(r"^"+alias_pattern(alias_norm)+r"(?=\s|[:：=\-—.]|$)", normalized)
                if match:
                    matches.append((len(alias_norm), key, len(match.group())))
        method, probability = "label", 1.0
        if matches:
            _, key, end = max(matches)
            # Find the alias in the original string: whitespace normalization changes
            # character offsets and must not truncate the beginning of a value.
            for alias in SCHEMAS[document_type]["fields"][key]:
                pattern=r"^\s*"+alias_pattern(alias)+r"(?=\s|[:：=\-—.]|$)"
                raw_match=re.match(pattern,row["text"],flags=re.IGNORECASE)
                if raw_match and len(normalize(raw_match.group()))==end:
                    end=raw_match.end();break
            value = row["text"][end:].strip(" :：=—–-.")
        elif model:
            prefix = re.split(r"[:：=]", row["text"], maxsplit=1)[0]
            probabilities = model.predict_proba([prefix])[0]
            best = int(probabilities.argmax())
            key = str(model.classes_[best])
            probability = float(probabilities[best])
            if key not in fields or probability < .65:
                continue
            if key == "program" and re.search(r"\b(?:направленность\s+программы|профиль)\s*[:=]", normalized):
                # A specialization/profile is distinct from the main degree program.
                continue
            method = "trained_classifier"
            pieces = re.split(r"[:：=]", row["text"], maxsplit=1)
            if len(pieces) != 2:
                continue
            value = pieces[1].strip()
        else:
            continue
        evidence = dict(row, method=method)
        def has_label(text):
            return any(re.match(r"^"+alias_pattern(normalize(a))+r"(?=\s|[:：=\-—.]|$)",normalize(text))
                       for aa in SCHEMAS[document_type]["fields"].values() for a in aa)
        if not value:
            # Associate an isolated label with a nearby same-line value without
            # merging an entire second column into the first field.
            height=row["bbox"][3]-row["bbox"][1]
            cy=(row["bbox"][1]+row["bbox"][3])/2
            right=[r for r in rows if r is not row and r["page"]==row["page"]
                   and 0<r["bbox"][0]-row["bbox"][2]<min(350,12*height)
                   and abs((r["bbox"][1]+r["bbox"][3])/2-cy)<height*.45]
            following=min(right,key=lambda r:r["bbox"][0]) if right else None
            if following and not has_label(following["text"]):
                value=following["text"];evidence=dict(following,method=method+"_right_value")
        if not value and index+1 < len(rows):
            height=row["bbox"][3]-row["bbox"][1]
            below=[r for r in rows if r is not row and r["page"]==row["page"]
                   and 0<=r["bbox"][1]-row["bbox"][3]<2*height
                   and abs(r["bbox"][0]-row["bbox"][0])<height*1.5]
            following=min(below,key=lambda r:r["bbox"][1]) if below else rows[index+1]
            same_page = following["page"] == row["page"]
            gap = following["bbox"][1]-row["bbox"][3]
            following_text = normalize(following["text"])
            is_label = any(following_text.startswith(normalize(a))
                           for aliases in SCHEMAS[document_type]["fields"].values() for a in aliases)
            if same_page and 0 <= gap < 2*(row["bbox"][3]-row["bbox"][1]) and not is_label:
                value, evidence = following["text"], dict(following, method=method+"_next_row")
        if not value or normalize(value) in {"не указано", "нет", "не найдено", "—"}:
            continue
        if key == "student_name" and re.match(r"(?:специалиста|исполнителя|ректора|декана|руководителя|сотрудника)\b", normalize(value)):
            continue
        if key == 'study_form' and re.match(r'^(?:справки|документа|отзыва|заявления)\b',normalize(value)):continue
        if key == 'supervisor' and re.fullmatch(r'(?:от|ot)\s+организации\s*\(?предприятия\)?',normalize(value)):continue
        if key == "issue_date" and re.match(r"^выдана\b", normalized) and not re.match(r"\d", value):
            # 'Справка выдана для представления' is not an issuance date.
            continue
        if key in {"issue_date","application_date","start_date","end_date"} and not re.search(r"\d",value):
            continue
        if key == "supervisor":
            if re.match(r"^[А-Яа-яЁё]+\s+отдела\b",value):continue
            from .narrative import NAME
            partial=re.fullmatch(r"от\s+("+NAME+r")",value)
            if partial:
                height=row['bbox'][3]-row['bbox'][1]
                continuation=[r for r in rows if r['page']==row['page'] and normalize(r['text'])=='организации'
                              and 0<=r['bbox'][1]-row['bbox'][3]<1.5*height and abs(r['bbox'][0]-row['bbox'][0])<height]
                if continuation:
                    value=partial[1]
                    part=continuation[0]
                    evidence={**evidence,'label_continuation':dict(part),'parts':[dict(row),dict(part)],
                              'text':row['text']+'\n'+part['text'],'confidence':min(row['confidence'],part['confidence']),
                              'bbox':[min(row['bbox'][0],part['bbox'][0]),min(row['bbox'][1],part['bbox'][1]),
                                      max(row['bbox'][2],part['bbox'][2]),max(row['bbox'][3],part['bbox'][3])],
                              'method':method+'_wrapped_supervisor_label'}
        if key in {"study_period", "practice_period"}:
            period=re.match(r"^(\d{1,2}\.\d{1,2}\.\d{4})\s*(?:[-–—]|по)?\s+(\d{1,2}\.\d{1,2}\.\d{4})(?=[\s.;]|$)",value)
            if period:value=period[1]+" - "+period[2]
        if re.fullmatch(r"[_\s.]+(?:\([^)]{0,80}\))?",value) or not re.search(r"[^\W_]",value):
            continue
        if key in {"university","organization","program","reason"}:
            parts=[dict(evidence)];last=evidence
            bounded_program=False
            if key == "program" and re.match(r"^\d{2}\.\d{2}\.\d{2}\s+\S",value):
                height=last['bbox'][3]-last['bbox'][1]
                nearby=[r for r in rows if r is not row and r['page']==row['page']
                        and -.35*height<=r['bbox'][1]-last['bbox'][3]<.9*height
                        and abs(r['bbox'][0]-last['bbox'][0])<2*height]
                if nearby:
                    continuation=min(nearby,key=lambda r:r['bbox'][1])
                    boundary=re.match(r"^([А-Яа-яЁё][А-Яа-яЁё\s-]{0,100}?)\s+(?:Направленность\s+программы|профиль)\s*[:=]",continuation['text'],re.IGNORECASE)
                    if boundary:
                        value+=' '+boundary[1].strip();parts.append(dict(continuation));last=continuation
                        bounded_program=True
            for _ in range(0 if bounded_program else 2):
                height=last["bbox"][3]-last["bbox"][1]
                below=[r for r in rows if r["page"]==row["page"]
                       and 0<=r["bbox"][1]-last["bbox"][3]<height*.9
                       and abs(r["bbox"][0]-last["bbox"][0])<height*1.5]
                if not below:break
                following=min(below,key=lambda r:r["bbox"][1])
                gap=following["bbox"][1]-last["bbox"][3]
                height=last["bbox"][3]-last["bbox"][1]
                if following["page"]!=row["page"] or not 0<=gap<height*.9 or has_label(following["text"]):break
                if abs(following["bbox"][0]-last["bbox"][0])>height*1.5:break
                if re.search(r"подпись|м\.п\.|учебный образец",normalize(following["text"])):break
                if re.match(r"(?:прош[её]л|прошла|проходил[а]?|дана|прошу|обучается|дата начала|предполагаемая дата окончания)\b",normalize(following["text"])):break
                value+=" "+following["text"];parts.append(dict(following));last=following
            if len(parts)>1:
                evidence={**evidence,"text":"\n".join(p['text'] for p in parts) if bounded_program else value,"method":method+("_wrapped_program_boundary" if bounded_program else "_wrapped"),"parts":parts,
                          "confidence":min(p["confidence"] for p in parts),
                          "bbox":[min(p["bbox"][0] for p in parts),min(p["bbox"][1] for p in parts),
                                  max(p["bbox"][2] for p in parts),max(p["bbox"][3] for p in parts)]}
        value=canonical(key,value)
        confidence = min(row["confidence"], evidence["confidence"], probability)
        existing = fields[key]
        if existing["status"]=="conflict" and normalize(existing["value"])==normalize(value):continue
        if existing["value"] is not None and normalize(existing["value"]) != normalize(value):
            if key=='supervisor' and same_supervisor(existing['value'],value):
                existing.setdefault('corroborating_evidence',[]).append(evidence)
                continue
            existing["status"] = "conflict"
            existing.setdefault("alternatives", []).append({"value": value, "evidence": evidence})
            continue
        fields[key] = {"value": value, "status": "found" if confidence >= .55 else "uncertain",
                       "confidence": confidence, "evidence": evidence}
    from .narrative import candidates
    from .official_patterns import candidates as official_candidates
    merged=merge_rows(lines)
    for candidate in [*candidates(merged, document_type),*official_candidates(merged,document_type)]:
        key = candidate["key"]
        value = canonical(key, candidate["value"])
        evidence = candidate["evidence"]
        confidence = evidence["confidence"]
        existing = fields[key]
        if existing["value"] is None:
            fields[key] = {"value": value, "status": "found" if confidence >= .55 else "uncertain",
                           "confidence": confidence, "evidence": evidence}
        elif normalize(existing["value"]) != normalize(value):
            existing["status"] = "conflict"
            alternatives = existing.setdefault("alternatives", [])
            if not any(normalize(a["value"]) == normalize(value) for a in alternatives):
                alternatives.append({"value": value, "evidence": evidence})
    return fields


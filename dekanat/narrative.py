"""Conservative, evidence-backed extraction from common certificate sentences."""
import re
from datetime import datetime

DATE = r"\d{1,2}\.\d{1,2}\.\d{4}"
NUMBER_SIGN = r"(?:№|N[gGoOº°])"
NAME = r"[А-ЯЁ][а-яё]+(?:[-‑][А-ЯЁа-яё]+)?(?:\s+[А-ЯЁ][а-яё]+(?:[-‑][А-ЯЁа-яё]+)?){2}"


def windows(rows, relaxed=False):
    """Bounded same-column paragraph windows; never concatenate across pages."""
    ordered = sorted(rows, key=lambda r: (r["page"], r["bbox"][1], r["bbox"][0]))
    for start, first in enumerate(ordered):
        parts = [first]
        yield parts
        for following in ordered[start+1:start+5]:
            last = parts[-1]
            height = max(last["bbox"][3]-last["bbox"][1], following["bbox"][3]-following["bbox"][1])
            gap = following["bbox"][1]-last["bbox"][3]
            if following["page"] != first["page"] or not (-.35*height if relaxed else 0) <= gap < 2.5*height:
                break
            if abs(following["bbox"][0]-first["bbox"][0]) > (3 if relaxed else 2)*height:
                break
            parts = [*parts, following]
            yield parts


def candidates(rows, kind):
    results, seen = [], set()

    def emit(key, value, parts, text, start, end, rule):
        value = re.sub(r"\s+", " ", value).strip(" \n\t.;")
        if not value or "_" in value:
            return
        identity = (key, value, parts[0]["page"], tuple(tuple(p["bbox"]) for p in parts))
        if identity in seen:
            return
        seen.add(identity)
        results.append({"key": key, "value": value, "evidence": {
            "text": text, "source_text": text, "value_span": [start, end], "rule": rule,
            "method": "narrative_pattern", "page": parts[0]["page"],
            "confidence": min(p["confidence"] for p in parts), "parts": [dict(p) for p in parts],
            "bbox": [min(p["bbox"][0] for p in parts), min(p["bbox"][1] for p in parts),
                     max(p["bbox"][2] for p in parts), max(p["bbox"][3] for p in parts)]}})

    def find(pattern, text, parts, key, rule, flags=re.IGNORECASE):
        for match in re.finditer(pattern, text, flags):
            start, end = match.span("value")
            # Retain only the OCR rows supporting the matched sentence, not the
            # unused context window. Spans refer to the joined evidence text.
            positions, cursor = [], 0
            for part in parts:
                positions.append((cursor, cursor+len(part["text"]), part))
                cursor += len(part["text"])+1
            selected = [(a, b, p) for a, b, p in positions if a < match.end() and b > match.start()]
            offset = selected[0][0]
            supporting = [p for _, _, p in selected]
            evidence_text = "\n".join(p["text"] for p in supporting)
            emit(key, match.group("value"), supporting, evidence_text, start-offset, end-offset, rule)

    for parts in windows(rows):
        text = "\n".join(p["text"] for p in parts)
        if kind in {"study", "practice"}:
            find(r"(?:^|\n)(?:Исх[.:]?|Исходящий)\s*"+r"(?:№|N[gGoOº°]?)"+r"\s*(?P<value>[А-Яа-яЁёA-Za-z0-9/\-]+)(?:\s+от\s+"+DATE+r")?\s*(?:$|\n)",
                 text, parts, "document_number", "outgoing_header_number")
            find(r"(?:^|\n)(?:Исх[.:]?|Исходящий)\s*(?:№|N[gGoOº°]?)\s*[А-Яа-яЁёA-Za-z0-9/\-]+\s+от\s+(?P<value>"+DATE+r")\s*(?:$|\n)",
                 text, parts, "issue_date", "outgoing_header_date")
            find(r"\bсправка\s*"+NUMBER_SIGN+r"\s*(?P<value>[А-Яа-яЁёA-Za-z0-9][А-Яа-яЁёA-Za-z0-9/\-]*)\s+от\s+"+DATE,
                 text, parts, "document_number", "certificate_number_date")
            find(r"\bсправка\s*"+NUMBER_SIGN+r"\s*[А-Яа-яЁёA-Za-z0-9/\-]+\s+от\s+(?P<value>"+DATE+r")\b",
                 text, parts, "issue_date", "certificate_number_date")
            find(r"(?:^|\n)(?P<value>"+DATE+r")\s*(?:г\.)?\s*"+NUMBER_SIGN+r"\s*[А-Яа-яЁёA-Za-z0-9/\-]+\s*(?:$|\n)",
                 text, parts, "issue_date", "certificate_date_number")
            find(r"(?:^|\n)"+DATE+r"\s*(?:г\.)?\s*"+NUMBER_SIGN+r"\s*(?P<value>[А-Яа-яЁёA-Za-z0-9/\-]+)\s*(?:$|\n)",
                 text, parts, "document_number", "certificate_date_number")
        if kind == "study":
            find(r"(?i:\bдана\s+)(?P<value>"+NAME+r")(?i:\s+[вb]\s+[тt][оo][мm][,.:;]?\s+ч[тt][оo])",
                 text, parts, "student_name", "certificate_recipient", flags=0)
            find(r"\bстудент(?:ом|кой|ом\(кой\))?\s+(?:\d+\s+курса\s+)?(?P<value>очно-заочной|очной|заочной)\s+формы\s+обучения",
                 text, parts, "study_form", "student_study_form")
            find(r"(?:^|\n)(?P<value>(?:ФГ[БB][ОO]У|ФГАОУ|Г[БB][ОO]У|[АA][НH][ОO]|ЧОУ)\s+[ВB][ОO]\s*[«»\"][^«»\"]{5,180}[«»\"])(?:[.,\s]|$)",
                 text, parts, "university", "institution_legal_name")
            find(r"\b(?:по\s+(?:специальности/направлению|направлению\s+подготовки|специальности)|направления\s+подготовки\s*\(специальности\))\s+[«»\"](?P<value>[^«»\"]{3,140})[«»\"]",
                 text, parts, "program", "quoted_study_program")
            find(r"\bобучается\s+[сc]\s+(?P<value>"+DATE+r"\s+по\s+"+DATE+r")\b",
                 text, parts, "study_period", "explicit_study_date_range")
            # Separate explicitly labelled dates can safely form a period. Do
            # not infer dates from duration, admission order or course number.
            for match in re.finditer(r"\bдата\s+начала\s+обучения(?:\s+в\s+университете)?\s*[:—-]?\s*(?P<start>"+DATE+r")\s*[.;]?\s*(?:предполагаемая\s+)?дата\s+окончания(?:\s+обучения)?(?:\s+в\s+университете)?\s*[:—-]?\s*(?P<end>"+DATE+r")", text, re.IGNORECASE):
                emit("study_period", match.group("start")+" - "+match.group("end"), parts, text,
                     match.start("start"), match.end("end"), "explicit_study_start_end")
        if kind == "leave":
            find(r"\bакадемический\s+отпуск\s+[сc]\s+(?P<value>"+DATE+r")\s+по\s+"+DATE,
                 text, parts, "start_date", "requested_leave_period")
            find(r"\bакадемический\s+отпуск\s+[сc]\s+"+DATE+r"\s+по\s+(?P<value>"+DATE+r")",
                 text, parts, "end_date", "requested_leave_period")
            from .official_patterns import LEAVE_BEFORE_PERIOD
            if not re.search(DATE+r"\s+по\s+"+DATE+r"\s+по\s+(?:семейным\s+обстоятельствам|состоянию\s+здоровья)",text,re.IGNORECASE) and not re.search(LEAVE_BEFORE_PERIOD,text,re.IGNORECASE):
                find(r"\b(?:прошу\s+предоставить\s+(?:мне\s+)?академический\s+отпуск)[\s\S]{0,120}?\s+в\s+связи\s+[сc]\s+(?P<value>[^.\n]{3,100})(?:\.|$)",
                     text, parts, "reason", "requested_leave_reason")
        if kind == "practice":
            find(r"\b(?:проходил[а]?|прош[её]л|прошла)\s+(?:учебную\s+|производственную\s+)?практику\s+(?:[сc]\s+)?(?P<value>"+DATE+r"\s+по\s+"+DATE+r")",
                 text, parts, "practice_period", "explicit_practice_period")
    # Additional patterns require an explicit semantic anchor. Relaxed windows
    # tolerate first-line indentation and slightly overlapping OCR row boxes.
    for parts in windows(rows, relaxed=True):
        text = "\n".join(p["text"] for p in parts)
        if kind == "study":
            find(r"\bнормативный\s+период\s+обучения\s*[:=]\s*(?P<value>"+DATE+r"\s*(?:[-–—]|по)?\s+"+DATE+r")(?=[\s.;]|$)",
                 text, parts, "study_period", "explicit_normative_study_period")
            find(r"\bобучается\s+по\s+образовательной\s+программе\s+(?:бакалавриата|магистратуры|специалитета)\s+(?P<value>\d{2}\.\d{2}\.\d{2}\s+[А-Яа-яЁё][^;\n]{1,100}(?:\n[^;\n]{1,100})?)\s*;\s*профиль\b",
                 text, parts, "program", "educational_program_before_profile")
            find(r"\bформа\s+обучения\s*[:=]?\s*(?P<value>очно-заочная|очная|заочная)(?=\s+Обучение\b|[.;]|$)",
                 text, parts, "study_form", "explicit_inline_study_form")
            find(r"(?:^|\n)(?P<value>"+NAME+r")(?i:\s+является\s+студент(?:ом|кой)\b)",
                 text, parts, "student_name", "named_student_subject", flags=0)
            find(r"(?i:настоящим\s+подтверждается[;,:]?\s+что\s+)(?P<value>"+NAME+r")(?i:\s+обучается\b)",
                 text, parts, "student_name", "confirmed_student_subject", flags=0)
        if kind == "practice":
            find(r"(?i:подтверждаем[;,:]?\s+что\s+)(?P<value>"+NAME+r")(?i:[;,]?\s+студент(?:ка)?\b)",
                 text, parts, "student_name", "confirmed_practice_student", flags=0)
            find(r"(?:^|\n)(?P<value>"+NAME+r")(?i:[;,]?\s+студент(?:ка)?\s+[\s\S]{0,150}?проходил[а]?\s+(?:производственную\s+)?(?:преддипломную\s+)?практику)",
                 text, parts, "student_name", "practice_student_subject", flags=0)
            find(r"\b(?:проходил[а]?|прош[её]л|прошла)\s+(?:производственную\s+)?(?:преддипломную\s+)?практику\s+[\s\S]{0,100}?\s+[сc]\s+(?P<value>"+DATE+r"\s+по\s+"+DATE+r")",
                 text, parts, "practice_period", "practice_period_after_organization")
        if kind == "leave":
            find(r"\bот\s+студент(?:а|ки)\s+(?P<value>\d{1,2})\s+курса\b", text, parts,
                 "course", "applicant_course")
            request = r"\bпрошу\s+предоставить\s+(?:мне\s+)?академический\s+отпуск\s+(?:[сc]\s+)?"
            find(request+r"(?P<value>"+DATE+r")\s+по\s+"+DATE, text, parts, "start_date", "explicit_leave_request_start")
            find(request+DATE+r"\s+по\s+(?P<value>"+DATE+r")", text, parts, "end_date", "explicit_leave_request_end")
            find(request+DATE+r"\s+по\s+"+DATE+r"\s+(?P<value>по\s+(?:семейным\s+обстоятельствам|состоянию\s+здоровья)(?:\s+в\s+связи\s+[сc]\s+[^.\n]*(?:\n(?!Подтверждающие|Приложение)[^.\n]*)?)?)[.:]",
                 text, parts, "reason", "explicit_leave_request_reason")
            # The applicant's printed signature expansion may be horizontally
            # displaced. Search only a short region after the explicit label.
            if len(parts) == 1 and re.fullmatch(r"Заявитель", parts[0]["text"], re.IGNORECASE):
                first=parts[0];height=first["bbox"][3]-first["bbox"][1]
                nearby=[r for r in rows if r["page"]==first["page"] and 0<=r["bbox"][1]-first["bbox"][3]<4*height and re.fullmatch(NAME,r["text"])]
                if len(nearby)==1:
                    name=nearby[0];joined=first["text"]+"\n"+name["text"]
                    emit("student_name",name["text"],[first,name],joined,len(first["text"])+1,len(joined),"applicant_signature_expansion")
    # A model can emit impossible dates. Keep those out of this conservative
    # fallback; the original OCR remains available for review.
    valid = []
    for candidate in results:
        dates = re.findall(DATE, candidate["value"])
        try:
            for date in dates:
                datetime.strptime(date, "%d.%m.%Y")
        except ValueError:
            continue
        if candidate["key"] == "university" and not re.search(r"университет|институт|академи", candidate["value"], re.IGNORECASE):
            continue
        if candidate["key"] == "study_form":
            candidate["value"] = {"очной": "очная", "заочной": "заочная", "очно-заочной": "очно-заочная"}.get(candidate["value"].lower(),candidate["value"].lower())
        if candidate["key"] in {"study_period", "practice_period"} and len(dates) == 2:
            candidate["value"] = dates[0]+" - "+dates[1]
        valid.append(candidate)
    return valid

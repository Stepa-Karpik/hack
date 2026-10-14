import re
from datetime import datetime
from .schema import LABELS, SCHEMAS, validate_policy, policy_question_key
from .extraction import normalize

def parse_date(value):
    match = re.fullmatch(r"\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*", value or "")
    if not match:
        return None
    try:
        return datetime(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        return None

def answer(question, document_type, fields, policy):
    validate_policy(policy)
    q = normalize(question)
    applicable = [r for r in policy["rules"] if document_type in r.get("types", [])]
    if not q:
        return {"status": "no_answer", "answer": "Введите вопрос.", "sources": []}
    for rule in applicable:
        if policy_question_key(question) in [policy_question_key(x) for x in rule.get("questions", [])]:
            return {"status": "answered", "answer": rule["text"],
                    "sources": [{"kind": "policy", "id": rule["id"], "text": rule["text"]}]}
    unknown_topics = ["стоимост", "оплат", "стипенди", "второй курс", "2 курс", "второго курса", "срок рассмотрения"]
    compliance = any(word in q for word in ["подход", "достаточ", "хватит", "порядк", "принять", "принима", "не хватает", "провер", "все поля", "все ли", "есть в документе", "соответств", "комплект"])
    # Eligibility to transfer is not inferred from mere document completeness.
    if any(word in q for word in unknown_topics):
        return {"status": "no_answer", "answer": "В доступном Положении нет правила, позволяющего ответить на этот вопрос. Обратитесь в деканат.", "sources": []}
    if not compliance:
        if any(word in q for word in ["нужн", "обязательн", "требован", "требует", "требуются"]):
            rules=[r for r in applicable if "required" in r]
            if rules:
                return {"status":"answered","answer":" ".join(r["text"] for r in rules),
                        "sources":[{"kind":"policy","id":r["id"],"text":r["text"]} for r in rules]}
        for key,words in {"signature":["подпис", "подпись"],"stamp":["печат"]}.items():
            if key in fields and any(word in q for word in words):
                f=fields[key]
                if f["status"]!="found":
                    return {"status":"insufficient","answer":f"Поле «{LABELS[key]}» не подтверждено уверенно. Нужна проверка изображения.","sources":[]}
                return {"status":"answered","answer":f"{LABELS[key]} обнаружена на изображении. Подлинность не проверяется.",
                        "sources":[{"kind":"field","id":key,"evidence":f["evidence"]}]}
        for key, aliases in SCHEMAS[document_type]["fields"].items():
            if any(normalize(a) in q for a in aliases) or (key == "student_name" and "кому" in q):
                field = fields[key]
                if field["status"] != "found":
                    return {"status": "insufficient", "answer": f"Поле «{LABELS[key]}» не найдено или не прочитано уверенно.", "sources": []}
                return {"status": "answered", "answer": f"{LABELS[key]}: {field['value']}.", "sources": [{"kind": "field", "id": key, "evidence": field["evidence"]}]}
        required_query = any(x in q for x in ["требован", "обязательн", "какие документы", "какие поля"])
        if required_query:
            rules = [r for r in applicable if "required" in r]
            if not rules:
                return {"status": "no_answer", "answer": "В Положении нет требований к этому типу документа.", "sources": []}
            return {"status": "answered", "answer": " ".join(r["text"] for r in rules),
                    "sources": [{"kind": "policy", "id": r["id"], "text": r["text"]} for r in rules]}
        return {"status": "no_answer", "answer": "В документе и доступном Положении не найдено подтверждённого ответа. Обратитесь в деканат.", "sources": []}
    required_rules = [r for r in applicable if "required" in r]
    if not required_rules:
        return {"status": "no_answer", "answer": "В Положении нет требований к этому типу документа.", "sources": []}
    required = list(dict.fromkeys(k for r in required_rules for k in r["required"]))
    missing, uncertain = [], []
    for key in required:
        f = fields.get(key, {})
        if f.get("status") == "not_found" or (f.get("status") == "found" and f.get("value") is False):
            missing.append(LABELS.get(key, key))
        elif f.get("status") != "found":
            uncertain.append(LABELS.get(key, key))
    problems = []
    used_rules = list(required_rules)
    for rule in applicable:
        if "date_order" in rule:
            first, second = [fields.get(k, {}) for k in rule["date_order"]]
            d1, d2 = parse_date(first.get("value")), parse_date(second.get("value"))
            if first.get("status") == second.get("status") == "found":
                used_rules.append(rule)
                if not d1 or not d2:
                    uncertain.append("Формат или корректность дат отпуска")
                elif d2 < d1:
                    problems.append("Дата окончания отпуска раньше даты начала")
    sources = [{"kind": "policy", "id": r["id"], "text": r["text"]} for r in used_rules]
    if missing or uncertain or problems:
        parts = []
        if missing: parts.append("Не найдены обязательные сведения: "+", ".join(missing)+".")
        if uncertain: parts.append("Нужна проверка: "+", ".join(uncertain)+".")
        if problems: parts.append("; ".join(problems)+".")
        parts.append("Основание: "+", ".join("п. "+r["id"] for r in used_rules)+". Окончательное решение примет сотрудник деканата.")
        return {"status": "insufficient", "answer": " ".join(parts), "sources": sources}
    return {"status": "complete", "answer": "Документ содержит все сведения, обязательные по "+", ".join("п. "+r["id"] for r in used_rules)+". Окончательное решение примет сотрудник деканата.", "sources": sources}


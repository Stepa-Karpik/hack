from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

SCHEMAS = {
    "study": {"title": "Справка об обучении", "fields": {
        "student_name": ["ФИО студента", "ФИО", "Студент", "Обучающийся"],
        "university": ["Название вуза", "Учебное заведение", "Вуз", "Университет"],
        "program": ["Направление подготовки", "Направление", "Специальность"],
        "study_form": ["Форма обучения", "Форма"],
        "study_period": ["Период обучения", "Срок обучения"],
        "document_number": ["Номер документа", "Номер справки", "Регистрационный номер", "Номер"],
        "issue_date": ["Дата выдачи", "Выдана", "Дата оформления"],
    }, "visual": ["signature", "stamp"]},
    "leave": {"title": "Заявление на академический отпуск", "fields": {
        "student_name": ["ФИО студента", "ФИО", "Студент", "Обучающийся"],
        "group": ["Учебная группа", "Группа"],
        "course": ["Курс обучения", "Курс"],
        "reason": ["Причина отпуска", "Причина", "Основание отпуска"],
        "start_date": ["Дата начала отпуска", "Начало отпуска", "Отпуск с"],
        "end_date": ["Дата окончания отпуска", "Окончание отпуска", "Отпуск до"],
        "application_date": ["Дата заявления", "Дата подачи заявления", "Дата подачи"],
    }, "visual": ["signature"]},
    "practice": {"title": "Справка о практике", "fields": {
        "student_name": ["ФИО студента", "ФИО", "Студент", "Обучающийся"],
        "organization": ["Организация практики", "Организация", "Место практики"],
        "practice_period": ["Сроки практики", "Период практики"],
        "supervisor": ["Руководитель практики от организации", "Руководитель практики", "Руководитель"],
        "grade": ["Итоговая оценка за практику", "Оценка за практику", "Оценка", "Результат практики"],
        "document_number": ["Номер документа", "Номер справки", "Регистрационный номер", "Номер"],
        "issue_date": ["Дата выдачи", "Выдана", "Дата оформления"],
    }, "visual": ["signature", "stamp"]},
}
LABELS = {k: aliases[0] for s in SCHEMAS.values() for k, aliases in s["fields"].items()}
LABELS.update(signature="Подпись", stamp="Печать")

def validate_policy(policy):
    """Validate executable policy rules before they can affect an answer."""
    def fail(message):
        raise ValueError("Положение: " + message)

    if not isinstance(policy, dict):
        fail("ожидается объект JSON")
    for key in ("title", "provenance"):
        if not isinstance(policy.get(key), str) or not policy[key].strip():
            fail(f"{key} должен быть непустой строкой")
    if not isinstance(policy.get("demo"), bool):
        fail("demo должен быть true или false")
    rules = policy.get("rules")
    if not isinstance(rules, list) or not rules:
        fail("rules должен содержать хотя бы один пункт")
    ids, questions = set(), set()
    for rule in rules:
        if not isinstance(rule, dict):
            fail("каждый пункт должен быть объектом")
        unknown = set(rule) - {"id", "text", "types", "required", "date_order", "questions"}
        if unknown:
            fail("неподдерживаемые свойства пункта: " + ", ".join(sorted(unknown)))
        for key in ("id", "text"):
            if not isinstance(rule.get(key), str) or not rule[key].strip():
                fail(f"{key} пункта должен быть непустой строкой")
        if rule["id"] in ids:
            fail(f"повтор номера пункта {rule['id']}")
        ids.add(rule["id"])
        kinds = rule.get("types")
        if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or k not in SCHEMAS for k in kinds):
            fail(f"п. {rule['id']}: types должен содержать известные типы документов")
        for attribute in ("required", "date_order"):
            if attribute not in rule:
                continue
            keys = rule[attribute]
            if not isinstance(keys, list) or not keys or any(not isinstance(k, str) for k in keys):
                fail(f"п. {rule['id']}: {attribute} должен быть списком полей")
            if len(keys) != len(set(keys)):
                fail(f"п. {rule['id']}: повтор поля в {attribute}")
            if attribute == "date_order" and len(keys) != 2:
                fail(f"п. {rule['id']}: date_order должен содержать две даты")
            for kind in kinds:
                allowed = set(SCHEMAS[kind]["fields"])
                if attribute == "required":
                    allowed.update(SCHEMAS[kind]["visual"])
                else:
                    allowed = {k for k in allowed if k.endswith("_date")}
                if any(k not in allowed for k in keys):
                    fail(f"п. {rule['id']}: неизвестное или неподходящее поле для {kind} в {attribute}")
        if "questions" in rule:
            queries = rule["questions"]
            if not isinstance(queries, list) or not queries or any(not isinstance(q, str) or not policy_question_key(q) for q in queries):
                fail(f"п. {rule['id']}: questions должен содержать непустые строки")
            for kind in kinds:
                for q in queries:
                    key = (kind, policy_question_key(q))
                    if key in questions:
                        fail(f"неоднозначный вопрос для {kind}: {q}")
                    questions.add(key)
    return policy


def policy_question_key(question):
    import re
    import unicodedata
    text = unicodedata.normalize("NFKC", question).casefold().replace("ё", "е")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def load_policy(path=None):
    return validate_policy(json.loads(Path(path or ROOT / "configs" / "policy.demo.json").read_text(encoding="utf-8")))


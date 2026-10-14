"""Controlled prose layouts inspired by public blank forms, with fictional values."""
import argparse
import io
import json
import random
import sys
import types
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT, SCHEMAS
from dekanat.synthetic import values, font_path, signature, stamp
from dekanat.extraction import normalize
from dekanat.pipeline import analyze


def example(kind, style, seed):
    rng = random.Random(seed)
    data = values(rng)
    truth = {key: data[key] for key in SCHEMAS[kind]["fields"]}
    image = Image.new("RGB", (1500, 1500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path(), 25)
    draw.text((60, 35), "УЧЕБНЫЙ ОБРАЗЕЦ / ВЫМЫШЛЕННЫЕ ДАННЫЕ", font=font, fill="#555")
    lines = [SCHEMAS[kind]["title"].upper()]
    date, number = data["issue_date"], data["document_number"]
    if kind == "study":
        data["university"] = f'АНО ВО «{data["university"]}»'
        truth["university"] = data["university"]
        form = {"очная": "очной", "заочная": "заочной", "очно-заочная": "очно-заочной"}[data["study_form"]]
        lines += [data["university"], f"СПРАВКА № {number} от {date}"]
        if style == "wrapped":
            lines += [f'Дана {data["student_name"]}', f'в том, что он является студентом {form} формы обучения.']
            first, last = data["program"].rsplit(" ", 1)
            lines += [f'Обучается по направлению подготовки «{first}', f'{last}».']
        else:
            lines += [f'Дана {data["student_name"]} в том, что он является студентом',
                      f'{form} формы обучения по направлению подготовки «{data["program"]}».']
        if style == "separate_dates":
            lines += ["Дата начала обучения в университете 01.09.2024", "Предполагаемая дата окончания в университете 30.06.2026"]
        else:
            lines += ["Обучается с 01.09.2024 по 30.06.2026."]
        lines += ["Приказ о зачислении: № 987 от 01.09.2024.", "Исполнитель:", "ФИО специалиста факультета"]
    elif kind == "leave":
        truth["reason"] = "семейными обстоятельствами"
        lines += [f'ФИО: {data["student_name"]}', f'Группа: {data["group"]}', f'Курс: {data["course"]}']
        sentence = f'Прошу предоставить мне академический отпуск с {data["start_date"]} по {data["end_date"]}'
        if style == "wrapped":
            lines += [sentence, "в связи с семейными обстоятельствами."]
        else:
            lines += [sentence+" в связи с семейными обстоятельствами."]
        lines += [f'Дата заявления: {data["application_date"]}']
    else:
        lines += [f'{date} № {number}', f'ФИО: {data["student_name"]}', f'Организация: {data["organization"]}']
        period = "Прошел производственную практику с 01.06.2026 по 30.06.2026."
        if style == "wrapped":
            lines += ["Прошел производственную практику", "с 01.06.2026 по 30.06.2026."]
        else:
            lines += [period]
        lines += [f'Руководитель практики: {data["supervisor"]}', f'Оценка за практику: {data["grade"]}']
    y = 150
    for text in lines:
        # Wrap long prose at word boundaries to stay within the page. A real
        # document's OCR segmentation is measured by analyze, not injected.
        words, current, output = text.split(), "", []
        for word in words:
            proposed = (current+" "+word).strip()
            if draw.textlength(proposed, font=font) > 1370 and current:
                output.append(current)
                current = word
            else:
                current = proposed
        output.append(current)
        for line in output:
            draw.text((60, y), line, font=font, fill="black")
            y += 43
        y += 12
    draw.text((60, 1210), "Подпись: _________   М.П.", font=font, fill="black")
    signature(draw, rng, (240, 1270, 200, 65))
    if kind != "leave":
        stamp(draw, rng, (900, 1240, 140, 140))
    return image, truth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", action="store_true")
    parser.add_argument("--save-demo", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--quote-model", type=Path)
    parser.add_argument("--without-quote", action="store_true")
    args = parser.parse_args()
    import dekanat.pipeline as pipeline
    import dekanat.extraction as current_extraction
    pipeline.extract, pipeline.detect_type = current_extraction.extract, current_extraction.detect_type
    if args.previous:
        module = types.ModuleType("dekanat.before_narrative")
        module.__package__ = "dekanat"
        source = (ROOT/"tests/fixtures/extraction_before_narrative.py.txt").read_text(encoding="utf-8")
        exec(compile(source, "before_narrative.py", "exec"), module.__dict__)
        pipeline.extract, pipeline.detect_type = module.extract, module.detect_type
    analyze((ROOT/"data/demo/study.png").read_bytes(), "warmup.png", "study", retry=False)
    records = []
    for index, kind in enumerate(SCHEMAS):
        for variant, style in enumerate(["plain", "wrapped", "separate_dates"]):
            image, truth = example(kind, style, (2026101500 if args.fresh else 2026101400)+10*index+variant)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            _, result = analyze(buffer.getvalue(), "prose.png", "auto", retry=False, quote_weights=False if args.previous or args.without_quote else args.quote_model)
            errors, correct, reliable_correct, confident_wrong = [], 0, 0, 0
            for key, expected in truth.items():
                field = result["fields"].get(key, {"value": None, "status": "not_found"})
                equal = field["value"] is not None and normalize(str(field["value"])) == normalize(expected)
                correct += int(equal)
                reliable_correct += int(equal and field["status"] == "found")
                confident_wrong += int(not equal and field["status"] == "found")
                if not equal:
                    errors.append({"field": key, "expected": expected, "actual": field["value"], "status": field["status"]})
            row = {"type": kind, "style": style, "detected_type": result["type"], "correct": correct, "reliable_correct": reliable_correct, "confident_wrong": confident_wrong, "total": len(truth), "errors": errors, "seconds": result["seconds"], "quote_recovery": result["ocr"].get("quote_recovery")}
            records.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "quote_recovery"}, ensure_ascii=False), flush=True)
            if args.save_demo and kind == "study" and style == "wrapped":
                image.save(ROOT/"data/demo/study_prose.png")
                (ROOT/"data/demo/study_prose.json").write_text(json.dumps({"type": kind, "fields": truth, "scope": "Own fictional prose example; not a completed real student certificate"}, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"scope": "Nine own fictional prose/hybrid examples with actual OCR and automatic type detection. Public blank university forms informed the study sentence structures; source PDFs not rendered or redistributed here. Development suite; fresh values retain same layouts, not an independent real-world test.",
              "documents": len(records), "variant": "previous" if args.previous else "without_quote" if args.without_quote else "candidate", "fresh": args.fresh, "quote_model": str(args.quote_model) if args.quote_model else None,
              "correct": sum(r["correct"] for r in records), "reliable_correct": sum(r["reliable_correct"] for r in records), "confident_wrong": sum(r["confident_wrong"] for r in records), "total": sum(r["total"] for r in records), "type_correct": sum(r["type"] == r["detected_type"] for r in records), "rows": records}
    suffix = "_fresh" if args.fresh else ""
    (ROOT/f"artifacts/narrative_{report['variant']}{suffix}_metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

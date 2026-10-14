"""Bounded OCR-based quarter-turn recovery with original-coordinate mapping."""
from copy import deepcopy
import re

import numpy as np
from PIL import Image

from .extraction import detect_type, normalize
from .preprocessing import quality_metrics
from .schema import SCHEMAS


def reading_score(lines):
    confident = [line for line in lines if line["confidence"] >= .55]
    text = normalize(" ".join(line["text"] for line in confident))
    keys = set()
    for schema in SCHEMAS.values():
        for key, aliases in schema["fields"].items():
            if any(re.search(r"(?<!\w)"+re.escape(normalize(alias))+r"(?=\s|[:：=]|$)", text) for alias in aliases):
                keys.add(key)
    markers = sum(bool(re.search(pattern, text)) for pattern in [
        r"дана.+в\s+[тt][оo][мm]", r"является студент", r"формы обучения", r"обучается\s+[сc]",
        r"фгбо[уy]|ано\s+[вb][оo]", r"по направлению подготовки", r"прошу предоставить.+академический отпуск"])
    kind = detect_type(confident)
    return {"score": len(keys)+markers+(2 if kind else 0), "label_fields": sorted(keys), "markers": markers,
            "type": kind, "median_confidence": float(np.median([line["confidence"] for line in confident])) if confident else 0.}


def rotate_page(page, degrees):
    if degrees not in [90, 180, 270]:
        raise ValueError("Only lossless quarter turns are supported")
    width, height = page.size
    inverse = {90: [[0,-1,width-1],[1,0,0],[0,0,1]],
               180: [[-1,0,width-1],[0,-1,height-1],[0,0,1]],
               270: [[0,1,0],[-1,0,height-1],[0,0,1]]}[degrees]
    result = page.transpose({90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}[degrees])
    metadata = deepcopy(page.info["preprocessing"])
    metadata["rectified_to_input"] = (np.asarray(metadata["rectified_to_input"])@np.asarray(inverse)).tolist()
    metadata["output_size"] = list(result.size)
    metadata["quality"] = quality_metrics(result)
    metadata["orientation"] = {"applied": True, "degrees_ccw": degrees, "method": "bounded_ocr_quarter_turns"}
    result.info["preprocessing"] = metadata
    return result


def recover(pages, ocr_pages, ocr, recognize, expected_type="auto"):
    summaries, extra_attempts, extra_seconds = [], 0, 0.
    original_lines = list(ocr["lines"])
    updated_lines = list(original_lines)
    for index, page in enumerate(pages):
        lines = [line for line in original_lines if line["page"] == index]
        initial = reading_score(lines)
        summary = {"page": index, "applied": False, "degrees_ccw": 0, "initial": initial, "attempts": 0}
        # Strong text anchors already establish orientation. Empty white pages
        # cannot benefit from three additional OCR calls.
        ink_fraction = float((np.asarray(ocr_pages[index]).mean(axis=2) < 180).mean())
        if initial["score"] >= 4 or ink_fraction < .001:
            summaries.append(summary)
            continue
        trials = []
        for degrees in [90, 180, 270]:
            transformed = ocr_pages[index].transpose({90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}[degrees])
            reading = recognize([transformed])
            score = reading_score(reading["lines"])
            trials.append((score["score"], degrees, reading, score))
            extra_attempts += 1
            extra_seconds += reading["seconds"]
        ranked = sorted(trials, key=lambda item: item[0], reverse=True)
        best_score, degrees, reading, details = ranked[0]
        runner_up = max(initial["score"], ranked[1][0])
        summary.update(attempts=3, trials=[{"degrees_ccw": d, **s} for _, d, _, s in trials])
        # Require several independent anchors, a clear winning orientation and
        # an allowed type; never rotate merely because confidence rose.
        allowed_type = details["type"] in SCHEMAS and (expected_type == "auto" or details["type"] == expected_type)
        if best_score >= 5 and best_score-runner_up >= 3 and details["median_confidence"] >= .6 and allowed_type:
            corrected = rotate_page(page, degrees)
            pages[index] = corrected
            ocr_pages[index] = ocr_pages[index].transpose({90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}[degrees])
            new_lines = [{**line, "page": index} for line in reading["lines"]]
            updated_lines = [line for line in updated_lines if line["page"] != index]+new_lines
            summary.update(applied=True, degrees_ccw=degrees, selected=details)
            ocr["retries"] += reading["retries"]
        summaries.append(summary)
    ocr["lines"] = sorted(updated_lines, key=lambda line: (line["page"], line["bbox"][1]))
    ocr["seconds"] += extra_seconds
    ocr["retries"] += extra_attempts
    return {"pages": summaries, "attempts": extra_attempts,
            "scope": "OCR anchor heuristic over four orientations, not a learned orientation classifier or a proof of document authenticity"}

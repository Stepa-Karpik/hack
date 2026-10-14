"""Record data roles and local fingerprints without distributing source data."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dekanat.schema import ROOT


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", type=Path)
    args = parser.parse_args()
    datasets = [
        {"id": "synthetic_documents_v1", "status": "used", "source": "dekanat/synthetic.py + scripts/generate_data.py", "license": "Team code AGPL-3.0; fictitious content", "roles": ["field training", "visual training", "evaluation"], "counts": {"train": 1200, "val": 240, "test": 240}, "seed": 20261010},
        {"id": "field_prefixes_v1", "status": "used", "derived_from": "synthetic_documents_v1", "roles": ["training", "validation", "development test"], "counts": {"train": 21802, "val": 4344, "test": 4340}, "source": "scripts/train_fields.py", "noise_seed": 42},
        {"id": "synthetic_footer_v1", "status": "used", "derived_from": "synthetic_documents_v1", "roles": ["MobileNet training/evaluation"], "counts": {"train": 1200, "val": 240, "test": 240}},
        {"id": "ocr_crops_v1", "status": "used", "source": "scripts/train_ocr.py", "roles": ["OCR fine-tuning", "checkpoint selection"], "counts": {"train": 4000, "val": 480}, "seeds": [42001, 73001], "storage": "generated in memory"},
        {"id": "ultralytics_signature", "status": "used", "url": "https://docs.ultralytics.com/datasets/detect/signature/", "download_url": "https://github.com/ultralytics/assets/releases/download/v0.0.0/signature.zip", "license": "AGPL-3.0 per source documentation", "counts": {"train": 143, "val": 35}, "roles": ["YOLO fine-tuning", "checkpoint validation"], "original_split_preserved": True, "revision": "Download URL not immutable; local archive SHA recorded below"},
        {"id": "synthetic_marks_v1", "status": "used", "source": "scripts/prepare_detection.py", "roles": ["YOLO fine-tuning", "checkpoint validation"], "counts": {"train": 240, "val": 60}, "seeds": {"train_start": 300000, "val_start": 400000}},
        {"id": "mixed_marks_v1", "status": "used", "derived_from": ["ultralytics_signature", "synthetic_marks_v1"], "counts": {"train": 383, "val": 95}},
        {"id": "audit_dev_v1", "status": "used", "roles": ["OCR mode selection", "debugging", "regression"], "count": 36, "seed_start": 9000000, "source": "scripts/make_audit.py"},
        {"id": "audit_final_v1", "status": "used", "roles": ["separate initial evaluation", "subsequent debugging"], "count": 36, "seed_start": 9500000, "independent_for_future_changes": False, "source": "scripts/make_audit.py"},
        {"id": "demo_v1", "status": "used", "roles": ["demonstration", "smoke test"], "count": 4, "source": "scripts/make_demo.py"},
        {"id": "stress_demo_v1", "status": "used", "roles": ["deskew diagnosis and regression"], "count": 18, "derived_from": "demo_v1", "source": "scripts/stress_test.py", "independent": False},
        {"id": "camera_diagnostic_v1", "status": "used", "roles": ["preprocessing selection and diagnosis, not model training"], "count": 57, "conditions": 19, "base_documents": 3, "derived_from": "demo_v1", "source": "dekanat/photo_augment.py + scripts/stress_camera.py", "independent": False},
        {"id": "camera_fresh_v1", "status": "used", "roles": ["first evaluation after preprocessing selection, not model training"], "count": 57, "conditions": 19, "base_documents": 3, "seed_start": 9800000, "templates": [52,53,54], "source": "dekanat/synthetic.py + dekanat/photo_augment.py", "scope": "same generator; not real camera photos"},
        {"id": "blur_candidates_v1", "status": "used", "roles": ["rejected preprocessing candidates"], "count": 8, "derived_from": "camera_diagnostic_v1", "source": "scripts/compare_blur.py"},
        {"id": "photo_demo_v1", "status": "used", "roles": ["UI demonstration"], "count": 4, "derived_from": "demo_v1", "source": "scripts/make_photo_examples.py"},
        {"id": "layout_diagnostic_v1", "status": "used", "roles": ["extraction development, not weight training"], "count": 9, "seed_start": 9900000, "source": "scripts/evaluate_layouts.py"},
        {"id": "receipts_ru_audit", "status": "downloaded_quarantined_not_trained", "url": "https://huggingface.co/datasets/cdek-ocr/receipt-ocr-ru", "revision": "50a7383534b3fe498c49eff9e7bb35b20f300eba", "counts": {"train":12,"validation":6,"test":6}, "license":"MIT per card", "roles":["data-quality audit; 3 seller and 36 numeric crops visually checked; not trained"]},
        {"id": "public_university_forms", "status": "local_reference_not_trained", "counts": {"downloaded_pdf":2}, "sources":["https://rosnou.ru/uploads/file/d/8/9/d89799014088000d8edf81c85f0ba524.pdf","https://nvsu.ru/ru/smk/1383/Instruktsiya_po_deloproizvodstvu_FGBOU_VO_NVGU_%282017%29_%282%29.PDF"],"license":"No explicit redistribution license found; originals excluded", "roles":["layout reference"]},
        {"id":"DocLayNet","status":"considered_not_used","url":"https://github.com/DS4SD/DocLayNet","candidate_role":"layout segmentation","license":"CDLA-Permissive-1.0, verified source LICENSE"},
        {"id":"XFUND","status":"considered_not_used","url":"https://github.com/doc-analysis/XFUND","candidate_role":"form relations; Russian not included","license":"CC BY-NC-SA 4.0"},
        {"id": "policy_demo", "status": "used", "roles": ["fictional demo knowledge base"], "source": "configs/policy.demo.json", "rule_count": 5, "official": False},
        {"id": "organizer_brief", "status": "used", "roles": ["requirements"], "source": "Центр-инвест.pdf (organizer case brief)", "license": "Not provided; file excluded from release"},
        {"id": "MWS-Vision-Bench", "status": "considered_not_used", "url": "https://huggingface.co/datasets/MTSAIR/MWS-Vision-Bench", "license": "Card metadata CC-BY-4.0; body MIT, unresolved discrepancy", "candidate_role": "OCR/KIE/VQA evaluation"},
        {"id": "school_notebooks_RU", "status": "candidate_training_rejected_not_deployed", "url": "https://huggingface.co/datasets/ai-forever/school_notebooks_RU", "revision": "a10cd26104f054dc116a9dbc4a29c34b494eb9ae", "license": "MIT per card", "counts": {"downloaded_crops":108,"approved_train":44,"approved_validation":17,"approved_test":14}, "roles": ["reviewed Russian handwriting pilot with synthetic replay"], "evidence": "artifacts/notebooks_pilot_v1.json"},
        {"id": "HWR200", "status": "reviewed_lines_diagnostic_not_trained", "url": "https://huggingface.co/datasets/AntiplagiatCompany/HWR200", "revision":"366a882a2b8d043d437126d2878bd3812ec55a94", "license": "Apache-2.0 per card", "counts":{"writers":3,"scanned_pages":3,"manually_reviewed_lines":9,"diagnostic_validation":6,"diagnostic_test":3}, "candidate_role": "Russian handwriting after reviewed literal line transcription", "evidence":"artifacts/parseq_hwr200_diagnostic.json"},
        {"id": "kaggle_signatures_stamps", "status": "considered_not_used", "url": "https://www.kaggle.com/datasets/igorkarayman/signatures-and-stamps/data", "license": "Not verified", "candidate_role": "Real stamps"},
    ]
    def read_report(path):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    datasets.append({"id":"Hukyl_parseq_s_handwriting", "status":"downloaded_isolated_diagnostic_not_deployed", "url":"https://huggingface.co/Hukyl/parseq-s-cyrillic-handwritten", "revision":"7ee349c4aa082a3ea6a694263b329ae613ce4dcd", "license":"CC BY-SA 4.0 weights; Apache-2.0 code per card", "candidate_role":"Separate Cyrillic handwriting recognizer", "evidence":"artifacts/parseq_handwriting_diagnostic.json", "caveat":"School notebooks included in upstream pretraining: current pilot is not independent for evaluating this base"})
    datasets.extend([
        {"id":"quote_crops_v2", "status":"trained_narrow_fallback", "source":"scripts/train_quote_ocr.py", "license":"Own synthetic values; third-party font files excluded", "counts":{"train_quotes":3000,"train_replay":1600,"validation_quotes":400,"test_quotes":400,"validation_replay":480}, "roles":["Guillemet alphabet fine-tuning; not global OCR replacement"], "seeds":[2026101600,2026101601,2026101602,2026101603]},
        {"id":"narrative_layouts", "status":"diagnostic_evaluation", "source":"scripts/evaluate_narrative.py", "license":"Own generated images/fictional values; source blank PDFs reference only", "counts":{"development_documents":9,"fresh_value_documents":9,"text_fields_per_suite":63}, "roles":["Actual OCR with automatic type detection; same structures/limited value vocabulary, not independent real-document evaluation"]}
    ])
    datasets.append({"id":"orientation_diagnostic_v1", "status":"diagnostic_evaluation", "source":"scripts/evaluate_orientation.py", "license":"Own synthetic documents and fictional values", "counts":{"known_documents":3,"fresh_documents":3,"rotations_per_document":4,"text_fields_per_suite":84}, "seeds":[2026101700,2026101701,2026101702], "roles":["Quarter-turn OCR recovery; same generator, not real phone/student-document validation; no weight training"]})
    datasets.append({"id":"date_validation_example_v1", "status":"ui_and_structural_diagnostic_not_trained", "source":"scripts/make_date_example.py", "license":"Own generated image and fictional values; third-party fonts excluded", "counts":{"documents":1,"unit_cases":18}, "seed":2026101800, "template":73, "roles":["Printed incomplete date negative example; no model weight training"]})
    datasets.append({"id":"field_abstention_diagnostic_v1", "status":"development_calibration_not_deployed", "derived_from":"camera_diagnostic_v1", "source":"scripts/evaluate_field_abstention.py + scripts/summarize_field_abstention.py", "license":"Own synthetic demo content and project code AGPL-3.0; third-party fonts excluded", "counts":{"images":57,"text_fields":399,"global_threshold_trials":22}, "roles":["Abstention cost diagnosis; no weight training"], "independent":False})
    datasets.append({"id":"field_abstention_fresh_v1", "status":"fixed_hypothesis_validation_now_viewed", "derived_from":"synthetic_documents_v1 generator", "source":"scripts/validate_abstention_fresh.py", "license":"Own generated images and fictional values, project code AGPL-3.0; fonts not redistributed", "counts":{"documents":6,"transformed_cases":132,"text_fields":924}, "seed_start":2026101900, "templates":[81,82,83,84,85,86], "fonts":["times.ttf","georgia.ttf"], "roles":["First validation of two thresholds fixed before OCR; no training"], "scope":"Same generator, not real camera accuracy; viewed results cannot serve as independent test for future tuning", "input_archive":"artifacts/field_abstention_fresh_inputs.zip"})
    datasets.append({"id":"manual_documents_v1", "status":"manual_demo_and_viewed_diagnostic_not_trained", "source":"../Документы-для-проверки/ИСТОЧНИКИ.json + GENERATION_SCRIPTS", "license":"Own fictional content/project code AGPL-3.0; fonts not redistributed", "counts":{"images":14,"pdfs":4,"actual_v9_pipeline_runs":18}, "seed_start":2026102001, "roles":["User manual checks; uncertain visual candidate diagnosis"], "scope":"Same generator; PDFs and transformed pages duplicate base documents; not independent accuracy evaluation"})
    datasets.append({"id":"mark_threshold_diagnostic_v1", "status":"viewed_development_diagnostic", "derived_from":"mixed_marks_v1 validation + manual_documents_v1 frozen results", "source":"scripts/diagnose_mark_thresholds.py", "counts":{"real_validation_images":35,"synthetic_validation_images":60,"thresholds":5}, "roles":["Object-level threshold tradeoff diagnosis, not training"], "evidence":"artifacts/mark_threshold_diagnostic.json", "independent":False})
    datasets.append({"id":"realistic_word_documents_v1", "status":"viewed_manual_diagnostic_not_trained", "source":"../Реалистичные-документы/ИСХОДНИКИ/make_realistic_documents.py", "license":"Own composition/project generation code AGPL-3.0; reference PDFs and Windows fonts excluded", "counts":{"layouts":6,"pages":7,"docx":6,"pdf":6,"png":7,"artificial_jpeg":4,"actual_pipeline_runs":10}, "roles":["User manual checks; prose/table extraction development diagnosis and paired v9/v10/v11/v12/v13/v14 rule validation"], "evidence":"artifacts/realistic_documents_sources.json", "independent_for_future_tuning":False})
    by_id = {d["id"]: d for d in datasets}
    manifest = read_report(ROOT/"data/manifest.json")
    if manifest:
        counts = {k: v["count"] for k, v in manifest["splits"].items()}
        by_id["synthetic_documents_v1"]["counts"] = counts
        by_id["synthetic_footer_v1"]["counts"] = counts
    prefixes = read_report(ROOT/"artifacts/fields_metrics.json")
    if prefixes:
        by_id["field_prefixes_v1"]["counts"] = {"train": prefixes["train_examples"], **{k: prefixes[k]["examples"] for k in ("val", "test")}}
    ocr = read_report(ROOT/"artifacts/ocr_training_metrics.json")
    if ocr:
        by_id["ocr_crops_v1"]["counts"] = {"train": ocr["train_examples"], "val": ocr["baseline"]["examples"]}
    detection = read_report(ROOT/"artifacts/detection_data.json")
    if detection:
        for id_, component in (("ultralytics_signature", "real"), ("synthetic_marks_v1", "synthetic")):
            by_id[id_]["counts"] = {k: v[component] for k, v in detection["counts"].items()}
        by_id["mixed_marks_v1"]["counts"] = {k: sum(v.values()) for k, v in detection["counts"].items()}
    assignments=[]
    for filename in ['official_evaluation_truth.json','official_extra_evaluation_truth.json','official_round3_evaluation_truth.json']:
        path=ROOT/'artifacts'/filename
        if path.exists():assignments.extend(json.loads(path.read_text(encoding='utf-8'))['records'])
    def institutional_role(source):
        if source['institution'] in {'isu','kfu'}:
            return 'Viewed after first V17 source check' if (ROOT/'artifacts/official_round3_v17_initial.json').exists() else 'Labels/visual QA frozen before first model check'
        if source['institution']=='tsu':
            return 'Viewed development after initial TSU check' if (ROOT/'artifacts/official_tsu_v16_initial.json').exists() else 'Original extra source, labels/visual QA prepared; initial model check not yet run'
        return 'Viewed development, including initial v15 source holdout subsequently used to fix v16'
    for filename in ['official_sources_intake.json','official_sources_extra_intake.json','official_sources_round3_intake.json']:
        path=ROOT/'artifacts'/filename
        if path.exists():
            intake=json.loads(path.read_text(encoding='utf-8'))
            for source in intake['rows']:
                datasets.append({'id':'institutional_'+source['id'],'status':source['status'],
                                 'url':source['url'],'source_page':source['source_page'],'license':source['license'],
                                 'sha256':source.get('sha256'),'bytes':source.get('bytes'),
                                 'roles':['Local template/reference evaluation or untouched intake only; no weight training'],
                                 'distributed':False,'evidence':filename,
                                 'evaluation_assignments':[{'input_id':r['id'],'initial_split':r['split'],
                                                            'current_role':institutional_role(source),
                                                            'input_sha256':r['sha256']} for r in assignments if r['source_id']==source['id']]})
    datasets.append({'id':'official_fictional_filled_v1','status':'development_evaluation_only','counts':{'documents':4,'institutions':2},
                     'source':'scripts/fill_official_development.py','license':'Underlying official template reuse rights not verified; local-only fictional filled derivatives',
                     'roles':['Viewed development; no weight training'],'evidence':'artifacts/official_filled_truth.json','distributed':False})
    if (ROOT/'artifacts/official_round3_filled_manifest.json').exists():
        datasets.append({'id':'official_fictional_round3','counts':{'documents':4,'institutions':2},
                         'status':'viewed_after_first_check' if (ROOT/'artifacts/official_round3_v17_initial.json').exists() else 'frozen_before_first_model_check',
                         'source':'scripts/prepare_official_round3.py','roles':['Local evaluation only; no weight training'],
                         'license':'Official template rights unresolved; invented filled values, no marks; derivative files not distributed',
                         'evidence':['artifacts/official_round3_filled_manifest.json','artifacts/official_round3_evaluation_truth.json'],'distributed':False})
    if (ROOT/'artifacts/official_camera_v17.json').exists():
        datasets.append({'id':'official_camera_76','counts':{'inputs':76,'source_templates':4,'conditions':19},
                         'status':'viewed_development','source':'scripts/evaluate_official_camera.py',
                         'roles':['Deterministic camera simulation evaluation; no weight training'],
                         'license':'Official template rights unresolved; local-only derivatives',
                         'scope':'Not actual phone photographs or independent student-document accuracy',
                         'evidence':'artifacts/official_camera_v17.json','distributed':False})
    for identifier,evidence,counts,role in [
        ('native_pdf_slots_v18','native_pdf_slots_probe_v18.json',{'viewed_institutional_inputs':23},'Offline native glyph and missing-slot proposals; source confidence is not ML confidence'),
        ('native_pdf_visibility_controls','native_pdf_eligibility_probe.json',{'own_synthetic_controls':8,'viewed_institutional_inputs':23},'Offline visible text, hidden/white/occluded text, rotation and raster fallback eligibility checks'),
        ('ocr_slots_shadow','ocr_slots_shadow_probe.json',{'stored_outputs':99,'present_fields':506},'Offline replay of stored OCR output with missing-slot proposals, no new inference')]:
        if (ROOT/'artifacts'/evidence).exists():
            datasets.append({'id':identifier,'status':'isolated_not_deployed','counts':counts,
                             'source':'scripts/experiments/','roles':[role,'No weight training'],
                             'license':'Institutional template rights unresolved; local-only source derivatives. Own synthetic visibility controls use local Arial, no font distribution.',
                             'scope':'Viewed development diagnostics, not independent real-student/phone accuracy',
                             'evidence':'artifacts/'+evidence,'distributed':False})
    datasets.append({'id':'official_native_pdf_prototype_v1','status':'offline_unqualified_prototype','counts':{'viewed_fictional_pdfs':4},
                     'derived_from':'official_fictional_filled_v1','roles':['Native PDF characters/glyph coordinates diagnosis; not ML inference, no weight training'],
                     'evidence':['artifacts/native_pdf_text_probe.json','artifacts/native_pdf_geometry_probe.json'],'deployed':False})
    for path in sorted((ROOT/'artifacts').glob('ocr_official_training_v*.json')):
        experiment=json.loads(path.read_text(encoding='utf-8'))
        datasets.append({'id':path.stem,'status':'isolated_experiment_not_deployed','source':'scripts/train_official_ocr.py',
                         'roles':['Own synthetic caption/grade/organization training plus own synthetic replay'],
                         'license':'Own fictional text; Windows fonts used locally, not distributed',
                         'recipe':experiment['recipe'],'data_fingerprints':experiment['data'],'evidence':str(path.relative_to(ROOT)),
                         'selected':experiment.get('selected'),'numerical_failure':experiment.get('numerical_failure'),
                         'scope':experiment['scope']})
    participant_intake=ROOT/'artifacts/participant_kit_v1_intake.json'
    if participant_intake.exists():
        intake=json.loads(participant_intake.read_text(encoding='utf-8'))
        datasets.append({'id':'organizer_participant_kit_v1','status':'first_pass_evaluated_now_viewed_development_not_trained',
            'source':'User-provided participant kit folder','license':intake['license'],
            'counts':{'documents':30,'questions':120,'paired_representations':60,'source_files':68},
            'roles':['Target case rules/format','Initial frozen V21 evaluation; future development'],
            'source_fingerprints':intake['files'],'evidence':'artifacts/participant_kit_v1_intake.json',
            'caveat':'PNG/PDF are equivalent views, not60independent examples; no real-document accuracy or ML training claim'})
    crop_controls=ROOT/'artifacts/participant_crop_controls_v4.json'
    if crop_controls.exists():
        controls=json.loads(crop_controls.read_text(encoding='utf-8'))
        datasets.append({'id':'participant_crop_controls_v4','status':'diagnostic_only_not_trained',
            'source':'scripts/experiments/participant_crop_controls.py',
            'license':'Own fictional date text; installed Windows fonts used locally, not distributed',
            'counts':{'printed_crop_controls':12,'font_variants':2,'positive':6,'negative':6},
            'roles':['Standalone bounded date reread diagnostics'],
            'evidence':'artifacts/participant_crop_controls_v4.json',
            'scope':controls['scope'],'correct':controls['correct'],
            'new_wrong_nonempty':controls['new_wrong_nonempty']})
    value_controls=ROOT/'artifacts/participant_value_quote_controls_v6.json'
    if value_controls.exists():
        controls=json.loads(value_controls.read_text(encoding='utf-8'))
        datasets.append({'id':'participant_value_quote_controls_v6','status':'diagnostic_only_not_trained',
            'source':'scripts/experiments/participant_value_quote_controls.py',
            'license':'Own fictional names; installed Windows fonts used locally, not distributed',
            'counts':{'crop_controls':8,'font_variants':2,'positive':4,'negative':4},
            'roles':['Standalone quote value recovery diagnostics'],
            'evidence':'artifacts/participant_value_quote_controls_v6.json',
            'scope':controls['scope'],'correct':controls['correct'],'changed_to_wrong':controls['changed_to_wrong']})
    wrapped_controls=ROOT/'artifacts/wrapped_names_study_v1.json'
    wrapped_reread=ROOT/'artifacts/wrapped_names_reread_v1.json'
    if wrapped_controls.exists():
        controls=json.loads(wrapped_controls.read_text(encoding='utf-8'))
        datasets.append({'id':'wrapped_names_study_v1','status':'diagnostic_only_not_trained',
            'source':'scripts/experiments/wrapped_names_study.py',
            'license':'Own fictional text; local Windows fonts not distributed',
            'counts':{'synthetic_full_service_uploads':12,'layouts':6,'font_variants':2,'positive':8,'negative':4},
            'roles':['Full-service wrapped-name diagnosis; isolated correlated reread candidate'],
            'evidence':['artifacts/wrapped_names_study_v1.json','artifacts/wrapped_names_reread_v1.json'],
            'scope':controls['scope'],'baseline_exact':controls['exact'],'negative_false_nonempty':controls['negative_false_nonempty']})
    adversarial_controls=ROOT/'artifacts/wrapped_names_adversarial_v1.json'
    adversarial_reviewed=ROOT/'artifacts/wrapped_names_adversarial_v2_reviewed.json'
    if adversarial_reviewed.exists():
        reviewed=json.loads(adversarial_reviewed.read_text(encoding='utf-8'))
        datasets.append({'id':'wrapped_names_adversarial','status':'diagnostic_only_not_trained',
            'source':'scripts/experiments/wrapped_names_adversarial.py',
            'license':'Own fictional text; locally installed Calibri/Verdana not distributed',
            'counts':{'original_runs':16,'reviewed_runs':16,'unique_images':20,'reviewed_positive':8,'reviewed_negative':8},
            'roles':['New column/duplicate/note layout controls; unchanged offline reread v1 candidate'],
            'evidence':['artifacts/wrapped_names_adversarial_v1.json','artifacts/wrapped_names_adversarial_v2_reviewed.json'],
            'scope':reviewed['scope'],'reviewed_baseline_exact':reviewed['baseline_exact'],'reviewed_candidate_exact':reviewed['candidate_exact'],
            'changed_wrong':reviewed['changed_wrong'],'proposal_false_nonempty':reviewed['proposal_false_nonempty'],
            'original_annotation_warning':'Four rows excluded: author-intent blank value is visually ambiguous; two printed fragments overlap. Raw v1 retained, not valid aggregate accuracy.'})
    wrapped_guard_replay=ROOT/'artifacts/wrapped_names_guard_replay_v2.json'
    wrapped_image_full=ROOT/'artifacts/wrapped_image_full_v3.json'
    wrapped_image_positive=ROOT/'artifacts/wrapped_image_seen_positive_v3.json'
    if wrapped_image_full.exists():
        study=json.loads(wrapped_image_full.read_text(encoding='utf-8'))
        datasets.append({'id':'wrapped_image_shadow_v3','status':'diagnostic_only_not_trained',
            'source':'scripts/experiments/wrapped_image_qualification.py',
            'license':'Fresh fictional texts are own; fonts local, not distributed. Kit/own inputs retain their documented licenses.',
            'counts':{'kit_views':60,'own_inputs':10,'fresh_controls':8,'seen_positive_recheck':1},
            'roles':['Full unchanged service plus separate guarded image shadow qualification'],
            'evidence':['artifacts/wrapped_image_full_v3.json','artifacts/wrapped_image_seen_positive_v3.json'],
            'scope':study['scope'],'groups':study['groups']})
    fingerprints = {}
    paths = [*ROOT.glob("data/*/annotations.jsonl"), ROOT/"data/manifest.json", ROOT/"data/detection/signature.zip", ROOT/"data/detection/dataset.yaml", ROOT/"configs/policy.demo.json"]
    paths += [ROOT/'configs/participant_v1.json',participant_intake,crop_controls,value_controls]
    paths += [wrapped_controls,wrapped_reread]
    paths += [adversarial_controls,adversarial_reviewed]
    paths += [wrapped_guard_replay]
    paths += [wrapped_image_full,wrapped_image_positive]
    paths += [p for p in (ROOT/"data/demo").glob("*") if p.is_file()]
    paths += [p for p in (ROOT/"models").glob("*") if p.suffix in (".pt", ".joblib", ".json")]
    paths += list((ROOT/"models/cache/easyocr").glob("*.pth"))
    paths += [ROOT/"requirements.lock.txt", *ROOT.glob("dekanat/*.py"), *(ROOT/"scripts").rglob("*.py")]
    paths += [*[p for p in (ROOT/"web").rglob("*") if p.is_file()], *ROOT.glob("deploy/*"), ROOT/"artifacts/web_remote_smoke_v1.json", ROOT/"artifacts/web_cpu_three_types_v1.json", ROOT/"artifacts/web_remote_cpu4_smoke_v1.json"]
    paths += list(ROOT.glob("data/external/real_documents/receipts/*_selected.jsonl"))
    paths += list(ROOT.glob("data/external/real_documents/forms/*.pdf"))
    paths += [ROOT/"tests/fixtures/extraction_reference.py.txt", ROOT/"tests/fixtures/extraction_before_narrative.py.txt"]
    paths += [ROOT/"artifacts/field_abstention_fresh_inputs.zip"]
    for path in paths:
        if path.exists():
            fingerprints[str(path.relative_to(ROOT)).replace("\\", "/")] = {"sha256": sha(path), "bytes": path.stat().st_size}
    if args.brief:
        if not args.brief.is_file():
            raise ValueError("Provided brief file does not exist")
        fingerprints["external/organizer_brief.pdf"] = {"sha256": sha(args.brief), "bytes": args.brief.stat().st_size}
    fonts = []
    for name in ("arial.ttf", "times.ttf", "georgia.ttf", "calibri.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            fonts.append({"file": name, "sha256": sha(path), "distributed": False})
    from datetime import date
    report = {"format": "data-registry-v1", "snapshot_date": str(date.today()), "counts_scope": "Latest local manifests/training reports where present; expected reference counts otherwise. Not a dataset revision date.", "datasets": datasets,
              "pretrained_bases": [
                  {"id": "CRAFT", "source": "EasyOCR official assets", "role": "text detection, not fine-tuned"},
                  {"id": "cyrillic_g2", "source": "EasyOCR 1.7.2 official assets", "role": "base and fine-tuning"},
                  {"id": "yolov8n.pt", "source": "Ultralytics official assets", "pretraining": "COCO", "role": "marks fine-tuning"},
                  {"id": "MobileNet_V3_Small_Weights.DEFAULT", "source": "torchvision", "pretraining": "ImageNet-1K", "role": "footer fine-tuning"},
                  {"id": "yolo26n.pt", "source": "Ultralytics AMP diagnostic", "role": "not a training base, excluded from release"}],
              "local_fingerprints": fingerprints, "local_fonts": fonts,
              "release_exclusions": ["Original real signature images", "Training corpora", "Windows font files", "Diagnostic and obsolete checkpoints", "Organizer brief PDF"]}
    vendor=ROOT/"web/vendor/manifest.json"
    if vendor.exists():report["frontend_components"]=json.loads(vendor.read_text(encoding="utf-8"))
    target = ROOT/"artifacts/data_registry.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(datasets)} data sources/derived sets; {len(fingerprints)} local fingerprints")


if __name__ == "__main__":
    main()

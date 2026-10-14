"""Additional untouched TSU sources for a future independent evaluation."""
import json
from intake_official import fetch,BASE,PROJECT

SOURCES=[
    ('tsu_leave_2026','tsu','leave','https://ui.tsu.ru/wp-content/uploads/2026/02/11-заявление-на-акад.отпуск-новый-бланк.docx','https://ui.tsu.ru/?page_id=3651'),
    ('tsu_request_study_negative','tsu',None,'https://ui.tsu.ru/wp-content/uploads/2014/06/заявление-на-справку-об-обучении.docx','https://ui.tsu.ru/?page_id=3651'),
]

if __name__=='__main__':
    (BASE/'originals').mkdir(parents=True,exist_ok=True)
    rows=[fetch(source) for source in SOURCES]
    report={'scope':'Additional official source institution; intake only, unread/unscored. Request for a study certificate is not the certificate. No ML weight training; rights unresolved and files excluded from distribution. Splits/labels must be frozen before scoring.','rows':rows}
    (PROJECT/'artifacts/official_sources_extra_intake.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in rows:print(row['id'],row['status'],row.get('bytes',row.get('error')),flush=True)

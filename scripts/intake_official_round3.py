"""Additional primary-source forms; no model inference or training during intake."""
import json
from intake_official import fetch, BASE, PROJECT

SOURCES=[
    ('isu_leave_2020','isu','leave','https://physdep.isu.ru/export/sites/physdep/ru/staff/student/.galleries/docs/zayav-akad-otpusk2020.docx','https://physdep.isu.ru/ru/staff/student/application/'),
    ('isu_leave_return_2020','isu',None,'https://physdep.isu.ru/export/sites/physdep/ru/staff/student/.galleries/docs/zayav-akad-otpusk-vyhod2020.docx','https://physdep.isu.ru/ru/staff/student/application/'),
    ('kfu_practice_character','kfu','practice','https://kpfu.ru/portal/docs/F_875370367/5..OTZYV.na.praktikanta.docx','https://kpfu.ru/kgp/praktika'),
]

if __name__=='__main__':
    (BASE/'originals').mkdir(parents=True,exist_ok=True)
    rows=[fetch(source) for source in SOURCES]
    report={'scope':'New primary institutions after V17 source freeze. Intake only; no model scoring or weight training. Labels/filled variants must be reviewed and frozen before any inference. Local evaluation, no originals redistributed; rights unresolved. Return from leave is outside the leave-request schema.', 'rows':rows}
    (PROJECT/'artifacts/official_sources_round3_intake.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in rows:print(row['id'],row['status'],row.get('bytes',row.get('error')),flush=True)

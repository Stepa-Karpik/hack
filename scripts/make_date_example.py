"""Own fictional document containing an explicitly incomplete date, not OCR loss."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dekanat import synthetic
from dekanat.schema import ROOT


def main():
    original=synthetic.values
    def values(rng):
        fields=original(rng)
        fields['application_date']='05.10.2'
        return fields
    try:
        synthetic.values=values
        image,record=synthetic.document(2026101800,template=73,document_type='leave',missing_rate=0,force_marks=(True,False))
    finally:
        synthetic.values=original
    record['scope']='Own fictional negative date-syntax example; literal incomplete date is printed. No real personal data or official policy; not weight training.'
    image.save(ROOT/'data/demo/leave_bad_date.png')
    (ROOT/'data/demo/leave_bad_date.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()

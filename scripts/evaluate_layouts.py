"""E2E comparison on new controlled layouts, not real completed student documents."""
import argparse,importlib.util,io,json,random,sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from dekanat.schema import ROOT,SCHEMAS
from dekanat.synthetic import values,font_path
from dekanat.pipeline import analyze
from dekanat.extraction import normalize


def example(kind,style,seed):
    rng=random.Random(seed);data=values(rng)
    font=ImageFont.truetype(font_path(),22);heading=ImageFont.truetype(font_path(),30)
    image=Image.new("RGB",(1500,1500),"white");draw=ImageDraw.Draw(image)
    draw.text((60,40),SCHEMAS[kind]["title"]+" / УЧЕБНЫЙ ОБРАЗЕЦ",font=heading,fill="black")
    draw.text((60,100),"Входящий отдел: учебная часть. Контакт: example.invalid",font=font,fill="black")
    truth={}
    for i,(key,aliases) in enumerate(SCHEMAS[kind]["fields"].items()):
        value=data[key];label=aliases[0];truth[key]=value
        if style=="columns":
            x,y=60+(i%2)*720,220+(i//2)*150
            draw.text((x,y),label+":",font=font,fill="black")
            draw.text((x,y+40),value,font=font,fill="black")
        elif style=="right_values":
            y=220+i*120
            draw.text((60,y),label+":",font=font,fill="black")
            draw.text((480,y),value,font=font,fill="black")
        else:
            y=220+i*140
            words=value.split()
            if key in {"reason","program","organization","university"} and len(words)>1:
                draw.text((60,y),label+":",font=font,fill="black")
                draw.text((60,y+35)," ".join(words[:-1]),font=font,fill="black")
                draw.text((60,y+65),words[-1],font=font,fill="black")
            else:draw.text((60,y),label+": "+value,font=font,fill="black")
    draw.text((60,1370),"Служебная отметка: копия. Подлинность проверяется сотрудником.",font=font,fill="black")
    return image,truth


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--previous",action="store_true");args=parser.parse_args()
    if args.previous:
        # Isolated reference module, no mutation of the installed package or weights.
        source=(ROOT/"tests/fixtures/extraction_reference.py.txt").read_text(encoding="utf-8")
        import types,dekanat.pipeline as pipeline
        module=types.ModuleType("dekanat.reference_extraction");module.__package__="dekanat"
        exec(compile(source,"reference_extraction.py","exec"),module.__dict__)
        pipeline.extract=module.extract
    analyze((ROOT/"data/demo/study.png").read_bytes(),"warmup.png","study",retry=False)
    rows=[]
    for index,kind in enumerate(SCHEMAS):
        for style in ["columns","right_values","wrapped"]:
            image,truth=example(kind,style,9900000+index)
            data=io.BytesIO();image.save(data,format="PNG")
            _,result=analyze(data.getvalue(),"layout.png",kind,retry=False)
            errors=[];correct=0
            for key,value in truth.items():
                actual=result["fields"][key]["value"]
                equal=actual is not None and normalize(value)==normalize(str(actual))
                correct+=int(equal)
                if not equal:errors.append({"field":key,"expected":value,"actual":actual,"status":result["fields"][key]["status"]})
            row={"type":kind,"style":style,"correct":correct,"total":len(truth),"errors":errors,"seconds":result["seconds"]}
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    report={"scope":"Nine new synthetic layouts, 3 types x 3 arrangements; used for layout development, same value generator. Not real student-document accuracy.",
            "variant":"previous" if args.previous else "candidate","correct":sum(r["correct"] for r in rows),"total":sum(r["total"] for r in rows),"rows":rows}
    (ROOT/f"artifacts/layout_{report['variant']}_metrics.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()

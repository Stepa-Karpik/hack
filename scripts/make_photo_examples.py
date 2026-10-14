"""Add reproducible synthetic camera examples to the local demonstration."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from dekanat.schema import ROOT
from dekanat.photo_augment import conditions


def main():
    demo=ROOT/"data/demo"
    with Image.open(demo/"study.png") as image:source=image.convert("RGB")
    truth=json.loads((demo/"study.json").read_text(encoding="utf-8"))
    for name,condition in {"photo_angle":"perspective_from_right","photo_light":"combined_view_shadow_blur",
                           "photo_blur":"defocus_2_2","photo_glare":"flash_clipped"}.items():
        conditions()[condition](source).save(demo/f"{name}.png")
        record={**truth,"id":name,"augmentation":condition,"source":"Team synthetic study demo; not a real phone photo"}
        (demo/f"{name}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    print("4 synthetic photo examples generated")


if __name__=="__main__":main()

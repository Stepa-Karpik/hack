"""Deterministic synthetic documents; no genuine personal data or official seals."""
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .schema import SCHEMAS

def font_path():
    for path in ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(path).exists(): return path
    raise RuntimeError("Установите шрифт Arial или DejaVu Sans с кириллицей.")

def values(rng):
    surnames = ["Иванов", "Петров", "Смирнов", "Соколов", "Волков", "Орлов", "Кузнецов", "Зайцев", "Морозов", "Лебедев"]
    names = ["Иван", "Алексей", "Андрей", "Дмитрий", "Михаил", "Павел", "Никита"]
    patronymics = ["Иванович", "Петрович", "Алексеевич", "Сергеевич", "Андреевич"]
    def full_name(): return f"{rng.choice(surnames)} {rng.choice(names)} {rng.choice(patronymics)}"
    start, end = rng.randint(1, 25), rng.randint(1, 25)
    return {
        "student_name": full_name(), "university": rng.choice(["Учебный университет Северный", "Учебный институт Восточный", "Демонстрационный университет"]),
        "program": rng.choice(["09.03.01 Информатика", "38.03.01 Экономика", "01.03.02 Прикладная математика"]),
        "study_form": rng.choice(["очная", "заочная", "очно-заочная"]),
        "study_period": "01.09.2024 - 30.06.2026", "document_number": f"УЧ-{rng.randint(100,9999)}",
        "issue_date": f"{rng.randint(1,28):02d}.{rng.randint(1,12):02d}.2026",
        "group": f"ИТ-{rng.randint(10,99)}", "course": str(rng.randint(1,5)),
        "reason": rng.choice(["по состоянию здоровья", "по семейным обстоятельствам", "в связи с уходом за ребёнком"]),
        "start_date": f"{start:02d}.10.2026", "end_date": f"{end:02d}.10.2027",
        "application_date": "05.10.2026", "organization": rng.choice(["Учебное ООО Альфа", "Учебное ООО Вектор", "Учебный центр Практика"]),
        "practice_period": "01.06.2026 - 30.06.2026", "supervisor": full_name(),
        "grade": rng.choice(["отлично", "хорошо", "удовлетворительно"]),
    }

def signature(draw, rng, box):
    x, y, w, h = box
    color = rng.choice(["#153b88", "#25364e", "#121212"])
    points = [(x+i*w/28, y+h/2+rng.uniform(-h*.42,h*.42)) for i in range(29)]
    draw.line(points, fill=color, width=rng.randint(2,4), joint="curve")
    for _ in range(rng.randint(2,5)):
        px, py = x+rng.uniform(0,w*.7), y+rng.uniform(0,h*.5)
        draw.arc((px,py,px+w*.25,py+h*.65), 0, 320, fill=color, width=2)
    draw.line((x,y+h*.8,x+w,y+h*.65),fill=color,width=2)

def stamp(draw, rng, box):
    x,y,w,h = box
    ink = rng.choice(["#24479a", "#493590", "#303030"])
    draw.ellipse((x,y,x+w,y+h), outline=ink,width=3)
    draw.ellipse((x+8,y+8,x+w-8,y+h-8),outline=ink,width=2)
    small = ImageFont.truetype(font_path(), max(11,int(w/10)))
    draw.text((x+w*.12,y+h*.36),"УЧЕБНАЯ",font=small,fill=ink)
    draw.text((x+w*.19,y+h*.56),"ПЕЧАТЬ",font=small,fill=ink)

def visual_zone(seed, split="train", force=None):
    rng = random.Random(seed)
    # Split-specific distributions include black marks and more difficult compression.
    image = Image.new("RGB", (600,240), rng.choice(["white", "#faf7f0", "#efefef"]))
    draw = ImageDraw.Draw(image)
    f = ImageFont.truetype(font_path(), rng.randint(16,23))
    draw.text((20,rng.randint(10,30)),"Подпись руководителя: __________",font=f,fill="#303030")
    draw.text((420,20),"М.П.",font=f,fill="#303030")
    has_signature, has_stamp = rng.random() < .5, rng.random() < .5
    if force is not None:has_signature,has_stamp=force
    if has_signature: signature(draw,rng,(rng.randint(60,180),rng.randint(65,110),rng.randint(120,220),rng.randint(35,70)))
    if has_stamp: stamp(draw,rng,(rng.randint(330,450),rng.randint(55,95),rng.randint(95,130),rng.randint(95,130)))
    # Hard negatives: ruled lines, circles/logos and printed names, not signatures.
    if rng.random()<.4:
        draw.text((25,190),"Иванов И.И. / учебный образец",font=f,fill="#333333")
    if rng.random()<.3:
        draw.rectangle((10,65,55,120),outline="#28518d",width=2)
        draw.line((12,68,53,118),fill="#28518d",width=3)
    if rng.random()<.3:
        image=image.filter(ImageFilter.GaussianBlur(rng.uniform(.2,1.2)))
    return image,[float(has_signature),float(has_stamp)]

def document(seed, template=0, document_type=None, degrade=False,missing_rate=.13,force_marks=None,omitted=()):
    rng=random.Random(seed)
    kind=document_type or rng.choice(list(SCHEMAS))
    data=values(rng)
    image=Image.new("RGB",(1000,1400),"white")
    draw=ImageDraw.Draw(image)
    text_font=ImageFont.truetype(font_path(),rng.randint(23,28))
    title_font=ImageFont.truetype(font_path(),30)
    draw.text((60,40),"УЧЕБНЫЙ ОБРАЗЕЦ / ВЫМЫШЛЕННЫЕ ДАННЫЕ",font=ImageFont.truetype(font_path(),19),fill="#666666")
    draw.text((60,115),SCHEMAS[kind]["title"],font=title_font,fill="black")
    rows=[]
    keys=list(SCHEMAS[kind]["fields"])
    random.Random(template+100).shuffle(keys)
    y=220
    for key in keys:
        aliases=SCHEMAS[kind]["fields"][key]
        label=aliases[template % len(aliases)]
        value=data[key]
        if rng.random()<missing_rate or key in omitted:
            data[key]=None
            continue
        separator=[": "," = ",":  "][template % 3]
        line=label+separator+value
        x=60+(template%3)*12
        draw.text((x,y),line,font=text_font,fill="black")
        box=list(draw.textbbox((x,y),line,font=text_font))
        rows.append({"text":line,"confidence":1.,"bbox":box,"page":0,"field":key})
        y+=rng.randint(77,95)
    # Footer position matches the visual model's explicitly documented ROI.
    footer, marks=visual_zone(seed+9981,force=force_marks)
    footer=footer.resize((900,360))
    image.paste(footer,(50,1030))
    for key,flag in zip(["signature","stamp"],marks):
        if key in SCHEMAS[kind]["visual"]: data[key]=bool(flag)
    if degrade:
        image=image.filter(ImageFilter.GaussianBlur(.55))
    return image,{"id":str(seed),"template":template,"type":kind,"fields":{k:data[k] for k in keys+SCHEMAS[kind]["visual"]},"lines":rows}


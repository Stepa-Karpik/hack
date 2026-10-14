"""Original natural-looking Russian pages for language-only OCR adaptation (v5).

New relative to v4b: real-distribution surnames (Wikidata, CC0) instead of
syllable names; Russian Wikipedia prose (CC BY-SA 4.0) as natural dense text;
~30 installed Cyrillic font families with a *font-family-disjoint* held-out
split; varied label vocabularies, page sizes, margins, alignment, two-column
prose, and mild scan degradations. Surnames, articles and seeds are disjoint
between splits. No organizer or user document pixels/values are read.
"""
import argparse
import hashlib
import io
import json
import random
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = 'C:/Windows/Fonts/'
FAMILIES = {
    # family: (regular, bold, italic) — bold/italic optional
    'times': ('times.ttf', 'timesbd.ttf', 'timesi.ttf'), 'cambria': ('cambria.ttc', 'cambriab.ttf', 'cambriai.ttf'),
    'constantia': ('constan.ttf', 'constanb.ttf', 'constani.ttf'), 'palatino': ('pala.ttf', 'palab.ttf', 'palai.ttf'),
    'bookantiqua': ('BKANT.TTF', 'ANTQUAB.TTF', 'ANTQUAI.TTF'), 'century': ('CENTURY.TTF', None, None),
    'garamond': ('GARA.TTF', 'GARABD.TTF', 'GARAIT.TTF'), 'sitka': ('SitkaVF.ttf', None, 'SitkaVF-Italic.ttf'),
    'arial': ('arial.ttf', 'arialbd.ttf', 'ariali.ttf'), 'arialnarrow': ('ARIALN.TTF', 'ARIALNB.TTF', 'ARIALNI.TTF'),
    'calibri': ('calibri.ttf', 'calibrib.ttf', 'calibrii.ttf'), 'corbel': ('corbel.ttf', 'corbelb.ttf', 'corbeli.ttf'),
    'verdana': ('verdana.ttf', 'verdanab.ttf', 'verdanai.ttf'), 'tahoma': ('tahoma.ttf', 'tahomabd.ttf', None),
    'trebuchet': ('trebuc.ttf', 'trebucbd.ttf', 'trebucit.ttf'), 'segoe': ('segoeui.ttf', 'segoeuib.ttf', 'segoeuii.ttf'),
    'centurygothic': ('GOTHIC.TTF', 'GOTHICB.TTF', 'GOTHICI.TTF'), 'bahnschrift': ('bahnschrift.ttf', None, None),
    'courier': ('cour.ttf', 'courbd.ttf', 'couri.ttf'), 'consolas': ('consola.ttf', 'consolab.ttf', 'consolai.ttf'),
    # held-out families (never rendered in train)
    'georgia': ('georgia.ttf', 'georgiab.ttf', 'georgiai.ttf'), 'bookman': ('BOOKOS.TTF', 'BOOKOSB.TTF', 'BOOKOSI.TTF'),
    'sylfaen': ('sylfaen.ttf', None, None), 'candara': ('Candara.ttf', 'Candarab.ttf', 'Candarai.ttf'),
    'franklin': ('framd.ttf', None, 'framdit.ttf'), 'microsoftsans': ('micross.ttf', None, None),
    'cascadiamono': ('CascadiaMono.ttf', None, None),
}
HELDOUT = {'georgia', 'bookman', 'sylfaen', 'candara', 'franklin', 'microsoftsans', 'cascadiamono'}
MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
MALE = ['Александр', 'Алексей', 'Андрей', 'Антон', 'Артём', 'Богдан', 'Вадим', 'Валерий', 'Василий', 'Виктор', 'Виталий',
        'Владимир', 'Владислав', 'Вячеслав', 'Георгий', 'Глеб', 'Григорий', 'Даниил', 'Денис', 'Дмитрий', 'Евгений', 'Егор',
        'Иван', 'Игорь', 'Илья', 'Кирилл', 'Константин', 'Лев', 'Леонид', 'Максим', 'Марк', 'Матвей', 'Михаил', 'Никита',
        'Николай', 'Олег', 'Павел', 'Пётр', 'Роман', 'Руслан', 'Семён', 'Сергей', 'Станислав', 'Степан', 'Тимур', 'Фёдор',
        'Юрий', 'Ярослав', 'Эдуард', 'Анатолий', 'Борис', 'Геннадий', 'Захар', 'Тимофей', 'Арсений', 'Всеволод', 'Ринат']
FEMALE = ['Александра', 'Алина', 'Алиса', 'Анастасия', 'Анна', 'Валентина', 'Валерия', 'Вера', 'Вероника', 'Виктория',
          'Галина', 'Дарья', 'Диана', 'Ева', 'Евгения', 'Екатерина', 'Елена', 'Елизавета', 'Жанна', 'Зоя', 'Инна', 'Ирина',
          'Карина', 'Кира', 'Ксения', 'Лариса', 'Любовь', 'Людмила', 'Маргарита', 'Марина', 'Мария', 'Надежда', 'Наталья',
          'Нина', 'Оксана', 'Ольга', 'Полина', 'Светлана', 'София', 'Таисия', 'Татьяна', 'Ульяна', 'Юлия', 'Яна', 'Эльвира']
PATRONYMICS = [('Александрович', 'Александровна'), ('Алексеевич', 'Алексеевна'), ('Андреевич', 'Андреевна'),
               ('Антонович', 'Антоновна'), ('Борисович', 'Борисовна'), ('Вадимович', 'Вадимовна'), ('Васильевич', 'Васильевна'),
               ('Викторович', 'Викторовна'), ('Владимирович', 'Владимировна'), ('Геннадьевич', 'Геннадьевна'),
               ('Григорьевич', 'Григорьевна'), ('Дмитриевич', 'Дмитриевна'), ('Евгеньевич', 'Евгеньевна'), ('Иванович', 'Ивановна'),
               ('Игоревич', 'Игоревна'), ('Константинович', 'Константиновна'), ('Максимович', 'Максимовна'),
               ('Михайлович', 'Михайловна'), ('Николаевич', 'Николаевна'), ('Олегович', 'Олеговна'), ('Павлович', 'Павловна'),
               ('Петрович', 'Петровна'), ('Романович', 'Романовна'), ('Сергеевич', 'Сергеевна'), ('Степанович', 'Степановна'),
               ('Юрьевич', 'Юрьевна'), ('Фёдорович', 'Фёдоровна'), ('Анатольевич', 'Анатольевна'), ('Леонидович', 'Леонидовна'),
               ('Рустамович', 'Рустамовна'), ('Ильич', 'Ильинична'), ('Кузьмич', 'Кузьминична')]
ORG_WORDS = ['Северный', 'Волжский', 'Уральский', 'Сибирский', 'Балтийский', 'Приморский', 'Центральный', 'Южный',
             'Камский', 'Донской', 'Окский', 'Енисейский', 'Байкальский', 'Невский', 'Тверской', 'Ладожский']
ORG_KINDS = ['государственный университет', 'технический университет', 'педагогический университет',
             'аграрный университет', 'институт экономики и права', 'политехнический колледж', 'медицинский университет']
COMPANIES = ['ООО', 'АО', 'ПАО', 'ФГБУ', 'МУП', 'ГБУЗ', 'ИП']
COMPANY_NAMES = ['Вектор', 'Горизонт', 'Северсталь-Сервис', 'ТехноПарк', 'Ладья', 'Меридиан-Строй', 'Альфа-Логистик',
                 'Кедр', 'Импульс', 'Гранит', 'Росинка', 'Сфера', 'Восход', 'Полюс', 'Магистраль', 'Энергия',
                 'Пульсар', 'Ирбис', 'Стрела', 'Феникс', 'Атлант', 'Заря', 'Квант', 'Орион', 'Рубин', 'Сокол']
PROGRAMS = ['09.03.01 Информатика и вычислительная техника', '38.03.01 Экономика', '40.03.01 Юриспруденция',
            '01.03.02 Прикладная математика и информатика', '44.03.01 Педагогическое образование',
            '13.03.02 Электроэнергетика и электротехника', '08.03.01 Строительство', '42.03.02 Журналистика',
            '15.03.01 Машиностроение', '37.03.01 Психология', '45.03.02 Лингвистика', '27.03.04 Управление в технических системах',
            '05.03.06 Экология и природопользование', '19.03.04 Технология продукции и организация общественного питания']
REASONS = ['по состоянию здоровья', 'по семейным обстоятельствам', 'в связи с призывом на военную службу',
           'в связи с беременностью и родами', 'по уходу за ребёнком', 'в связи с длительной командировкой',
           'по медицинским показаниям', 'в связи с тяжёлым материальным положением']
LABELS = {
    'name': ['ФИО студента', 'Ф.И.О.', 'Фамилия, имя, отчество', 'Обучающийся', 'Студент(ка)', 'ФИО'],
    'group': ['Группа', 'Учебная группа', 'Академическая группа', 'Группа №'],
    'course': ['Курс', 'Курс обучения'],
    'number': ['Номер справки', 'Рег. №', 'Регистрационный номер', 'Исх. №', '№ документа'],
    'date': ['Дата выдачи', 'Дата', 'Дата составления', 'Выдана'],
    'org': ['Организация', 'Место прохождения практики', 'Название организации', 'Предприятие'],
    'program': ['Направление подготовки', 'Специальность', 'Образовательная программа'],
    'form': ['Форма обучения'],
    'grade': ['Оценка', 'Итоговая оценка', 'Результат'],
    'supervisor': ['Руководитель практики', 'ФИО руководителя', 'Руководитель от организации'],
    'phone': ['Телефон', 'Контактный телефон', 'Тел.'],
    'email': ['Электронная почта', 'E-mail', 'Почта'],
    'reason': ['Причина', 'Основание', 'Причина отпуска'],
    'period': ['Период', 'Срок', 'Период обучения', 'Сроки практики'],
}
TITLES = ['СПРАВКА', 'СПРАВКА ОБ ОБУЧЕНИИ', 'СПРАВКА О ПРАКТИКЕ', 'ЗАЯВЛЕНИЕ', 'ХАРАКТЕРИСТИКА', 'ВЫПИСКА ИЗ ПРИКАЗА',
          'СЛУЖЕБНАЯ ЗАПИСКА', 'УВЕДОМЛЕНИЕ', 'ПРОТОКОЛ', 'АКТ', 'ДОВЕРЕННОСТЬ', 'СПРАВКА-ВЫЗОВ', 'ОТЗЫВ РУКОВОДИТЕЛЯ',
          'ЗАЯВЛЕНИЕ НА АКАДЕМИЧЕСКИЙ ОТПУСК', 'ДОГОВОР О ПРАКТИКЕ', 'ЛИСТ ОЗНАКОМЛЕНИЯ']
GRADES = ['отлично', 'хорошо', 'удовлетворительно', 'зачтено', '5 (отлично)', '4 (хорошо)']


def clean_name(text):
    text = unicodedata.normalize('NFC', ''.join(ch for ch in unicodedata.normalize('NFD', text) if ch != '\u0301'))
    return text if re.fullmatch(r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?', text) else None


def sentences(article):
    keep = []
    for paragraph in article.split('\n'):
        paragraph = re.sub(r'\s+', ' ', paragraph).strip()
        if len(paragraph) < 60:
            continue  # headings, list stubs and captions
        for s in re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«(])', paragraph):
            s = s.strip().replace(chr(0x301), '').replace(chr(0xa0), ' ')
            latin = len(re.findall('[A-Za-z]', s))
            if not (25 <= len(s) <= 260) or not re.search('[а-яё]', s) or latin > .15 * len(s):
                continue
            if re.search(r'\s[.,;:)]|\(\s*\)|\(\s*[;,]|[|{}\[\]<>]|\s{2}|[Ͱ-Ͽ֐-ۿ　-鿿]', s):
                continue  # removed templates/links leave broken punctuation
            keep.append(s)
    return keep


class Pools:
    def __init__(self, surnames, articles, rng):
        self.surnames, self.articles, self.rng = surnames, articles, rng

    def person(self):
        r = self.rng
        surname = r.choice(self.surnames)
        female = surname.endswith(('ова', 'ева', 'ина', 'ая', 'ёва', 'ына')) or (r.random() < .5 and surname.endswith(('ко', 'ук', 'юк', 'их', 'ых', 'дзе', 'ян')))
        if not female and surname.endswith(('ов', 'ев', 'ин', 'ёв', 'ын')) and r.random() < .45:
            surname, female = surname + 'а', True
        if not female and surname.endswith('ский') and r.random() < .45:
            surname, female = surname[:-4] + 'ская', True
        first = r.choice(FEMALE if female else MALE)
        patronymic = r.choice(PATRONYMICS)[int(female)]
        style = r.random()
        if style < .7:
            return f'{surname} {first} {patronymic}'
        if style < .85:
            return f'{surname} {first[0]}. {patronymic[0]}.'
        return f'{first[0]}.{patronymic[0]}. {surname}'

    def date(self):
        r = self.rng
        y, m, d = r.randrange(2019, 2031), r.randrange(1, 13), r.randrange(1, 29)
        return r.choice([f'{d:02d}.{m:02d}.{y}', f'{d} {MONTHS[m-1]} {y} г.', f'«{d:02d}» {MONTHS[m-1]} {y} г.',
                         f'{d} {MONTHS[m-1]} {y} года', f'{y}-{m:02d}-{d:02d}', f'{d:02d}/{m:02d}/{y}', f'{d:02d}.{m:02d}.{y} г.'])

    def org(self):
        r = self.rng
        if r.random() < .5:
            return f'{r.choice(ORG_WORDS)} {r.choice(ORG_KINDS)}'
        return f'{r.choice(COMPANIES)} «{r.choice(COMPANY_NAMES)}»'

    def code(self):
        r = self.rng
        letters = ''.join(r.choice('АБВГДЕИКЛМНОПРСТУФЭЮЯ') for _ in range(r.randrange(1, 4)))
        return r.choice([f'{letters}-{r.randrange(10, 99)}-{r.randrange(1, 9)}', f'{r.randrange(1, 9999)}/{r.randrange(1, 99)}-{letters.lower()}',
                         f'{letters}-{r.randrange(100, 99999)}', f'{r.randrange(100, 9999)}', f'{letters}{r.randrange(10, 999)}'])

    def phone(self):
        r = self.rng
        return f'+7 ({r.randrange(900, 999)}) {r.randrange(100, 999)}-{r.randrange(10, 99)}-{r.randrange(10, 99)}'

    def prose(self, count):
        art = self.rng.choice(self.articles)
        start = self.rng.randrange(0, max(1, len(art) - count))
        return art[start:start + count]

    def value(self, kind):
        r = self.rng
        return {'name': self.person, 'supervisor': self.person, 'group': self.code, 'number': self.code,
                'course': lambda: str(r.randrange(1, 6)), 'date': self.date, 'org': self.org,
                'program': lambda: r.choice(PROGRAMS), 'form': lambda: r.choice(['очная', 'заочная', 'очно-заочная']),
                'grade': lambda: r.choice(GRADES), 'phone': self.phone,
                'email': lambda: f'{r.choice(["student", "info", "dekanat", "pr"])}{r.randrange(1, 999)}@example.ru',
                'reason': lambda: r.choice(REASONS), 'period': lambda: f'{self.date()} – {self.date()}'}[kind]()


def wrap(draw, text, font, width):
    words, lines, line = text.split(), [], ''
    for w in words:
        trial = (line + ' ' + w).strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def compose(pools, rng):
    """Return a list of blocks: (kind, text, style) in reading order."""
    blocks = []
    if rng.random() < .7:
        org = pools.org()
        blocks.append(('header', org.upper() if rng.random() < .4 else org, 'bold' if rng.random() < .5 else 'regular'))
        if rng.random() < .5:
            blocks.append(('header', f'{rng.randrange(100000, 999999)}, г. {rng.choice(["Казань", "Пермь", "Томск", "Самара", "Омск", "Тверь", "Курск", "Иркутск"])}, ул. {rng.choice(["Ленина", "Гагарина", "Садовая", "Мира", "Советская", "Школьная"])}, д. {rng.randrange(1, 120)}', 'regular'))
    if rng.random() < .6:
        blocks.append(('line', f'{pools.date()} № {pools.code()}', 'regular'))
    blocks.append(('title', rng.choice(TITLES), 'bold'))
    order = rng.sample(['fields', 'prose', 'fields2'], 3) if rng.random() < .5 else ['prose', 'fields']
    for part in order:
        if part.startswith('fields'):
            kinds = rng.sample(list(LABELS), rng.randrange(3, 8))
            for k in kinds:
                value = '' if rng.random() < .12 else pools.value(k)
                sep = rng.choice([': ', ': ', ' — ', ' '])
                if not value:
                    sep = ': ' if sep.strip() == '' else sep
                blocks.append(('field', rng.choice(LABELS[k]) + sep + value, 'regular'))
        elif part == 'prose':
            text = ' '.join(pools.prose(rng.randrange(2, 7)))
            if rng.random() < .5:
                text = f'Настоящая справка выдана {pools.person()} в том, что {text[0].lower() + text[1:]}'
            blocks.append(('para', text, 'regular'))
    if rng.random() < .6:
        role = rng.choice(['Декан факультета', 'Руководитель практики', 'Секретарь', 'Начальник отдела кадров', 'Студент', 'Директор'])
        blocks.append(('sign', f'{role} ____________ {pools.person()}', 'regular'))
    if rng.random() < .3:
        blocks.append(('line', 'М.П.', 'regular'))
    return blocks


def render(blocks, family, rng, dense=False):
    width, height = rng.choice([(1240, 1754), (1536, 2048), (1654, 2339), (1191, 1684)])
    paper = tuple(rng.randrange(236, 256) for _ in range(3)) if rng.random() < .5 else (255, 255, 255)
    ink = tuple([rng.randrange(0, 60)] * 3) if rng.random() < .8 else (rng.randrange(10, 40), rng.randrange(20, 50), rng.randrange(80, 140))
    image = Image.new('RGB', (width, height), paper)
    draw = ImageDraw.Draw(image)
    files = FAMILIES[family]
    size = int(rng.uniform(.0145, .024) * width) if not dense else int(rng.uniform(.0125, .017) * width)
    fonts = {style: ImageFont.truetype(FONTS + (files[i] or files[0]), size + (4 if style == 'title' else 0))
             for i, style in enumerate(['regular', 'bold', 'italic'])}
    fonts['title'] = ImageFont.truetype(FONTS + (files[1] or files[0]), int(size * rng.uniform(1.05, 1.35)))
    margin = int(width * rng.uniform(.07, .13))
    right = width - int(width * rng.uniform(.07, .12))
    y = int(height * rng.uniform(.04, .1))
    leading = rng.uniform(1.25, 1.7)
    lines, boxes, owners = [], [], []
    two_col = dense and rng.random() < .3
    for block_id, (kind, text, style) in enumerate(blocks):
        font = fonts['title'] if kind == 'title' else fonts['bold'] if style == 'bold' else fonts['regular']
        if kind == 'para' and rng.random() < .15:
            font = fonts['italic']
        avail = right - margin
        if kind == 'para' and two_col:
            avail = (right - margin) // 2 - 20
        wrapped = wrap(draw, text, font, avail) if kind in {'para', 'header', 'field', 'sign'} else [text]
        if kind == 'para' and two_col:
            half = (len(wrapped) + 1) // 2
            cols = [wrapped[:half], wrapped[half:]]
            col_y = y
            for c, col in enumerate(cols):
                yy = col_y
                x0 = margin + c * ((right - margin) // 2 + 20)
                for line in col:
                    box = draw.textbbox((x0, yy), line, font=font)
                    draw.text((x0, yy), line, font=font, fill=ink)
                    lines.append(line); boxes.append(box); owners.append([block_id, kind, c])
                    yy += int(font.size * leading)
                y = max(y, yy)
            y += int(font.size * .6)
            continue
        for line in wrapped:
            if kind == 'title' or (kind == 'header' and rng.random() < .5):
                x = (width - draw.textlength(line, font=font)) / 2
            elif kind == 'sign' and rng.random() < .3:
                x = right - draw.textlength(line, font=font)
            else:
                x = margin + (int(size * 2) if kind == 'para' and line is wrapped[0] and rng.random() < .5 else 0)
            box = draw.textbbox((x, y), line, font=font)
            draw.text((x, y), line, font=font, fill=ink)
            lines.append(line); boxes.append(box); owners.append([block_id, kind, 0])
            y += int(font.size * leading)
        y += int(size * rng.uniform(.3, 1.2))
        if y > height * .95:
            break
    return image, lines, boxes, size, owners


def degrade(image, rng):
    ops = []
    if rng.random() < .35:
        angle = rng.uniform(-.7, .7)
        image = image.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=image.getpixel((2, 2)))
        ops.append(f'rotate{angle:.2f}')
    if rng.random() < .35:
        r = rng.uniform(.3, .9)
        image = image.filter(ImageFilter.GaussianBlur(r))
        ops.append(f'blur{r:.2f}')
    if rng.random() < .4:
        q = rng.randrange(45, 85)
        buf = io.BytesIO()
        image.save(buf, 'JPEG', quality=q)
        image = Image.open(io.BytesIO(buf.getvalue())).convert('RGB')
        ops.append(f'jpeg{q}')
    return image, ops


def valid(lines, boxes, width, height):
    for box in boxes:
        if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            return False
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            p, q = boxes[a], boxes[b]
            if p[0] < q[2] and q[0] < p[2] and p[1] < q[3] and q[1] < p[3]:
                return False
    return all(line.strip() for line in lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--train', type=int, default=360)
    p.add_argument('--val', type=int, default=36)
    p.add_argument('--test', type=int, default=48)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Fresh output directory required')
    args.output.mkdir(parents=True)
    names = json.loads((args.sources / 'wikidata_names.json').read_text(encoding='utf-8'))
    surnames = sorted({n for n in map(clean_name, names['family']) if n})
    wiki = json.loads((args.sources / 'ruwiki_rows.json').read_text(encoding='utf-8'))['articles']
    articles = [(a['title'], sentences(a['text'])) for a in wiki]
    articles = [a for a in articles if len(a[1]) >= 4]
    split_rng = random.Random(20261014)
    split_rng.shuffle(surnames)
    split_rng.shuffle(articles)
    n_s, n_a = len(surnames), len(articles)
    parts = {'train': (surnames[:int(n_s * .7)], articles[:int(n_a * .7)]),
             'val': (surnames[int(n_s * .7):int(n_s * .8)], articles[int(n_a * .7):int(n_a * .8)]),
             'test': (surnames[int(n_s * .8):], articles[int(n_a * .8):])}
    train_fams = sorted(set(FAMILIES) - HELDOUT)
    manifest = {'scope': 'Original synthetic natural-looking pages; not real documents', 'heldout_families': sorted(HELDOUT),
                'train_families': train_fams, 'surname_source': 'Wikidata P1705 ru labels of family names (CC0)',
                'prose_source': 'ru.wikipedia random article extracts (CC BY-SA 4.0), sentence-level, attribution in sources file',
                'splits': {}}
    seen_sha = set()
    for split, count, base_seed in [('train', args.train, 505000), ('val', args.val, 506000), ('test', args.test, 507000)]:
        sn, arts = parts[split]
        rows = []
        i = 0
        seed = base_seed
        while len(rows) < count:
            rng = random.Random(seed)
            seed += 1
            pools = Pools(sn, [a[1] for a in arts], rng)
            # val uses train families (in-family generalisation); test uses held-out families only.
            family = rng.choice(sorted(HELDOUT) if split == 'test' else train_fams)
            dense = rng.random() < .3
            blocks = compose(pools, rng) if not dense else [('title', rng.choice(TITLES), 'bold')] + [
                ('para', ' '.join(pools.prose(rng.randrange(3, 7))), 'regular') for _ in range(rng.randrange(2, 5))]
            image, lines, boxes, size, owners = render(blocks, family, rng, dense)
            if not valid(lines, boxes, image.width, image.height) or len(lines) < 4:
                continue
            image, ops = degrade(image, rng)
            target = '\n'.join(lines)
            name = f'{split}-{i:03d}.png'
            image.save(args.output / name)
            digest = hashlib.sha256((args.output / name).read_bytes()).hexdigest()
            if digest in seen_sha:
                raise ValueError('Duplicate pixels')
            seen_sha.add(digest)
            rows.append({'image': name, 'sha256': digest, 'seed': seed - 1, 'family': family, 'font_px': size,
                         'dense': dense, 'degradations': ops, 'size': [image.width, image.height],
                         'target_text': target, 'lines': lines, 'line_blocks': owners, 'boxes': [list(map(int, b)) for b in boxes], 'kind': 'natural_page_v5'})
            i += 1
        (args.output / f'{split}.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
        manifest['splits'][split] = {'count': len(rows), 'surnames': len(sn), 'articles': [a[0] for a in arts],
                                     'families': sorted({r['family'] for r in rows})}
        print(split, len(rows), flush=True)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

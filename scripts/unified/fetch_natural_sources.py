"""Text sources for the v5 page generator: Wikidata names (CC0) and Russian Wikipedia rows (CC BY-SA 4.0).

    python -m scripts.unified.fetch_natural_sources work/ocr-v5/sources

Writes wikidata_names.json and ruwiki_rows.json, the inputs of prepare_natural_pages.py
and prepare_mark_pages.py (--sources). Only text is downloaded; no document images.
"""
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {'User-Agent': 'online-dekanat-research/1.0 (synthetic OCR training pages)'}


def get(url, timeout=170):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def wikidata_names():
    names = {}
    for label, qid in [('family', 'Q101352'), ('male', 'Q12308941'), ('female', 'Q11879590')]:
        query = f'SELECT DISTINCT ?l WHERE {{ ?x wdt:P31 wd:{qid}; wdt:P1705 ?l. FILTER(lang(?l)="ru") }} LIMIT 20000'
        data = get('https://query.wikidata.org/sparql?format=json&query=' + urllib.parse.quote(query))
        names[label] = sorted({b['l']['value'] for b in data['results']['bindings']})
        print(label, len(names[label]), flush=True)
    return {'license': 'CC0 (Wikidata)', 'retrieved': time.strftime('%Y-%m-%d'), **names}


def wikipedia_rows(windows=12, seed=20261014):
    """Random 100-article windows of wikimedia/wikipedia 20231101.ru via the datasets server."""
    rng = random.Random(seed)
    articles = []
    for k in range(windows):
        offset = rng.randrange(0, 1_900_000)
        url = ('https://datasets-server.huggingface.co/rows?dataset=wikimedia/wikipedia&config=20231101.ru'
               f'&split=train&offset={offset}&length=100')
        for _ in range(3):
            try:
                data = get(url, timeout=90)
                break
            except Exception as error:
                print('retry', error, flush=True)
                time.sleep(5)
        else:
            continue
        for row in data['rows']:
            text = row['row']['text']
            if len(text) > 1500:
                articles.append({'title': row['row']['title'], 'url': row['row']['url'], 'text': text[:8000]})
        print(k, offset, len(articles), flush=True)
    return {'license': 'CC BY-SA 4.0 / GFDL (Wikipedia contributors), via wikimedia/wikipedia 20231101.ru',
            'articles': articles}


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'wikidata_names.json').write_text(json.dumps(wikidata_names(), ensure_ascii=False), encoding='utf-8')
    (out / 'ruwiki_rows.json').write_text(json.dumps(wikipedia_rows(), ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()

"""Logical separation of adjacent empty public-schema labels; no value edits."""
import re
from scripts.participantkit.format_v1 import LABELS
from scripts.unified.contract import KEYS, MARKS
from scripts.unified.text_binding import TITLES


def separate_empty_labels(text):
    kinds={kind for kind,title in TITLES.items() if any(line.strip().casefold()==title.casefold() for line in text.splitlines())}
    if len(kinds)!=1:
        return text, []
    kind=kinds.pop()
    labels={LABELS[key].casefold():key for key in KEYS[kind] if key not in MARKS}
    patterns='|'.join(re.escape(LABELS[key]) for key in KEYS[kind] if key not in MARKS)
    pattern=re.compile(r'(?m)^(?P<prefix>[ \t]*)(?P<first>'+patterns+r')(?P<colon1>[ \t]*:)(?P<separator>[ \t]+)(?P<second>'+patterns+r')(?P<colon2>[ \t]*:)(?P<suffix>[ \t]*)$',re.I)
    edits=[]
    def replacement(match):
        first,second=labels[match['first'].casefold()],labels[match['second'].casefold()]
        if first==second:
            return match[0]
        begin,end=match.span('separator')
        edits.append(dict(first_key=first,second_key=second,raw_span=[begin,end],
                          operation='whitespace_to_logical_newline',geometry_verified=False))
        value=match[0]
        offset=begin-match.start()
        return value[:offset]+'\n'+' '*(end-begin-1)+value[offset+end-begin:]
    result=pattern.sub(replacement,text)
    assert len(result)==len(text)
    assert re.sub(r'\s','',result)==re.sub(r'\s','',text)
    return result,edits


def separate_label_runs(text):
    """v2: split one physical line holding several distinct public-schema labels.

    Generalises separate_empty_labels to runs such as
    "Начало периода обучения: Окончание периода обучения: Номер справки: УК-1".
    Only the single whitespace run before each later complete "Label:" becomes a
    logical newline; all non-whitespace characters, offsets and length are kept.
    Lines whose labels repeat, or that do not start with a known label, are left
    unchanged. Chosen after observing merged label lines (post-selection).
    """
    kinds = {kind for kind, title in TITLES.items() if any(line.strip().casefold() == title.casefold() for line in text.splitlines())}
    if len(kinds) != 1:
        return text, []
    kind = kinds.pop()
    names = [LABELS[key] for key in KEYS[kind] if key not in MARKS]
    keys = {LABELS[key].casefold(): key for key in KEYS[kind] if key not in MARKS}
    alternatives = '|'.join(re.escape(n).replace(r'\ ', r'\s+') for n in sorted(names, key=len, reverse=True))
    label = re.compile(r'(?<![^\s])(' + alternatives + r')[ \t]*:', re.I)
    out, edits, offset = list(text), [], 0
    for line in text.split('\n'):
        starts = [m for m in label.finditer(line)]
        if len(starts) >= 2 and not line[:starts[0].start()].strip():
            found = [keys.get(re.sub(r'\s+', ' ', m[1]).casefold()) for m in starts]
            if None not in found and len(set(found)) == len(found):
                for m, key in zip(starts[1:], found[1:]):
                    gap_end = m.start()
                    gap_start = gap_end
                    while gap_start > 0 and line[gap_start - 1] in ' \t':
                        gap_start -= 1
                    if gap_start == gap_end:
                        continue
                    out[offset + gap_start] = '\n'
                    edits.append(dict(key=key, raw_span=[offset + gap_start, offset + gap_end],
                                      operation='whitespace_to_logical_newline', geometry_verified=False))
        offset += len(line) + 1
    result = ''.join(out)
    assert len(result) == len(text)
    assert re.sub(r'\s', '', result) == re.sub(r'\s', '', text)
    return result, edits

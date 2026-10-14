"""Conservative shadow helpers; not imported by deployed service."""
import math,re
from scripts.participantkit.labeled_fields import label_match,_box
from scripts.participantkit.crop_recovery import quoted
from scripts.participantkit.format_v1 import MISSING,norm


def box(line):
    result=_box(line)
    return result if result and all(math.isfinite(v) for v in result) else None


def select_rows(lines):
    starts=[p for p in lines if label_match(p.get('text','')) and label_match(p['text'])[0]=='university']
    if len(starts)!=1:return [],'unique_label_required'
    start=starts[0];literal=label_match(start['text'])[1];bounds=box(start)
    if not literal:return [],'empty_label'
    if quoted(literal):return [],'closed_name'
    if bounds is None:return [],'invalid_box'
    height=bounds[3]-bounds[1];parts=[start];bottom=bounds[3]
    for _ in range(2):
        near=[p for p in lines if box(p) and p.get('page',0)==start.get('page',0)
              and 0<=box(p)[1]-bottom<=height*1.2 and abs(box(p)[0]-bounds[0])<=height*2]
        near.sort(key=lambda p:box(p)[1])
        if not near:break
        row=[p for p in near if abs(box(p)[1]-box(near[0])[1])<=height*.5]
        if len(row)!=1:return [],'ambiguous_row'
        part=row[0]
        if label_match(part['text']) or ':' in part['text'] or re.search(r'макет|вымышлен|подпись|печать',part['text'],re.I):break
        parts.append(part);bottom=box(part)[3]
        if part['text'].strip().endswith('»'):break
    return (parts,'eligible') if len(parts)>1 else ([], 'no_wrapped_rows')


def visible_letters(value):
    # Only punctuation is ignored; k/x/F and every other visible letter remain.
    return norm(re.sub(r'[«»<>"\s]+',' ',value))


def accept_proposal(before,raw,binding,proposal,lines):
    if raw.get('status') in {'found','conflict'} or binding.get('status')=='conflict':
        return None,'preserve_found_or_conflict'
    if before==MISSING or quoted(before):return None,'preserve_empty_or_closed'
    parts,reason=select_rows(lines)
    if not parts:return None,reason
    offered=proposal.get('parts',[])
    if [(p.get('text'),p.get('bbox'),p.get('page',0)) for p in offered]!=[(p.get('text'),p.get('bbox'),p.get('page',0)) for p in parts]:
        return None,'selected_parts_disagree'
    candidate=proposal.get('accepted')
    if not quoted(candidate):return None,'no_balanced_consensus'
    prefix=label_match(parts[0]['text'])[1].split('«')[0].split('<')[0].strip()
    if not norm(candidate).startswith(norm(prefix)) or visible_letters(before)!=visible_letters(candidate):
        return None,'visible_letters_disagree'
    return candidate,'accepted_uncertain_punctuation_only'

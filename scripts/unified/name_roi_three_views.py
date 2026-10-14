"""Conservative revision: whole-line spotting must agree with both ROI views."""
import re

from scripts.participantkit.format_v1 import LABELS
from scripts.unified.name_roi import accept


def accept_three(old, audit, readings, whole_line, field):
    candidate, reason = accept(old, audit, readings)
    if candidate is None:
        return None, reason
    if field not in {'student_name', 'supervisor_name'} or not isinstance(whole_line, str):
        return None, 'missing_whole_line'
    match = re.fullmatch(re.escape(LABELS[field])+r'\s*:\s*(.+)', whole_line.strip(), re.I)
    if match is None or ' '.join(match[1].split()) != candidate:
        return None, 'whole_line_disagreement'
    return candidate, 'bounded_three_context_consensus'

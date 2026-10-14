"""Portable, anonymous text for documentation and public source exports."""
import re
from pathlib import Path

def anonymize(text):
    text=re.sub(r'https?://dekanat\.[A-Za-z0-9.-]+', 'https://dekanat.example.org',text)
    text=re.sub(r'(?<![\w.])dekanat\.[A-Za-z0-9.-]+','dekanat.example.org',text)
    text=re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])',
        lambda m:m[0] if m[0] in {'127.0.0.1','0.0.0.0','192.0.2.10'} else '192.0.2.10',text)
    # Normalize escaped Windows paths first, including JSON/docstring literals.
    text=re.sub(r'[CD]:[/\\]+Users[/\\]+[^/\\]+[/\\]+Downloads[/\\]+[^`"\r\n]*?[/\\]+online-dean-participants-v1',
        'data/external/participant-kit',text,flags=re.I)
    pattern=r'(?<![A-Za-z0-9])[CD]:[/\\][^\s`"<>|;]*'
    def path(match):
        value=match.group(0).replace('\\\\','/').replace('\\','/').rstrip()
        suffix=''
        while value and value[-1] in '.,):':suffix=value[-1]+suffix;value=value[:-1]
        lower=value.lower()
        if 'online-dean-participants-v1' in lower:
            tail=value[lower.index('online-dean-participants-v1')+len('online-dean-participants-v1'):]
            return 'data/external/participant-kit'+tail+suffix
        if '/venv/scripts/python.exe' in lower:return 'python'+suffix
        if '/models-cache' in lower:return 'models/cache'+value[lower.index('/models-cache')+13:]+suffix
        if '/notebook-sample' in lower:return 'data/external/notebooks'+value[lower.index('/notebook-sample')+16:]+suffix
        if '/online-dekanat/' in lower:
            tail=value[lower.index('/online-dekanat/')+16:]
            if tail.startswith('work/'):tail=tail[5:]
            return tail+suffix
        if '/windows/fonts/' in lower:return 'fonts/'+value.rsplit('/',1)[-1]+suffix
        return 'data/external'+suffix
    text=re.sub(pattern,path,text)
    account=Path.home().name
    if account and account.lower() not in {'root','user','users'}:
        text=re.sub(r'\b'+re.escape(account)+r'\b','local-account',text,flags=re.I)
    return text

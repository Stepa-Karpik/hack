import json
import zipfile
import re
from pathlib import Path
from scripts.documentation_privacy import anonymize

ROOT=Path(__file__).resolve().parents[1]

def test_private_path_with_spaces_is_portable_without_truncating_prose():
    raw='Dataset: `C:'+ '/Users/alice/Downloads/Chat Client/online-dean-participants-v1`. Keep 30 documents and 120 questions.'
    assert anonymize(raw)=='Dataset: `data/external/participant-kit`. Keep 30 documents and 120 questions.'
    raw='Checkpoint D:'+ '/project/online-dekanat/models/candidate.pt is isolated; metric 0.536 is unchanged.'
    assert anonymize(raw)=='Checkpoint models/candidate.pt is isolated; metric 0.536 is unchanged.'

def test_network_and_escaped_paths_do_not_expose_host_configuration():
    value=json.dumps({'path':'C:'+r'\Users\alice\Documents\online-dekanat\models\cache','server':'.'.join(['203','0','113','49']),'url':'https://'+'dekanat.'+'private.example'})
    result=json.loads(anonymize(value))
    assert result['path']=='models/cache' and result['server']=='192.0.2.10'
    assert result['url']=='https://dekanat.example.org'
    assert anonymize('http://127.0.0.1:8765')=='http://127.0.0.1:8765'

def test_public_documentation_and_source_export_are_anonymous():
    # Whatever documentation the checkout contains: README, docs/**, built web docs, source archive.
    texts=[p.read_text(encoding='utf-8-sig') for p in ROOT.glob('docs/**/*.md')]
    texts += [(ROOT/'README.md').read_text(encoding='utf-8')]
    texts += [p.read_text(encoding='utf-8') for p in (ROOT/'web/docs.json',ROOT/'web-native/docs.json') if p.exists()]
    for text in texts:
        assert 'по новой просьбе пользователя' not in text.lower() and 'путь получен от пользователя' not in text.lower()
    if (ROOT/'web/source.zip').exists():
        with zipfile.ZipFile(ROOT/'web/source.zip') as archive:
            texts += [archive.read(p).decode('utf-8-sig') for p in archive.namelist() if p.endswith(('.md','.json','.py','.conf','.service','.html','.js'))]
    account=Path.home().name.lower()
    for text in texts:
        lower=re.sub(r'github\.com/[\w.-]+','github.com/owner',text.lower())  # public repository links are expected
        assert not re.search(r'[cd]:[/\\]+users[/\\]+[^/\\\s\x22\x27]+[/\\]+',lower)
        if account not in {'root','user','users'}:assert account not in lower

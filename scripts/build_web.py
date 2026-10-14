"""Build local liquid-glass UI and the complete searchable documentation, no network."""
from pathlib import Path
import json
import hashlib
import re
import zipfile
from documentation_privacy import anonymize

def main():
    root=Path(__file__).resolve().parents[1];web=root/'web'
    vendor=(web/'vendor'/'daisyui-components.css').read_text(encoding='utf-8')
    theme=(web/'liquid-theme.css').read_text(encoding='utf-8')
    (web/'style.css').write_text(vendor+'\n'+theme,encoding='utf-8')
    prefix='\n'.join((web/'app.js').read_text(encoding='utf-8-sig').splitlines()[:5])
    (web/'app.js').write_text(prefix+'\n'+(web/'liquid-interactions.js').read_text(encoding='utf-8'),encoding='utf-8')
    docs=[]
    first=['LIQUID_GLASS.md','ARCHITECTURE.md','IMPLEMENTATION.md','PARTICIPANT_KIT.md','LOCAL_HTTP_API.md','RUNBOOK.md','DATASETS.md','SOURCES.md']
    files=sorted((root/'docs').glob('*.md'),key=lambda p:(first.index(p.name) if p.name in first else 100,p.name))
    for p in [root/'README.md']+files:
        content=anonymize(p.read_text(encoding='utf-8-sig'));heading=re.search(r'^#\s+(.+)$',content,re.M)
        docs.append({'id':p.stem.lower().replace('_','-'),'file':str(p.relative_to(root)).replace('\\','/'),
            'title':heading[1] if heading else p.stem,'content':content,
            'sha256':hashlib.sha256(content.encode('utf-8')).hexdigest(),
            'group':'Проект' if p.name in first or p.name=='README.md' else 'Исследования и журнал'})
    for p in [root/'configs/participant_v1.json',root/'requirements.lock.txt',root/'deploy/server-requirements.lock.txt',root/'web/vendor/manifest.json',root/'artifacts/data_registry.json',root/'LICENSE']:
        if p.is_file():docs.append({'id':p.stem.lower().replace('_','-')+'-reference','file':str(p.relative_to(root)).replace('\\','/'),
            'title':str(p.relative_to(root)).replace('\\','/'),'content':'# '+p.name+'\n\n```\n'+anonymize(p.read_text(encoding='utf-8-sig'))+'\n```',
            'sha256':hashlib.sha256(anonymize(p.read_text(encoding='utf-8-sig')).encode('utf-8')).hexdigest(),'group':'Конфигурация и лицензии'})
    inventory=[]
    for directory in ['dekanat','scripts','tests','configs','deploy','web','notebooks']:
        for p in sorted((root/directory).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py','.js','.html','.json','.css','.conf','.service','.ipynb'} and p.name!='docs.json':
                public=anonymize(p.read_text(encoding='utf-8-sig')).encode('utf-8')
                inventory.append('| `'+str(p.relative_to(root)).replace('\\','/')+'` | '+str(len(public))+' | `'+hashlib.sha256(public).hexdigest()+'` |')
    for p in [root/'app.py',root/'launch.ps1']:
        public=anonymize(p.read_text(encoding='utf-8-sig')).encode('utf-8')
        inventory.append('| `'+p.name+'` | '+str(len(public))+' | `'+hashlib.sha256(public).hexdigest()+'` |')
    docs.append({'id':'source-inventory','file':'generated/source-inventory.md','title':'Полный каталог кода','group':'Конфигурация и лицензии',
        'content':'# Полный каталог кода\n\nФайлы текущей сборки. Байты и SHA-256 позволяют проверить происхождение. Бинарные модели, исходные документы и секреты не публикуются.\n\n| Файл | Байт | SHA-256 |\n| --- | --- | --- |\n'+'\n'.join(inventory)})
    (web/'docs.json').write_text(json.dumps({'version':'liquid-glass-v4','documents':docs},ensure_ascii=False),encoding='utf-8')
    with zipfile.ZipFile(web/'source.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in [root/'README.md',root/'LICENSE',root/'requirements.txt',root/'requirements.lock.txt',root/'app.py',root/'launch.ps1']:
            archive.writestr('online-dekanat/'+p.name,anonymize(p.read_text(encoding='utf-8-sig')))
        for directory in ['dekanat','scripts','tests','configs','docs','web','deploy','notebooks']:
            for p in sorted((root/directory).rglob('*')):
                if p.is_file() and '__pycache__' not in p.parts and p.name!='source.zip':
                    name='online-dekanat/'+str(p.relative_to(root)).replace('\\','/')
                    if p.suffix in {'.md','.py','.js','.html','.json','.css','.conf','.service','.txt','.ps1','.ipynb'}:
                        archive.writestr(name,anonymize(p.read_text(encoding='utf-8-sig')))
                    else:archive.write(p,name)

if __name__=='__main__':main()

"""Public fixed-revision weight transfer with exact range and SHA validation."""
import concurrent.futures
import hashlib
from pathlib import Path


def download(repo,revision,filename,target,size,sha256,chunk_bytes=16*1024*1024):
    import requests
    if target.exists():raise ValueError('Never overwrite existing model weights')
    parts=target.parent/'.ranged'/filename
    parts.mkdir(parents=True,exist_ok=False)
    url=f'https://huggingface.co/{repo}/resolve/{revision}/{filename}'
    count=(size+chunk_bytes-1)//chunk_bytes
    def fetch(i):
        start=i*chunk_bytes;end=min(size,start+chunk_bytes)-1
        output=parts/f'{i:05d}.part'
        for attempt in range(3):
            try:
                with requests.get(url,params={'download':'true','range_part':str(i)},
                                  headers={'Range':f'bytes={start}-{end}'},stream=True,timeout=(15,40)) as response:
                    if response.status_code!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':
                        raise ValueError('Server did not honor the exact byte range')
                    written=0
                    with output.open('wb') as stream:
                        for data in response.iter_content(1024*1024):
                            written+=len(data)
                            if written>end-start+1:raise ValueError('Range exceeds expected size')
                            stream.write(data)
                    if written!=end-start+1:raise ValueError('Truncated range')
                return i
            except (requests.RequestException,ValueError):
                if attempt==2:raise
    done=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for _ in executor.map(fetch,range(count)):
            done+=1
            if done%16==0 or done==count:print(f'Verified byte ranges {done}/{count}',flush=True)
    temporary=target.with_suffix(target.suffix+'.verified-new')
    digest=hashlib.sha256()
    with temporary.open('xb') as stream:
        for i in range(count):
            with (parts/f'{i:05d}.part').open('rb') as part:
                while data:=part.read(1024*1024):digest.update(data);stream.write(data)
    if temporary.stat().st_size!=size or digest.hexdigest()!=sha256:
        raise ValueError('Assembled weights fail published LFS SHA')
    if target.exists():raise ValueError('Destination appeared during transfer')
    temporary.rename(target)

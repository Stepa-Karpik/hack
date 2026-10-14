import hashlib
import pytest
import requests
from scripts.unified.ranged_download import download


class Response:
    status_code=206
    def __init__(self,start,end,total,data):
        self.headers={'Content-Range':f'bytes {start}-{end}/{total}'};self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,_):yield self.data


def test_range_assembly_must_match_published_sha(monkeypatch,tmp_path):
    data=b'abcdefgh'
    def get(url,headers,**kwargs):
        start,end=map(int,headers['Range'][6:].split('-'))
        return Response(start,end,len(data),data[start:end+1])
    monkeypatch.setattr(requests,'get',get)
    target=tmp_path/'weights.safetensors'
    download('fixed/repo','revision','weights.safetensors',target,len(data),hashlib.sha256(data).hexdigest(),chunk_bytes=3)
    assert target.read_bytes()==data


def test_wrong_range_or_sha_never_becomes_usable_weights(monkeypatch,tmp_path):
    monkeypatch.setattr(requests,'get',lambda *args,**kwargs:Response(1,3,3,b'abc'))
    target=tmp_path/'bad-range.safetensors'
    with pytest.raises(ValueError):download('fixed/repo','revision',target.name,target,3,'0'*64)
    assert not target.exists()
    monkeypatch.setattr(requests,'get',lambda *args,**kwargs:Response(0,2,3,b'abc'))
    target=tmp_path/'bad-sha.safetensors'
    with pytest.raises(ValueError):download('fixed/repo','revision',target.name,target,3,'0'*64)
    assert not target.exists()

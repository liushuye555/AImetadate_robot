import hashlib
import math
import sqlite3
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from qq_onebot_whitelist.gilbert_obfuscation import curve_order, analyze_image, DETECTOR_VERSION
from qq_onebot_whitelist.maintenance import reclassify_possible_obfuscation, restore_confirmed_obfuscation
from qq_onebot_whitelist.store import Store


def fixture(tmp_path, reason='xiaofanqie_compressed', metadata=True):
    w,h=72,54
    raw=bytes((x*255//(w-1)+y*40)%256 for y in range(h) for x in range(w))
    order=curve_order(w,h);n=w*h;shift=round((math.sqrt(5)-1)/2*n)
    encoded=bytearray(n)
    for s in range(n):encoded[order[s]]=raw[order[(s+shift)%n]]
    source=tmp_path/'data'/'original.png';source.parent.mkdir(parents=True,exist_ok=True)
    info=PngInfo();info.add_text('parameters','Steps: 20, Size: 72x54')
    Image.frombytes('L',(w,h),bytes(encoded)).save(source,pnginfo=info if metadata else None)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    store=Store(tmp_path/'data'/'bot.db')
    store.record_image(scope='group:1',user_id='test-user',result={
        'sha256':digest,'format':'PNG','size':source.stat().st_size,'width':w,'height':h,
        'kept_path':str(source),'retention_reason':reason,'has_ai_metadata':metadata,'ai_source':'A1111' if metadata else None,
    },raw={})
    with sqlite3.connect(store.path) as conn:mid=conn.execute('SELECT id FROM images').fetchone()[0]
    store.save_obfuscation_score(digest,ratio=.4,layers=1,obfuscated=True,confidence='possible',version=0)
    return store,source,digest,mid,raw


def row(store):
    with sqlite3.connect(store.path) as conn:
        conn.row_factory=sqlite3.Row
        return dict(conn.execute('SELECT * FROM images').fetchone())


def test_old_compressed_cache_is_rechecked_restored_and_returns_to_ai_source(tmp_path,monkeypatch):
    store,source,digest,mid,raw=fixture(tmp_path)
    original_bytes=source.read_bytes()
    assert reclassify_possible_obfuscation(tmp_path,image_ids=[mid])==1
    record=row(store)
    assert record['retention_reason']=='xiaofanqie_obfuscated'
    assert record['context_reason']=='ai_metadata' and record['deobfuscated']==1
    assert record['size']==Path(record['kept_path']).stat().st_size
    with Image.open(record['kept_path']) as restored:
        assert restored.convert('L').tobytes()==raw
        assert restored.text['parameters']=='Steps: 20, Size: 72x54'
    backup=tmp_path/'data'/'images'/'obfuscation-originals'/digest[:2]/f'{digest}.png'
    assert backup.read_bytes()==original_bytes
    detail=store.obfuscation_details(digest)
    assert detail['direction']=='encode' and detail['detector_version']==DETECTOR_VERSION
    monkeypatch.setattr('qq_onebot_whitelist.maintenance.analyze_image',lambda *a:pytest.fail('already restored'))
    assert reclassify_possible_obfuscation(tmp_path,image_ids=[mid])==0


@pytest.mark.parametrize('unsupported',[False,True])
def test_failed_recheck_keeps_compressed_original_and_classification(tmp_path,monkeypatch,unsupported):
    store,source,digest,mid,raw=fixture(tmp_path,metadata=False)
    original=source.read_bytes()
    def failed(path):
        if unsupported:return None
        raise OSError('temporary read failure')
    monkeypatch.setattr('qq_onebot_whitelist.maintenance.analyze_image',failed)
    assert reclassify_possible_obfuscation(tmp_path,image_ids=[mid])==0
    assert row(store)['retention_reason']=='xiaofanqie_compressed'
    assert source.read_bytes()==original


def test_context_legacy_negative_cache_is_invalidated_and_repaired(tmp_path):
    store,source,digest,mid,raw=fixture(tmp_path,reason='prompt_bound',metadata=False)
    store.save_obfuscation_score(digest,ratio=.99,layers=None,obfuscated=False,confidence='none',version=0)
    assert restore_confirmed_obfuscation(tmp_path)==1
    assert row(store)['deobfuscated']==1
    assert store.obfuscation_details(digest)['direction']=='encode'


def test_rechecks_are_bounded_and_unsupported_cache_releases_next_batch(tmp_path,monkeypatch):
    store,source,digest,mid,raw=fixture(tmp_path,reason='positive_feedback',metadata=False)
    store.record_image(scope='group:1',user_id='test-user',result={'sha256':'other','format':'PNG','size':1,'width':8,'height':8,'kept_path':str(source),'retention_reason':'positive_feedback'},raw={})
    calls=[]
    def unsupported(path):calls.append(path);return None
    monkeypatch.setattr('qq_onebot_whitelist.maintenance.analyze_image',unsupported)
    assert restore_confirmed_obfuscation(tmp_path,max_rechecks=1)==0
    assert len(calls)==1
    assert restore_confirmed_obfuscation(tmp_path,max_rechecks=1)==0
    assert len(calls)==2
    assert restore_confirmed_obfuscation(tmp_path,max_rechecks=1)==0
    assert len(calls)==2


def test_damaged_first_record_does_not_starve_later_legacy_records(tmp_path,monkeypatch):
    store,source,digest,mid,raw=fixture(tmp_path,reason='positive_feedback',metadata=False)
    damaged=tmp_path/'data'/'damaged.png';damaged.write_bytes(b'not-an-image')
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE images SET kept_path=? WHERE id=?',(str(damaged),mid))
    store.record_image(scope='group:1',user_id='test-user',result={'sha256':'other','format':'PNG','size':1,'width':72,'height':54,'kept_path':str(source),'retention_reason':'prompt_bound'},raw={})
    store.save_obfuscation_score('other',ratio=.99,layers=None,obfuscated=False,confidence='none',version=0)
    with sqlite3.connect(store.path) as conn:conn.execute("UPDATE image_hashes SET updated_at='2000-01-01 00:00:00'")
    def detect(path):
        if Path(path)==damaged:raise OSError('persistent corruption')
        return None
    monkeypatch.setattr('qq_onebot_whitelist.maintenance.analyze_image',detect)
    assert restore_confirmed_obfuscation(tmp_path,max_rechecks=1)==0
    assert store.obfuscation_details('other')['detector_version']==0
    assert restore_confirmed_obfuscation(tmp_path,max_rechecks=1)==0
    assert store.obfuscation_details('other')['confidence']=='unsupported'

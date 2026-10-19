"""Integration checks against a read-only copy of the connected device.
Usage: PYTHONPATH=<mutagen-dir> python3 Sources/test_engine.py <mount> <mp3>
Only temporary copies are modified. Never writes to the source mount.
"""
import json, shutil, sys, tempfile
from pathlib import Path
from unittest.mock import patch
import engine as e

def main():
    mount,sample=map(Path,sys.argv[1:3]);state=e.inspect(mount);guid=state['guid']
    root=Path(tempfile.mkdtemp(prefix='ipod-drop-suite-'))
    try:
        e.backup_home=lambda:root/'backups'
        def clone(name):
            dest=root/name/'iPod_Control/iTunes';dest.mkdir(parents=True)
            origin=mount/'iPod_Control/iTunes'
            shutil.copytree(origin/'iTunes Library.itlp',dest/'iTunes Library.itlp')
            shutil.copy2(origin/'iTunesCDB',dest/'iTunesCDB')
            return root/name
        vectors=json.loads((Path(__file__).parent/'vendor/hashab-vectors.json').read_text())
        for v in vectors:
            sha=bytes.fromhex(v['sha1']);g=bytes.fromhex(v['uuid']);target=bytes.fromhex(v['target'])
            assert e.HashAB().sign(sha,g,b'ABCDEFGHIJKLMNOPQRSTUVW')==target
            assert e.recover_nonce(target,sha,g)==b'ABCDEFGHIJKLMNOPQRSTUVW'
        print(f'PASS: {len(vectors)} HashAB vectors and nonce recovery')
        device=clone('normal');itunes=device/'iPod_Control/iTunes'
        original=e.state_signature(itunes)
        result=e.import_songs([sample],device,guid)
        assert result['added']==1 and result['count']==state['count']+1
        e.preservation(mount/'iPod_Control/iTunes/iTunes Library.itlp',itunes/'iTunes Library.itlp')
        assert e.inspect(device,guid)['count']==state['count']+1
        assert e.import_songs([sample],device,guid)['duplicates']==1
        print('PASS: append, both indexes, original rows, signatures, exact-file deduplication')
        device=clone('rollback');itunes=device/'iPod_Control/iTunes'
        original=e.state_signature(itunes);replace=e.os.replace
        def fail_install(src,dst):
            if Path(src).name=='new-iTunesCDB':raise OSError('injected install failure')
            return replace(src,dst)
        with patch.object(e.os,'replace',fail_install):
            try:e.import_songs([sample],device,guid)
            except OSError as ex:assert 'injected' in str(ex)
            else:raise AssertionError('failure not injected')
        assert e.state_signature(itunes)==original
        assert not list((device/'iPod_Control/Music').rglob('*.mp3'))
        assert not (itunes/'.ipoddrop-transaction').exists()
        print('PASS: interrupted install rolls back matching database set and new audio')
        device=clone('corrupt');itunes=device/'iPod_Control/iTunes'
        p=itunes/'iTunes Library.itlp/Locations.itdb.cbk';data=bytearray(p.read_bytes());data[-1]^=1;p.write_bytes(data)
        try:e.import_songs([sample],device,guid)
        except e.ImportErrorDetail:pass
        else:raise AssertionError('bad signature accepted')
        assert not (itunes/'.ipoddrop-transaction').exists()
        print('PASS: corrupted signature blocks before copying audio')
        device=clone('crash');itunes=device/'iPod_Control/iTunes';original=e.state_signature(itunes)
        tx=itunes/'.ipoddrop-transaction';tx.mkdir()
        e.save_json(tx/'manifest.json',{'phase':'installing','audio':[]})
        e.os.replace(itunes/'iTunes Library.itlp',tx/'old-iTunes Library.itlp')
        shutil.copytree(tx/'old-iTunes Library.itlp',itunes/'iTunes Library.itlp')
        assert e.recover(device)['message']
        assert e.state_signature(itunes)==original
        print('PASS: next-launch journal recovery')
        print('ALL CHECKS PASSED; original iPod was read only.')
    finally:shutil.rmtree(root)

if __name__=='__main__':main()

"""Append-only iPod nano 6/7 importer. No Apple library or cloud service.

All edits happen in a staging directory. Existing SQLite rows and CDB records
are retained. The matching CDB/SQLite set is backed up before installation.
HashAB implementation: ipodsync / dstaley/hashab, see vendor licenses.
"""
from __future__ import annotations
import contextlib, hashlib, json, os, plistlib, re, secrets, shutil, sqlite3
import struct, subprocess, sys, time, uuid, zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
from ipodsync.hashab import HashAB
from ipodsync._hashab_py import FINAL_PERM
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3

class ImportErrorDetail(RuntimeError): pass

def run(args,timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          creationflags=0x08000000 if os.name == 'nt' else 0)

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)

def rows(path, sql, args=()):
    with contextlib.closing(ro(path)) as c:
        return c.execute(sql, args).fetchall()

def u32(b, off): return struct.unpack_from('<I', b, off)[0]
def put32(b, off, value): struct.pack_into('<I', b, off, value)

def recover_nonce(sig, sha, guid):
    if len(sig) != 57 or sig[:2] != b'\x03\x00':
        raise ImportErrorDetail('不支持的 iPod 签名格式。')
    inv1 = {((93 ^ (13*x & 255)) ^ (128 if x & 1 else 0)): x for x in range(256)}
    inv2 = {(69*x + 118*(x & 0x5d) + 17) & 255: x for x in range(256)}
    work = bytearray(sig)
    for i in range(2, 57): work[i] = inv1[work[i]]
    for i in range(54, -1, -1):
        j = u32(FINAL_PERM, i*4)
        work[i+2], work[j+2] = work[j+2], work[i+2]
    nonce = bytes(inv2[x] for x in work[2:25])
    if HashAB().sign(sha, guid, nonce) != sig:
        raise ImportErrorDetail('设备标识与曲库签名不匹配，已停止导入。')
    return nonce

def cdb_digest(data):
    b = bytearray(data)
    for start, count in [(0x18,8),(0x58,20),(0x72,46),(0xab,57)]:
        b[start:start+count] = bytes(count)
    return hashlib.sha1(b).digest()

def cbk_body(data):
    parts = b''.join(hashlib.sha1(data[i:i+1024].ljust(1024,b'\0')).digest()
                     for i in range(0,len(data),1024))
    return hashlib.sha1(parts).digest(), parts

def verify_cbk(bundle, guid):
    data = (bundle/'Locations.itdb').read_bytes()
    cbk = (bundle/'Locations.itdb.cbk').read_bytes()
    sha, parts = cbk_body(data)
    if cbk[57:] != sha + parts:
        raise ImportErrorDetail('Locations 曲库校验失败，未改动设备。')
    return recover_nonce(cbk[:57],sha,guid)

def candidates():
    if os.name == 'nt':
        return [Path(f'{x}:/') for x in 'DEFGHIJKLMNOPQRSTUVWXYZ']
    return list(Path('/Volumes').iterdir())

def guid_candidates(root):
    values = []
    for name in ['SysInfoExtended','SysInfo']:
        p = root/'iPod_Control/Device'/name
        if p.exists():
            data = p.read_bytes()
            try:
                value = plistlib.loads(data).get('FireWireGUID','')
                values += re.findall(r'(?:0x)?([0-9a-fA-F]{16})',str(value))
            except Exception: pass
            values += re.findall(r'FireWireGUID\W{0,50}(?:0x)?([0-9a-fA-F]{16})',data.decode('utf-8','ignore'),re.I)
    if sys.platform == 'darwin':
        output = run(['/usr/sbin/ioreg','-p','IOUSB','-l','-w','0']).stdout
        values += re.findall(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"',output)
    elif os.name == 'nt':
        script = "Get-CimInstance Win32_DiskDrive | Where-Object {$_.Model -match 'iPod'} | Select-Object -ExpandProperty SerialNumber"
        output = run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script]).stdout
        values += re.findall(r'\b[0-9A-Fa-f]{16}\b',output)
        script = "Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match 'VID_05AC&PID_126[67]'} | Select-Object -ExpandProperty InstanceId"
        output = run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script]).stdout
        values += re.findall(r'\\([0-9A-Fa-f]{16})(?:\W|$)',output)
    return list(dict.fromkeys(bytes.fromhex(v) for v in values))

def inspect(root=None, guid=None):
    mounts = [Path(root)] if root else [p for p in candidates() if (p/'iPod_Control').is_dir()]
    if not mounts: raise ImportErrorDetail('请连接 iPod，并等待系统将它显示为磁盘。Windows 读取 Mac 格式的 iPod 需先安装 HFS+ 驱动。')
    if len(mounts) != 1: raise ImportErrorDetail('检测到多台 iPod，请一次只连接一台。')
    root = mounts[0].resolve()
    itunes = root/'iPod_Control/iTunes'
    tx = itunes/'.ipoddrop-transaction'
    if tx.exists(): raise ImportErrorDetail('上次导入未完成，请先点击“恢复上次曲库”。')
    bundle = itunes/'iTunes Library.itlp'
    data = (itunes/'iTunesCDB').read_bytes()
    if len(data)<244 or data[:4]!=b'mhbd' or struct.unpack_from('<H',data,0x30)[0]!=3:
        raise ImportErrorDetail('此版本支持 SQLite / HashAB 格式的 iPod nano 6、7。')
    valid = None
    for candidate in ([bytes.fromhex(guid)] if guid else guid_candidates(root)):
        try:
            recover_nonce(data[0xab:0xab+57],cdb_digest(data),candidate)
            verify_cbk(bundle,candidate)
            valid = candidate
            break
        except ImportErrorDetail: continue
    if not valid: raise ImportErrorDetail('未能核对设备标识和签名；请重新连接 iPod 后刷新。')
    for name in ['Library.itdb','Locations.itdb','Dynamic.itdb','Extras.itdb','Genius.itdb']:
        if rows(bundle/name,'PRAGMA integrity_check') != [('ok',)]:
            raise ImportErrorDetail(name+' 完整性检查失败。')
    pids = {r[0] for r in rows(bundle/'Library.itdb','SELECT pid FROM item')}
    for name, query in [('Locations.itdb','SELECT item_pid FROM location'),('Dynamic.itdb','SELECT item_pid FROM item_stats')]:
        if {r[0] for r in rows(bundle/name,query)} != pids:
            raise ImportErrorDetail('歌曲索引不一致，已停止导入。')
    cdb_ids = set(cdb_tracks(data))
    if cdb_ids != {p & ((1<<64)-1) for p in pids}:
        raise ImportErrorDetail('iTunesCDB 与设备歌曲索引不一致。')
    space = shutil.disk_usage(root)
    return dict(root=str(root),name=root.name,guid=valid.hex(),count=len(pids),free=space.free,total=space.total)

def chunks(data, start, end):
    off = start
    while off < end:
        if off+12>end: raise ImportErrorDetail('曲库记录截断。')
        size = u32(data,off+8)
        if size<12 or off+size>end: raise ImportErrorDetail('曲库记录长度异常。')
        yield off, size
        off += size

def inflate(data):
    head = u32(data,4)
    if not 244<=head<len(data): raise ImportErrorDetail('曲库头长度异常。')
    return head,zlib.decompress(data[head:])

def cdb_tracks(data):
    _, body=inflate(data)
    result={}
    for off,n in chunks(body,0,len(body)):
        if u32(body,off+12)!=1: continue
        lst=off+u32(body,off+4)
        if body[lst:lst+4]!=b'mhlt': raise ImportErrorDetail('缺少歌曲列表。')
        for t,k in chunks(body,lst+u32(body,lst+4),off+n):
            if body[t:t+4]!=b'mhit': raise ImportErrorDetail('歌曲格式异常。')
            result[struct.unpack_from('<Q',body,t+112)[0]]=bytes(body[t:t+k])
    return result

def cdb_remove(data, ids, guid):
    """Remove tracks and their playlist entries, then re-sign the CDB."""
    ids={int(x) & ((1<<64)-1) for x in ids}
    head,body=inflate(data); out=bytearray(); removed_tracks=0; found_list=False
    for off,n in chunks(body,0,len(body)):
        ds=bytearray(body[off:off+n]); kind=u32(ds,12); h=u32(ds,4)
        if kind==1:
            found_list=True
            lh=u32(ds,h+4); start=h+lh; kept=[]
            for t,k in chunks(ds,start,len(ds)):
                if struct.unpack_from('<Q',ds,t+112)[0] in ids:
                    removed_tracks+=1
                else:
                    kept.append(bytes(ds[t:t+k]))
            if removed_tracks>u32(ds,h+8):
                raise ImportErrorDetail('歌曲列表计数异常，已停止删除。')
            ds=ds[:start]+b''.join(kept)
            put32(ds,h+8,u32(ds,h+8)-removed_tracks)
        elif kind in (3,5):
            lh=u32(ds,h+4); start=h+lh; playlists=[]
            for po,pn in chunks(ds,start,len(ds)):
                pl=bytearray(ds[po:po+pn]); ph=u32(pl,4)
                meta=[]; entries=[]
                for eo,en in chunks(pl,ph,len(pl)):
                    if pl[eo:eo+4]==b'mhip':
                        if u32(pl,eo+24) in ids: continue
                        entries.append(bytearray(pl[eo:eo+en]))
                    else:
                        meta.append(bytes(pl[eo:eo+en]))
                pl=pl[:ph]+b''.join(meta)+b''.join(entries)
                if len(entries)!=u32(pl,16):
                    put32(pl,16,len(entries))
                put32(pl,8,len(pl))
                playlists.append(pl)
            ds=ds[:start]+b''.join(playlists)
        put32(ds,8,len(ds));out+=ds
    if not found_list:raise ImportErrorDetail('未找到歌曲列表，已停止删除。')
    if not removed_tracks:raise ImportErrorDetail('设备曲库中找不到选中的歌曲。')
    result=bytearray(data[:head])+zlib.compress(out,1);put32(result,8,len(result))
    nonce=recover_nonce(data[0xab:0xab+57],cdb_digest(data),guid)
    result[0xab:0xab+57]=HashAB().sign(cdb_digest(result),guid,nonce)
    old=cdb_tracks(data);new=cdb_tracks(result)
    if set(new)!=set(old)-ids or any(new[k]!=old[k] for k in new):
        raise ImportErrorDetail('删除后的歌曲记录核对失败。')
    return result

def library_songs(root):
    bundle=Path(root)/'iPod_Control/iTunes/iTunes Library.itlp'
    items=rows(bundle/'Library.itdb','''
        SELECT pid,coalesce(title,''),coalesce(artist,''),coalesce(album,''),
               coalesce(total_time_ms,0),coalesce(track_number,0),
               coalesce(disc_number,0),coalesce(media_kind,0)
        FROM item ORDER BY artist_order,album_order,disc_number,track_number,title_order
    ''')
    locations={}
    for pid,base,relative,size in rows(bundle/'Locations.itdb','''
        SELECT l.item_pid,coalesce(b.path,''),coalesce(l.location,''),coalesce(l.file_size,0)
        FROM location l LEFT JOIN base_location b ON b.id=l.base_location_id
    '''):
        locations[pid]=dict(path=base.rstrip('/')+'/'+relative.lstrip('/'),size=size)
    songs=[]
    for pid,title,artist,album,ms,track,disc,kind in items:
        info=locations.get(pid,{})
        songs.append(dict(pid=str(pid),title=title,artist=artist,album=album,ms=int(ms or 0),
                          track=track,disc=disc,size=int(info.get('size',0)),
                          path=info.get('path',''),kind=kind))
    return songs

def song_list(root=None,guid=None):
    state=inspect(root,guid)
    return dict(root=state['root'],songs=library_songs(Path(state['root'])))

def chunk(tag,size):
    b=bytearray(size); b[:4]=tag; put32(b,4,size); put32(b,8,size); return b

def mhod(kind,text):
    raw=text.encode('utf-16le'); b=chunk(b'mhod',40)
    put32(b,12,kind); put32(b,24,1); put32(b,28,len(raw))
    b+=raw; put32(b,8,len(b)); return b

def track_record(m):
    b=chunk(b'mhit',0x148)
    fields={16:m['id'],20:1,24:0x4d503320,32:m['date1904'],36:m['size'],40:m['ms'],44:m['track'],52:m['year'],56:m['kbps'],60:m['hz']<<16,104:m['date1904'],208:1}
    for off,value in fields.items(): put32(b,off,value & 0xffffffff)
    b[29]=1; struct.pack_into('<Q',b,112,m['pid'] & ((1<<64)-1))
    texts=[(1,m['title']),(2,':iPod_Control:Music:'+m['location'].replace('/',':')),(3,m['album']),(4,m['artist']),(5,m['genre'])]
    put32(b,12,sum(bool(t) for _,t in texts))
    for k,t in texts:
        if t: b+=mhod(k,t)
    put32(b,8,len(b)); return b

def playlist_entry(tid,position,date):
    b=chunk(b'mhip',0x4c); p=chunk(b'mhod',44)
    put32(p,4,24);put32(p,12,100);put32(p,24,position)
    for o,v in [(12,1),(20,1000+position),(24,tid),(28,date)]: put32(b,o,v)
    b+=p;put32(b,8,len(b));return b

def append_cdb(data, songs, guid):
    head,body=inflate(data); out=bytearray(); master_updates=0
    for off,n in chunks(body,0,len(body)):
        ds=bytearray(body[off:off+n]); kind=u32(ds,12); h=u32(ds,4)
        if kind==1:
            for m in songs: ds+=track_record(m)
            put32(ds,h+8,u32(ds,h+8)+len(songs))
        elif kind in (2,3,5):
            lst=ds[h:]; lh=u32(lst,4); updated=bytearray(lst[:lh])
            if lst[:4]!=b'mhlp': raise ImportErrorDetail('歌单格式异常。')
            for po,pn in chunks(lst,lh,len(lst)):
                pl=bytearray(lst[po:po+pn])
                if pl[20]&1:
                    count=u32(pl,16)
                    for i,m in enumerate(songs): pl+=playlist_entry(m['id'],count+i+1,m['date1904'])
                    put32(pl,16,count+len(songs));put32(pl,8,len(pl));master_updates+=1
                updated+=pl
            ds=ds[:h]+updated
        put32(ds,8,len(ds));out+=ds
    if not master_updates: raise ImportErrorDetail('未找到主歌曲列表，已停止导入。')
    result=bytearray(data[:head])+zlib.compress(out,1);put32(result,8,len(result))
    nonce=recover_nonce(data[0xab:0xab+57],cdb_digest(data),guid)
    result[0xab:0xab+57]=HashAB().sign(cdb_digest(result),guid,nonce)
    old=cdb_tracks(data);new=cdb_tracks(result)
    if any(new.get(k)!=v for k,v in old.items()) or len(new)!=len(old)+len(songs):
        raise ImportErrorDetail('旧歌曲记录保留检查失败。')
    return result

def columns(c,table): return {r[1] for r in c.execute('PRAGMA table_info("'+table+'")')}
def insert(c,table,data):
    data={k:v for k,v in data.items() if k in columns(c,table)}
    c.execute('INSERT INTO "'+table+'" ('+','.join('"'+k+'"' for k in data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values()))

def pid(): return secrets.randbits(63) or 1
def maxval(c,t,col): return c.execute(f'SELECT coalesce(max("{col}"),0) FROM "{t}"').fetchone()[0] or 0

def add_sqlite(bundle,songs):
    cx={n:sqlite3.connect(bundle/(n+'.itdb')) for n in ['Library','Locations','Dynamic','Extras']}
    try:
        lib,loc,dyn,ext=[cx[n] for n in ['Library','Locations','Dynamic','Extras']]
        master=lib.execute('SELECT primary_container_pid FROM db_info').fetchone()[0]
        musicbase=loc.execute("SELECT id FROM base_location WHERE rtrim(path,'/')='iPod_Control/Music'").fetchone()
        if not musicbase: raise ImportErrorDetail('无法识别歌曲存储目录。')
        def lookup(table,name,extra=None,condition=None):
            where,args=condition or ('name=?',(name,))
            r=lib.execute(f'SELECT pid FROM {table} WHERE '+where,args).fetchone()
            if r:return r[0]
            val=pid(); order=maxval(lib,table,'name_order')+100
            insert(lib,table,dict(pid=val,name=name,sort_name=name,name_order=order,**(extra or {})))
            return val
        for m in songs:
            artist=lookup('artist',m['artist'],dict(kind=2,artwork_status=0,has_songs=1,has_non_compilation_tracks=1,album_count=1))
            album=lookup('album',m['album'],dict(kind=2,artist_pid=artist,artwork_status=0,has_songs=1,item_count=1,artist_count_calc=1),('name=? AND artist_pid=?',(m['album'],artist)))
            ta=lookup('track_artist',m['artist'],dict(has_songs=1,has_non_compilation_tracks=1,album_count=1))
            genre=0
            if m['genre']:
                g=lib.execute('SELECT id FROM genre_map WHERE genre=?',(m['genre'],)).fetchone()
                genre=g[0] if g else maxval(lib,'genre_map','id')+1
                if not g:insert(lib,'genre_map',dict(id=genre,genre=m['genre'],genre_order=genre*100,has_music=1))
            order=maxval(lib,'item','title_order')+100
            insert(lib,'item',dict(pid=m['pid'],media_kind=1,is_song=1,date_modified=m['date2001'],year=m['year'],artwork_status=2,total_time_ms=m['ms'],stop_time_ms=0,track_number=m['track'],genre_id=genre,artist_pid=artist,album_pid=album,track_artist_pid=ta,title=m['title'],artist=m['artist'],album=m['album'],album_artist=m['artist'],sort_title=m['title'],sort_artist=m['artist'],sort_album=m['album'],sort_album_artist=m['artist'],title_order=order,artist_order=order,album_order=order,album_artist_order=order,album_by_artist_order=order,genre_order=order,physical_order=maxval(lib,'item','physical_order')+1))
            insert(lib,'avformat_info',dict(item_pid=m['pid'],sub_id=0,audio_format=301,bit_rate=m['kbps'],sample_rate=m['hz']))
            insert(lib,'item_to_container',dict(item_pid=m['pid'],container_pid=master,physical_order=maxval(lib,'item_to_container','physical_order')+1))
            insert(loc,'location',dict(item_pid=m['pid'],sub_id=0,base_location_id=musicbase[0],location_type=1179208773,location=m['location'],extension=1297101600,kind_id=1,date_created=m['date2001'],file_size=m['size']))
            insert(dyn,'item_stats',dict(item_pid=m['pid'],has_been_played=0,play_count_user=0,play_count_recent=0,user_rating=0,user_rating_common=0))
            if 'track_size_calc' in {r[0] for r in lib.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                lib.execute("UPDATE track_size_calc SET size=coalesce(size,0)+? WHERE kind='audio'",(m['size'],))
        for c in cx.values():c.commit()
    finally:
        for c in cx.values():c.close()

def delete_sqlite(bundle,pids):
    pids=list(dict.fromkeys(int(x) for x in pids))
    if not pids:raise ImportErrorDetail('没有选中歌曲。')
    marks=','.join('?' for _ in pids)
    cx={n:sqlite3.connect(bundle/(n+'.itdb')) for n in ['Library','Locations','Dynamic','Extras']}
    try:
        lib,loc,dyn,ext=[cx[n] for n in ['Library','Locations','Dynamic','Extras']]
        info=lib.execute('SELECT pid,coalesce(album_pid,0),coalesce(artist_pid,0),'
                         'coalesce(track_artist_pid,0),coalesce(genre_id,0) '
                         'FROM item WHERE pid IN ('+marks+')',pids).fetchall()
        if len(info)!=len(pids):raise ImportErrorDetail('部分歌曲已不在设备曲库中，请刷新后重试。')
        album_ids={r[1] for r in info if r[1]};artist_ids={r[2] for r in info if r[2]}
        track_artist_ids={r[3] for r in info if r[3]};genre_ids={r[4] for r in info if r[4]}
        files=loc.execute('SELECT l.item_pid,coalesce(b.path,\'\'),coalesce(l.location,\'\'),'
                          'coalesce(l.file_size,0) FROM location l '
                          'LEFT JOIN base_location b ON b.id=l.base_location_id '
                          'WHERE l.item_pid IN ('+marks+')',pids).fetchall()
        total=sum(int(r[3] or 0) for r in files)
        for table in ['avformat_info','item_to_container','podcast_info','store_info',
                      'video_info','video_characteristics','container_seed']:
            if table in {r[0] for r in lib.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                lib.execute('DELETE FROM "'+table+'" WHERE item_pid IN ('+marks+')',pids)
        lib.execute('DELETE FROM item WHERE pid IN ('+marks+')',pids)
        if 'track_size_calc' in {r[0] for r in lib.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            lib.execute("UPDATE track_size_calc SET size=max(coalesce(size,0)-?,0) WHERE kind='audio'",(total,))
        for table in ['location']:
            loc.execute('DELETE FROM "'+table+'" WHERE item_pid IN ('+marks+')',pids)
        dyn.execute('DELETE FROM item_stats WHERE item_pid IN ('+marks+')',pids)
        for table in ['chapter','lyrics']:
            if table in {r[0] for r in ext.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                ext.execute('DELETE FROM "'+table+'" WHERE item_pid IN ('+marks+')',pids)
        for album in album_ids:
            count=lib.execute('SELECT count(*),count(DISTINCT artist_pid) FROM item WHERE album_pid=?',(album,)).fetchone()
            lib.execute('UPDATE album SET item_count=?,has_songs=?,artist_count_calc=? WHERE pid=?',
                        (count[0],1 if count[0] else 0,count[1],album))
        for artist in artist_ids:
            count=lib.execute('SELECT count(*),count(DISTINCT album_pid) FROM item WHERE artist_pid=?',(artist,)).fetchone()
            lib.execute('UPDATE artist SET has_songs=?,has_non_compilation_tracks=?,album_count=? WHERE pid=?',
                        (1 if count[0] else 0,1 if count[0] else 0,count[1],artist))
        for artist in track_artist_ids:
            count=lib.execute('SELECT count(*),count(DISTINCT album_pid) FROM item WHERE track_artist_pid=?',(artist,)).fetchone()
            lib.execute('UPDATE track_artist SET has_songs=?,has_non_compilation_tracks=?,album_count=? WHERE pid=?',
                        (1 if count[0] else 0,1 if count[0] else 0,count[1],artist))
        for genre in genre_ids:
            row=lib.execute('SELECT count(*),count(DISTINCT artist_pid),count(DISTINCT album_pid),'
                            'sum(CASE WHEN is_compilation THEN 1 ELSE 0 END) '
                            'FROM item WHERE genre_id=?',(genre,)).fetchone()
            lib.execute('UPDATE genre_map SET has_music=?,artist_count_calc=?,album_count_calc=?,'
                        'compilation_count_calc=? WHERE id=?',
                        (1 if row[0] else 0,row[1],row[2],row[3] or 0,genre))
        for c in cx.values():c.commit()
        return dict(total=total,files=[dict(pid=r[0],path=r[1].rstrip('/')+'/'+r[2].lstrip('/'),size=int(r[3] or 0)) for r in files],
                    albums=album_ids,artists=artist_ids,track_artists=track_artist_ids,genres=genre_ids)
    finally:
        for c in cx.values():c.close()

def validate_counts(bundle,albums=None,artists=None,track_artists=None,genres=None):
    with contextlib.closing(ro(bundle/'Library.itdb')) as c:
        album_rows=c.execute('SELECT pid,item_count,has_songs,artist_count_calc FROM album').fetchall()
        if albums is not None:album_rows=[r for r in album_rows if r[0] in albums]
        for pid,item_count,has_songs,artist_count in album_rows:
            row=c.execute('SELECT count(*),count(DISTINCT artist_pid) FROM item WHERE album_pid=?',(pid,)).fetchone()
            if (item_count or 0)!=row[0] or (has_songs or 0)!=(1 if row[0] else 0) or (artist_count or 0)!=row[1]:
                raise ImportErrorDetail('专辑计数核对失败。')
        artist_rows=c.execute('SELECT pid,has_songs,album_count FROM artist').fetchall()
        if artists is not None:artist_rows=[r for r in artist_rows if r[0] in artists]
        for pid,has_songs,album_count in artist_rows:
            row=c.execute('SELECT count(*),count(DISTINCT album_pid) FROM item WHERE artist_pid=?',(pid,)).fetchone()
            if (has_songs or 0)!=(1 if row[0] else 0) or (album_count or 0)!=row[1]:
                raise ImportErrorDetail('歌手计数核对失败。')
        track_rows=c.execute('SELECT pid,has_songs,album_count FROM track_artist').fetchall()
        if track_artists is not None:track_rows=[r for r in track_rows if r[0] in track_artists]
        for pid,has_songs,album_count in track_rows:
            row=c.execute('SELECT count(*),count(DISTINCT album_pid) FROM item WHERE track_artist_pid=?',(pid,)).fetchone()
            if (has_songs or 0)!=(1 if row[0] else 0) or (album_count or 0)!=row[1]:
                raise ImportErrorDetail('曲目歌手计数核对失败。')
        genre_rows=c.execute('SELECT id,has_music,artist_count_calc,album_count_calc,compilation_count_calc FROM genre_map').fetchall()
        if genres is not None:genre_rows=[r for r in genre_rows if r[0] in genres]
        for pid,has_music,artist_count,album_count,compilations in genre_rows:
            row=c.execute('SELECT count(*),count(DISTINCT artist_pid),count(DISTINCT album_pid),'
                          'sum(CASE WHEN is_compilation THEN 1 ELSE 0 END) FROM item WHERE genre_id=?',(pid,)).fetchone()
            if (has_music or 0)!=(1 if row[0] else 0) or (artist_count or 0)!=row[1] or (album_count or 0)!=row[2] or (compilations or 0)!=(row[3] or 0):
                raise ImportErrorDetail('流派计数核对失败。')

def preservation_delete(before,after,pids,counts=None):
    pids=set(pids)
    item_tables={'item','avformat_info','item_to_container','podcast_info','store_info',
                 'video_info','video_characteristics','container_seed','location','item_stats',
                 'lyrics','chapter'}
    for p in before.glob('*.itdb'):
        with contextlib.closing(ro(p)) as old, contextlib.closing(ro(after/p.name)) as new:
            for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                if table in {'album','artist','track_artist','genre_map','track_size_calc'}:continue
                sql='SELECT * FROM "'+table.replace('"','""')+'"'
                original=set(old.execute(sql)); current=set(new.execute(sql))
                lost=original-current
                if not lost:continue
                if table not in item_tables:raise ImportErrorDetail('旧数据保留检查失败：'+p.name+'/'+table)
                cols=[r[1] for r in old.execute('PRAGMA table_info("'+table+'")')]
                if 'item_pid' in cols:index=cols.index('item_pid')
                elif table=='item' and 'pid' in cols:index=cols.index('pid')
                else:raise ImportErrorDetail('旧数据保留检查失败：'+p.name+'/'+table)
                if any(row[index] not in pids for row in lost):
                    raise ImportErrorDetail('旧数据保留检查失败：'+p.name+'/'+table)
    validate_counts(after,**(counts or {}))

def preservation(before,after):
    """Check every pre-existing row in every table, not only the track count."""
    for p in before.glob('*.itdb'):
        with contextlib.closing(ro(p)) as old, contextlib.closing(ro(after/p.name)) as new:
            for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                if table=='track_size_calc':continue
                sql='SELECT * FROM "'+table.replace('"','""')+'"'
                original=set(old.execute(sql)); current=set(new.execute(sql))
                if not original<=current:raise ImportErrorDetail('旧数据保留检查失败：'+p.name+'/'+table)

def backup_home():
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) if os.name=='nt' else Path.home()/'Library/Application Support'
    return base/'iPod Drop'/'Backups'

def state_signature(itunes):
    paths=[itunes/'iTunesCDB']+list((itunes/'iTunes Library.itlp').glob('*'))
    return {str(p.relative_to(itunes)):digest(p) for p in paths if p.is_file()}

@contextlib.contextmanager
def device_lock(itunes):
    p=itunes/'.ipoddrop.lock'
    f=open(p,'a+b');f.seek(0);f.write(b'0');f.flush();f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise ImportErrorDetail('另一窗口正在导入，请等待完成。')
    try:yield
    finally:f.close()

def save_json(path,value):
    tmp=path.with_suffix('.new')
    with open(tmp,'w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def recover(root):
    itunes=Path(root)/'iPod_Control/iTunes';tx=itunes/'.ipoddrop-transaction'
    with device_lock(itunes):
        if not tx.exists():return dict(message='没有需要恢复的事务。')
        manifest=json.loads((tx/'manifest.json').read_text('utf-8'))
        if manifest['phase']=='committed':
            shutil.rmtree(tx);return dict(message='上次导入已完成，临时文件已清理。')
        _restore_transaction(Path(root),itunes,tx,manifest)
        return dict(message='已恢复操作前的曲库与歌曲，原有歌曲保留。')

def _restore_transaction(root,itunes,tx,manifest):
    for name in ['iTunes Library.itlp','iTunesCDB']:
        old=tx/('old-'+name)
        if old.exists():
            live=itunes/name
            if live.is_dir():shutil.rmtree(live)
            elif live.exists():live.unlink()
            os.replace(old,live)
    music=(root/'iPod_Control/Music').resolve()
    for relative in manifest.get('audio',[]):
        safe=(root/relative).resolve()
        if not safe.is_relative_to(music):raise ImportErrorDetail('恢复路径异常。')
        safe.unlink(missing_ok=True)
    for relative in manifest.get('moved',[]):
        safe=(root/relative).resolve()
        if not safe.is_relative_to(music):raise ImportErrorDetail('恢复路径异常。')
        source=tx/'audio'/relative
        if source.exists():
            safe.parent.mkdir(parents=True,exist_ok=True)
            if safe.exists():raise ImportErrorDetail('恢复目标已存在，未覆盖：'+str(relative))
            os.replace(source,safe)
    shutil.rmtree(tx,ignore_errors=True)

def import_songs(paths,root=None,guid=None):
    state=inspect(root,guid);root=Path(state['root']);itunes=root/'iPod_Control/iTunes'
    with device_lock(itunes):
        return _import(paths,state,root,itunes)

def _import(paths,state,root,itunes):
    bundle=itunes/'iTunes Library.itlp';guid=bytes.fromhex(state['guid'])
    files=[];ignored=0
    for item in paths:
        p=Path(item).resolve()
        if p.is_dir(): files+=sorted(x for x in p.rglob('*') if x.suffix.lower()=='.mp3' and not x.name.startswith('._'))
        elif p.is_file() and p.suffix.lower()=='.mp3':files.append(p)
        else:ignored+=1
    files=list(dict.fromkeys(files))
    if not files:raise ImportErrorDetail('没有找到 MP3 文件。')
    sizes={p.stat().st_size for p in files}; existing=set()
    for base,relative,size in rows(bundle/'Locations.itdb','SELECT b.path,l.location,l.file_size FROM location l JOIN base_location b ON b.id=l.base_location_id'):
        path=(root/base/relative).resolve()
        if not path.is_relative_to(root):raise ImportErrorDetail('设备歌曲路径异常。')
        if size in sizes and path.is_file():existing.add(digest(path))
    songs=[];duplicates=0;now=int(time.time());oldcdb=(itunes/'iTunesCDB').read_bytes()
    nextid=max(u32(t,16) for t in cdb_tracks(oldcdb).values())+1 if state['count'] else 100
    for p in files:
        sha=digest(p)
        if sha in existing:duplicates+=1;continue
        existing.add(sha)
        audio=MP3(p);tags=EasyID3(p) if audio.tags else {}
        def tag(k):return str(tags.get(k,[''])[0])
        def number(s):
            m=re.match(r'\d+',s);return int(m.group()) if m else 0
        if not 0<audio.info.length or audio.info.sample_rate>48000 or audio.info.bitrate>320000:
            raise ImportErrorDetail(p.name+' 的 MP3 参数不适合此 iPod。')
        songs.append(dict(source=str(p),sha=sha,pid=pid(),id=nextid,title=tag('title') or p.stem,artist=tag('artist'),album=tag('album'),genre=tag('genre'),track=number(tag('tracknumber')),year=number(tag('date')[:4]),ms=int(audio.info.length*1000),kbps=audio.info.bitrate//1000,hz=audio.info.sample_rate,size=p.stat().st_size,date1904=now+2082844800,date2001=now-978307200,location='F00/ID'+secrets.token_hex(6).upper()+'.mp3'))
        nextid+=1
    if not songs:return dict(message=f'全部已存在，跳过 {duplicates} 首。',added=0,duplicates=duplicates,failed=0)
    if sum(m['size'] for m in songs)+10*1024*1024>state['free']:raise ImportErrorDetail('iPod 剩余空间不足。')
    baseline=state_signature(itunes)
    if any(time.time()-p.stat().st_mtime<10 for p in [itunes/'iTunesCDB',bundle/'Library.itdb']):
        # Our last completed import is safe; only refuse a currently changing set.
        time.sleep(1)
        if baseline!=state_signature(itunes):raise ImportErrorDetail('系统正在同步 iPod，请等待结束。')
    backup=backup_home()/state['guid']/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True)
    shutil.copytree(bundle,backup/'iTunes Library.itlp');shutil.copy2(itunes/'iTunesCDB',backup/'iTunesCDB')
    save_json(backup/'info.json',dict(device=state,sources=[m['source'] for m in songs]))
    tx=itunes/'.ipoddrop-transaction';tx.mkdir()
    manifest=dict(phase='staging',audio=[],backup=str(backup))
    save_json(tx/'manifest.json',manifest)
    try:
        staged=tx/'new-iTunes Library.itlp';shutil.copytree(bundle,staged)
        add_sqlite(staged,songs)
        nonce=verify_cbk(bundle,guid);sha,parts=cbk_body((staged/'Locations.itdb').read_bytes())
        (staged/'Locations.itdb.cbk').write_bytes(HashAB().sign(sha,guid,nonce)+sha+parts)
        verify_cbk(staged,guid)
        preservation(bundle,staged)
        for p in staged.glob('*.itdb'):
            if rows(p,'PRAGMA integrity_check')!=[('ok',)]:raise ImportErrorDetail('新曲库完整性检查失败。')
        newcdb=append_cdb(oldcdb,songs,guid)
        (tx/'new-iTunesCDB').write_bytes(newcdb)
        for m in songs:
            dest=root/'iPod_Control/Music'/m['location']
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():raise ImportErrorDetail('歌曲目标文件重名。')
            manifest['audio'].append(str(dest.relative_to(root)));save_json(tx/'manifest.json',manifest)
            with open(m['source'],'rb') as src,open(dest,'xb') as out:
                shutil.copyfileobj(src,out);out.flush();os.fsync(out.fileno())
            if digest(dest)!=m['sha']:raise ImportErrorDetail('歌曲复制校验失败。')
        if baseline!=state_signature(itunes):raise ImportErrorDetail('曲库被其他程序修改，已停止本次导入。')
        for p in tx.rglob('*'):
            if p.is_file():
                with open(p,'r+b') as f:os.fsync(f.fileno())
        manifest['phase']='installing';save_json(tx/'manifest.json',manifest)
        for name in ['iTunes Library.itlp','iTunesCDB']:
            os.replace(itunes/name,tx/('old-'+name));os.replace(tx/('new-'+name),itunes/name)
        preservation(backup/'iTunes Library.itlp',bundle)
        if len(cdb_tracks((itunes/'iTunesCDB').read_bytes()))!=state['count']+len(songs):raise ImportErrorDetail('导入后歌曲数核验失败。')
        verify_cbk(bundle,guid)
        manifest['phase']='committed';save_json(tx/'manifest.json',manifest)
        shutil.rmtree(tx)
        return dict(message=f'已导入 {len(songs)} 首，跳过重复 {duplicates} 首。',added=len(songs),duplicates=duplicates,ignored=ignored,backup=str(backup),count=state['count']+len(songs))
    except Exception:
        # Keep the journal on failed rollback, so the next run never guesses.
        for name in ['iTunes Library.itlp','iTunesCDB']:
            old=tx/('old-'+name)
            if old.exists():
                live=itunes/name
                if live.is_dir():shutil.rmtree(live)
                elif live.exists():live.unlink()
                os.replace(old,live)
        for relative in manifest['audio']:(root/relative).unlink(missing_ok=True)
        shutil.rmtree(tx)
        raise

def delete_songs(pids,root=None,guid=None):
    state=inspect(root,guid);root=Path(state['root']);itunes=root/'iPod_Control/iTunes'
    pids=list(dict.fromkeys(int(x) for x in pids))
    if not pids:raise ImportErrorDetail('没有选中歌曲。')
    with device_lock(itunes):
        return _delete(pids,state,root,itunes)

def _delete(pids,state,root,itunes):
    bundle=itunes/'iTunes Library.itlp';guid=bytes.fromhex(state['guid'])
    marks=','.join('?' for _ in pids)
    found=rows(bundle/'Library.itdb','SELECT pid,coalesce(title,\'\') FROM item WHERE pid IN ('+marks+')',pids)
    if len(found)!=len(pids):raise ImportErrorDetail('部分歌曲已不在设备曲库中，请刷新后重试。')
    oldcdb=(itunes/'iTunesCDB').read_bytes();oldtracks=cdb_tracks(oldcdb)
    missing=[p for p in pids if (p & ((1<<64)-1)) not in oldtracks]
    if missing:raise ImportErrorDetail('设备签名曲库中找不到选中的歌曲，已停止删除。')
    baseline=state_signature(itunes)
    if any(time.time()-p.stat().st_mtime<10 for p in [itunes/'iTunesCDB',bundle/'Library.itdb']):
        time.sleep(1)
        if baseline!=state_signature(itunes):raise ImportErrorDetail('系统正在同步 iPod，请等待结束。')
    backup=backup_home()/state['guid']/(time.strftime('%Y%m%d-%H%M%S')+'-delete-'+uuid.uuid4().hex[:6])
    backup.mkdir(parents=True)
    shutil.copytree(bundle,backup/'iTunes Library.itlp');shutil.copy2(itunes/'iTunesCDB',backup/'iTunesCDB')
    save_json(backup/'info.json',dict(device=state,deleted=[dict(pid=p,title=t) for p,t in found]))
    tx=itunes/'.ipoddrop-transaction';tx.mkdir()
    manifest=dict(phase='staging',action='delete',audio=[],moved=[],backup=str(backup))
    save_json(tx/'manifest.json',manifest)
    try:
        staged=tx/'new-iTunes Library.itlp';shutil.copytree(bundle,staged)
        removed=delete_sqlite(staged,pids)
        counts=dict(albums=removed['albums'],artists=removed['artists'],
                    track_artists=removed['track_artists'],genres=removed['genres'])
        nonce=verify_cbk(bundle,guid);sha,parts=cbk_body((staged/'Locations.itdb').read_bytes())
        (staged/'Locations.itdb.cbk').write_bytes(HashAB().sign(sha,guid,nonce)+sha+parts)
        verify_cbk(staged,guid)
        preservation_delete(bundle,staged,pids,counts)
        for p in staged.glob('*.itdb'):
            if rows(p,'PRAGMA integrity_check')!=[('ok',)]:raise ImportErrorDetail('新曲库完整性检查失败。')
        newcdb=cdb_remove(oldcdb,pids,guid)
        (tx/'new-iTunesCDB').write_bytes(newcdb)
        for item in removed['files']:
            source=(root/item['path']).resolve()
            if not source.is_relative_to((root/'iPod_Control/Music').resolve()):
                raise ImportErrorDetail('设备歌曲路径异常，已停止删除。')
            if not source.exists():continue
            relative=str(source.relative_to(root))
            destination=tx/'audio'/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            os.replace(source,destination)
            manifest['moved'].append(relative);save_json(tx/'manifest.json',manifest)
        if baseline!=state_signature(itunes):raise ImportErrorDetail('曲库被其他程序修改，已停止本次删除。')
        manifest['phase']='installing';save_json(tx/'manifest.json',manifest)
        for name in ['iTunes Library.itlp','iTunesCDB']:
            os.replace(itunes/name,tx/('old-'+name));os.replace(tx/('new-'+name),itunes/name)
        if len(cdb_tracks((itunes/'iTunesCDB').read_bytes()))!=state['count']-len(pids):
            raise ImportErrorDetail('删除后歌曲数核验失败。')
        verify_cbk(bundle,guid);preservation_delete(backup/'iTunes Library.itlp',bundle,pids,counts)
        manifest['phase']='committed';save_json(tx/'manifest.json',manifest)
        if rows(bundle/'Library.itdb','SELECT count(*) FROM item')[0][0]!=state['count']-len(pids):
            raise ImportErrorDetail('删除后歌曲索引核验失败。')
        shutil.rmtree(tx)
        for folder in sorted((root/'iPod_Control/Music').rglob('*'),key=lambda p:len(p.parts),reverse=True):
            if folder.is_dir():
                try:folder.rmdir()
                except OSError:pass
        return dict(message=f'已从 iPod 删除 {len(pids)} 首歌曲，电脑上的原文件未动。',deleted=len(pids),
                    count=state['count']-len(pids),backup=str(backup))
    except Exception:
        _restore_transaction(root,itunes,tx,manifest)
        raise

def eject(root):
    if sys.platform=='darwin':
        p=run(['/usr/sbin/diskutil','eject',root])
        if p.returncode:raise ImportErrorDetail(p.stderr or p.stdout)
    else:
        # Use Windows' shell eject verb; the user sees the safe-removal result.
        drive=str(Path(root).drive)
        script="$s=New-Object -ComObject Shell.Application; $s.Namespace(17).ParseName('"+drive.replace("'","''")+"').InvokeVerb('Eject')"
        p=run(['powershell.exe','-NoProfile','-Command',script])
        if p.returncode:raise ImportErrorDetail(p.stderr)
    return dict(message='已请求安全弹出，请确认系统提示后拔线。')

def windows_probe():
    if os.name!='nt':raise ImportErrorDetail('Windows 驱动助手只在 Windows 上运行。')
    script=(
        "$ErrorActionPreference='SilentlyContinue';"
        "$usb=@(Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match 'VID_05AC&PID_126[67]'} | "
        "ForEach-Object {[pscustomobject]@{name=$_.FriendlyName;status=[string]$_.Status}});"
        "$vols=@(Get-Volume | Where-Object {$_.DriveType -eq 'Removable'} | "
        "ForEach-Object {[pscustomobject]@{letter=[string]$_.DriveLetter;label=$_.FileSystemLabel;"
        "fs=$_.FileSystem;type=$_.FileSystemType;size=$_.Size;free=$_.SizeRemaining}});"
        "$drv=@(Get-Service | Where-Object {$_.Name -match 'hfs|paragon|macdrive'} | "
        "ForEach-Object {[pscustomobject]@{name=$_.Name;status=[string]$_.Status}});"
        "$wg=if(Get-Command winget -ErrorAction SilentlyContinue){$true}else{$false};"
        "[pscustomobject]@{usb=$usb;volumes=$vols;drivers=$drv;winget=$wg}|ConvertTo-Json -Depth 6 -Compress"
    )
    p=run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],timeout=35)
    text=p.stdout.strip()
    start=text.find('{')
    if start<0:
        raise ImportErrorDetail('无法读取 Windows 驱动状态。'+(p.stderr or text)[-300:])
    try:data=json.loads(text[start:])
    except Exception:raise ImportErrorDetail('Windows 驱动状态格式异常。')
    volumes=data.get('volumes') or []
    if isinstance(volumes,dict):volumes=[volumes]
    drivers=data.get('drivers') or []
    if isinstance(drivers,dict):drivers=[drivers]
    usb=data.get('usb') or []
    if isinstance(usb,dict):usb=[usb]
    return dict(platform='windows',usb=usb,volumes=volumes,drivers=drivers,
                winget=bool(data.get('winget')),
                driver_installed=any('hfs' in str(d.get('name','')).lower() or
                                     'paragon' in str(d.get('name','')).lower() or
                                     'macdrive' in str(d.get('name','')).lower() for d in drivers))

def install_windows_driver():
    if os.name!='nt':raise ImportErrorDetail('Windows 驱动助手只在 Windows 上运行。')
    script=Path(__file__).parent/'drivers/install-hfs-driver.ps1'
    if not script.exists():raise ImportErrorDetail('驱动安装脚本缺失，请重新解压完整工具包。')
    path=str(script).replace("'","''")
    command=('Start-Process powershell.exe -Verb RunAs -ArgumentList '
             "'-NoExit -ExecutionPolicy Bypass -File \""+path+"\"'")
    p=run(['powershell.exe','-NoProfile','-Command',command])
    if p.returncode:raise ImportErrorDetail((p.stderr or p.stdout or '未能打开管理员安装窗口。').strip())
    return dict(message='已打开管理员驱动安装窗口。安装完成后重启 Windows，再连接 iPod 点“重新检测”。')

def main():
    try:
        request=json.loads(sys.stdin.read())
        action=request.get('action','status')
        if action=='status':result=inspect(request.get('root'))
        elif action=='songs':result=song_list(request.get('root'))
        elif action=='import':result=import_songs(request['paths'],request.get('root'))
        elif action=='delete':result=delete_songs(request['pids'],request.get('root'))
        elif action=='recover':result=recover(request['root'])
        elif action=='eject':result=eject(request['root'])
        elif action=='driver':result=windows_probe()
        elif action=='install-driver':result=install_windows_driver()
        else:raise ImportErrorDetail('未知操作。')
        print(json.dumps(dict(ok=True,**result),ensure_ascii=False))
    except Exception as e:print(json.dumps(dict(ok=False,error=str(e)),ensure_ascii=False))

if __name__=='__main__':main()

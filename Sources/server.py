"""Windows portable UI. Binds only to loopback; files never leave this PC."""
import json, os, secrets, shutil, sys, tempfile, threading, time, traceback, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import engine

TOKEN=secrets.token_urlsafe(32)
TEMP=Path(tempfile.mkdtemp(prefix='ipod-drop-'))
UPLOADS={}
LOCK=threading.Lock()
STATE={'busy':False,'message':'连接 iPod 后点击刷新。','device':None,'error':False}

def refresh():
    try:
        device=engine.inspect()
        STATE.update(device=device,error=False)
        return device
    except Exception as e:
        STATE.update(device=None,error=True,message=str(e))
        return None

def import_job(ids):
    try:
        result=engine.import_songs([str(UPLOADS[x]) for x in ids],STATE['device']['root'])
        STATE.update(message=result['message'],error=False,backup=result.get('backup'))
        refresh()
        for x in ids:
            UPLOADS.pop(x).unlink(missing_ok=True)
    except Exception as e:STATE.update(error=True,message=str(e))
    finally:
        STATE['busy']=False
        LOCK.release()

def delete_job(pids):
    try:
        result=engine.delete_songs(pids,STATE['device']['root'])
        STATE.update(message=result['message'],error=False,backup=result.get('backup'))
        refresh()
    except Exception as e:STATE.update(error=True,message=str(e))
    finally:
        STATE['busy']=False
        LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,data,code=200,kind='application/json; charset=utf-8'):
        raw=json.dumps(data,ensure_ascii=False).encode() if isinstance(data,dict) else data
        self.send_response(code)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; connect-src 'self'")
        self.end_headers();self.wfile.write(raw)
    def valid(self):
        return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and self.headers.get('X-iPod-Token')==TOKEN
    def do_GET(self):
        if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':return self.reply({'error':'Forbidden'},403)
        if self.path=='/':
            page=(Path(__file__).parent/'windows.html').read_text('utf-8').replace('__TOKEN__',TOKEN)
            return self.reply(page.encode(),kind='text/html; charset=utf-8')
        if not self.valid():return self.reply({'error':'Forbidden'},403)
        if self.path=='/api/status':return self.reply(dict(ok=True,**STATE))
        if self.path=='/api/songs':
            if not STATE['device']:return self.reply(dict(ok=False,error='请连接 iPod 并刷新。'),400)
            try:return self.reply(dict(ok=True,**engine.song_list(STATE['device']['root'])))
            except Exception as e:return self.reply(dict(ok=False,error=str(e)),400)
        if self.path=='/api/driver':
            try:
                result=engine.windows_probe()
                result.update(ok=True)
            except Exception as e:
                result=dict(ok=True,platform=sys.platform,unsupported=True,
                            error=str(e),usb=[],volumes=[],drivers=[],winget=False,driver_installed=False)
            try:
                result.update(device=engine.inspect(),mounted=True)
            except Exception as e:
                result.update(device=None,mounted=False,mount_error=str(e))
            return self.reply(result)
        return self.reply({'error':'Not found'},404)
    def do_POST(self):
        if not self.valid():return self.reply({'error':'Forbidden'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            path=urlparse(self.path)
            if path.path=='/api/upload':
                if STATE['busy']:raise ValueError('正在导入，请稍候。')
                if not 0<length<=512*1024*1024:raise ValueError('文件大小需在 0–512 MB 之间。')
                if sum(p.stat().st_size for p in UPLOADS.values())+length>8*1024**3:raise ValueError('单次暂存上限为 8 GB，请分批导入。')
                name=Path(parse_qs(path.query).get('name',['song.mp3'])[0].replace('\\','/')).name
                if not name.lower().endswith('.mp3'):raise ValueError('仅支持 MP3。')
                key=secrets.token_hex(12);dest=TEMP/key/name;dest.parent.mkdir()
                remaining=length
                with open(dest,'xb') as f:
                    while remaining:
                        chunk=self.rfile.read(min(1024*1024,remaining))
                        if not chunk:raise ValueError('文件接收中断。')
                        f.write(chunk);remaining-=len(chunk)
                UPLOADS[key]=dest
                return self.reply(dict(ok=True,id=key,name=name))
            if length>64*1024:raise ValueError('请求过大。')
            data=json.loads(self.rfile.read(length) or b'{}')
            if path.path=='/api/import':
                ids=data.get('ids',[])
                if not ids or any(x not in UPLOADS for x in ids):raise ValueError('请重新添加 MP3。')
                if not STATE['device']:raise ValueError('请连接 iPod 并刷新。')
                if not LOCK.acquire(blocking=False):raise ValueError('正在导入，请稍候。')
                STATE.update(busy=True,error=False,message='正在检查重复、备份曲库并导入，请保持连接…')
                threading.Thread(target=import_job,args=(ids,),daemon=False).start()
                return self.reply(dict(ok=True))
            if path.path=='/api/delete':
                pids=data.get('pids',[])
                if not isinstance(pids,list) or not pids:raise ValueError('请先勾选要删除的歌曲。')
                try:pids=[int(x) for x in pids]
                except Exception:raise ValueError('歌曲编号无效。')
                if not STATE['device']:raise ValueError('请连接 iPod 并刷新。')
                if not LOCK.acquire(blocking=False):raise ValueError('正在处理，请稍候。')
                STATE.update(busy=True,error=False,message='正在备份曲库并删除选中歌曲，请保持连接…')
                threading.Thread(target=delete_job,args=(pids,),daemon=False).start()
                return self.reply(dict(ok=True))
            if not LOCK.acquire(blocking=False):raise ValueError('正在导入，请稍候。')
            try:
                if path.path=='/api/refresh':
                    if refresh():STATE['message']='可以导入，原有歌曲会保留。'
                elif path.path=='/api/recover':
                    roots=[p for p in engine.candidates() if (p/'iPod_Control').is_dir()]
                    if len(roots)!=1:raise ValueError('请只连接一台 iPod。')
                    result=engine.recover(roots[0]);refresh();STATE.update(message=result['message'],error=False)
                elif path.path=='/api/eject':
                    if not STATE['device']:raise ValueError('没有已连接的设备。')
                    result=engine.eject(STATE['device']['root']);STATE.update(device=None,message=result['message'],error=False)
                elif path.path=='/api/backup':
                    folder=engine.backup_home();folder.mkdir(parents=True,exist_ok=True)
                    if os.name=='nt':os.startfile(folder)
                    else:engine.run(['open',str(folder)])
                elif path.path=='/api/quit':
                    self.reply(dict(ok=True));threading.Thread(target=self.server.shutdown).start();return
                elif path.path=='/api/driver-install':
                    return self.reply(dict(ok=True,**engine.install_windows_driver()))
                else:raise ValueError('未知操作。')
                return self.reply(dict(ok=True,**STATE))
            finally:LOCK.release()
        except Exception as e:self.reply(dict(ok=False,error=str(e)),400)

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    refresh()
    url=f'http://127.0.0.1:{server.server_port}/'
    print(url,flush=True)
    if '--no-browser' not in sys.argv:webbrowser.open(url)
    try:server.serve_forever(poll_interval=.25)
    finally:server.server_close();shutil.rmtree(TEMP,ignore_errors=True)

if __name__=='__main__':
    try:main()
    except Exception:
        log=Path(os.environ.get('TEMP',str(Path.home())))/'ipod-drop-error.txt'
        log.write_text(traceback.format_exc(),encoding='utf-8')
        if os.name=='nt':os.startfile(log)
        else:raise

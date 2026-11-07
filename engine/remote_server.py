"""
Phone remote: control MXB from your phone's browser over your home Wi-Fi.

"MXB, turn on phone remote" -> asks for confirmation -> shows a URL + QR code.
Open it on your phone: chat with MXB, see live progress, press Stop, answer Yes/No
questions, and peek at the PC screen.

Security model:
- OFF by default; turning it on needs a spoken/typed "yes".
- Every API call needs a random 128-bit token (in the QR link, stored by the phone page).
- Only private-network clients (192.168.x, 10.x, 172.16-31.x, localhost) are served.
- 10 bad tokens from one address -> that address is blocked for 10 minutes.
- Screen peek can be disabled (remote.allow_screen = false).
It is plain HTTP on your LAN: don't enable it on public/untrusted Wi-Fi.
"""
import ipaddress
import json
import secrets
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from utils.logger import log

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MXB Remote</title>
<style>
:root{--bg:#0c0e14;--panel:#12151e;--line:#232a3a;--cyan:#00e5ff;--pink:#ff2a5f;--text:#e8ecf4;--muted:#8a93a6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;display:flex;flex-direction:column;height:100dvh}
header{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--line)}
header b{color:var(--cyan);letter-spacing:2px;font-size:14px}#status{color:var(--muted);font-size:12px;flex:1;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button{background:#1a1f2c;color:var(--text);border:1px solid #2b3245;border-radius:10px;padding:9px 13px;font-size:14px}
#stop{background:#3a0f1a;border-color:var(--pink);color:#ffb3c4;font-weight:700}
#log{flex:1;overflow-y:auto;padding:10px 12px}.msg{margin:8px 0;max-width:88%;padding:8px 11px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}
.you{margin-left:auto;background:#2a1520;border:1px solid #4a2232}.mxb{background:var(--panel);border:1px solid var(--line)}
.meta{font-size:11px;color:var(--muted);margin-bottom:2px}#progress{color:#a0ffa0;font:12px Consolas,monospace;padding:0 12px 6px;min-height:16px}
#confirm{display:none;margin:0 12px 8px;padding:10px;border:1px solid #ffd700;border-radius:10px;background:#2a2410;color:#ffe680}
#confirm div{margin-top:8px;display:flex;gap:8px}#yes{background:#0f3a22;border-color:#2bd67b;flex:1}#no{background:#3a0f1a;border-color:var(--pink);flex:1}
form{display:flex;gap:8px;padding:10px 12px;border-top:1px solid var(--line)}input{flex:1;background:var(--panel);color:#fff;border:1px solid var(--cyan);border-radius:10px;padding:11px;font-size:15px}
#screen{display:none;padding:0 12px 8px}#screen img{width:100%;border-radius:10px;border:1px solid var(--line)}
#auth{display:none;padding:20px;color:var(--muted)}
</style></head><body>
<header><b>MXB</b><button id="peek">Screen</button><span id="status">connecting…</span><button id="stop">■ Stop</button></header>
<div id="auth">This link is missing its access token. Open the full link or scan the QR code shown in MXB's chat window on your PC.</div>
<div id="log"></div><div id="screen"><img id="shot" alt="PC screen"></div>
<div id="confirm"><span id="q"></span><div><button id="yes">Yes</button><button id="no">No</button></div></div>
<div id="progress"></div>
<form id="f"><input id="t" placeholder="Tell MXB what to do…" autocomplete="off"><button>Send</button></form>
<script>
const qs=new URLSearchParams(location.search);let token=qs.get('t');
try{if(token){localStorage.setItem('mxb_token',token);history.replaceState(null,'','/')}else token=localStorage.getItem('mxb_token')}catch(e){}
const $=id=>document.getElementById(id);let after=0;
if(!token){$('auth').style.display='block'}
async function api(path,opts={}){opts.headers=Object.assign({'Authorization':'Bearer '+token,'Content-Type':'application/json'},opts.headers||{});
 const r=await fetch(path,opts);if(r.status===401){$('auth').style.display='block';throw new Error('auth')}return r}
function add(cls,who,text){const d=document.createElement('div');d.className='msg '+cls;const m=document.createElement('div');m.className='meta';m.textContent=who;d.appendChild(m);d.appendChild(document.createTextNode(text));$('log').appendChild(d);$('log').scrollTop=1e9}
function handle(ev){if(ev.type==='user')add('you','You · '+ev.source,ev.text);else if(ev.type==='reply'){if(ev.text)add('mxb','MXB',ev.text)}
 else if(ev.type==='feedback')$('progress').textContent=ev.text;else if(ev.type==='status')$('status').textContent=ev.text;
 else if(ev.type==='confirm'){$('q').textContent=ev.text;$('confirm').style.display='block'}else if(ev.type==='confirm_done')$('confirm').style.display='none'}
async function poll(){while(true){try{const r=await api('/api/events?after='+after+'&wait=25');const j=await r.json();
 for(const ev of j.events){after=Math.max(after,ev.id);handle(ev)}}catch(e){await new Promise(r=>setTimeout(r,3000))}}}
$('f').onsubmit=async e=>{e.preventDefault();const t=$('t').value.trim();if(!t)return;$('t').value='';await api('/api/command',{method:'POST',body:JSON.stringify({text:t})})};
$('stop').onclick=()=>api('/api/stop',{method:'POST'});
$('yes').onclick=()=>api('/api/confirm',{method:'POST',body:JSON.stringify({approved:true})});
$('no').onclick=()=>api('/api/confirm',{method:'POST',body:JSON.stringify({approved:false})});
let peeking=null;$('peek').onclick=()=>{const s=$('screen');if(peeking){clearInterval(peeking);peeking=null;s.style.display='none';return}
 s.style.display='block';const load=async()=>{try{const r=await api('/api/screen');if(r.ok)$('shot').src=URL.createObjectURL(await r.blob())}catch(e){}};load();peeking=setInterval(load,2500)};
if(token){api('/api/status').then(r=>r.json()).then(s=>{$('status').textContent=s.status}).catch(()=>{});poll()}
</script></body></html>"""


def is_private_address(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the outgoing interface
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class EventLog:
    """Thread-safe ring buffer with long-polling."""

    def __init__(self, maxlen: int = 300):
        self._events: deque = deque(maxlen=maxlen)
        self._cond = threading.Condition()
        self._next_id = 1

    def push(self, type_: str, text: str = "", source: str = ""):
        with self._cond:
            self._events.append({"id": self._next_id, "type": type_, "text": text, "source": source, "time": time.time()})
            self._next_id += 1
            self._cond.notify_all()

    def since(self, after: int, wait: float = 0.0) -> list[dict]:
        deadline = time.time() + wait
        with self._cond:
            while True:
                items = [e for e in self._events if e["id"] > after]
                remaining = deadline - time.time()
                if items or remaining <= 0:
                    return items
                self._cond.wait(remaining)


class RemoteServer:
    def __init__(self, bus=None, config: dict | None = None, store_path: str | Path | None = None,
                 screen_grabber=None):
        cfg = (config or {}).get("remote", {}) if isinstance(config, dict) else {}
        self.bus = bus
        self.port = int(cfg.get("port", 8765))
        self.host = cfg.get("host", "0.0.0.0")
        self.allow_screen = bool(cfg.get("allow_screen", True))
        self.store_path = Path(store_path) if store_path else Path(__file__).parent.parent / "remote.json"
        self.token = self._load_or_create_token()
        self.events = EventLog()
        self.screen_grabber = screen_grabber
        self._httpd: ThreadingHTTPServer | None = None
        self._thread = None
        self._failures: dict[str, list[float]] = {}
        self._fail_lock = threading.Lock()
        self._wired = False

    # ------------------------------------------------------------------ token
    def _load_or_create_token(self) -> str:
        try:
            if self.store_path.exists():
                tok = json.loads(self.store_path.read_text(encoding="utf-8")).get("token")
                if tok and len(tok) >= 20:
                    return tok
        except Exception:
            pass
        tok = secrets.token_urlsafe(16)
        try:
            self.store_path.write_text(json.dumps({"token": tok}), encoding="utf-8")
        except Exception:
            pass
        return tok

    def rotate_token(self) -> str:
        self.token = secrets.token_urlsafe(16)
        try:
            self.store_path.write_text(json.dumps({"token": self.token}), encoding="utf-8")
        except Exception:
            pass
        return self.token

    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}/?t={self.token}"

    # ------------------------------------------------------------------ bus wiring
    def wire_bus(self):
        if self._wired or self.bus is None:
            return
        from PySide6.QtCore import Qt
        direct = Qt.ConnectionType.DirectConnection  # called on the emitting thread; EventLog is thread-safe
        self.bus.user_message.connect(lambda t, s: self.events.push("user", t, s), direct)
        self.bus.reply_ready.connect(lambda t, s: self.events.push("reply", t, s), direct)
        self.bus.feedback.connect(lambda t: self.events.push("feedback", t), direct)
        self.bus.status_changed.connect(lambda t: self.events.push("status", t), direct)
        self.bus.confirmation_requested.connect(lambda q: self.events.push("confirm", q), direct)
        self.bus.confirmation_resolved.connect(lambda ok: self.events.push("confirm_done", "yes" if ok else "no"), direct)
        self._wired = True

    # ------------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> str:
        if self.running:
            return self.url()
        self.wire_bus()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _send(self, code: int, body: bytes, ctype: str = "application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, obj):
                self._send(code, json.dumps(obj).encode("utf-8"))

            def _guard(self, need_token: bool = True) -> bool:
                client = self.client_address[0]
                if not is_private_address(client):
                    self._json(403, {"error": "private network only"})
                    return False
                if server.is_locked_out(client):
                    self._json(429, {"error": "too many bad tokens; try again later"})
                    return False
                if not need_token:
                    return True
                auth = self.headers.get("Authorization", "")
                supplied = auth[7:] if auth.startswith("Bearer ") else ""
                if not supplied or not secrets.compare_digest(supplied, server.token):
                    server.note_failure(client)
                    self._json(401, {"error": "bad token"})
                    return False
                return True

            def _body(self) -> dict:
                try:
                    length = min(int(self.headers.get("Content-Length", 0)), 20000)
                    return json.loads(self.rfile.read(length) or b"{}")
                except Exception:
                    return {}

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/index.html"):
                    if self._guard(need_token=False):
                        self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if not self._guard():
                    return
                if parsed.path == "/api/status":
                    self._json(200, server.status())
                elif parsed.path == "/api/events":
                    q = parse_qs(parsed.query)
                    after = int((q.get("after") or ["0"])[0] or 0)
                    wait = min(float((q.get("wait") or ["0"])[0] or 0), 25.0)
                    self._json(200, {"events": server.events.since(after, wait)})
                elif parsed.path == "/api/screen":
                    data = server.screen_jpeg()
                    if data is None:
                        self._json(403 if not server.allow_screen else 503, {"error": "screen unavailable"})
                    else:
                        self._send(200, data, "image/jpeg")
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                parsed = urlparse(self.path)
                if not self._guard():
                    return
                body = self._body()
                if parsed.path == "/api/command":
                    text = str(body.get("text", "")).strip()[:500]
                    result = server.bus.submit(text, "phone") if (server.bus and text) else "empty"
                    self._json(200, {"result": result})
                elif parsed.path == "/api/stop":
                    if server.bus:
                        server.bus.submit("stop", "phone")
                    self._json(200, {"result": "stopped"})
                elif parsed.path == "/api/confirm":
                    if server.bus:
                        server.bus.resolve_confirmation(bool(body.get("approved")))
                    self._json(200, {"result": "ok"})
                else:
                    self._json(404, {"error": "not found"})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="MXB-Remote", daemon=True)
        self._thread.start()
        log.info(f"Remote: phone remote listening on port {self.port}")
        return self.url()

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            log.info("Remote: phone remote stopped")

    # ------------------------------------------------------------------ helpers
    def note_failure(self, client: str):
        with self._fail_lock:
            now = time.time()
            hits = [t for t in self._failures.get(client, []) if now - t < 600] + [now]
            self._failures[client] = hits

    def is_locked_out(self, client: str) -> bool:
        with self._fail_lock:
            now = time.time()
            hits = [t for t in self._failures.get(client, []) if now - t < 600]
            self._failures[client] = hits
            return len(hits) >= 10

    def status(self) -> dict:
        bus = self.bus
        if bus is None:
            return {"status": "no bus"}
        return {"status": bus.describe_status(), "busy": bus.busy, "pending_confirmation": bus.confirm.has_pending()}

    def screen_jpeg(self) -> bytes | None:
        if not self.allow_screen or self.screen_grabber is None:
            return None
        try:
            import io
            img = self.screen_grabber()
            if img is None:
                return None
            img = img.convert("RGB")
            if img.width > 1280:
                img = img.resize((1280, int(img.height * 1280 / img.width)))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            return buf.getvalue()
        except Exception as e:
            log.warning(f"Remote: screen capture failed: {e}")
            return None

    def qr_png(self) -> bytes | None:
        try:
            import io
            import qrcode
            img = qrcode.make(self.url())
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

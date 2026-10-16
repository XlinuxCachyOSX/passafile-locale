#!/usr/bin/env python3
import argparse, html, os, re, socket, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

V = "1.0.1"
E = [-1, 10, 16, 26, 18, 24, 16]
N = [-1, 1, 1, 1, 2, 2, 4]

def mul(a, b):
    z = 0
    for i in range(7, -1, -1):
        z = ((z << 1) ^ ((z >> 7) * 0x11D)) & 0xFF
        z ^= ((b >> i) & 1) * a
    return z

def rs(data, d):
    div = [0]*(d-1)+[1]; root = 1
    for _ in range(d):
        for j in range(d): div[j] = mul(div[j], root); div[j] ^= div[j+1] if j+1 < d else 0
        root = mul(root, 2)
    r = [0]*d
    for b in data:
        f = b ^ r.pop(0); r.append(0)
        for i, g in enumerate(div): r[i] ^= mul(g, f)
    return r

def rawmods(v):
    t = (16*v+128)*v+64
    if v >= 2:
        a = v//7+2; t -= (25*a-10)*a-55
    return t
def encode(data):
    for v in range(1, 7):
        cap = (rawmods(v)//8-E[v]*N[v])*8
        if 12+8*len(data) <= cap: break
    else: raise ValueError
    bits = f"0100{len(data):08b}"+"".join(f"{b:08b}" for b in data)+"0000"
    cw = [int((bits+"1110110000010001"*60)[:cap][i:i+8], 2) for i in range(0, cap, 8)]
    nb, be = N[v], E[v]; raw = rawmods(v)//8
    ns = nb-raw % nb; sl = raw//nb; bl = []; k = 0
    for i in range(nb):
        dl = sl-be+(0 if i < ns else 1); d = cw[k:k+dl]; k += dl
        bl.append(d+([0] if i < ns else [])+rs(d, be))
    return v, [b[i] for i in range(len(bl[0])) for j, b in enumerate(bl) if i != sl-be or j >= ns]

def fmt(S, setf):
    b = 0x5412
    for i in range(6): setf(8, i, (b >> i) & 1)
    setf(8, 7, (b >> 6) & 1); setf(8, 8, (b >> 7) & 1); setf(7, 8, (b >> 8) & 1)
    for i in range(9, 15): setf(14-i, 8, (b >> i) & 1)
    for i in range(8): setf(S-1-i, 8, (b >> i) & 1)
    for i in range(8, 15): setf(8, S-15+i, (b >> i) & 1)
    setf(8, S-8, 1)

def aligns(v):
    return [] if v == 1 else [6, 4*v+10]

def matrix(text):
    v, cw = encode(text.encode())
    S = v*4+17; M = [[False]*S for _ in range(S)]; G = [r[:] for r in M]
    def setf(x, y, dk): M[y][x] = dk; G[y][x] = True
    for i in range(S): setf(6, i, i % 2 == 0); setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (S-4, 3), (3, S-4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if 0 <= cx+dx < S and 0 <= cy+dy < S: setf(cx+dx, cy+dy, max(abs(dx), abs(dy)) not in (2, 4))
    al = aligns(v); la = len(al)-1
    for i, y in enumerate(al):
        for j, x in enumerate(al):
            if (i, j) in ((0, 0), (0, la), (la, 0)): continue
            for dy in range(-2, 3):
                for dx in range(-2, 3): setf(x+dx, y+dy, max(abs(dx), abs(dy)) != 1)
    fmt(S, setf)
    idx = 0; right = S-1
    while right >= 1:
        if right == 6: right = 5
        for vert in range(S):
            for j in range(2):
                x = right-j; y = S-1-vert if ((right+1) & 2) == 0 else vert
                if not G[y][x] and idx < len(cw)*8:
                    M[y][x] = ((cw[idx >> 3] >> (7-idx % 8)) & 1) != 0; idx += 1
        right -= 2
    for y in range(S):
        for x in range(S):
            if not G[y][x] and (x+y) % 2 == 0: M[y][x] = not M[y][x]
    return M

def qr_txt(text):
    m = matrix(text); n = len(m)+8
    g = [[False]*n]*4+[[False]*4+row+[False]*4 for row in m]+[[False]*n]*4
    g.append([False]*n)
    return "\n".join("".join(("\033[30m" if g[y][x] else "\033[97m")+("\033[40m" if g[y+1][x] else "\033[107m")+"▀" for x in range(n))+"\033[0m" for y in range(0, n, 2))

def lip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("1.1.1.1", 1)); r = s.getsockname()[0]
    except OSError: r = "127.0.0.1"
    s.close(); return r

def clean(p):
    p = unquote(p).replace("\\", "/").strip("/")
    return "/".join(x for x in p.split("/") if x not in ("", ".", ".."))

def mp_parse(body, bd):
    out = []
    for p in body.split(b"--"+bd)[1:-1]:
        i = p.find(b"\r\n\r\n")
        m = re.search(br'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', p[:i]) if i >= 0 else None
        f = m.group(1).strip() if m else b""
        if f: out.append((f.decode("utf-8", "replace"), p[i+4:-2]))
    return out

PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><style>
body{font:15px system-ui,sans-serif;background:#111;color:#eee;max-width:700px;margin:auto;padding:24px 16px}p{color:#999;font-size:.85rem;margin:8px 0}.c{background:#161b22;border:1px solid #333;padding:12px;margin:14px 0}input{width:100%;box-sizing:border-box;padding:16px;color:#999}ul{list-style:none;padding:0}li{display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid #333}.n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}a,button{background:#222;border:1px solid #333;color:#eee;padding:5px 9px;cursor:pointer;text-decoration:none}#off{display:none;background:#411;border:1px solid #f55;color:#fbb;padding:10px}
</style></head><body><h1>📦 Passafile Locale</h1><div id=off>⚠ Server non raggiungibile: riavvia start.</div><div class=c><h2>Carica</h2><input type=file id=fi multiple></div><div class=c><h2>File condivisi (__C__)</h2>__L__</div><p>v__V__ · __U__</p><script>
function offl(){off.style.display='block'}fi.onchange=async()=>{const fd=new FormData;for(const f of fi.files)fd.append('file',f);try{(await fetch('/upload',{method:'POST',body:fd})).ok?location.reload():alert('Errore')}catch(e){offl()}};async function del(n){if(!confirm('Eliminare "'+n+'"?'))return;try{(await fetch('/delete',{method:'POST',body:'name='+encodeURIComponent(n)})).ok&&location.reload()}catch(e){offl()}}fetch('/ping').catch(offl);
</script></body></html>"""

def page(share, base):
    rows = []
    for n in os.listdir(share):
        if n.startswith("."): continue
        if not os.path.isfile(os.path.join(share, n)): continue
        j = html.escape(n.replace("\\", "\\\\").replace("'", "\\'"))
        rows.append(f'<li><span class=n>{html.escape(n)}</span><a href="/f/{quote(n)}">⬇</a><button onclick="del(\'{j}\')">✕</button></li>')
    lst = "<ul>"+"".join(rows)+"</ul>" if rows else "<p>Nessun file.</p>"
    return PAGE.replace("__C__", str(len(rows))).replace("__L__", lst).replace("__V__", V).replace("__U__", html.escape(base))

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def snd(self, code, body="", ct="text/plain"):
        body = body.encode()
        try:
            self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body))); self.end_headers()
            if self.command != "HEAD": self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass
    def rdr(self): return self.rfile.read(int(self.headers.get("Content-Length") or 0))
    def safe(self, raw):
        rel = clean(raw); root = os.path.realpath(self.server.sd); full = os.path.realpath(os.path.join(root, rel))
        return (rel, full) if full == root or full.startswith(root+os.sep) else None
    def do_GET(self):
        p = unquote(urlsplit(self.path).path)
        if p == "/": self.snd(200, page(self.server.sd, self.server.u), "text/html")
        elif p == "/ping": self.snd(200, "ok")
        elif p.startswith("/f/"): self.dl(p[3:])
        else: self.snd(404, "Non trovato")
    do_HEAD = do_GET
    def do_POST(self):
        p = urlsplit(self.path).path
        if p == "/upload":
            data = self.rdr()
            ct = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ct: self.snd(400, "multipart richiesto"); return
            sd = self.server.sd; saved = []
            for raw, content in mp_parse(data, ct.split("boundary=")[-1].strip('"').encode()):
                name = os.path.basename(clean(raw))
                if not name: continue
                tgt = name; i = 1
                while os.path.exists(sd+"/"+tgt): b, e = os.path.splitext(name); tgt = f"{b} ({i}){e}"; i += 1
                open(sd+"/"+tgt, "wb").write(content); saved.append(tgt)
            self.snd(200, "\n".join(saved))
        elif p == "/delete":
            r = self.safe(parse_qs(self.rdr().decode("utf-8", "replace")).get("name", [""])[0])
            if not r or not r[0] or not os.path.isfile(r[1]): self.snd(404, "Non trovato"); return
            os.remove(r[1]); self.snd(200, "ok")
        else: self.rdr(); self.snd(404, "Non trovato")
    def dl(self, raw):
        r = self.safe(raw)
        if not r: self.snd(403, "accesso negato"); return
        rel, full = r
        if not rel or any(x.startswith(".") for x in rel.split("/")) or not os.path.isfile(full):
            self.snd(404, "Non trovato"); return
        data = open(full, "rb").read(); fn = os.path.basename(rel)
        self.send_response(200); self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data))); self.send_header("Content-Disposition", "attachment; filename*=UTF-8''"+quote(fn)); self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError): pass

def main():
    ap = argparse.ArgumentParser(description="Passafile: server locale con QR.")
    ap.add_argument("-d", "--dir", default=os.path.join(os.path.dirname(__file__), "condivisi"))
    ap.add_argument("-p", "--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", dest="op")
    a = ap.parse_args()
    share = os.path.realpath(a.dir); os.makedirs(share, exist_ok=True)
    port = a.port
    while True:
        try: srv = ThreadingHTTPServer(("", port), H); break
        except OSError: port += 1
    url = f"http://{lip()}:{port}/"; srv.sd = share; srv.u = url
    print(f"\n  Passafile {V} | {url} | {share}\n")
    try: print("  Inquadra col telefono:\n"+qr_txt(url)+"\n")
    except ValueError: pass
    if a.op: threading.Timer(.6, lambda: webbrowser.open(url)).start()
    print("  Ctrl+C per fermare.\n")
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\n  Server fermato.")
    finally: srv.server_close()

if __name__ == "__main__": main()

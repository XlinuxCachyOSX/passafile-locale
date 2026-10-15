#!/usr/bin/env python3
import argparse
import html
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import unicodedata
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

VERSION = "1.0.0"
EC_M = 0

_ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24,
                  28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
                  28, 28, 28, 28, 28, 28, 28, 28, 28]
_NUM_BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14,
               16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40,
               43, 45, 47, 49]

_drawn = None


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = ((z << 1) ^ ((z >> 7) * 0x11D)) & 0xFF
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, g in enumerate(divisor):
            result[i] ^= _gf_mul(g, factor)
    return result


def _num_raw_data_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def _num_data_codewords(ver):
    return _num_raw_data_modules(ver) // 8 - _ECC_PER_BLOCK[ver] * _NUM_BLOCKS[ver]


def _alignment_positions(ver):
    if ver == 1:
        return []
    numalign = ver // 7 + 2
    step = 26 if ver == 32 else (ver * 4 + numalign * 2 + 1) // (numalign * 2 - 2) * 2
    result = [6]
    pos = ver * 4 + 10
    for _ in range(1, numalign):
        result.insert(1, pos)
        pos -= step
    return result


def _bit(val, i):
    return ((val >> i) & 1) != 0


def _choose_version(nbytes):
    for ver in range(1, 41):
        cc = 8 if ver < 10 else 16
        if 4 + cc + 8 * nbytes <= _num_data_codewords(ver) * 8:
            return ver
    raise ValueError("contenuto troppo lungo per un QR code")


def _encode_byte_stream(data, ver):
    cap = _num_data_codewords(ver) * 8
    bits = []

    def append(val, n):
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)

    append(0b0100, 4)
    append(len(data), 8 if ver < 10 else 16)
    for b in data:
        append(b, 8)
    append(0, min(4, cap - len(bits)))
    append(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) + 8 <= cap:
        append(pad, 8)
        pad ^= 0xEC ^ 0x11
    return [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]


def _add_ecc(data, ver):
    numblocks = _NUM_BLOCKS[ver]
    blockecc = _ECC_PER_BLOCK[ver]
    rawcodewords = _num_raw_data_modules(ver) // 8
    numshort = numblocks - rawcodewords % numblocks
    shortlen = rawcodewords // numblocks
    gen = _rs_divisor(blockecc)
    blocks = []
    k = 0
    for i in range(numblocks):
        datlen = shortlen - blockecc + (0 if i < numshort else 1)
        dat = data[k:k + datlen]
        k += datlen
        ecc = _rs_remainder(dat, gen)
        if i < numshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != shortlen - blockecc or j >= numshort:
                result.append(block[i])
    return result


def _set_func(x, y, dark):
    _modules[y][x] = dark
    _drawn[y][x] = True


def _draw_finder(x, y):
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            dist = max(abs(dx), abs(dy))
            xx, yy = x + dx, y + dy
            if 0 <= xx < _size and 0 <= yy < _size:
                _set_func(xx, yy, dist not in (2, 4))


def _draw_alignment(x, y):
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            _set_func(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)


def _draw_format(mask):
    data = (EC_M << 3) | mask
    rem = data
    for _ in range(10):
        rem = ((rem << 1) ^ ((rem >> 9) * 0x537)) & 0x7FF
    bits = ((data << 10) | rem) ^ 0x5412
    for i in range(6):
        _set_func(8, i, _bit(bits, i))
    _set_func(8, 7, _bit(bits, 6))
    _set_func(8, 8, _bit(bits, 7))
    _set_func(7, 8, _bit(bits, 8))
    for i in range(9, 15):
        _set_func(14 - i, 8, _bit(bits, i))
    for i in range(8):
        _set_func(_size - 1 - i, 8, _bit(bits, i))
    for i in range(8, 15):
        _set_func(8, _size - 15 + i, _bit(bits, i))
    _set_func(8, _size - 8, True)


def _draw_version(ver):
    if ver < 7:
        return
    rem = ver
    for _ in range(12):
        rem = ((rem << 1) ^ ((rem >> 11) * 0x1F25)) & 0x3FFFF
    bits = (ver << 12) | rem
    for i in range(18):
        dark = _bit(bits, i)
        a = _size - 11 + i % 3
        b = i // 3
        _set_func(a, b, dark)
        _set_func(b, a, dark)


def _mask_fn(mask, x, y):
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (y // 2 + x // 3) % 2 == 0
    if mask == 5:
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:
        return (x * y % 2 + x * y % 3) % 2 == 0
    return ((x + y) % 2 + x * y % 3) % 2 == 0


def _line_score(getter, length):
    score = 0
    run_color = getter(0)
    run_len = 1
    for i in range(1, length):
        if getter(i) == run_color:
            run_len += 1
        else:
            if run_len >= 5:
                score += 3 + run_len - 5
            run_color = getter(i)
            run_len = 1
    if run_len >= 5:
        score += 3 + run_len - 5

    padded = [getter(i) for i in range(length)]
    padded = [False] * 4 + padded + [False] * 4
    p1 = [True, False, True, True, True, False, True, False, False, False, False]
    p2 = [False, False, False, False, True, False, True, True, True, False, True]
    for i in range(length):
        win = padded[i:i + 11]
        if win == p1 or win == p2:
            score += 40
    return score


def _penalty():
    score = 0
    for y in range(_size):
        score += _line_score(lambda x, y=y: _modules[y][x], _size)
    for x in range(_size):
        score += _line_score(lambda y, x=x: _modules[y][x], _size)
    for y in range(_size - 1):
        for x in range(_size - 1):
            c = _modules[y][x]
            if c == _modules[y][x + 1] == _modules[y + 1][x] == _modules[y + 1][x + 1]:
                score += 3
    dark = sum(1 for row in _modules for c in row if c)
    total = _size * _size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    score += k * 10
    return score


def qr_matrix(text):
    global _modules, _drawn, _size
    data = text.encode("utf-8")
    ver = _choose_version(len(data))
    _size = ver * 4 + 17
    size = _size
    codewords = _add_ecc(_encode_byte_stream(data, ver), ver)
    _modules = [[False] * size for _ in range(size)]
    _drawn = [[False] * size for _ in range(size)]

    for i in range(size):
        _set_func(6, i, i % 2 == 0)
        _set_func(i, 6, i % 2 == 0)
    for x, y in ((3, 3), (size - 4, 3), (3, size - 4)):
        _draw_finder(x, y)
    aligns = _alignment_positions(ver)
    last = len(aligns) - 1
    for i, y in enumerate(aligns):
        for j, x in enumerate(aligns):
            if (i, j) not in ((0, 0), (0, last), (last, 0)):
                _draw_alignment(x, y)
    _draw_format(0)
    _draw_version(ver)

    idx = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not _drawn[y][x] and idx < len(codewords) * 8:
                    _modules[y][x] = _bit(codewords[idx >> 3], 7 - (idx & 7))
                    idx += 1
        right -= 2

    best_matrix = None
    best_score = None
    best_mask = 0
    for mask in range(8):
        for y in range(size):
            for x in range(size):
                if not _drawn[y][x] and _mask_fn(mask, x, y):
                    _modules[y][x] = not _modules[y][x]
        _draw_format(mask)
        sc = _penalty()
        if best_score is None or sc < best_score:
            best_score = sc
            best_matrix = [row[:] for row in _modules]
            best_mask = mask
        for y in range(size):
            for x in range(size):
                if not _drawn[y][x] and _mask_fn(mask, x, y):
                    _modules[y][x] = not _modules[y][x]

    _modules = best_matrix
    _draw_format(best_mask)
    return [row[:] for row in _modules]


def qr_svg(text, border=3):
    m = qr_matrix(text)
    size = len(m)
    dim = size + border * 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {dim} {dim}" '
           f'shape-rendering="crispEdges" width="100%" height="100%">',
           f'<rect width="{dim}" height="{dim}" fill="#ffffff"/>']
    for y, row in enumerate(m):
        x = 0
        while x < size:
            if row[x]:
                x2 = x + 1
                while x2 < size and row[x2]:
                    x2 += 1
                out.append(f'<rect x="{x + border}" y="{y + border}" '
                           f'width="{x2 - x}" height="1" fill="#111417"/>')
                x = x2
            else:
                x += 1
    out.append("</svg>")
    return "".join(out)


def qr_terminal(text, border=2):
    m = qr_matrix(text)
    size = len(m) + border * 2
    grid = [[False] * size for _ in range(size)]
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            grid[y + border][x + border] = v
    if size % 2:
        grid.append([False] * size)
    lines = []
    for y in range(0, size, 2):
        parts = []
        for x in range(size):
            top, bottom = grid[y][x], grid[y + 1][x]
            fg = "\033[30m" if top else "\033[97m"
            bg = "\033[40m" if bottom else "\033[107m"
            parts.append(fg + bg + "\u2580")
        lines.append("".join(parts) + "\033[0m")
    return "\n".join(lines)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


def sanitize_name(name):
    name = unicodedata.normalize("NFC", unquote(str(name))).replace("\\", "/").strip("/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def unique_path(directory, relpath):
    full = os.path.join(directory, relpath)
    if not os.path.exists(full):
        return relpath
    base, ext = os.path.splitext(relpath)
    i = 1
    while True:
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(os.path.join(directory, cand)):
            return cand
        i += 1


def parse_multipart(body, boundary):
    delim = b"--" + boundary
    files = []
    for part in body.split(delim):
        if part in (b"--", b"--\r\n", b""):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if part == b"--" or b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        headers = header_blob.decode("utf-8", "replace")
        match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";\r\n]+)\"?", headers, re.I)
        if not match:
            continue
        filename = match.group(1).strip()
        if filename:
            files.append((filename, content))
    return files


PAGE = """<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Passafile Locale</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--txt:#e6edf3;--dim:#8b949e;
--acc:#2ea043;--acc2:#388bfd;--dang:#f85149}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--txt);min-height:100vh;padding:24px 16px}
.wrap{max-width:760px;margin:0 auto}
header{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#2ea043,#388bfd);
display:flex;align-items:center;justify-content:center;font-size:22px;flex:none}
h1{font-size:1.35rem}
.sub{color:var(--dim);font-size:.9rem;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:18px;margin-bottom:16px}
.drop{border:2px dashed var(--line);border-radius:12px;padding:34px 16px;text-align:center;
cursor:pointer;transition:.15s;color:var(--dim)}
.drop:hover,.drop.over{border-color:var(--acc);background:rgba(46,160,67,.08);color:var(--txt)}
.drop b{display:block;color:var(--txt);font-size:1.02rem;margin-bottom:6px}
.grid{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:start}
.qr{background:#fff;padding:10px;border-radius:10px;width:160px;aspect-ratio:1}
h2{font-size:1rem;margin-bottom:12px;color:var(--dim);font-weight:600;text-transform:uppercase;
letter-spacing:.05em}
ul{list-style:none}
li{display:flex;align-items:center;gap:10px;padding:11px 4px;border-bottom:1px solid var(--line)}
li:last-child{border:none}
.ico{width:34px;height:34px;border-radius:8px;background:#21262d;display:flex;
align-items:center;justify-content:center;font-size:16px;flex:none}
.meta{flex:1;min-width:0}
.name{font-size:.95rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.size{color:var(--dim);font-size:.78rem}
.acts{display:flex;gap:6px}
button,.btn{background:#21262d;border:1px solid var(--line);color:var(--txt);
border-radius:8px;padding:7px 11px;font-size:.8rem;cursor:pointer;text-decoration:none;
display:inline-block;transition:.12s}
button:hover,.btn:hover{border-color:var(--acc2);color:var(--acc2)}
button.del:hover{border-color:var(--dang);color:var(--dang)}
.empty{color:var(--dim);text-align:center;padding:18px 0;font-size:.9rem}
.bar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;
margin-bottom:10px}
.url{font-family:ui-monospace,monospace;color:var(--acc2);font-size:.85rem;
word-break:break-all;user-select:all}
.crumb{font-size:.85rem;color:var(--dim);margin-bottom:14px}
.crumb a{color:var(--acc2);text-decoration:none}
.crumb a:hover{text-decoration:underline}
footer{color:var(--dim);font-size:.78rem;text-align:center;margin-top:18px;line-height:1.6}
#prog{position:fixed;top:0;left:0;height:3px;background:var(--acc);width:0;transition:width .2s;z-index:9}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#1f6feb;
color:#fff;padding:10px 18px;border-radius:10px;font-size:.85rem;opacity:0;pointer-events:none;
transition:.25s;z-index:10}
#toast.show{opacity:1}
@media(max-width:560px){.grid{grid-template-columns:1fr}.qr{margin:0 auto}}
</style>
</head>
<body>
<div id="prog"></div>
<div class="wrap">
<header><div class="logo">&#128230;</div>
<div><h1>Passafile Locale</h1></div></header>
<p class="sub">Condividi file tra i dispositivi sulla stessa rete Wi-Fi.</p>

<div class="card">
<div class="grid">
<div>
<h2>Carica file</h2>
<div class="drop" id="drop"><b>Trascina qui i file</b>oppure clicca per selezionare
<input type="file" id="inp" multiple hidden></div>
</div>
<div>
<h2>Apri su telefono</h2>
<div class="qr">__QR__</div>
</div>
</div>
</div>

<div class="card">
<div class="bar"><h2>File (__COUNT__)</h2>
<span class="url" id="url">__URL__</span></div>
__CRUMB__
__LIST__
</div>

<footer>Passafile Locale v__VER__ &middot; funziona solo nella tua rete locale<br>
Non chiudere questa finestra mentre il server &egrave; in esecuzione</footer>
</div>
<div id="toast"></div>
<script>
const drop=document.getElementById('drop'),inp=document.getElementById('inp'),
prog=document.getElementById('prog');
function toast(t){const e=document.getElementById('toast');e.textContent=t;
e.classList.add('show');setTimeout(()=>e.classList.remove('show'),2200)}
async function send(files){
if(!files.length)return;
prog.style.width='30%';
const fd=new FormData();
for(const f of files)fd.append('file',f);
try{
const r=await fetch('/upload',{method:'POST',body:fd});
prog.style.width='100%';
if(r.ok){const j=await r.json();
toast(j.uploaded.length+' file caricati');setTimeout(()=>location.reload(),500)}
else{prog.style.width='0';toast('Errore durante il caricamento')}
}catch(e){prog.style.width='0';toast('Errore di rete')}
}
drop.addEventListener('click',()=>inp.click());
inp.addEventListener('change',()=>{send([...inp.files]);inp.value=''});
['dragover','dragenter'].forEach(ev=>drop.addEventListener(ev,e=>{
e.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{
e.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',e=>send([...e.dataTransfer.files]));
async function del(name){
if(!confirm('Eliminare "'+name+'"?'))return;
const r=await fetch('/delete',{method:'POST',
headers:{'Content-Type':'application/x-www-form-urlencoded'},
body:'name='+encodeURIComponent(name)});
if(r.ok)location.reload();else toast('Errore')
}
async function copy(name){
try{await navigator.clipboard.writeText(location.origin+'/f/'+name.split('/')
.map(encodeURIComponent).join('/'));
toast('Link copiato')}catch(e){toast('Copia non riuscita')}
}
</script>
</body>
</html>"""

FILE_ROW = """<li><div class="ico">__ICON__</div>
<div class="meta"><div class="name" title="__NAME__">__NAME__</div>
<div class="size">__SIZE__ &middot; __DATE__</div></div>
<div class="acts">__BTN__
<button onclick="copy('__JSNAME__')">Copia link</button>
<button class="del" onclick="del('__JSNAME__')">Elimina</button>
</div></li>"""


def file_icon(name, is_dir):
    if is_dir:
        return "&#128193;"
    ext = os.path.splitext(name)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic"):
        return "&#128247;"
    if ext in (".mp4", ".mkv", ".mov", ".avi", ".webm"):
        return "&#127916;"
    if ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
        return "&#127925;"
    if ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"):
        return "&#128230;"
    if ext in (".py", ".js", ".ts", ".c", ".cpp", ".java", ".html", ".css",
               ".json", ".sh", ".bat", ".yml", ".yaml", ".toml"):
        return "&#128736;"
    if ext in (".pdf", ".doc", ".docx", ".odt", ".rtf", ".md", ".epub"):
        return "&#128196;"
    if ext in (".xls", ".xlsx", ".ods", ".csv"):
        return "&#128202;"
    return "&#128196;"


def list_entries(share, rel=""):
    base = os.path.join(share, rel)
    entries = []
    try:
        names = sorted(os.listdir(base),
                       key=lambda n: (not os.path.isdir(os.path.join(base, n)), n.lower()))
    except OSError:
        return entries
    for n in names:
        if n.startswith("."):
            continue
        full = os.path.join(base, n)
        relpath = f"{rel}/{n}" if rel else n
        try:
            st = os.stat(full)
        except OSError:
            continue
        entries.append({"name": n, "path": relpath, "is_dir": os.path.isdir(full),
                        "size": st.st_size, "mtime": st.st_mtime})
    return entries


def js_escape(s):
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def build_page(share, base_url, rel=""):
    entries = list_entries(share, rel)
    rows = []
    for e in entries:
        name_html = html.escape(e["name"], quote=True)
        icon = file_icon(e["name"], e["is_dir"])
        size = "cartella" if e["is_dir"] else human_size(e["size"])
        date = time.strftime("%d/%m/%Y %H:%M", time.localtime(e["mtime"]))
        href = "/".join(quote(p) for p in e["path"].split("/"))
        if e["is_dir"]:
            btn = f'<a class="btn" href="/?p={href}">Apri</a>'
        else:
            btn = f'<a class="btn" href="/f/{href}">Scarica</a>'
        rows.append(FILE_ROW.replace("__ICON__", icon)
                    .replace("__NAME__", name_html)
                    .replace("__SIZE__", size)
                    .replace("__DATE__", date)
                    .replace("__BTN__", btn)
                    .replace("__JSNAME__", js_escape(e["path"])))
    if rows:
        listing = "<ul>" + "".join(rows) + "</ul>"
    else:
        listing = '<div class="empty">Nessun file qui. Trascina qualcosa qui sopra.</div>'
    if rel:
        parent = "/".join(rel.split("/")[:-1])
        up = f'/?p={"/".join(quote(p) for p in parent.split("/")) if parent else ""}'
        crumb = (f'<div class="crumb"><a href="/">&#8592; Cartella superiore</a> '
                 f'&middot; {html.escape(rel)}</div>')
    else:
        crumb = ""
    return (PAGE.replace("__QR__", qr_svg(base_url))
            .replace("__COUNT__", str(len(entries)))
            .replace("__URL__", html.escape(base_url))
            .replace("__CRUMB__", crumb)
            .replace("__LIST__", listing)
            .replace("__VER__", VERSION))


class PassafileHandler(BaseHTTPRequestHandler):
    server_version = "PassafileLocale/" + VERSION
    protocol_version = "HTTP/1.1"

    @property
    def share(self):
        return self.server.share_dir

    @property
    def base_url(self):
        return self.server.base_url

    def log_message(self, fmt, *args):
        self.server.log(fmt % args)

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _redirect(self, location):
        try:
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _safe(self, raw):
        rel = sanitize_name(raw)
        full = os.path.realpath(os.path.join(self.share, rel))
        root = os.path.realpath(self.share)
        if full != root and not full.startswith(root + os.sep):
            return None
        return rel, full

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self):
        split = urlsplit(self.path)
        path = unquote(split.path)
        if path == "/":
            query = parse_qs(split.query)
            rel = sanitize_name(query.get("p", [""])[0])
            resolved = self._safe(rel)
            if resolved is None:
                self._send(403, "accesso negato")
                return
            rel, full = resolved
            if rel and not os.path.isdir(full):
                self._send(404, "cartella non trovata")
                return
            if any(p.startswith(".") for p in rel.split("/") if p):
                self._send(404, "cartella non trovata")
                return
            self._send(200, build_page(self.share, self.base_url, rel),
                       "text/html; charset=utf-8")
        elif path == "/qr.svg":
            self._send(200, qr_svg(self.base_url), "image/svg+xml")
        elif path.startswith("/f/"):
            self._download(path[3:])
        elif path == "/api/files":
            query = parse_qs(split.query)
            rel = sanitize_name(query.get("p", [""])[0])
            self._send(200, json.dumps({"base_url": self.base_url,
                                        "path": rel,
                                        "files": list_entries(self.share, rel)}),
                       "application/json; charset=utf-8")
        elif path == "/ping":
            self._send(200, "ok")
        else:
            self._send(404, "Non trovato")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        split = urlsplit(self.path)
        if split.path == "/upload":
            self._upload()
        elif split.path == "/delete":
            self._delete()
        else:
            self._read_body()
            self._send(404, "Non trovato")

    def _upload(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send(400, json.dumps({"error": "multipart/form-data richiesto"}),
                       "application/json")
            return
        match = re.search(r'boundary="?([^";]+)"?', ctype)
        if not match:
            self._send(400, "boundary mancante")
            return
        body = self._read_body()
        files = parse_multipart(body, match.group(1).encode())
        saved, errors = [], []
        for raw_name, content in files:
            rel = sanitize_name(raw_name)
            if not rel:
                continue
            target_rel = unique_path(self.share, rel)
            target_full = os.path.join(self.share, target_rel)
            os.makedirs(os.path.dirname(target_full) or self.share, exist_ok=True)
            try:
                with open(target_full, "wb") as fh:
                    fh.write(content)
                saved.append(target_rel)
            except OSError:
                errors.append(rel)
        self._send(200, json.dumps({"uploaded": saved, "errors": errors}),
                   "application/json; charset=utf-8")

    def _delete(self):
        body = self._read_body()
        qs = parse_qs(body.decode("utf-8", "replace"))
        name = qs.get("name", [""])[0]
        resolved = self._safe(name)
        if not resolved:
            self._send(400, "percorso non valido")
            return
        rel, full = resolved
        if not rel or not os.path.isfile(full):
            self._send(404, "file non trovato")
            return
        try:
            os.remove(full)
            self._send(200, json.dumps({"deleted": rel}), "application/json")
        except OSError:
            self._send(500, "eliminazione fallita")

    def _download(self, raw):
        resolved = self._safe(raw)
        if not resolved:
            self._send(403, "accesso negato")
            return
        rel, full = resolved
        if not rel:
            self._redirect("/")
            return
        if any(p.startswith(".") for p in rel.split("/")):
            self._send(404, "file non trovato")
            return
        if os.path.isdir(full):
            self._redirect(f"/?p={'/'.join(quote(p) for p in rel.split('/'))}")
            return
        if not os.path.isfile(full):
            self._send(404, "file non trovato")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        size = os.path.getsize(full)
        fname = rel.split("/")[-1]
        ascii_name = fname.encode("ascii", "replace").decode().replace('"', "")
        disp = f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(fname)}'
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", disp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(full, "rb") as fh:
                while True:
                    chunk = fh.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, share_dir, base_url, verbose=True):
        super().__init__(addr, handler)
        self.share_dir = share_dir
        self.base_url = base_url
        self.verbose = verbose

    def log(self, message):
        if self.verbose:
            print(f"  {message}", flush=True)

    def handle_error(self, request, client_address):
        if self.verbose:
            import traceback
            traceback.print_exc()


def find_port(host, start, tries=20):
    import errno
    for port in range(start, start + tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.close()
            return port
        except OSError as e:
            if e.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            s.close()
    raise RuntimeError("nessuna porta libera trovata")


def main():
    default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "condivisi")
    parser = argparse.ArgumentParser(
        prog="pasafile.py",
        description="Passafile Locale: server one-click per condividere file "
                    "in rete locale con QR code.")
    parser.add_argument("-d", "--dir", default=default_dir,
                        help="cartella da condividere (default: ./condivisi)")
    parser.add_argument("-p", "--port", type=int, default=8000,
                        help="porta del server (default: 8000, cerca la successiva se occupata)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="indirizzo di ascolto (default: 0.0.0.0)")
    parser.add_argument("--no-qr", action="store_true", help="non stampare il QR code")
    parser.add_argument("--open", action="store_true", dest="open_browser",
                        help="apre il browser automaticamente")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="non stampare i log delle richieste")
    parser.add_argument("--version", action="version", version=f"Passafile Locale {VERSION}")
    args = parser.parse_args()

    share = os.path.realpath(os.path.abspath(args.dir))
    os.makedirs(share, exist_ok=True)

    ip = local_ip() if args.host in ("0.0.0.0", "::") else args.host
    port = find_port(args.host, args.port)
    base_url = f"http://{ip}:{port}"
    server = QuietServer((args.host, port), PassafileHandler, share, base_url,
                         not args.quiet)

    print()
    print("  \033[1mPassafile Locale\033[0m  v" + VERSION)
    print("  Cartella condivisa: " + share)
    print()
    print(f"  \033[1mApri nel browser:\033[0m  \033[92m{base_url}/\033[0m")
    print()
    if not args.no_qr:
        print("  Scansiona con il telefono per aprire il pannello:")
        print()
        print(qr_terminal(base_url + "/"))
        print()

    if args.open_browser:
        timer = threading.Timer(0.6, lambda: webbrowser.open(base_url + "/"))
        timer.daemon = True
        timer.start()

    print("  In ascolto... premi Ctrl+C per fermare il server.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server fermato. Arrivederci!")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

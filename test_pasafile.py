#!/usr/bin/env python3
"""Suite di verifica Passafile: QR (diff vs lib qrcode + decode OpenCV) + HTTP server.

Dipendenze dei SOLE test (Passafile stesso non ne ha):
    pip install qrcode opencv-python-headless numpy

Esecuzione (con il server non già avviato):
    python3 test_pasafile.py
"""
import http.client, os, shutil, socket, subprocess, sys, tempfile, time, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
SHARE = tempfile.mkdtemp(prefix="passafile-test-")
_sk = socket.socket(); _sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
_sk.bind(("", 0)); PORT = _sk.getsockname()[1]; _sk.close()

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1; print(f"  OK   {name}")
    else:
        fail += 1; print(f"  FAIL {name} {extra}")

def req(method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse(); data = r.read(); h = dict(r.getheaders()); st = r.status
    c.close()
    return st, data, h

def multipart(filename, content=b"hello world"):
    b = "testboundary123"
    part = (f"--{b}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{b}--\r\n".encode()
    return part, {"Content-Type": f"multipart/form-data; boundary={b}", "Content-Length": str(len(part))}

# ---------------- QR ----------------
print("-- QR --")
sys.path.insert(0, ROOT)
import qrcode
from qrcode.util import QRData, MODE_8BIT_BYTE
import numpy as np, cv2
from pasafile import matrix, qr_txt

def decode(m, b=6, sc=8):
    n = len(m) + 2*b
    img = np.ones((n, n), np.uint8) * 255
    for y, row in enumerate(m):
        for x, c in enumerate(row):
            if c: img[y+b][x+b] = 0
    img = cv2.resize(img, (n*sc, n*sc), interpolation=cv2.INTER_NEAREST)
    d, *_ = cv2.QRCodeDetector().detectAndDecode(img)
    return d

qr_tests = [
    "http://192.168.1.42:8000/",
    "http://10.0.0.7:8001/",
    "http://192.168.137.77:9000/pagina?ciao=mondo",
    "a",
    "http://172.16.0.5:8000/" + "x" * 70,
    "http://192.168.1.100:8000/f/relazione%20finale%20(2).pdf",
    "http://192.168.50.1:8000/" + "y" * 60,
    "http://192.168.0.100:9090/",
]
for text in qr_tests:
    mine = matrix(text)
    ver = (len(mine) - 17) // 4
    qr = qrcode.QRCode(version=ver, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=1, border=0, mask_pattern=0)
    qr.add_data(QRData(text.encode(), mode=MODE_8BIT_BYTE))
    qr.make(fit=False)
    ref = [[bool(c) for c in row] for row in qr.get_matrix()]
    diff_ok = ref == mine
    dk = decode(mine) == text or decode(mine, b=12) == text
    check(f"QR len={len(text)} v{ver} diff+decode", diff_ok and dk, f"diff={diff_ok} dec={dk}")

t = qr_txt("http://192.168.1.42:8000/")
lines = t.splitlines()
check("qr_txt righe coprono la matrice", len(lines) * 2 >= 33, len(lines))
check("qr_txt ansi presente", "\033[40m" in t and "▀" in t)

# URL oltre v6 -> ValueError gestito
try:
    matrix("http://1.2.3.4:8000/" + "z" * 120)
    check("URL lunghissimo -> ValueError", False)
except ValueError:
    check("URL lunghissimo -> ValueError", True)

# ---------------- HTTP ----------------
print("\n-- HTTP --")
shutil.rmtree(SHARE, ignore_errors=True)
os.makedirs(SHARE)
with open(os.path.join(SHARE, "iniziale.txt"), "wb") as f: f.write(b"primo file")
with open(os.path.join(SHARE, ".nascosto"), "wb") as f: f.write(b"segreto")
os.makedirs(os.path.join(SHARE, "cartella"), exist_ok=True)

print("avvio server...")
srv = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "pasafile.py"), "-d", SHARE, "-p", str(PORT)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    last = ""
    for i in range(60):
        try:
            st, data, _ = req("GET", "/ping")
            last = f"status={st} body={data[:20]}"
            if st == 200: break
            time.sleep(0.1)
        except OSError as e:
            last = f"{type(e).__name__}: {e}"; time.sleep(0.1)
    else:
        print("SERVER NON PARTITO:", last)
        out = srv.communicate(timeout=3)[0]
        print("log:", out.decode("utf-8", "replace")[-600:])
        sys.exit(1)

    st, data, h = req("GET", "/")
    page = data.decode("utf-8", "replace")
    check("GET / 200", st == 200, st)
    check("content-type html", "text/html" in h.get("Content-Type", ""), h.get("Content-Type"))
    check("titolo presente", "Passafile Locale" in page)
    check("input upload", 'id=fi' in page)
    check("banner offline", 'id=off' in page)
    check("heartbeat ping", "fetch('/ping')" in page)
    check("lista iniziale.txt", "iniziale.txt" in page)
    check("cartella non elencata", "cartella" not in page)
    check("nascosto non elencato", ".nascosto" not in page)
    check("conteggio (1)", "File condivisi (1)" in page)
    check("no subfolder api", req("GET", "/api/files")[0] == 404)
    check("no qr.svg", req("GET", "/qr.svg")[0] == 404)
    check("404 base", req("GET", "/nope")[0] == 404)

    body, hdrs = multipart("documento test.txt", b"contenuto prova")
    st, data, _ = req("POST", "/upload", body, hdrs)
    check("upload 200", st == 200, st)
    check("upload response = nome", data.decode() == "documento test.txt", data)
    check("file su disco", open(os.path.join(SHARE, "documento test.txt"), "rb").read() == b"contenuto prova")

    st, data, _ = req("POST", "/upload", *multipart("documento test.txt", b"secondo"))
    check("duplicato (1)", data.decode() == "documento test (1).txt", data)

    st, data, _ = req("POST", "/upload", *multipart("sotto/note.md", b"note"))
    check("subdir appiattita", data.decode() == "note.md", data)
    check("nota in root", os.path.isfile(os.path.join(SHARE, "note.md")))
    check("no dir sotto/", not os.path.exists(os.path.join(SHARE, "sotto")))

    st, data, _ = req("POST", "/upload", *multipart("../evil.txt", b"evil"))
    check("traversal upload neutralizzato", data.decode() == "evil.txt", data)
    check("evil non uscito", not os.path.exists(os.path.join(os.path.dirname(SHARE), "evil.txt")))

    st, _, _ = req("POST", "/upload", b"nope", {"Content-Type": "text/plain"})
    check("non multipart -> 400", st == 400, st)

    st, data, _ = req("GET", "/")
    check("listato aggiornato", "note.md" in data.decode())

    q = urllib.parse.quote("documento test.txt")
    st, data, h = req("GET", "/f/" + q)
    check("download 200", st == 200, st)
    check("download contenuto", data == b"contenuto prova")
    check("content-disposition", "attachment" in h.get("Content-Disposition", ""), h.get("Content-Disposition"))

    st, _, _ = req("GET", "/f/" + urllib.parse.quote(".nascosto"))
    check("hidden 404", st == 404, st)
    for bad in ("/f/../pasafile.py", "/f/..%2F..%2Fetc%2Fpasswd", "/f/%2e%2e%2fpasafile.py", "/f/cartella/../iniziale.txt"):
        st, _, _ = req("GET", bad)
        check(f"traversal {bad} 403/404", st in (403, 404), st)
    check("download mancante 404", req("GET", "/f/non-esiste.txt")[0] == 404)

    body, hdrs = multipart('a<b>&c".txt', b"x")
    st, data, _ = req("POST", "/upload", body, hdrs)
    saved = data.decode()
    st, data, _ = req("GET", "/")
    page = data.decode()
    check("nome HTML escaped", "&lt;b&gt;&amp;c" in page and 'a<b>&c"' not in page, saved)
    st, data, _ = req("GET", "/f/" + urllib.parse.quote(saved))
    check("download nome speciale", st == 200 and data == b"x", st)

    b = "testboundary123"
    part = (f"--{b}\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename*=UTF-8''%22quoted%22.txt\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + b"q" + f"\r\n--{b}--\r\n".encode()
    st, data, _ = req("POST", "/upload", part, {"Content-Type": f"multipart/form-data; boundary={b}"})
    check("filename* quote", data.decode() == '"quoted".txt', data)
    st, data, _ = req("GET", "/")
    check("quote escaped", "&quot;quoted&quot;.txt" in data.decode())
    st, data, _ = req("GET", "/f/%22quoted%22.txt")
    check("download filename* ", st == 200 and data == b"q", st)
    os.remove(os.path.join(SHARE, '"quoted".txt'))

    st, data, _ = req("POST", "/delete", "name=" + urllib.parse.quote("documento test.txt"))
    check("delete 200", st == 200 and data.decode() == "ok", (st, data))
    check("file rimosso", not os.path.exists(os.path.join(SHARE, "documento test.txt")))
    st, _, _ = req("POST", "/delete", "name=iniziale.txt")
    check("delete secondo", st == 200)
    st, _, _ = req("POST", "/delete", "name=" + urllib.parse.quote(".nascosto"))
    check("delete hidden ok", st == 200, st)
    st, _, _ = req("POST", "/delete", "name=non-c%27e.txt")
    check("delete mancante 404", st == 404, st)
    st, _, _ = req("POST", "/delete", "name=" + urllib.parse.quote("../pasafile.py"))
    check("delete traversal 404", st == 404, st)
    check("pasafile.py intatto", os.path.isfile(os.path.join(ROOT, "pasafile.py")))
    check("POST sconosciuto 404", req("POST", "/sconosciuto", b"")[0] == 404)

    big = os.urandom(2 * 1024 * 1024)
    body, hdrs = multipart("grande.bin", big)
    st, data, _ = req("POST", "/upload", body, hdrs)
    check("upload 2MB", st == 200 and data.decode() == "grande.bin", st)
    st, data, _ = req("GET", "/f/grande.bin")
    check("download 2MB", data == big)
    os.remove(os.path.join(SHARE, "grande.bin"))

    # HEAD su /
    st, data, _ = req("HEAD", "/")
    check("HEAD / 200 body vuoto", st == 200 and data == b"", st)

finally:
    srv.terminate()
    try: out, _ = srv.communicate(timeout=5)
    except subprocess.TimeoutExpired: srv.kill(); out, _ = srv.communicate()
    txt = out.decode("utf-8", "replace")
    check("server log senza traceback", "Traceback" not in txt, txt[-400:])
    check("QR stampato nel terminale", "▀" in txt)
    shutil.rmtree(SHARE, ignore_errors=True)

print(f"\n{'='*50}\nRISULTATO: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)

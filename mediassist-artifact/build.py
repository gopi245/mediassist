"""Builds the artifact version of MediAssist v2 from the real source in ../mediassist-pro.
The Python server runs in the browser with Pyodide; the screens are the same files."""
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "mediassist-pro")
PYO = os.environ.get("PYODIDE_DIR", r"C:\Users\AMMU\AppData\Local\Temp\claude\pyo")
OUT = os.path.join(HERE, "dist")

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(os.path.join(OUT, "js"))
os.makedirs(os.path.join(OUT, "py", "app"))
os.makedirs(os.path.join(OUT, "pyodide"))

# python server code (unchanged) + bridge
shutil.copy(os.path.join(SRC, "server.py"), os.path.join(OUT, "py", "server.py"))
for f in os.listdir(os.path.join(SRC, "app")):
    if f.endswith(".py"):
        shutil.copy(os.path.join(SRC, "app", f), os.path.join(OUT, "py", "app", f))
shutil.copy(os.path.join(HERE, "src", "bridge.py"), os.path.join(OUT, "py", "bridge.py"))
# bridge.js loads a fixed list of Python files: every server module must be on it
listed = set(re.findall(r'"(app/[a-z_0-9]+\.py)"', open(os.path.join(HERE, "src", "bridge.js"), encoding="utf-8").read()))
missing = sorted(f"app/{f}" for f in os.listdir(os.path.join(SRC, "app")) if f.endswith(".py") and f"app/{f}" not in listed)
assert not missing, f"Add these to the PY list in src/bridge.js: {missing}"

# screens (unchanged) + bridge + demo additions
for f in os.listdir(os.path.join(SRC, "app", "static", "js")):
    p = os.path.join(SRC, "app", "static", "js", f)
    if os.path.isdir(p):
        shutil.copytree(p, os.path.join(OUT, "js", f))
    elif f not in ("public.js", "upload.js"):  # public pages aren't part of the demo
        shutil.copy(p, os.path.join(OUT, "js", f))
shutil.copy(os.path.join(HERE, "src", "bridge.js"), os.path.join(OUT, "js", "bridge.js"))
shutil.copy(os.path.join(HERE, "src", "demo.js"), os.path.join(OUT, "js", "demo.js"))

css = open(os.path.join(SRC, "app", "static", "app.css"), encoding="utf-8").read()
css += """
/* ---------------- artifact demo ---------------- */
#bootScreen{position:fixed;inset:0;z-index:100;display:grid;place-items:center;background:var(--side);color:var(--side-ink);padding:24px max(16px,env(safe-area-inset-left,0px))}
.boot-card{max-width:420px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:10px}
.boot-card .mark{width:54px;height:54px;border-radius:14px;background:var(--side-accent);display:grid;place-items:center}
.boot-card .mark svg{width:30px;height:30px}.boot-card .mark svg path{fill:var(--side)}
.boot-card h2{font:800 28px var(--f-display);margin:0;color:#fff}.boot-card .muted{color:var(--side-muted)}
.boot-bar{width:260px;max-width:100%;height:6px;border-radius:4px;background:rgba(255,255,255,.15);overflow:hidden}
.boot-bar i{display:block;height:100%;width:5%;background:var(--side-accent);transition:width .4s}
.demo-logins{border-top:1px solid var(--line);margin-top:8px;padding-top:8px;display:flex;flex-direction:column;gap:6px}
.demo-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.demo-grid .btn{flex-direction:column;align-items:flex-start;gap:0;text-align:left;margin:0}
.demo-grid .btn span{font-size:11px;font-weight:400;color:var(--muted)}
.printprev{border:1px solid var(--line);border-radius:8px;padding:14px;background:#fff;color:#111;max-height:60vh;overflow:auto}
.printprev table{width:100%;border-collapse:collapse}.printprev td,.printprev th{border-bottom:1px solid #ccc;padding:4px;color:#111;background:none}
.printprev .hdr{display:flex;justify-content:space-between;gap:12px;border-bottom:2px solid #111;padding-bottom:6px;margin-bottom:8px}
"""
open(os.path.join(OUT, "app.css"), "w", encoding="utf-8").write(css)
shutil.copy(os.path.join(SRC, "app", "static", "icon.svg"), os.path.join(OUT, "icon.svg"))

# page: the real index.html, made relative, without the document wrapper (the viewer adds it)
html = open(os.path.join(SRC, "app", "static", "index.html"), encoding="utf-8").read()
body = html.split("<body>", 1)[1].split("</body>", 1)[0]
body = body.replace('<script src="/js/core.js"></script>', '<script src="js/bridge.js"></script>\n<script src="js/core.js"></script>')
body = body.replace('<script src="/js/boot.js"></script>', '<script src="js/demo.js"></script>\n<script src="js/boot.js"></script>')
body = re.sub(r'src="/js/', 'src="js/', body)
head = """<title>MediAssist Pro</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="app.css">
"""
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(head + body)

for f in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json"):
    shutil.copy(os.path.join(PYO, f), os.path.join(OUT, "pyodide", f))
# artifacts don't serve .zip: ship the two archives as base64 text; bridge.js restores the exact bytes
import base64
for f in ("python_stdlib.zip", "sqlite3-1.0.0.zip"):
    with open(os.path.join(PYO, f), "rb") as fh, open(os.path.join(OUT, "pyodide", f + ".txt"), "w") as out:
        out.write(base64.b64encode(fh.read()).decode())

total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(OUT) for f in fs)
print(f"built {OUT}: {sum(len(fs) for _, _, fs in os.walk(OUT))} files, {total / 1e6:.1f} MB")

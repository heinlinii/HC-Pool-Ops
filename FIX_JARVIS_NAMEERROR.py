from pathlib import Path
import shutil
import time
import sys
import py_compile

MARK_START = "# ============================================================\n# JARVIS BRAIN LAYER - HEINLIN FIELD OPS"
MARK_END = "# ============================================================\n# END JARVIS BRAIN LAYER\n# ============================================================"

MIN_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis Brain</title><link rel="stylesheet" href="/static/jarvis-brain.css"></head>
<body><main class="jarvis-wrap"><section class="hero"><h1>J.A.R.V.I.S. Brain</h1><p>{{ greeting }}</p></section>
<section class="panel"><h2>Command</h2><textarea id="jarvisText" placeholder="Jarvis, what am I forgetting?"></textarea><button id="sendJarvis">Send to Jarvis</button><div id="jarvisReply"></div></section>
<section class="grid">{% for a in briefing.actions %}<div class="card">{{ a }}</div>{% endfor %}</section>
<section class="panel"><h2>Quick Actions</h2>{% for a in quick_actions %}{% if a.href %}<a class="pill" href="{{ a.href }}">{{ a.label }}</a>{% else %}<button class="pill quick" data-command="{{ a.command }}">{{ a.label }}</button>{% endif %}{% endfor %}</section>
</main><script src="/static/jarvis-brain.js"></script></body></html>'''
MIN_CSS = r'''body{margin:0;background:#080b10;color:#f4ead7;font-family:Arial,sans-serif}.jarvis-wrap{max-width:1100px;margin:auto;padding:24px}.hero,.panel,.card{background:linear-gradient(135deg,#151922,#0d1117);border:1px solid #8a6a34;border-radius:18px;padding:20px;margin:14px 0;box-shadow:0 10px 30px #0008}h1{font-size:42px;margin:0 0 8px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}textarea{width:100%;min-height:110px;border-radius:12px;background:#05070a;color:#fff;border:1px solid #8a6a34;padding:12px;font-size:16px;box-sizing:border-box}button,.pill{display:inline-block;margin:6px 6px 0 0;padding:11px 15px;border-radius:999px;border:1px solid #b68b45;background:#15100a;color:#ffe5b5;text-decoration:none;cursor:pointer}#jarvisReply{margin-top:14px;padding:12px;border-left:4px solid #b68b45;background:#0005;border-radius:8px}'''
MIN_JS = r'''async function sendJarvis(text){const box=document.getElementById('jarvisReply');box.textContent='Jarvis is handling it...';try{const r=await fetch('/jarvis-brain/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});const d=await r.json();box.textContent=d.reply||JSON.stringify(d);}catch(e){box.textContent='Jarvis command failed: '+e;}}document.addEventListener('click',e=>{if(e.target.id==='sendJarvis'){sendJarvis(document.getElementById('jarvisText').value)}if(e.target.classList.contains('quick')){document.getElementById('jarvisText').value=e.target.dataset.command;sendJarvis(e.target.dataset.command)}});'''

def is_repo(path: Path) -> bool:
    return (path / "app" / "app.py").exists()

def find_repo() -> Path:
    cwd = Path.cwd().resolve()
    checks = [cwd] + list(cwd.parents)
    for c in checks:
        if is_repo(c):
            return c
    common = [
        Path(r"C:\dev\HC-Pool-Ops-2\HC-Pool-Ops-Jarvis-Built\HC-Pool-Ops"),
        Path(r"C:\dev\HC-Pool-Ops"),
        Path(r"C:\dev"),
    ]
    for c in common:
        if is_repo(c):
            return c
    dev = Path(r"C:\dev")
    if dev.exists():
        for app_py in dev.rglob("app.py"):
            if app_py.parent.name == "app" and (app_py.parent.parent / ".git").exists():
                return app_py.parent.parent
        for app_py in dev.rglob("app.py"):
            if app_py.parent.name == "app":
                return app_py.parent.parent
    raise SystemExit("Could not find your app folder. Run this from inside the HC-Pool-Ops folder that has app\\app.py.")

def strip_existing_block(text: str) -> str:
    start = text.find(MARK_START)
    end = text.find(MARK_END)
    if start != -1 and end != -1 and end > start:
        return text[:start].rstrip() + "\n\n" + text[end + len(MARK_END):].lstrip()
    return text

def remove_broken_imports(text: str) -> str:
    new_lines = []
    removed = []
    for line in text.splitlines():
        s = line.strip()
        if s in ("from app.routes import jarvis_brain", "import app.routes.jarvis_brain"):
            removed.append(line)
            continue
        if s.startswith("from app.routes import") and "jarvis_brain" in s:
            # Preserve other imports if any exist on the same line.
            prefix, names = line.split("import", 1)
            parts = [p.strip() for p in names.split(",")]
            parts = [p for p in parts if p != "jarvis_brain"]
            if parts:
                new_lines.append(prefix + "import " + ", ".join(parts))
            removed.append(line)
            continue
        new_lines.append(line)
    return "\n".join(new_lines) + "\n"

def main():
    repo = find_repo()
    app_py = repo / "app" / "app.py"
    route_file = repo / "app" / "routes" / "jarvis_brain.py"
    print(f"Using repo: {repo}")
    print(f"Using app.py: {app_py}")
    if not route_file.exists():
        raise SystemExit(f"Could not find {route_file}. This repair needs the Jarvis route file that caused the NameError.")
    route_text = route_file.read_text(encoding="utf-8")
    if "@app.get(\"/jarvis-brain" not in route_text and "@app.get('/jarvis-brain" not in route_text:
        print("WARNING: route file does not obviously contain /jarvis-brain, but I will still append it.")
    original = app_py.read_text(encoding="utf-8")
    backup = app_py.with_suffix(f".py.before_jarvis_nameerror_fix_{time.strftime('%Y%m%d_%H%M%S')}.bak")
    shutil.copy2(app_py, backup)
    print(f"Backup made: {backup}")
    fixed = remove_broken_imports(strip_existing_block(original)).rstrip() + "\n\n" + route_text.strip() + "\n"
    app_py.write_text(fixed, encoding="utf-8")

    # Make sure template/static exist, so the page can render even if prior ZIP copy failed.
    templates = repo / "app" / "templates"
    static = repo / "app" / "static"
    templates.mkdir(parents=True, exist_ok=True)
    static.mkdir(parents=True, exist_ok=True)
    html = templates / "jarvis_brain.html"
    css = static / "jarvis-brain.css"
    js = static / "jarvis-brain.js"
    if not html.exists():
        html.write_text(MIN_HTML, encoding="utf-8")
        print("Created minimal jarvis_brain.html")
    if not css.exists():
        css.write_text(MIN_CSS, encoding="utf-8")
        print("Created minimal jarvis-brain.css")
    if not js.exists():
        js.write_text(MIN_JS, encoding="utf-8")
        print("Created minimal jarvis-brain.js")

    print("Checking Python compile...")
    try:
        py_compile.compile(str(app_py), doraise=True)
    except Exception as e:
        print("COMPILE FAILED. Restoring backup.")
        shutil.copy2(backup, app_py)
        raise
    print("SUCCESS: Jarvis route is now inside app/app.py and the broken import is removed.")
    print("NEXT:")
    print("  python -m uvicorn app.app:app --reload")
    print("Then open:")
    print("  http://127.0.0.1:8000/jarvis-brain/install-check")
    print("  http://127.0.0.1:8000/jarvis-brain")

if __name__ == "__main__":
    main()

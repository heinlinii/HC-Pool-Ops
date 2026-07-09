from pathlib import Path
import os, sys, shutil, subprocess, time

START = "# ============================================================\n# JARVIS BRAIN LAYER - HEINLIN FIELD OPS"
END = "# END JARVIS BRAIN LAYER"

def here():
    return Path(__file__).resolve().parent

def is_repo(p: Path) -> bool:
    return (p / "app" / "app.py").exists()

def walk_for_repos(base: Path, max_depth=5):
    found=[]
    base=base.resolve()
    if not base.exists(): return found
    skip={".venv","venv","node_modules",".git","__pycache__","site-packages","AppData"}
    def rec(p, depth):
        if depth > max_depth: return
        if is_repo(p):
            found.append(p)
            return
        try:
            kids=list(p.iterdir())
        except Exception:
            return
        for k in kids:
            if k.is_dir() and k.name not in skip and not k.name.startswith("."):
                rec(k, depth+1)
    rec(base,0)
    return found

def find_repo():
    candidates=[]
    for p in [Path.cwd(), here(), *Path.cwd().parents, *here().parents]:
        if is_repo(p):
            candidates.append(p)
    for p in [Path("C:/dev"), Path.home()/"OneDrive"/"Desktop", Path.home()/"Desktop"]:
        candidates += walk_for_repos(p, max_depth=6)
    # unique
    uniq=[]
    seen=set()
    for c in candidates:
        s=str(c.resolve()).lower()
        if s not in seen:
            seen.add(s); uniq.append(c.resolve())
    if is_repo(Path.cwd()):
        return Path.cwd().resolve()
    if len(uniq)==1:
        return uniq[0]
    print("\nI found more than one HC-Pool-Ops-looking app folder.\n")
    for i,c in enumerate(uniq,1):
        print(f"{i}. {c}")
    if not uniq:
        print("\nI could not find app\\app.py automatically.")
        print("Move this fix folder into your real HC-Pool-Ops folder, then run it again.")
        sys.exit(1)
    choice=input("\nType the number for the app folder you are running in VS Code, then press Enter: ").strip()
    try:
        n=int(choice)
        return uniq[n-1]
    except Exception:
        print("Bad choice. Nothing changed.")
        sys.exit(1)

def remove_old_layer(text):
    s=text.find(START)
    if s == -1:
        return text
    e=text.find(END, s)
    if e == -1:
        # remove from start marker to end of file as broken partial install
        return text[:s].rstrip()+"\n"
    e = text.find("\n", e)
    if e == -1: e=len(text)
    return (text[:s] + text[e:]).rstrip()+"\n"

def main():
    pkg=here()
    repo=find_repo()
    app_py=repo/"app"/"app.py"
    print(f"\nUsing app folder:\n{repo}\n")
    original=app_py.read_text(encoding="utf-8", errors="replace")
    if "app = FastAPI" not in original and "FastAPI(" not in original:
        print("This does not look like the main FastAPI app.py. Stopping.")
        sys.exit(1)

    backup=app_py.with_name(f"app.py.backup_before_jarvis_{int(time.time())}")
    shutil.copy2(app_py, backup)
    print(f"Backup made:\n{backup}")

    layer=(pkg/"jarvis_brain_layer_fixed.py").read_text(encoding="utf-8")
    new=remove_old_layer(original)
    new = new.rstrip() + "\n\n" + layer.rstrip() + "\n"
    app_py.write_text(new, encoding="utf-8")
    print("Patched app\\app.py with Jarvis Brain routes.")

    tmpl_dir=repo/"app"/"templates"
    static_dir=repo/"app"/"static"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pkg/"jarvis_brain.html", tmpl_dir/"jarvis_brain.html")
    shutil.copy2(pkg/"jarvis-brain.css", static_dir/"jarvis-brain.css")
    shutil.copy2(pkg/"jarvis-brain.js", static_dir/"jarvis-brain.js")
    print("Copied template/static files.")

    print("\nChecking Python compile...")
    proc=subprocess.run([sys.executable, "-m", "py_compile", str(app_py)], cwd=str(repo), text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        shutil.copy2(backup, app_py)
        print("\nCompile failed. I restored your backup so the app is not broken.")
        sys.exit(proc.returncode)
    print("Compile OK.")

    print("\nNow run these commands in your VS Code terminal:")
    print(f'cd "{repo}"')
    print("python -m uvicorn app.app:app --reload")
    print("\nThen open:")
    print("http://127.0.0.1:8000/jarvis-brain/install-check")
    print("http://127.0.0.1:8000/jarvis-brain")
    print("\nIf install-check works but the page asks login, log in first, then open /jarvis-brain again.")

if __name__ == "__main__":
    main()

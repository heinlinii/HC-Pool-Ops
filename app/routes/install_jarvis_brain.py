#!/usr/bin/env python3
"""
Safe installer for the Heinlin Field Ops Jarvis Brain Layer.
Run from the root of your repo, usually: C:\dev\HC-Pool-Ops

What it does:
1. Backs up app/app.py.
2. Copies jarvis_brain.html, jarvis-brain.css, and jarvis-brain.js into app/templates and app/static.
3. Appends the Jarvis Brain route layer to app/app.py one time only.
4. Leaves your current database, logins, clients, jobs, photos, and role helpers alone.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

MARKER_START = "# ============================================================\n# JARVIS BRAIN LAYER - HEINLIN FIELD OPS"


def find_repo_root() -> Path:
    here = Path.cwd()
    candidates = [here, *here.parents]
    for c in candidates:
        if (c / "app" / "app.py").exists():
            return c
    raise SystemExit("Could not find app/app.py. Run this from the HC-Pool-Ops repo root.")


def copy_tree_files(src_root: Path, dst_root: Path) -> None:
    for path in src_root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src_root)
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"Wrote {dst}")


def main() -> None:
    package_root = Path(__file__).resolve().parent
    repo = find_repo_root()
    app_py = repo / "app" / "app.py"
    files_root = package_root / "files"
    append_file = package_root / "jarvis_brain_append.py"

    if not append_file.exists():
        raise SystemExit("Missing jarvis_brain_append.py next to installer.")
    if not files_root.exists():
        raise SystemExit("Missing files/ folder next to installer.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = app_py.with_suffix(f".py.bak_jarvis_brain_{stamp}")
    shutil.copy2(app_py, backup)
    print(f"Backup created: {backup}")

    copy_tree_files(files_root, repo)

    app_text = app_py.read_text(encoding="utf-8")
    append_text = append_file.read_text(encoding="utf-8")

    if MARKER_START in app_text:
        print("Jarvis Brain block is already installed in app/app.py. Leaving app.py alone.")
    else:
        if not app_text.endswith("\n"):
            app_text += "\n"
        app_py.write_text(app_text + "\n\n" + append_text + "\n", encoding="utf-8")
        print("Appended Jarvis Brain layer to app/app.py")

    print("\nInstalled. Run these from your repo root:")
    print("  python -m py_compile app/app.py")
    print("  uvicorn app.app:app --reload")
    print("Then open: http://127.0.0.1:8000/jarvis-brain")
    print("If local looks good, commit and push to Render.")


if __name__ == "__main__":
    main()

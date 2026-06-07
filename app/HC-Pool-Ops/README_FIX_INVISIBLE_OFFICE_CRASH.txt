This fixes the SyntaxError caused by the previous Invisible Office patch.
It restores a clean app.py from the core build and includes Invisible Office properly.

Install:
1. Extract ZIP
2. Copy contents into HC-Pool-Ops-FIXED-BY-JARVIS
3. Replace All
4. Run: .\INSTALL_FIX_INVISIBLE_OFFICE_CRASH.bat
5. Restart: uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload

POOL OPS PORTAL AUTH PATCH

Installs:
- Removes the old stuck left sidebar by disabling _sidebar.html and adding CSS overrides.
- Adds /employee-login and /employee-portal.
- Adds /portal-setup admin page.
- Adds employee card login setup forms.
- Keeps client portal login setup on client cards.
- Adds client card photo upload from phone photo library using a real file picker.

Install:
1. Extract this ZIP.
2. Copy everything into your PoolOps folder:
   C:\Users\Heinl\OneDrive\Desktop\HC-Pool-Ops-FIXED-BY-JARVIS
3. Choose Replace All.
4. Double-click APPLY_PORTAL_AUTH_PATCH.bat
5. Restart server:
   uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
6. Open:
   /portal-setup

Logins:
- Admin remains mike / mike or mike / 5500 depending your current DB.
- Employee login page is /employee-login.
- Client login page is /client-login.

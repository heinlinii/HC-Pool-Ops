HEINLIN FIELD OPS LIVE DATA IMPORT

This package contains your real local records exported from poolops2_local.db:
- 309 clients
- 285 properties
- 9 jobs
- 3 employees
- 2 invoices
- 5 photo logs

Install:
1. Copy the scripts folder into the GitHub repo:
   C:\dev\HC-Pool-Ops-2\HC-Pool-Ops-Jarvis-Built\HC-Pool-Ops

2. Commit and push:
   git add scripts/import_heinlin_live_data.py scripts/heinlin_live_data_export.json
   git commit -m "Add Heinlin live data import"
   git push origin main

3. After Render deploys, open Render Shell for the Hc-Pool-Ops service and run:
   python scripts/import_heinlin_live_data.py

4. Test live:
   https://ho-pools.com/invisible-office/search?q=larry
   https://ho-pools.com/properties

IMPORTANT:
- Do not paste your DATABASE_URL anywhere. Render Shell already has it as an environment variable.
- This imports operational data into live Postgres. It does not need the password pasted into ChatGPT.

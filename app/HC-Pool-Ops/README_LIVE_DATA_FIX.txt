HEINLIN FIELD OPS LIVE DATA FIX

This package fixes the real issue:
- Local app had SQLite data.
- Render live site uses Postgres and was empty.
- app/app.py now supports Postgres when DATABASE_URL is present.
- Migration scripts export local SQLite data and import it into Render Postgres.

INSTALL CODE PATCH:
1. Copy app/app.py into the GitHub repo folder, replacing the existing app/app.py.
2. Copy jarvis_live_migration folder too.
3. Commit and push to GitHub/Render.

EXPORT LOCAL DATA:
Run in your working local folder:
  .\EXPORT_LOCAL_DATA.bat
This creates heinlin_live_data_export.zip.

IMPORT LIVE DATA:
Best option: Render Shell. Upload/copy heinlin_live_data_export.zip into the repo folder, then run:
  python jarvis_live_migration/import_to_live_postgres.py heinlin_live_data_export.zip
Render Shell already has DATABASE_URL.

After import, restart Render and test:
- /properties
- /clients
- /invisible-office search: larry, bulkley

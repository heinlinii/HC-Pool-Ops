# Jarvis PoolOps Local Stabilization Package

Built for: `C:\dev\HC-Pool-Ops`

This package is built from `PoolOps_Organized_Imports.xlsx`.

## What is included

- `imports/clients_import.csv` — 309 app clients
- `imports/properties_import.csv` — 285 app properties
- `imports/employees_import.csv` — 3 employees
- `imports/jobs_import.csv` — 9 starting jobs
- `imports/invoices_import.csv` — 2 starting invoices
- `imports/photo_logs_import.csv` — 5 starting photo logs
- `imports/card_images.csv` — 10 available property/dashboard images
- `imports/review_needed.csv` — 10 address/property rows that need manual cleanup
- `scripts/import_poolops_data.py` — local import script
- `scripts/schema_poolops_foundation.sql` — safe PostgreSQL schema foundation
- `alembic/versions/20260526_001_poolops_foundation.py` — Alembic migration foundation
- `docs/POOL_OPS_NEXT_STEPS.md` — next development order

## Important

The `Contacts Master` sheet is intentionally NOT included in this app import package.

## Recommended order

1. Make sure local app runs first.
2. Back up the current database.
3. Copy this whole folder into the repo root:
   `C:\dev\HC-Pool-Ops\jarvis_import_package`
4. Run the schema/migration.
5. Run the import script.
6. Verify locally.
7. Do not touch Render until local login, dashboard, property cards, and schedule work.

## Quick local command

From the real repo:

```bat
cd C:\dev\HC-Pool-Ops
python jarvis_import_package\scripts\import_poolops_data.py --database-url %DATABASE_URL%
```

If your local `.env` has `DATABASE_URL`, this also works:

```bat
python jarvis_import_package\scripts\import_poolops_data.py
```

Login target remains:

```text
mike / mike
```

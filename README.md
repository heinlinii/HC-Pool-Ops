# PoolOps Pro

PoolOps Pro is a deploy-ready FastAPI app for a pool contractor business.

## What it includes
- Dashboard
- Clients
- Properties
- Employees
- Schedule
- Service stops
- Invoice-ready service stop detail page
- Client request intake form
- Database seeding
- PostgreSQL-ready configuration
- Render deployment config

## Local run
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:
- http://127.0.0.1:8000
- Seed sample data: http://127.0.0.1:8000/dev/seed

## Deploy on Render
1. Create a new Web Service on Render.
2. Upload this project to GitHub.
3. Connect the repo in Render.
4. Add environment variable:
   - `DATABASE_URL` = your Render PostgreSQL connection string
5. Deploy.

This repo includes `render.yaml` for easy setup.

## Notes
- By default it uses SQLite locally.
- In production, use PostgreSQL with `DATABASE_URL`.

HC Pool Ops fixed recovery package

What I changed:
1. app_fixed.py no longer crashes at startup when OPENAI_API_KEY is not loaded locally.
2. requirements.txt uses psycopg[binary] instead of psycopg2-binary so your local Python 3.14 install does not choke.
3. app/database.py converts postgresql:// to postgresql+psycopg:// for the psycopg v3 driver.

Local run commands from this folder:
    pip install -r requirements.txt
    python -m uvicorn app_fixed:app --reload --host 127.0.0.1 --port 8000

Then open:
    http://127.0.0.1:8000/login

Seed users route if needed:
    http://127.0.0.1:8000/admin/seed-users

Logins after seed:
    mike / 5500
    randy / 0318
    marty / 0712

HEINLIN FIELD OPS - CLEAN RENDER DEPLOY

Use this ZIP as a clean project root.

Render Web Service settings:
Root Directory: blank
Build Command: pip install -r requirements.txt
Start Command: gunicorn app.app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT

Environment variables required:
DATABASE_URL = full PostgreSQL URL for the active Render database
OPENAI_API_KEY = your OpenAI API key
SESSION_SECRET = any random long value

Default logins after first startup:
admin: mike / mike
crew: randy / randy
crew: marty / marty

The app now creates missing database tables/columns automatically at startup.

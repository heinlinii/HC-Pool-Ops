PoolOps Pro - Final Working Build

Render start command:
uvicorn app.app.app:app --host 0.0.0.0 --port $PORT

Build command:
pip install -r requirements.txt

Default logins:
admin / admin
mike / 1234
jake / 1234
smith / 1234

QuickBooks:
Set these Render environment variables when ready:
QUICKBOOKS_CLIENT_ID
QUICKBOOKS_CLIENT_SECRET
QUICKBOOKS_REDIRECT_URI
QUICKBOOKS_ENV=sandbox or production

Weather:
Weather alerts use Open-Meteo as a no-key forecast source. Default location is Evansville, IN.

web: uvicorn app.app:app --host 0.0.0.0 --port $PORT
web: gunicorn app.app:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
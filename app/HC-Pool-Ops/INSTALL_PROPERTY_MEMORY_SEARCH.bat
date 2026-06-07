@echo off
echo Installing property-centered Invisible Office memory search...
python jarvis_tools\install_property_memory_search.py
echo.
echo DONE. Restart PoolOps:
echo uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload
pause

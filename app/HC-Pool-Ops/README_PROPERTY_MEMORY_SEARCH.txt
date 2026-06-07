PROPERTY MEMORY SEARCH PATCH

This improves Invisible Office search so property cards become the center:
- Search result prioritizes Property Card
- Pulls related Jobs when it can
- Pulls related Photos when it can
- Pulls related Field Logs when it can
- Falls back to broad search across clients/properties/jobs/photos/field logs/crew/estimates/job costing/billing

Install:
1. Extract this ZIP.
2. Copy contents into HC-Pool-Ops-FIXED-BY-JARVIS.
3. Replace All.
4. Run:
   .\INSTALL_PROPERTY_MEMORY_SEARCH.bat
5. Restart:
   uvicorn app.app:app --host 0.0.0.0 --port 8000 --reload

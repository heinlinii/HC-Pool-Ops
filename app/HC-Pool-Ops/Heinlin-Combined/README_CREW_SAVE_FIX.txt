HEINLIN FIELD OPS - CREW SAVE FIX

Problem fixed:
- Crew page save can error on live Render/Postgres because employee.active may be a Boolean column while the old app submitted integer 1.
- Some deployments may also not have username/password columns yet.

What this package contains:
- app/app.py with a safer Crew save route
- app/models.py with username/password added to Employee model

Install:
1. Copy the app folder from this package into:
   C:\dev\HC-Pool-Ops-2\HC-Pool-Ops-Jarvis-Built\HC-Pool-Ops
2. Choose Replace All.
3. In VS Code terminal, run:
   cd "C:\dev\HC-Pool-Ops-2\HC-Pool-Ops-Jarvis-Built\HC-Pool-Ops"
   git add app/app.py app/models.py
   git commit -m "Fix crew save on Postgres"
   git push origin main
4. In Render, deploy latest commit.
5. Test Crew save again.

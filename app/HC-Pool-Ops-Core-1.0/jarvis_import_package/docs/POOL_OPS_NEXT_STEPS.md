# PoolOps / Heinlin Field Ops — Next Development Order

## Current locked facts

- Real repo folder: `C:\dev\HC-Pool-Ops`
- Recovery/reference folder: `HC-Pool-Ops-FIXED-BY-JARVIS`
- App domain: `hc-pools.com`
- Current local login target: `mike / mike`
- Contacts master lists stay out of app imports.

## Architecture rule

The app should be property-card-centered:

```text
Property Card
 ├── Client
 ├── Jobs
 ├── Schedule
 ├── Photos / geotagged media
 ├── Service history
 ├── Invoices
 ├── Crew notes
 └── AI assistant context
```

Do not let the app become a disconnected Clients / Jobs / Properties list.

## Priority 1 — Data import

Import order:

1. clients
2. properties
3. employees
4. jobs
5. invoices
6. photo logs
7. card images

Keep `review_needed.csv` separate until Mike checks those bad/partial addresses.

## Priority 2 — Dashboard cleanup

Remove these dashboard stat cards:

- Jobs
- Clients
- Properties

Replace with:

- Today’s Schedule
- Active Field Work
- Property Cards
- Month Calendar
- Recent Photos
- AI Assistant
- Weather / Route Map later

## Priority 3 — Property cards

Each property card should show:

- background pool image
- property name
- client name
- address / map button
- status
- latest job
- next scheduled date
- latest photo
- quick buttons:
  - Open Card
  - Add Job
  - Add Photo
  - Schedule
  - Invoice

## Priority 4 — Contractor calendar

Replace basic schedule with real month view:

- month grid
- day cells
- job pills inside days
- click day to add job
- click job to open property/job detail
- week/day views later

## Priority 5 — Migrations

Stop emergency DB patch routes.

Use one of these:

- Alembic if already configured
- schema SQL locally first if Alembic is not yet stable

Do not push to Render until local app works.

## Safety rule

Before Render:

```bat
cd C:\dev\HC-Pool-Ops
python -m compileall app
python -m uvicorn app.app:app --reload
```

Then manually verify:

- login works
- dashboard loads
- clients/properties pages load
- property cards load
- schedule page loads
- imports are visible

# Heinlin Field Ops Core 1.0 — Safe Install Instructions

This package was built from the uploaded `HC-Pool-Ops-current(2).zip` repo. It keeps the current FastAPI/Render/Postgres structure and adds Core 1.0 features without wiping live data.

## What changed

- Adds Cloudflare R2 photo upload support with local fallback for development.
- Adds `poolops2_service_requests` table for client portal service requests.
- Adds `/schedule/year` yearly operations board.
- Updates client portal with future schedule, photos, property info, and request-service form.
- Updates employee portal with My Info, jobs, calendar, weather, map, photos, field ops, and GPS clock in/out.
- Keeps admin-only delete controls.
- Keeps clients restricted to their own client/property/photo/job data.
- Keeps employees away from Invisible Office and delete controls.
- Applies Heinlin identity language.

## Before touching Render

1. Download a fresh backup/export from Render Postgres.
2. Confirm your GitHub repo is clean.
3. Make a new branch:

```bash
git checkout -b core-1.0
```

## Files to replace/add

Copy the files from this package into your repo. Important changed files:

```text
app/app.py
app/templates/base.html
app/templates/client_portal.html
app/templates/employee_portal.html
app/templates/schedule_year.html
app/static/style.css
requirements.txt
.env.example
```

## Render environment variables for permanent photo storage

In Render → your web service → Environment, add these after creating a Cloudflare R2 bucket:

```text
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_ACCESS_KEY_ID=your_r2_access_key
R2_SECRET_ACCESS_KEY=your_r2_secret_key
R2_BUCKET_NAME=your_bucket_name
R2_PUBLIC_URL=https://your-public-r2-domain-or-custom-domain
```

If `R2_PUBLIC_URL` is blank, uploads still store in R2, but browser viewing may need a public bucket/custom domain.

## Test locally

```bash
pip install -r requirements.txt
uvicorn app.app:app --reload
```

Open:

```text
http://127.0.0.1:8000/login
```

Check these pages:

```text
/dashboard
/schedule/year
/client-portal
/employee
/photos
/weather
/map
/invisible-office
```

## Deploy

```bash
git add .
git commit -m "Install Heinlin Field Ops Core 1.0"
git push origin core-1.0
```

Then open a GitHub pull request into `main`, or merge when ready. Render will redeploy from `main`.

## First live checks after deploy

1. Login as admin.
2. Open `/dashboard`.
3. Open `/schedule/year`.
4. Upload a test photo from phone using `/photos`.
5. Confirm the photo URL is R2, not `/static/uploads/...`.
6. Login as an employee and confirm no delete buttons/Invisibile Office access.
7. Login as a client and confirm only that client’s records show.
8. Submit a client service request.

## Rollback

If anything breaks, revert the commit in GitHub or Render rollback to previous deploy. This package does not intentionally delete live data.

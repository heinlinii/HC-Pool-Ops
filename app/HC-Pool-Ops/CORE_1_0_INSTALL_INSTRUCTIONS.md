# Heinlin Field Ops Core 1.0 Install Instructions

## Do not skip the backup
Before replacing files, create a Render Postgres backup/snapshot. This package changes app code and adds the service request table automatically at startup.

## Files changed
- app/app.py
- app/templates/base.html
- app/templates/client_portal.html
- app/templates/employee_portal.html
- app/templates/weather.html
- app/templates/schedule_year.html
- app/static/style.css
- requirements.txt
- .env.example

## Render Environment variables
Add these in Render > Web Service > Environment:

R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=heinlin-field-ops
R2_PUBLIC_URL=
TOMORROW_API_KEY=
DEFAULT_WEATHER_LAT=37.9716
DEFAULT_WEATHER_LON=-87.5711

## Cloudflare R2
Create an R2 bucket named heinlin-field-ops. Create an R2 API token with object read/write. Set a public domain or public development URL and use that as R2_PUBLIC_URL with no trailing slash.

## Tomorrow.io
Create an API key and put it in TOMORROW_API_KEY. The app calls Tomorrow.io from the backend at /api/weather so the key is not exposed in the browser.

## Test pages after deploy
/login
/dashboard
/weather
/schedule/year
/client-portal
/employee
/photos
/map

## GPS behavior
Employees update GPS at clock-in and every 5 minutes while clocked in with the employee portal page open. Admin can see clocked-in employees on /map.

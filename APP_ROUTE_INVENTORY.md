# Heinlin Field Ops Route Inventory

This file is a working map of the current FastAPI routes. It is meant to make future cleanup safer without changing behavior.

## Core

- `/`
- `/login`
- `/logout`
- `/jarvis`
- `/dashboard`
- `/admin/link-check`
- `/design-studio`

## AI / Jarvis

- `/ai-systems`
- `/assistant-interview-live`
- `/assistant-live/send`
- `/invisible-office`
- `/invisible-office/add`
- `/invisible-office/{item_id}/delete`
- `/invisible-office/note`
- `/invisible-office/search`

## Safe Aliases

- `/handle-it` -> `/organize-my-day`
- `/send-it` -> `/assistant-interview-live`
- `/sendit` -> `/assistant-interview-live`
- `/talk-to-jarvis` -> `/assistant-interview-live`
- `/talk-to-jarvis-live` -> `/assistant-interview-live`
- `/ai` -> `/assistant-interview-live`
- `/assistant-live` -> `/assistant-interview-live`
- `/crew-portal` -> `/employee`
- `/employees` -> `/crew`
- `/schedule/today` -> `/schedule/day`
- `/todays-schedule` -> `/schedule/day`
- `/calendar` -> `/schedule/year`
- `/daily-schedule` -> `/schedule/day`
- `/monthly-schedule` -> `/schedule/year`
- `/gps-day-log` -> `/gps/day`
- `/gps-stops` -> `/gps/stops`

## Clients / Properties / Jobs

- `/clients`
- `/clients/{client_id}`
- `/properties`
- `/properties/{property_id}`
- `/jobs`
- `/jobs/{job_id}`

## Schedule

- `/schedule`
- `/schedule/day`
- `/schedule/week`
- `/schedule/month`
- `/schedule/year`
- `/organize-my-day`
- `/crew/my-day`

## Field / Crew

- `/crew`
- `/employee`
- `/gps/ping`
- `/gps/day`
- `/gps/stops`
- `/field-logs`
- `/field-log`

## Operations

- `/photos`
- `/map`
- `/weather`
- `/freeze-watch`
- `/weather-watch`
- `/pool-monitoring`
- `/estimates`
- `/job-costing`
- `/quickbooks`
- `/contact-us`

## Cleanup Notes

- `/invisible-office` had duplicate GET definitions. The earlier duplicate was removed; the remaining route lives near the add/delete/search handlers.
- Relative redirects to `jarvis` were changed to absolute `/jarvis`.

# Legacy PoolOps nightly business export

Render job `crn-d8erlsmq1p3s73b3gc7g` follows `core-1.0` in this repository and runs `python scripts/nightly_backup.py` at `0 7 * * *` UTC. It is separate from Heinlin OS production.

The October 18, 2026 failure occurred before export: the configured PostgreSQL host `dpg-d8abgg19rddc73a02mp0-a` could not resolve, and the Render database lookup returned 404. Do not silently substitute another database. The surviving `pool-ops-db` instance `dpg-d7e4idv7f7vs73eccge0-a` contains historical business records; verify its relationship to the missing source and the legacy web service before rebinding this job.

## Deployment and configuration

Preserve the existing Render-managed environment. No connection string or storage credentials belong in Git. Required settings: `DATABASE_URL`, `R2_ENABLED=true`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`.

Confirm the approved legacy database binding using the Render dashboard. Set the connection using its existing secure database configuration. Do not redirect to Heinlin OS: it has a different schema. Keep the existing R2 bucket and `poolops-backups/` prefix. The existing storage identity must permit upload and object readback; a write-only key cannot pass verification. Do not broaden permissions without authorization.

The script uses one PostgreSQL repeatable-read, read-only transaction. It exports all public base tables except `app_users`, `users`, `poolops2_users`, and `quickbooks_tokens`. The original five top-level JSON sections remain available, and invoices are included. All exported tables appear under `tables`, with counts under `table_counts`. Required legacy tables must exist, so a wrong database cannot quietly produce an empty successful export. It never imports the web app or runs schema setup.

This is a business-record export, not a full disaster-recovery dump: schema DDL, roles, sequences, credentials, referenced media objects and files are not included. Preserve those separately before retiring any legacy database or backup.

## Verification

Run `python3 -m unittest discover -s tests -v` for the isolated regression tests. Tests cover disabled/missing storage, database selection validation, a read-only consistent snapshot, invoice inclusion, credential exclusion, upload failure, readback denial, corrupt stored bytes and safe failure reporting. These tests use mocks and do not replace a live run.

After deployment and verified configuration, manually trigger the existing Render cron. Success requires the script's `R2 backup verified` message and final JSON with `status: success`, nonzero bytes, SHA-256, source database and expected table counts. The script downloads the stored object and hashes its bytes before printing success. Upload or verification errors exit 1. No backups are deleted by this script.

Download the resulting object and validate its JSON and expected counts independently. Verify restoration in an isolated environment before treating it as recovery proof or recommending retirement. Do not run the existing merge script against production as a test: it writes records and its field-log table mapping needs separate review.

During the October 18 investigation, the surviving database had 309 `poolops2_clients`, 285 `poolops2_properties`, 9 `poolops2_jobs`, 3 `poolops2_employees`, 1 `field_logs` and 1,801 `poolops2_invoices`. These are diagnostic reference counts, not assertions that may replace a fresh source comparison.

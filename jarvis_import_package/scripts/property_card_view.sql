
-- Optional helper view for property-card dashboard.
-- Run only after foundation tables exist.

CREATE OR REPLACE VIEW property_card_view AS
SELECT
    p.id AS property_db_id,
    p.external_id AS property_id,
    p.property_name,
    COALESCE(p.client_name, c.client_name) AS client_name,
    p.full_address,
    p.google_maps_url,
    p.card_image,
    p.needs_review,
    latest_job.id AS latest_job_id,
    latest_job.job_type AS latest_job_type,
    latest_job.status AS latest_job_status,
    latest_job.scheduled_date AS latest_job_date,
    latest_photo.photo_url AS latest_photo_url,
    latest_photo.title AS latest_photo_title
FROM properties p
LEFT JOIN clients c ON c.id = p.client_id
LEFT JOIN LATERAL (
    SELECT j.*
    FROM jobs j
    WHERE j.property_id = p.id
    ORDER BY j.scheduled_date DESC NULLS LAST, j.id DESC
    LIMIT 1
) latest_job ON true
LEFT JOIN LATERAL (
    SELECT ph.*
    FROM photo_logs ph
    WHERE ph.property_id = p.id
    ORDER BY ph.photo_date DESC NULLS LAST, ph.id DESC
    LIMIT 1
) latest_photo ON true;

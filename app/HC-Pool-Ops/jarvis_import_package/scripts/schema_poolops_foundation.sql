
-- PoolOps / Heinlin Field Ops foundation schema
-- Safe design: property-card-centered architecture.
-- Run locally before importing data.

CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(32) UNIQUE,
    client_name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    source TEXT,
    notes TEXT,
    portal_username TEXT,
    portal_password TEXT,
    card_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS properties (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(32) UNIQUE,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    client_external_id VARCHAR(32),
    client_name TEXT,
    property_name TEXT NOT NULL,
    street TEXT,
    city TEXT,
    state TEXT,
    zip_code TEXT,
    full_address TEXT,
    google_maps_url TEXT,
    raw_address TEXT,
    card_image TEXT,
    needs_review BOOLEAN DEFAULT FALSE,
    source TEXT,
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(32) UNIQUE,
    name TEXT NOT NULL,
    phone TEXT,
    role TEXT,
    username TEXT UNIQUE,
    password TEXT,
    card_image TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(32) UNIQUE,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    client_external_id VARCHAR(32),
    client_name TEXT,
    property_name TEXT,
    address TEXT,
    job_type TEXT,
    status TEXT DEFAULT 'Requested',
    crew TEXT,
    scheduled_date DATE,
    raw_date TEXT,
    priority TEXT DEFAULT 'Normal',
    notes TEXT,
    card_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(32) UNIQUE,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    client_name TEXT,
    description TEXT,
    amount NUMERIC(12,2),
    status TEXT DEFAULT 'Draft',
    invoice_date DATE,
    raw_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS photo_logs (
    id SERIAL PRIMARY KEY,
    external_id VARCHAR(32) UNIQUE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    client_name TEXT,
    photo_type TEXT,
    title TEXT,
    photo_url TEXT,
    photo_date DATE,
    raw_date TEXT,
    notes TEXT,
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS property_card_images (
    id SERIAL PRIMARY KEY,
    filename TEXT UNIQUE,
    app_path TEXT,
    recommended_use TEXT,
    assigned_client TEXT,
    assigned_property TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_properties_client_id ON properties(client_id);
CREATE INDEX IF NOT EXISTS idx_jobs_property_id ON jobs(property_id);
CREATE INDEX IF NOT EXISTS idx_jobs_scheduled_date ON jobs(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_photo_logs_property_id ON photo_logs(property_id);

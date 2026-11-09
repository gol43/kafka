CREATE SCHEMA IF NOT EXISTS copilot_data_cleaner;

CREATE TABLE IF NOT EXISTS copilot_data_cleaner.cleaner_jobs (
    id VARCHAR(36) PRIMARY KEY,
    call_id VARCHAR(64) NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'waiting',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    last_error VARCHAR(1000) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_anonymization_status_next
    ON copilot_data_cleaner.cleaner_jobs (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS ix_anonymization_expires
    ON copilot_data_cleaner.cleaner_jobs (expires_at);

CREATE TABLE IF NOT EXISTS copilot_data_cleaner.callback_deliveries (
    id VARCHAR(36) PRIMARY KEY,
    call_id VARCHAR(64) NOT NULL,
    subscriber_name VARCHAR(100) NOT NULL,
    subscriber_url VARCHAR(1000) NOT NULL,
    body JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'waiting',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ,
    last_error VARCHAR(1000) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_delivery_status_next
    ON copilot_data_cleaner.callback_deliveries (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS ix_delivery_expires
    ON copilot_data_cleaner.callback_deliveries (expires_at);
CREATE INDEX IF NOT EXISTS ix_callback_deliveries_call_id
    ON copilot_data_cleaner.callback_deliveries (call_id);

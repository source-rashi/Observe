CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Signal samples table (hypertable)
CREATE TABLE IF NOT EXISTS signal_samples (
    time        TIMESTAMPTZ      NOT NULL,
    signal      TEXT             NOT NULL,
    endpoint    TEXT             NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (time, signal, endpoint)
);

SELECT create_hypertable('signal_samples', 'time', if_not_exists => TRUE);
SELECT add_retention_policy('signal_samples', INTERVAL '7 days', if_not_exists => TRUE);

-- Incidents table
CREATE TABLE IF NOT EXISTS incidents (
    id           TEXT        PRIMARY KEY,
    status       TEXT        NOT NULL,
    severity     TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    resolved_at  TIMESTAMPTZ NULL,
    last_seen_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents (status);

-- Anomalies table
CREATE TABLE IF NOT EXISTS anomalies (
    id             TEXT             PRIMARY KEY,
    incident_id    TEXT             REFERENCES incidents(id),
    signal         TEXT             NOT NULL,
    endpoint       TEXT             NOT NULL,
    severity       TEXT             NOT NULL,
    direction      TEXT             NOT NULL,
    unit           TEXT             NOT NULL,
    value          DOUBLE PRECISION NOT NULL,
    baseline_mean  DOUBLE PRECISION NOT NULL,
    baseline_std   DOUBLE PRECISION NOT NULL,
    z_score        DOUBLE PRECISION NOT NULL,
    status         TEXT             NOT NULL,
    started_at     TIMESTAMPTZ      NOT NULL,
    last_seen_at   TIMESTAMPTZ      NOT NULL,
    resolved_at    TIMESTAMPTZ      NULL,
    points         JSONB            NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anomalies_status           ON anomalies (status);
CREATE INDEX IF NOT EXISTS idx_anomalies_incident_id      ON anomalies (incident_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_signal_endpoint_started ON anomalies (signal, endpoint, started_at DESC);

-- ============================================================
-- SuryaGrid AI — Database Initialisation SQL
-- Runs once automatically when TimescaleDB container first starts
-- (mounted at /docker-entrypoint-initdb.d/init.sql)
-- ============================================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- --------------------------------------------------------
-- Table: meter_readings
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS meter_readings (
    time        TIMESTAMPTZ     NOT NULL,
    village_id  VARCHAR(100)    NOT NULL,
    solar_kw    DOUBLE PRECISION,
    load_kw     DOUBLE PRECISION,
    battery_pct DOUBLE PRECISION,
    voltage     DOUBLE PRECISION,
    PRIMARY KEY (time, village_id)
);

-- Convert to TimescaleDB hypertable (partitioned by time)
SELECT create_hypertable(
    'meter_readings', 'time',
    if_not_exists => TRUE
);

-- Index for fast per-village queries
CREATE INDEX IF NOT EXISTS idx_meter_village
    ON meter_readings (village_id, time DESC);

-- --------------------------------------------------------
-- Table: alerts
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL          PRIMARY KEY,
    time        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    village_id  VARCHAR(100)    NOT NULL,
    alert_type  VARCHAR(100)    NOT NULL,
    message     TEXT
);

-- Index for fast per-village alert queries
CREATE INDEX IF NOT EXISTS idx_alerts_village
    ON alerts (village_id, time DESC);

-- Index for fast time-ordered queries
CREATE INDEX IF NOT EXISTS idx_alerts_time
    ON alerts (time DESC);

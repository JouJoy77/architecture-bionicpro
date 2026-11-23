CREATE TABLE telemetry (
    event_id text PRIMARY KEY,
    device_id text NOT NULL,
    event_time timestamptz NOT NULL,
    response_ms double precision NOT NULL CHECK (response_ms BETWEEN 0 AND 10000),
    battery_pct double precision NOT NULL CHECK (battery_pct BETWEEN 0 AND 100),
    movement boolean NOT NULL
);
CREATE INDEX telemetry_event_time_idx ON telemetry(event_time);
CREATE ROLE telemetry_reader LOGIN PASSWORD 'demo_telemetry_reader';
GRANT CONNECT ON DATABASE telemetry TO telemetry_reader;
GRANT USAGE ON SCHEMA public TO telemetry_reader;
GRANT SELECT ON telemetry TO telemetry_reader;

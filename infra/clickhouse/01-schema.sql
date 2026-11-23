CREATE DATABASE IF NOT EXISTS bionicpro;

CREATE TABLE bionicpro.daily_reports
(
    region LowCardinality(String),
    row_kind Enum8('data' = 1, 'coverage' = 2),
    report_date Date,
    idp_issuer String,
    subject String,
    customer_id String,
    device_id String,
    model LowCardinality(String),
    events_count UInt64,
    movements_count UInt64,
    avg_response_ms Float64,
    max_response_ms Float64,
    avg_battery_pct Float64,
    prepared_at DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY report_date
ORDER BY (region, row_kind, idp_issuer, subject, report_date, device_id);

CREATE TABLE bionicpro.crm_template
(
    device_id String,
    customer_id String,
    idp_issuer String,
    subject String,
    model String,
    valid_from DateTime64(3, 'UTC'),
    valid_to DateTime64(3, 'UTC')
) ENGINE = MergeTree ORDER BY (device_id, valid_from);

CREATE TABLE bionicpro.telemetry_template
(
    event_id String,
    device_id String,
    event_time DateTime64(3, 'UTC'),
    response_ms Float64,
    battery_pct Float64,
    movement UInt8
) ENGINE = MergeTree ORDER BY (device_id, event_time, event_id);

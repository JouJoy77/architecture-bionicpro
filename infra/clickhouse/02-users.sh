#!/bin/bash
set -euo pipefail
# Пароли создает scripts/setup.sh: только hex, без интерпретируемых SQL-символов.
[[ "$CLICKHOUSE_ETL_PASSWORD" =~ ^[a-f0-9]{48}$ ]]
[[ "$CLICKHOUSE_REPORT_PASSWORD" =~ ^[a-f0-9]{48}$ ]]
clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --multiquery <<SQL
CREATE USER IF NOT EXISTS etl IDENTIFIED WITH sha256_password BY '$CLICKHOUSE_ETL_PASSWORD';
GRANT SELECT, INSERT, CREATE TABLE, DROP TABLE, TRUNCATE, ALTER TABLE ON bionicpro.* TO etl;
CREATE USER IF NOT EXISTS reports IDENTIFIED WITH sha256_password BY '$CLICKHOUSE_REPORT_PASSWORD';
GRANT SELECT ON bionicpro.daily_reports TO reports;
ALTER USER reports SETTINGS max_execution_time = 20, max_memory_usage = 268435456, readonly = 1;
SQL

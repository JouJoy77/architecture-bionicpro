"""Суточная загрузка. Все временные таблицы принадлежат одному запуску."""

import os
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone

import psycopg2

from common.clickhouse import connect


CRM_SQL = """
SELECT o.device_id, c.customer_id, c.idp_issuer, c.subject, o.model,
       o.valid_from, COALESCE(o.valid_to, '2299-12-31T00:00:00Z'::timestamptz)
FROM device_ownership o JOIN customers c USING (customer_id)
WHERE o.valid_from < %s AND (o.valid_to IS NULL OR o.valid_to > %s)
"""
TELEMETRY_SQL = """
SELECT event_id, device_id, event_time, response_ms, battery_pct, movement::integer
FROM telemetry WHERE event_time >= %s AND event_time < %s
"""


def extract(client, dsn: str, sql: str, params: tuple, table: str) -> int:
    """Серверный курсор ограничивает память независимо от размера исходных данных."""
    count = 0
    with closing(psycopg2.connect(dsn, connect_timeout=10)) as connection, connection:
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with connection.cursor(name="etl_extract") as cursor:
            cursor.itersize = 5000
            cursor.execute(sql, params)
            while batch := cursor.fetchmany(5000):
                client.insert(table, batch)
                count += len(batch)
    return count


def validate_interval(start: datetime, end: datetime):
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("ETL interval must have a timezone")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if start.time().isoformat() != "00:00:00" or end - start != timedelta(days=1):
        raise ValueError("ETL interval must be one complete UTC day")
    if end > datetime.now(timezone.utc):
        raise ValueError("Cannot publish an unfinished day")
    return start, end


def run_day(start: datetime, end: datetime):
    start, end = validate_interval(start, end)
    region = os.environ.get("REGION", "RU")
    client = connect()
    suffix = uuid.uuid4().hex
    crm, telemetry, candidate = [
        f"bionicpro.{kind}_{suffix}" for kind in ("crm", "telemetry", "candidate")
    ]
    tables = []
    try:
        for table, template in (
            (crm, "crm_template"),
            (telemetry, "telemetry_template"),
            (candidate, "daily_reports"),
        ):
            client.command(f"CREATE TABLE {table} AS bionicpro.{template}")
            tables.append(table)
        crm_count = extract(client, os.environ["CRM_DSN"], CRM_SQL, (end, start), crm)
        event_count = extract(
            client, os.environ["TELEMETRY_DSN"], TELEMETRY_SQL, (start, end), telemetry
        )

        # Каждое событие должно попасть ровно к одному владельцу.
        matched = client.query(f"""
            SELECT count(), uniqExact(t.event_id)
            FROM {telemetry} t INNER JOIN {crm} c ON t.device_id = c.device_id
            WHERE t.event_time >= c.valid_from AND t.event_time < c.valid_to
        """).first_row
        if matched != (event_count, event_count):
            raise ValueError(
                "Telemetry contains missing/ambiguous ownership or duplicate event IDs"
            )
        params = {"region": region, "day": start.date()}
        client.command(
            f"""
            INSERT INTO {candidate}
            SELECT {{region:String}}, 'data', {{day:Date}}, c.idp_issuer, c.subject,
                   c.customer_id, t.device_id, c.model, count(), sum(t.movement),
                   round(avg(t.response_ms), 2), max(t.response_ms), round(avg(t.battery_pct), 2), now()
            FROM {telemetry} t INNER JOIN {crm} c ON t.device_id = c.device_id
            WHERE t.event_time >= c.valid_from AND t.event_time < c.valid_to
            GROUP BY c.idp_issuer, c.subject, c.customer_id, t.device_id, c.model
        """,
            parameters=params,
        )
        aggregated = client.query(
            f"SELECT sum(events_count) FROM {candidate}"
        ).first_row[0]
        if aggregated != event_count:
            raise ValueError("Mart event count differs from source event count")

        # Маркер нужен и для полностью пустого дня. Он входит в ту же партицию.
        client.command(
            f"""
            INSERT INTO {candidate} VALUES
            ({{region:String}}, 'coverage', {{day:Date}}, '', '', '', '', '', 0, 0, 0, 0, 0, now())
        """,
            parameters=params,
        )
        client.command(
            f"""
            ALTER TABLE bionicpro.daily_reports
            REPLACE PARTITION {{day:Date}} FROM {candidate}
        """,
            parameters=params,
        )
        return {
            "date": start.date().isoformat(),
            "crm_records": crm_count,
            "events": event_count,
        }
    finally:
        try:
            for table in tables:
                client.command(f"DROP TABLE IF EXISTS {table}")
        finally:
            client.close()

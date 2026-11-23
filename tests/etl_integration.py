"""Запускать внутри airflow-scheduler на локальном стенде, не на рабочих данных."""

from datetime import datetime, timedelta, timezone

import psycopg2

from common.clickhouse import connect
from pipeline.etl import run_day, validate_interval


def snapshot(client, day):
    return client.query(
        """
        SELECT row_kind, idp_issuer, subject, device_id, events_count, movements_count,
               avg_response_ms, max_response_ms, avg_battery_pct
        FROM daily_reports WHERE report_date = {day:Date}
        ORDER BY row_kind, subject, device_id
    """,
        parameters={"day": day},
    ).result_rows


def main():
    # Отдельный исторический день исключает конфликт с плановым DAG.
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    client = connect()
    crm_dsn = "postgresql://crm_admin:demo_crm@crm-db/crm"
    telemetry_dsn = "postgresql://telemetry_admin:demo_telemetry@telemetry-db/telemetry"
    try:
        with psycopg2.connect(crm_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO device_ownership VALUES
                ('TEST-TRANSFER', 'customer-1', 'Test model', %s, %s),
                ('TEST-TRANSFER', 'customer-2', 'Test model', %s, %s)
            """,
                (start, start + timedelta(hours=12), start + timedelta(hours=12), end),
            )
        with psycopg2.connect(telemetry_dsn) as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO telemetry VALUES (%s,%s,%s,%s,%s,%s)",
                [
                    (
                        "test-before",
                        "TEST-TRANSFER",
                        start + timedelta(hours=11),
                        60,
                        80,
                        True,
                    ),
                    (
                        "test-after",
                        "TEST-TRANSFER",
                        start + timedelta(hours=12),
                        70,
                        70,
                        False,
                    ),
                ],
            )
        run_day(start, end)
        first = snapshot(client, start.date())
        assert len(first) == 3  # Два владельца и маркер готовности.
        assert {r[2] for r in first if r[0] == "data"} == {
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        }
        assert all(r[4] == 1 for r in first if r[0] == "data")
        run_day(start, end)
        assert snapshot(client, start.date()) == first
        print("PASS: ownership at event time and idempotent partition replacement")

        with psycopg2.connect(telemetry_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO telemetry VALUES ('test-unknown', 'UNKNOWN', %s, 50, 90, true)",
                (start,),
            )
        try:
            run_day(start, end)
        except ValueError:
            pass
        else:
            raise AssertionError("Unknown ownership was published")
        assert snapshot(client, start.date()) == first
        print("PASS: failed ETL preserves the previous complete partition")

        with psycopg2.connect(telemetry_dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM telemetry WHERE event_id = 'test-unknown'")
            cur.execute(
                "INSERT INTO telemetry VALUES ('test-late', 'TEST-TRANSFER', %s, 80, 60, true)",
                (start + timedelta(hours=13),),
            )
        run_day(start, end)
        after = snapshot(client, start.date())
        assert sum(r[4] for r in after if r[0] == "data") == 3
        print("PASS: rerun includes a late event without duplicates")

        run_day(start - timedelta(days=1), start)
        empty = snapshot(client, (start - timedelta(days=1)).date())
        assert len(empty) == 1 and empty[0][0] == "coverage"
        print("PASS: empty completed day has a coverage marker")

        try:
            validate_interval(
                datetime.now(timezone.utc),
                datetime.now(timezone.utc) + timedelta(days=1),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Unfinished day was accepted")
        print("PASS: unfinished interval is rejected")
    finally:
        with psycopg2.connect(telemetry_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM telemetry WHERE event_id IN ('test-before','test-after','test-late','test-unknown')"
            )
        with psycopg2.connect(crm_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM device_ownership WHERE device_id = 'TEST-TRANSFER'"
            )
        for day in (start.date(), (start - timedelta(days=1)).date()):
            client.command(
                "ALTER TABLE daily_reports DROP PARTITION {day:Date}",
                parameters={"day": day},
            )
        client.close()


if __name__ == "__main__":
    main()

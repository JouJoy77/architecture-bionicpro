"""Только вымышленные данные, семь последних завершенных суток UTC."""

import os
from datetime import datetime, timedelta, timezone

import psycopg2


def main():
    issuer = os.environ["OIDC_ISSUER"]
    start = datetime.fromisoformat(os.environ["ETL_START_DATE"]).replace(
        tzinfo=timezone.utc
    )
    with psycopg2.connect(os.environ["CRM_ADMIN_DSN"]) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO customers VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                [
                    (f"customer-{i}", issuer, f"00000000-0000-0000-0000-00000000000{i}")
                    for i in (1, 2, 3)
                ],
            )
            for device, owner, model in (
                ("BP-101", "customer-1", "Hand M1"),
                ("BP-102", "customer-1", "Hand M2"),
                ("BP-201", "customer-2", "Hand M1"),
            ):
                cursor.execute(
                    """
                    INSERT INTO device_ownership
                    SELECT %s, %s, %s, %s, NULL
                    WHERE NOT EXISTS (SELECT 1 FROM device_ownership WHERE device_id = %s)
                """,
                    (device, owner, model, start, device),
                )
    with psycopg2.connect(os.environ["TELEMETRY_ADMIN_DSN"]) as connection:
        with connection.cursor() as cursor:
            end = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day = start
            while day < end:
                for device in ("BP-101", "BP-102", "BP-201"):
                    cursor.executemany(
                        """
                        INSERT INTO telemetry VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING
                    """,
                        [
                            (
                                f"{device}-{day.date()}-{i}",
                                device,
                                day + timedelta(hours=i * 2),
                                55 + i * 2,
                                95 - i * 3,
                                i % 3 != 0,
                            )
                            for i in range(12)
                        ],
                    )
                day += timedelta(days=1)
    print("Демонстрационные данные подготовлены")


if __name__ == "__main__":
    main()

import csv
import io
import logging
import os
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from common.auth import require_report_role, verify_token
from common.clickhouse import connect


app = FastAPI(title="Сервис отчетов BionicPRO")
bearer = HTTPBearer(auto_error=False)
REGION = os.environ.get("REGION", "RU")
logger = logging.getLogger(__name__)
FIELDS = [
    "report_date",
    "device_id",
    "model",
    "events_count",
    "movements_count",
    "avg_response_ms",
    "max_response_ms",
    "avg_battery_pct",
]


@app.middleware("http")
async def no_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(
            401, "Сначала войдите в приложение", headers={"WWW-Authenticate": "Bearer"}
        )
    claims = verify_token(credentials.credentials)
    require_report_role(claims)
    return claims


def query(sql: str, parameters: dict):
    client = None
    try:
        client = connect()
        return list(client.query(sql, parameters=parameters).named_results())
    except Exception as exc:
        # Не записываем SQL с идентификаторами пациентов в логи.
        logger.error("ClickHouse query failed: %s", type(exc).__name__)
        raise HTTPException(503, "Витрина отчетов временно недоступна") from exc
    finally:
        if client:
            client.close()


def check_parameters(request: Request, allowed: set[str]):
    if set(request.query_params) - allowed:
        raise HTTPException(400, "Неподдерживаемый параметр запроса")
    if len(request.query_params.multi_items()) != len(request.query_params):
        raise HTTPException(400, "Параметры запроса не должны повторяться")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/reports/availability")
def availability(request: Request, claims: dict = Depends(identity)):
    check_parameters(request, set())
    rows = query(
        """
        SELECT report_date FROM daily_reports
        WHERE region = {region:String} AND row_kind = 'coverage'
        ORDER BY report_date DESC LIMIT 366
    """,
        {"region": REGION},
    )
    return {"timezone": "UTC", "available_dates": [r["report_date"] for r in rows]}


def requested_days(start: date, end: date):
    if end < start or (end - start).days >= 93:
        raise HTTPException(400, "Выберите период от 1 до 93 дней")
    return {start + timedelta(days=i) for i in range((end - start).days + 1)}


def csv_value(value):
    # Текст из CRM не должен становиться формулой при открытии CSV в Excel.
    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        return "'" + value
    return value


@app.get("/reports")
def report(
    request: Request,
    start_date: date = Query(),
    end_date: date = Query(),
    format: Literal["json", "csv"] = "json",
    claims: dict = Depends(identity),
):
    check_parameters(request, {"start_date", "end_date", "format"})
    days = requested_days(start_date, end_date)
    # Данные и маркеры готовности читаются одним запросом из одного снимка таблицы.
    rows = query(
        """
        SELECT row_kind, report_date, device_id, model, events_count, movements_count,
               avg_response_ms, max_response_ms, avg_battery_pct
        FROM daily_reports
        WHERE region = {region:String}
          AND report_date BETWEEN {start:Date} AND {end:Date}
          AND (row_kind = 'coverage' OR
               (row_kind = 'data' AND idp_issuer = {issuer:String} AND subject = {subject:String}))
        ORDER BY report_date, device_id
        LIMIT 10001
    """,
        {
            "region": REGION,
            "start": start_date,
            "end": end_date,
            "issuer": claims["iss"],
            "subject": claims["sub"],
        },
    )
    if len(rows) > 10000:
        raise HTTPException(413, "Отчет слишком большой. Уменьшите период")
    complete = {r["report_date"] for r in rows if r["row_kind"] == "coverage"}
    missing = days - complete
    if missing:
        raise HTTPException(
            409,
            {
                "code": "period_not_ready",
                "message": "За часть периода данные еще не подготовлены",
                "missing_dates": [d.isoformat() for d in sorted(missing)],
            },
        )
    data = [
        {key: row[key] for key in FIELDS} for row in rows if row["row_kind"] == "data"
    ]
    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(FIELDS)
        writer.writerows([csv_value(row[key]) for key in FIELDS] for row in data)
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="bionicpro_{start_date}_{end_date}.csv"',
            },
        )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "UTC",
        "rows": data,
    }

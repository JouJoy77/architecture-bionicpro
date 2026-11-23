from datetime import date

import pytest
from fastapi.testclient import TestClient

from reports_service import main


@pytest.fixture
def client():
    main.app.dependency_overrides[main.identity] = lambda: {
        "iss": "issuer-ru",
        "sub": "patient-1",
    }
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


def row(day, kind="coverage"):
    return {
        "row_kind": kind,
        "report_date": date.fromisoformat(day),
        "device_id": "BP-101",
        "model": "Hand M1",
        "events_count": 12,
        "movements_count": 8,
        "avg_response_ms": 66.0,
        "max_response_ms": 77.0,
        "avg_battery_pct": 78.5,
    }


def test_anonymous_denied():
    with TestClient(main.app) as client:
        assert (
            client.get("/reports?start_date=2026-11-01&end_date=2026-11-01").status_code
            == 401
        )
        assert client.get("/reports/availability").status_code == 401


def test_identity_is_bound_to_verified_token(client, monkeypatch):
    def read(sql, parameters):
        assert "subject = {subject:String}" in sql
        assert "idp_issuer = {issuer:String}" in sql
        assert parameters["subject"] == "patient-1"
        assert parameters["issuer"] == "issuer-ru"
        return [row("2026-11-01"), row("2026-11-01", "data")]

    monkeypatch.setattr(main, "query", read)
    response = client.get("/reports?start_date=2026-11-01&end_date=2026-11-01")
    assert response.status_code == 200
    assert response.json()["rows"][0]["device_id"] == "BP-101"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "extra",
    [
        "user_id=patient-2",
        "subject=patient-2",
        "device_id=BP-201",
        "start_date=2026-11-02",
    ],
)
def test_cannot_select_someone_else(client, extra):
    response = client.get(f"/reports?start_date=2026-11-01&end_date=2026-11-01&{extra}")
    assert response.status_code == 400


def test_gap_in_middle_is_not_treated_as_ready(client, monkeypatch):
    monkeypatch.setattr(
        main, "query", lambda *args: [row("2026-11-01"), row("2026-11-03")]
    )
    response = client.get("/reports?start_date=2026-11-01&end_date=2026-11-03")
    assert response.status_code == 409
    assert response.json()["detail"]["missing_dates"] == ["2026-11-02"]


def test_complete_empty_day(client, monkeypatch):
    monkeypatch.setattr(main, "query", lambda *args: [row("2026-11-01")])
    response = client.get("/reports?start_date=2026-11-01&end_date=2026-11-01")
    assert response.status_code == 200
    assert response.json()["rows"] == []


def test_no_coverage_means_not_ready(client, monkeypatch):
    monkeypatch.setattr(main, "query", lambda *args: [])
    response = client.get("/reports?start_date=2026-11-01&end_date=2026-11-01")
    assert response.status_code == 409


def test_csv_download_and_formula_escaping(client, monkeypatch):
    data = row("2026-11-01", "data")
    data["model"] = "=1+1"
    monkeypatch.setattr(main, "query", lambda *args: [row("2026-11-01"), data])
    response = client.get(
        "/reports?start_date=2026-11-01&end_date=2026-11-01&format=csv"
    )
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "'=1+1" in response.text
    assert response.text.startswith("\ufeffreport_date,")


@pytest.mark.parametrize(
    "start,end,code",
    [
        ("2026-11-02", "2026-11-01", 400),
        ("2026-01-01", "2026-11-01", 400),
        ("not-a-date", "2026-11-01", 422),
    ],
)
def test_invalid_range(client, start, end, code):
    assert client.get(f"/reports?start_date={start}&end_date={end}").status_code == code

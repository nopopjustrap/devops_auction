import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import services
from app.db import connect
from app.main import create_app
from app.schemas import SaleCreate
from tests.test_api import create_auction, create_buyer, create_seller


def prepare_sale(client, rate=500):
    seller, buyer = create_seller(client), create_buyer(client)
    start = datetime.now(UTC)
    auction = client.post(
        "/api/v1/auctions",
        json={
            "title": "Commission auction",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "commission_bps": rate,
        },
    ).json()
    lot = client.post(
        f"/api/v1/auctions/{auction['id']}/lots",
        json={
            "seller_id": seller["id"],
            "title": "Commission lot",
            "starting_price": "100.00",
        },
    ).json()
    assert client.post(f"/api/v1/auctions/{auction['id']}/open").status_code == 200
    return auction, lot, buyer


def test_commission_sale_report_and_snapshot(client):
    auction, lot, buyer = prepare_sale(client, 500)
    sold = client.post(
        "/api/v1/sales",
        json={
            "lot_id": lot["id"],
            "buyer_id": buyer["id"],
            "final_price": "150.25",
        },
    )
    assert sold.status_code == 201
    assert Decimal(sold.json()["commission"]) == Decimal("7.51")
    assert Decimal(sold.json()["seller_proceeds"]) == Decimal("142.74")
    with closing(connect(client.app.state.database_path)) as c:
        c.execute(
            "UPDATE auctions SET commission_bps=1000 WHERE id=?", (auction["id"],)
        )
        c.commit()
    for suffix in ["", f"?auction_id={auction['id']}"]:
        report = client.get("/api/v1/reports/revenue" + suffix).json()
        assert report["sales_count"] == 1
        assert Decimal(report["gross_revenue"]) == Decimal("150.25")
        assert Decimal(report["commission_revenue"]) == Decimal("7.51")
        assert Decimal(report["seller_proceeds"]) == Decimal("142.74")


@pytest.mark.parametrize("rate,fee,net", [(0, "0", "100"), (10000, "100", "0")])
def test_sale_at_starting_price_and_rate_boundaries(client, rate, fee, net):
    _, lot, buyer = prepare_sale(client, rate)
    response = client.post(
        "/api/v1/sales",
        json={
            "lot_id": lot["id"],
            "buyer_id": buyer["id"],
            "final_price": "100.00",
        },
    )
    assert response.status_code == 201
    assert Decimal(response.json()["commission"]) == Decimal(fee)
    assert Decimal(response.json()["seller_proceeds"]) == Decimal(net)


@pytest.mark.parametrize("rate", [-1, 10001, 0.1, "500"])
def test_invalid_commission_rate(client, rate):
    start = datetime.now(UTC)
    response = client.post(
        "/api/v1/auctions",
        json={
            "title": "Bad rate",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "commission_bps": rate,
        },
    )
    assert response.status_code == 422


def test_lost_database_is_not_ready(raw_client):
    path = Path(raw_client.app.state.database_path)
    path.unlink()
    assert raw_client.get("/health").status_code == 200
    assert raw_client.get("/ready").status_code == 503
    assert not path.exists()


def test_missing_table_is_not_ready(raw_client):
    with closing(connect(raw_client.app.state.database_path)) as c:
        c.execute("DROP TABLE sales")
        c.commit()
    assert raw_client.get("/ready").status_code == 503


def test_read_participants_auction_and_empty_report(client):
    seller, buyer, auction = (
        create_seller(client),
        create_buyer(client),
        create_auction(client),
    )
    assert (
        client.get(f"/api/v1/sellers/{seller['id']}").json()["name"] == seller["name"]
    )
    assert client.get(f"/api/v1/buyers/{buyer['id']}").json()["name"] == buyer["name"]
    assert client.get(f"/api/v1/auctions/{auction['id']}").json()["status"] == "DRAFT"
    report = client.get("/api/v1/reports/revenue").json()
    assert report["sales_count"] == 0
    assert Decimal(report["commission_revenue"]) == 0
    assert client.get("/api/v1/reports/revenue?auction_id=999").status_code == 404


def test_business_constraints_and_rollback(client):
    auction, lot, buyer = prepare_sale(client)
    assert client.post(f"/api/v1/auctions/{auction['id']}/open").status_code == 409
    with closing(connect(client.app.state.database_path)) as c:
        c.execute("UPDATE buyers SET is_active=0")
        c.commit()
    request = {"lot_id": lot["id"], "buyer_id": buyer["id"], "final_price": "150.00"}
    assert (
        client.post("/api/v1/sales", json=request).json()["error"]["code"]
        == "BUYER_INACTIVE"
    )
    with closing(connect(client.app.state.database_path)) as c:
        c.execute("UPDATE buyers SET is_active=1")
        c.execute("UPDATE lots SET status='UNSOLD'")
        c.commit()
    assert (
        client.post("/api/v1/sales", json=request).json()["error"]["code"]
        == "LOT_NOT_AVAILABLE"
    )
    with closing(connect(client.app.state.database_path)) as c:
        assert c.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
    client.post(f"/api/v1/auctions/{auction['id']}/close")
    assert client.post(f"/api/v1/auctions/{auction['id']}/close").status_code == 409


def test_inactive_seller_and_missing_participant(client):
    seller, auction = create_seller(client), create_auction(client)
    with closing(connect(client.app.state.database_path)) as c:
        c.execute("UPDATE sellers SET is_active=0")
        c.commit()
    result = client.post(
        f"/api/v1/auctions/{auction['id']}/lots",
        json={
            "seller_id": seller["id"],
            "title": "Test lot",
            "starting_price": "10",
        },
    )
    assert result.json()["error"]["code"] == "SELLER_INACTIVE"
    assert client.get("/api/v1/buyers/999").status_code == 404


def test_two_concurrent_sales_have_one_winner(client):
    _, lot, buyer = prepare_sale(client)
    data = SaleCreate(lot_id=lot["id"], buyer_id=buyer["id"], final_price="150.00")

    def sell():
        with closing(connect(client.app.state.database_path)) as c:
            try:
                services.create_sale(c, data)
                c.commit()
                return "sold"
            except services.DomainError as error:
                c.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sell(), range(2)))
    assert sorted(results) == ["LOT_ALREADY_SOLD", "sold"]
    with closing(connect(client.app.state.database_path)) as c:
        assert c.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 1
        assert c.execute("SELECT commission_kopecks FROM sales").fetchone()[0] == 750


def test_expired_inactive_and_invalid_sessions(client):
    with closing(connect(client.app.state.database_path)) as c:
        c.execute("UPDATE users SET is_active=0")
        c.commit()
    assert client.get("/api/v1/auth/me").status_code == 403
    with closing(connect(client.app.state.database_path)) as c:
        c.execute("UPDATE users SET is_active=1")
        c.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        c.commit()
    assert client.get("/api/v1/auth/me").json()["error"]["code"] == "SESSION_EXPIRED"
    client.cookies.clear()
    client.cookies.set("auction_session", "unknown")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_preserves_password_spaces_and_redacts_validation(raw_client):
    credentials = {"username": "operator", "password": " abcdefgh "}
    assert raw_client.post("/api/v1/auth/register", json=credentials).status_code == 201
    assert (
        raw_client.post(
            "/api/v1/auth/login", json={**credentials, "password": "abcdefgh"}
        ).status_code
        == 401
    )
    assert raw_client.post("/api/v1/auth/login", json=credentials).status_code == 200
    response = raw_client.post(
        "/api/v1/auth/login", json={"username": "operator", "password": "secret"}
    )
    assert response.status_code == 422
    assert "secret" not in response.text


@pytest.mark.parametrize(
    "name,value",
    [
        ("SESSION_TTL_HOURS", "0"),
        ("SESSION_TTL_HOURS", "bad"),
        ("COOKIE_SECURE", "bad"),
    ],
)
def test_invalid_environment_fails_startup(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        create_app(str(tmp_path / "test.db"))


def test_secure_cookie_and_explicit_test_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    with TestClient(
        create_app(str(tmp_path / "secure.db")), base_url="https://testserver"
    ) as c:
        credentials = {"username": "operator", "password": "student123"}
        c.post("/api/v1/auth/register", json=credentials)
        response = c.post("/api/v1/auth/login", json=credentials)
        assert "; secure" in response.headers["set-cookie"].lower()
        assert c.get("/api/v1/auth/me").status_code == 200


def test_existing_database_is_not_migrated_implicitly(tmp_path):
    path = tmp_path / "old.db"
    path.touch()
    with pytest.raises(sqlite3.Error), TestClient(create_app(str(path))):
        pass

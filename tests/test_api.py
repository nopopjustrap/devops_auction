from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient


def create_seller(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/sellers",
        json={"name": "Анна", "email": "seller@example.com", "phone": "+79990000001"},
    )
    assert response.status_code == 201
    return response.json()


def create_buyer(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/buyers",
        json={"name": "Борис", "email": "buyer@example.com"},
    )
    assert response.status_code == 201
    return response.json()


def create_auction(client: TestClient) -> dict:
    start = datetime.now(UTC) + timedelta(hours=1)
    response = client.post(
        "/api/v1/auctions",
        json={
            "title": "Аукцион картин",
            "description": "Демонстрация ЛР1",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=2)).isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


def test_complete_sale_scenario(client: TestClient) -> None:
    seller = create_seller(client)
    buyer = create_buyer(client)
    auction = create_auction(client)

    empty_open = client.post(f"/api/v1/auctions/{auction['id']}/open")
    assert empty_open.status_code == 409
    assert empty_open.json()["error"]["code"] == "AUCTION_HAS_NO_LOTS"

    lot_response = client.post(
        f"/api/v1/auctions/{auction['id']}/lots",
        json={
            "seller_id": seller["id"],
            "title": "Картина",
            "starting_price": "100.00",
        },
    )
    assert lot_response.status_code == 201
    lot = lot_response.json()

    early_sale = client.post(
        "/api/v1/sales",
        json={"lot_id": lot["id"], "buyer_id": buyer["id"], "final_price": "150.00"},
    )
    assert early_sale.status_code == 409
    assert early_sale.json()["error"]["code"] == "AUCTION_NOT_OPEN"

    opened = client.post(f"/api/v1/auctions/{auction['id']}/open")
    assert opened.status_code == 200
    assert opened.json()["status"] == "OPEN"

    late_lot = client.post(
        f"/api/v1/auctions/{auction['id']}/lots",
        json={
            "seller_id": seller["id"],
            "title": "Поздний лот",
            "starting_price": "10.00",
        },
    )
    assert late_lot.status_code == 409
    assert late_lot.json()["error"]["code"] == "AUCTION_NOT_EDITABLE"

    cheap_sale = client.post(
        "/api/v1/sales",
        json={"lot_id": lot["id"], "buyer_id": buyer["id"], "final_price": "99.99"},
    )
    assert cheap_sale.status_code == 409
    assert cheap_sale.json()["error"]["code"] == "PRICE_BELOW_STARTING_PRICE"

    sale = client.post(
        "/api/v1/sales",
        json={"lot_id": lot["id"], "buyer_id": buyer["id"], "final_price": "150.00"},
    )
    assert sale.status_code == 201
    assert Decimal(sale.json()["final_price"]) == Decimal("150.00")

    duplicate = client.post(
        "/api/v1/sales",
        json={"lot_id": lot["id"], "buyer_id": buyer["id"], "final_price": "170.00"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "LOT_ALREADY_SOLD"

    report = client.get(f"/api/v1/reports/revenue?auction_id={auction['id']}")
    assert report.status_code == 200
    assert report.json()["sales_count"] == 1
    assert Decimal(report.json()["gross_revenue"]) == Decimal("150.00")

    closed = client.post(f"/api/v1/auctions/{auction['id']}/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"


def test_validation_conflicts_and_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}

    create_seller(client)
    duplicate = client.post(
        "/api/v1/sellers",
        json={"name": "Другой", "email": "seller@example.com"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"

    invalid = client.post(
        "/api/v1/auctions",
        json={
            "title": "Ошибка дат",
            "starts_at": "2026-09-05T12:00:00+00:00",
            "ends_at": "2026-09-05T11:00:00+00:00",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_timezone = client.post(
        "/api/v1/auctions",
        json={
            "title": "Нет часового пояса",
            "starts_at": "2026-09-05T12:00:00",
            "ends_at": "2026-09-05T13:00:00",
        },
    )
    assert missing_timezone.status_code == 422

    unknown = client.get("/api/v1/lots/999")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "LOT_NOT_FOUND"


def test_close_marks_unsold_lot(client: TestClient) -> None:
    seller = create_seller(client)
    auction = create_auction(client)
    lot = client.post(
        f"/api/v1/auctions/{auction['id']}/lots",
        json={"seller_id": seller["id"], "title": "Ваза", "starting_price": "500.00"},
    ).json()

    client.post(f"/api/v1/auctions/{auction['id']}/open")
    client.post(f"/api/v1/auctions/{auction['id']}/close")

    assert client.get(f"/api/v1/lots/{lot['id']}").json()["status"] == "UNSOLD"

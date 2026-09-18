import sqlite3

from fastapi.testclient import TestClient


def test_web_interface_and_public_service_routes(raw_client: TestClient) -> None:
    page = raw_client.get("/")
    assert page.status_code == 200
    assert "Auction Service" in page.text
    assert 'id="auth-form"' in page.text

    styles = raw_client.get("/static/styles.css")
    script = raw_client.get("/static/app.js")
    assert styles.status_code == 200
    assert script.status_code == 200

    assert raw_client.get("/health").json() == {"status": "ok"}
    assert raw_client.get("/ready").json() == {"status": "ready"}
    assert raw_client.get("/docs").status_code == 200


def test_business_api_requires_authentication(raw_client: TestClient) -> None:
    response = raw_client.post(
        "/api/v1/sellers",
        json={"name": "Анна", "email": "seller@example.com"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_first_user_registration_login_and_logout(raw_client: TestClient) -> None:
    credentials = {"username": "Operator", "password": "student123"}

    assert raw_client.get("/api/v1/auth/status").json() == {"registration_open": True}
    registered = raw_client.post("/api/v1/auth/register", json=credentials)
    assert registered.status_code == 201
    assert registered.json()["username"] == "operator"
    assert registered.json()["role"] == "OPERATOR"
    assert "password" not in registered.text

    assert raw_client.get("/api/v1/auth/status").json() == {"registration_open": False}
    repeated = raw_client.post(
        "/api/v1/auth/register",
        json={"username": "second", "password": "student456"},
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "REGISTRATION_CLOSED"

    wrong_password = raw_client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "wrong-pass"},
    )
    assert wrong_password.status_code == 401
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"

    login = raw_client.post("/api/v1/auth/login", json=credentials)
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "auction_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie

    current_user = raw_client.get("/api/v1/auth/me")
    assert current_user.status_code == 200
    assert current_user.json()["username"] == "operator"

    logout = raw_client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert raw_client.get("/api/v1/auth/me").status_code == 401


def test_password_is_hashed_and_auth_is_described_in_openapi(
    raw_client: TestClient,
) -> None:
    password = "student123"
    raw_client.post(
        "/api/v1/auth/register",
        json={"username": "operator", "password": password},
    )

    connection = sqlite3.connect(raw_client.app.state.database_path)
    try:
        stored_hash = connection.execute(
            "SELECT password_hash FROM users WHERE username = 'operator'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert stored_hash != password
    assert stored_hash.startswith("pbkdf2_sha256$")

    openapi = raw_client.get("/openapi.json").json()
    schemes = openapi["components"]["securitySchemes"]
    assert schemes["SessionCookie"]["in"] == "cookie"
    assert openapi["paths"]["/api/v1/sellers"]["post"]["security"] == [
        {"SessionCookie": []}
    ]

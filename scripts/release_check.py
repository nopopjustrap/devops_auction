"""Accept a running release through HTTP, including a real authenticated sale."""

import argparse
import http.cookiejar
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal


class ReleaseError(RuntimeError):
    pass


class HTTPClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, method, path, data=None, expected=200):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                if response.status != expected:
                    raise ReleaseError(f"{method} {path}: expected HTTP {expected}")
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            # Do not include response bodies, credentials or cookies in reports.
            raise ReleaseError(f"{method} {path}: HTTP {error.code}") from None
        except (OSError, ValueError):
            raise ReleaseError(f"{method} {path}: connection or JSON failure") from None


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def verify(client, revision, username, password):
    require(client.request("GET", "/health") == {"status": "ok"}, "health failed")
    require(client.request("GET", "/ready") == {"status": "ready"}, "readiness failed")
    version = client.request("GET", "/version")
    require(
        version.get("revision") == revision, "Running revision differs from image tag"
    )
    require(bool(version.get("version")), "Application version missing")
    client.request(
        "POST", "/api/v1/auth/login", {"username": username, "password": password}
    )
    try:
        client.request("GET", "/api/v1/auth/me")
        marker = "lr6-" + uuid.uuid4().hex
        seller = client.request(
            "POST",
            "/api/v1/sellers",
            {"name": marker, "email": marker + "-seller@example.com"},
            201,
        )
        buyer = client.request(
            "POST",
            "/api/v1/buyers",
            {"name": marker, "email": marker + "-buyer@example.com"},
            201,
        )
        start = datetime.now(UTC)
        auction = client.request(
            "POST",
            "/api/v1/auctions",
            {
                "title": marker,
                "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=1)).isoformat(),
                "commission_bps": 500,
            },
            201,
        )
        lot = client.request(
            "POST",
            f"/api/v1/auctions/{auction['id']}/lots",
            {"seller_id": seller["id"], "title": marker, "starting_price": "100.00"},
            201,
        )
        client.request("POST", f"/api/v1/auctions/{auction['id']}/open")
        sale = client.request(
            "POST",
            "/api/v1/sales",
            {"lot_id": lot["id"], "buyer_id": buyer["id"], "final_price": "150.25"},
            201,
        )
        require(Decimal(sale["commission"]) == Decimal("7.51"), "Wrong sale commission")
        require(
            Decimal(sale["seller_proceeds"]) == Decimal("142.74"),
            "Wrong seller proceeds",
        )
        report = client.request(
            "GET", f"/api/v1/reports/revenue?auction_id={auction['id']}"
        )
        require(report["sales_count"] == 1, "Sale missing from report")
        for key, expected in (
            ("gross_revenue", "150.25"),
            ("commission_revenue", "7.51"),
            ("seller_proceeds", "142.74"),
        ):
            require(Decimal(report[key]) == Decimal(expected), f"Wrong report {key}")
        client.request("POST", f"/api/v1/auctions/{auction['id']}/close")
        return {
            "status": "accepted",
            **version,
            "auction_id": auction["id"],
            "scenario": "login -> auction -> lot -> sale -> commission report -> close",
        }
    finally:
        client.request("POST", "/api/v1/auth/logout", expected=204)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    result = verify(
        HTTPClient(args.url),
        args.revision,
        os.environ["SMOKE_USERNAME"],
        os.environ["SMOKE_PASSWORD"],
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()

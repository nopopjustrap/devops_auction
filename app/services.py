"""SQL-запросы и бизнес-правила проекта."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.schemas import AuctionCreate, LotCreate, ParticipantCreate, SaleCreate


class DomainError(Exception):
    """Ожидаемая ошибка предметной области, которую API отдаёт клиенту."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _to_kopecks(value: Decimal) -> int:
    return int(value * 100)


def _from_kopecks(value: int) -> Decimal:
    return Decimal(value) / Decimal(100)


def _not_found(entity: str, object_id: int) -> DomainError:
    return DomainError(
        404, f"{entity.upper()}_NOT_FOUND", f"{entity} с id={object_id} не найден"
    )


def _participant_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["is_active"] = bool(result["is_active"])
    return result


def _lot_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["starting_price"] = _from_kopecks(result.pop("starting_price_kopecks"))
    return result


def _sale_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["final_price"] = _from_kopecks(result.pop("final_price_kopecks"))
    return result


def create_participant(
    connection: sqlite3.Connection,
    table: str,
    data: ParticipantCreate,
) -> dict[str, Any]:
    if table not in {"sellers", "buyers"}:
        raise ValueError("Unsupported participant table")

    try:
        cursor = connection.execute(
            f"INSERT INTO {table} (name, email, phone, created_at) VALUES (?, ?, ?, ?)",
            (data.name, data.email, data.phone, _now()),
        )
    except sqlite3.IntegrityError as error:
        raise DomainError(
            409, "EMAIL_ALREADY_EXISTS", "Участник с таким email уже существует"
        ) from error

    return get_participant(connection, table, cursor.lastrowid)


def get_participant(
    connection: sqlite3.Connection,
    table: str,
    participant_id: int | None,
) -> dict[str, Any]:
    if table not in {"sellers", "buyers"}:
        raise ValueError("Unsupported participant table")
    if participant_id is None:
        raise RuntimeError("SQLite did not return an inserted id")

    row = connection.execute(
        f"SELECT * FROM {table} WHERE id = ?", (participant_id,)
    ).fetchone()
    if row is None:
        raise _not_found(table[:-1].capitalize(), participant_id)
    return _participant_from_row(row)


def create_auction(
    connection: sqlite3.Connection, data: AuctionCreate
) -> dict[str, Any]:
    cursor = connection.execute(
        """
        INSERT INTO auctions (title, description, starts_at, ends_at, status, created_at)
        VALUES (?, ?, ?, ?, 'DRAFT', ?)
        """,
        (
            data.title,
            data.description,
            data.starts_at.astimezone(UTC).isoformat(),
            data.ends_at.astimezone(UTC).isoformat(),
            _now(),
        ),
    )
    return get_auction(connection, cursor.lastrowid)


def get_auction(
    connection: sqlite3.Connection, auction_id: int | None
) -> dict[str, Any]:
    if auction_id is None:
        raise RuntimeError("SQLite did not return an inserted id")
    row = connection.execute(
        "SELECT * FROM auctions WHERE id = ?", (auction_id,)
    ).fetchone()
    if row is None:
        raise _not_found("Auction", auction_id)
    return dict(row)


def create_lot(
    connection: sqlite3.Connection,
    auction_id: int,
    data: LotCreate,
) -> dict[str, Any]:
    auction = get_auction(connection, auction_id)
    if auction["status"] != "DRAFT":
        raise DomainError(
            409, "AUCTION_NOT_EDITABLE", "Лоты можно добавлять только в черновик"
        )

    seller = get_participant(connection, "sellers", data.seller_id)
    if not seller["is_active"]:
        raise DomainError(
            409, "SELLER_INACTIVE", "Неактивный продавец не может добавить лот"
        )

    cursor = connection.execute(
        """
        INSERT INTO lots (
            auction_id, seller_id, title, description,
            starting_price_kopecks, status, created_at
        ) VALUES (?, ?, ?, ?, ?, 'DRAFT', ?)
        """,
        (
            auction_id,
            data.seller_id,
            data.title,
            data.description,
            _to_kopecks(data.starting_price),
            _now(),
        ),
    )
    return get_lot(connection, cursor.lastrowid)


def get_lot(connection: sqlite3.Connection, lot_id: int | None) -> dict[str, Any]:
    if lot_id is None:
        raise RuntimeError("SQLite did not return an inserted id")
    row = connection.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
    if row is None:
        raise _not_found("Lot", lot_id)
    return _lot_from_row(row)


def open_auction(connection: sqlite3.Connection, auction_id: int) -> dict[str, Any]:
    connection.execute("BEGIN IMMEDIATE")
    auction = get_auction(connection, auction_id)
    if auction["status"] != "DRAFT":
        raise DomainError(
            409, "INVALID_AUCTION_STATUS", "Открыть можно только черновик аукциона"
        )

    lots_count = connection.execute(
        "SELECT COUNT(*) FROM lots WHERE auction_id = ?", (auction_id,)
    ).fetchone()[0]
    if lots_count == 0:
        raise DomainError(
            409, "AUCTION_HAS_NO_LOTS", "Нельзя открыть аукцион без лотов"
        )

    connection.execute(
        "UPDATE auctions SET status = 'OPEN' WHERE id = ?", (auction_id,)
    )
    connection.execute(
        "UPDATE lots SET status = 'AVAILABLE' WHERE auction_id = ? AND status = 'DRAFT'",
        (auction_id,),
    )
    return get_auction(connection, auction_id)


def close_auction(connection: sqlite3.Connection, auction_id: int) -> dict[str, Any]:
    connection.execute("BEGIN IMMEDIATE")
    auction = get_auction(connection, auction_id)
    if auction["status"] != "OPEN":
        raise DomainError(
            409, "INVALID_AUCTION_STATUS", "Закрыть можно только открытый аукцион"
        )

    connection.execute(
        "UPDATE auctions SET status = 'CLOSED' WHERE id = ?", (auction_id,)
    )
    connection.execute(
        "UPDATE lots SET status = 'UNSOLD' WHERE auction_id = ? AND status = 'AVAILABLE'",
        (auction_id,),
    )
    return get_auction(connection, auction_id)


def create_sale(connection: sqlite3.Connection, data: SaleCreate) -> dict[str, Any]:
    # IMMEDIATE не даёт двум параллельным запросам одновременно продать один лот.
    connection.execute("BEGIN IMMEDIATE")
    lot = get_lot(connection, data.lot_id)
    auction = get_auction(connection, lot["auction_id"])
    buyer = get_participant(connection, "buyers", data.buyer_id)

    if auction["status"] != "OPEN":
        raise DomainError(
            409, "AUCTION_NOT_OPEN", "Продажа разрешена только на открытом аукционе"
        )
    if lot["status"] == "SOLD":
        raise DomainError(409, "LOT_ALREADY_SOLD", "Лот уже продан")
    if lot["status"] != "AVAILABLE":
        raise DomainError(409, "LOT_NOT_AVAILABLE", "Лот недоступен для продажи")
    if not buyer["is_active"]:
        raise DomainError(
            409, "BUYER_INACTIVE", "Неактивный покупатель не может купить лот"
        )
    if data.final_price < lot["starting_price"]:
        raise DomainError(
            409,
            "PRICE_BELOW_STARTING_PRICE",
            "Итоговая цена не может быть ниже стартовой",
        )

    try:
        cursor = connection.execute(
            """
            INSERT INTO sales (lot_id, buyer_id, final_price_kopecks, sold_at)
            VALUES (?, ?, ?, ?)
            """,
            (data.lot_id, data.buyer_id, _to_kopecks(data.final_price), _now()),
        )
    except sqlite3.IntegrityError as error:
        raise DomainError(409, "LOT_ALREADY_SOLD", "Лот уже продан") from error

    connection.execute("UPDATE lots SET status = 'SOLD' WHERE id = ?", (data.lot_id,))
    return get_sale(connection, cursor.lastrowid)


def get_sale(connection: sqlite3.Connection, sale_id: int | None) -> dict[str, Any]:
    if sale_id is None:
        raise RuntimeError("SQLite did not return an inserted id")
    row = connection.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if row is None:
        raise _not_found("Sale", sale_id)
    return _sale_from_row(row)


def revenue_report(
    connection: sqlite3.Connection,
    auction_id: int | None,
) -> dict[str, Any]:
    parameters: tuple[int, ...] = ()
    condition = ""
    if auction_id is not None:
        get_auction(connection, auction_id)
        condition = "WHERE lots.auction_id = ?"
        parameters = (auction_id,)

    row = connection.execute(
        f"""
        SELECT COUNT(sales.id) AS sales_count,
               COALESCE(SUM(sales.final_price_kopecks), 0) AS revenue_kopecks
        FROM sales
        JOIN lots ON lots.id = sales.lot_id
        {condition}
        """,
        parameters,
    ).fetchone()
    return {
        "auction_id": auction_id,
        "sales_count": row["sales_count"],
        "gross_revenue": _from_kopecks(row["revenue_kopecks"]),
    }

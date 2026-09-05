"""HTTP API учебного проекта «Аукционы»."""

import os
import sqlite3
from collections.abc import Generator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import services
from app.db import connect, database_path_from_env, init_db
from app.schemas import (
    AuctionCreate,
    AuctionOut,
    LotCreate,
    LotOut,
    ParticipantCreate,
    ParticipantOut,
    RevenueReportOut,
    SaleCreate,
    SaleOut,
)
from app.services import DomainError


def create_app(database_path: str | None = None) -> FastAPI:
    selected_database_path = database_path or database_path_from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_db(application.state.database_path)
        yield

    application = FastAPI(
        title=os.getenv("APP_NAME") or "Auction Service",
        version="0.1.0",
        description="Учебный API для учёта аукционов, лотов и продаж.",
        lifespan=lifespan,
    )
    application.state.database_path = selected_database_path

    @application.exception_handler(DomainError)
    async def handle_domain_error(
        _request: Request, error: DomainError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Запрос не прошёл проверку",
                    "details": jsonable_encoder(error.errors()),
                }
            },
        )

    @application.exception_handler(sqlite3.Error)
    async def handle_database_error(
        _request: Request, _error: sqlite3.Error
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "База данных временно недоступна",
                    "details": {},
                }
            },
        )

    register_routes(application)
    return application


def get_connection(request: Request) -> Generator[sqlite3.Connection, None, None]:
    connection = connect(request.app.state.database_path)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


Database = Annotated[sqlite3.Connection, Depends(get_connection)]


def register_routes(application: FastAPI) -> None:
    @application.get("/health", tags=["service"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", tags=["service"])
    def ready(request: Request) -> dict[str, str]:
        connection = connect(request.app.state.database_path)
        try:
            connection.execute("SELECT 1")
        finally:
            connection.close()
        return {"status": "ready"}

    @application.post(
        "/api/v1/sellers",
        response_model=ParticipantOut,
        status_code=status.HTTP_201_CREATED,
        tags=["participants"],
    )
    def create_seller(data: ParticipantCreate, database: Database) -> dict[str, Any]:
        return services.create_participant(database, "sellers", data)

    @application.get(
        "/api/v1/sellers/{seller_id}",
        response_model=ParticipantOut,
        tags=["participants"],
    )
    def get_seller(seller_id: int, database: Database) -> dict[str, Any]:
        return services.get_participant(database, "sellers", seller_id)

    @application.post(
        "/api/v1/buyers",
        response_model=ParticipantOut,
        status_code=status.HTTP_201_CREATED,
        tags=["participants"],
    )
    def create_buyer(data: ParticipantCreate, database: Database) -> dict[str, Any]:
        return services.create_participant(database, "buyers", data)

    @application.get(
        "/api/v1/buyers/{buyer_id}",
        response_model=ParticipantOut,
        tags=["participants"],
    )
    def get_buyer(buyer_id: int, database: Database) -> dict[str, Any]:
        return services.get_participant(database, "buyers", buyer_id)

    @application.post(
        "/api/v1/auctions",
        response_model=AuctionOut,
        status_code=status.HTTP_201_CREATED,
        tags=["auctions"],
    )
    def create_auction(data: AuctionCreate, database: Database) -> dict[str, Any]:
        return services.create_auction(database, data)

    @application.get(
        "/api/v1/auctions/{auction_id}",
        response_model=AuctionOut,
        tags=["auctions"],
    )
    def get_auction(auction_id: int, database: Database) -> dict[str, Any]:
        return services.get_auction(database, auction_id)

    @application.post(
        "/api/v1/auctions/{auction_id}/lots",
        response_model=LotOut,
        status_code=status.HTTP_201_CREATED,
        tags=["lots"],
    )
    def create_lot(
        auction_id: int, data: LotCreate, database: Database
    ) -> dict[str, Any]:
        return services.create_lot(database, auction_id, data)

    @application.get(
        "/api/v1/auctions/{auction_id}/lots",
        response_model=list[LotOut],
        tags=["lots"],
    )
    def list_auction_lots(
        auction_id: int,
        database: Database,
    ) -> list[dict[str, Any]]:
        return services.list_auction_lots(database, auction_id)

    @application.get("/api/v1/lots/{lot_id}", response_model=LotOut, tags=["lots"])
    def get_lot(lot_id: int, database: Database) -> dict[str, Any]:
        return services.get_lot(database, lot_id)

    @application.post(
        "/api/v1/auctions/{auction_id}/open",
        response_model=AuctionOut,
        tags=["auctions"],
    )
    def open_auction(auction_id: int, database: Database) -> dict[str, Any]:
        return services.open_auction(database, auction_id)

    @application.post(
        "/api/v1/auctions/{auction_id}/close",
        response_model=AuctionOut,
        tags=["auctions"],
    )
    def close_auction(auction_id: int, database: Database) -> dict[str, Any]:
        return services.close_auction(database, auction_id)

    @application.post(
        "/api/v1/sales",
        response_model=SaleOut,
        status_code=status.HTTP_201_CREATED,
        tags=["sales"],
    )
    def create_sale(data: SaleCreate, database: Database) -> dict[str, Any]:
        return services.create_sale(database, data)

    @application.get(
        "/api/v1/reports/revenue",
        response_model=RevenueReportOut,
        tags=["reports"],
    )
    def revenue_report(
        database: Database,
        auction_id: Annotated[int | None, Query(gt=0)] = None,
    ) -> dict[str, Any]:
        return services.revenue_report(database, auction_id)


app = create_app()

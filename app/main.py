"""HTTP API учебного проекта «Аукционы»."""

import os
import sqlite3
from collections.abc import Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, Response, Security, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles

from app import auth, services
from app.db import connect, database_path_from_env, init_db
from app.schemas import (
    AuctionCreate,
    AuctionOut,
    AuthCredentials,
    AuthStatusOut,
    LotCreate,
    LotOut,
    ParticipantCreate,
    ParticipantOut,
    RevenueReportOut,
    SaleCreate,
    SaleOut,
    UserOut,
)
from app.services import DomainError

APP_VERSION = "0.1.1"
SESSION_COOKIE_NAME = "auction_session"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE_NAME,
    scheme_name="SessionCookie",
    auto_error=False,
)


def _positive_int_from_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} должен быть целым числом") from error
    if value <= 0:
        raise RuntimeError(f"{name} должен быть больше нуля")
    return value


def _boolean_from_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} должен иметь значение true или false")


def create_app(database_path: str | None = None) -> FastAPI:
    selected_database_path = database_path or database_path_from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_db(application.state.database_path)
        yield

    application = FastAPI(
        title=os.getenv("APP_NAME") or "Auction Service",
        version=APP_VERSION,
        description=(
            "Учебная система управления аукционами, лотами и продажами. "
            "Бизнес-операции доступны после входа оператора."
        ),
        lifespan=lifespan,
    )
    application.state.database_path = selected_database_path
    application.state.session_ttl_hours = _positive_int_from_env("SESSION_TTL_HOURS", 8)
    application.state.cookie_secure = _boolean_from_env("COOKIE_SECURE", False)
    application.mount(
        "/static",
        StaticFiles(directory=STATIC_DIRECTORY),
        name="static",
    )

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
SessionToken = Annotated[str | None, Security(session_cookie)]


def get_current_user(database: Database, token: SessionToken) -> dict[str, Any]:
    return auth.user_from_session(database, token)


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def register_routes(application: FastAPI) -> None:
    @application.get("/", include_in_schema=False, response_class=FileResponse)
    def web_interface() -> FileResponse:
        return FileResponse(STATIC_DIRECTORY / "index.html")

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

    @application.get(
        "/api/v1/auth/status",
        response_model=AuthStatusOut,
        tags=["authentication"],
    )
    def auth_status(database: Database) -> dict[str, bool]:
        return {"registration_open": auth.registration_is_open(database)}

    @application.post(
        "/api/v1/auth/register",
        response_model=UserOut,
        status_code=status.HTTP_201_CREATED,
        tags=["authentication"],
    )
    def register_user(
        credentials: AuthCredentials,
        database: Database,
    ) -> dict[str, Any]:
        return auth.register_first_user(database, credentials)

    @application.post(
        "/api/v1/auth/login",
        response_model=UserOut,
        tags=["authentication"],
    )
    def login(
        credentials: AuthCredentials,
        request: Request,
        response: Response,
        database: Database,
    ) -> dict[str, Any]:
        ttl_hours = request.app.state.session_ttl_hours
        token, user = auth.create_session(database, credentials, ttl_hours)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=ttl_hours * 60 * 60,
            httponly=True,
            secure=request.app.state.cookie_secure,
            samesite="lax",
            path="/",
        )
        return user

    @application.get(
        "/api/v1/auth/me",
        response_model=UserOut,
        tags=["authentication"],
    )
    def current_user(user: CurrentUser) -> dict[str, Any]:
        return user

    @application.post(
        "/api/v1/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["authentication"],
    )
    def logout(
        request: Request,
        database: Database,
        token: SessionToken,
    ) -> Response:
        auth.delete_session(database, token)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            httponly=True,
            secure=request.app.state.cookie_secure,
            samesite="lax",
            path="/",
        )
        return response

    @application.post(
        "/api/v1/sellers",
        response_model=ParticipantOut,
        status_code=status.HTTP_201_CREATED,
        tags=["participants"],
    )
    def create_seller(
        data: ParticipantCreate,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.create_participant(database, "sellers", data)

    @application.get(
        "/api/v1/sellers/{seller_id}",
        response_model=ParticipantOut,
        tags=["participants"],
    )
    def get_seller(
        seller_id: int,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.get_participant(database, "sellers", seller_id)

    @application.post(
        "/api/v1/buyers",
        response_model=ParticipantOut,
        status_code=status.HTTP_201_CREATED,
        tags=["participants"],
    )
    def create_buyer(
        data: ParticipantCreate,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.create_participant(database, "buyers", data)

    @application.get(
        "/api/v1/buyers/{buyer_id}",
        response_model=ParticipantOut,
        tags=["participants"],
    )
    def get_buyer(
        buyer_id: int,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.get_participant(database, "buyers", buyer_id)

    @application.post(
        "/api/v1/auctions",
        response_model=AuctionOut,
        status_code=status.HTTP_201_CREATED,
        tags=["auctions"],
    )
    def create_auction(
        data: AuctionCreate,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.create_auction(database, data)

    @application.get(
        "/api/v1/auctions/{auction_id}",
        response_model=AuctionOut,
        tags=["auctions"],
    )
    def get_auction(
        auction_id: int,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.get_auction(database, auction_id)

    @application.post(
        "/api/v1/auctions/{auction_id}/lots",
        response_model=LotOut,
        status_code=status.HTTP_201_CREATED,
        tags=["lots"],
    )
    def create_lot(
        auction_id: int,
        data: LotCreate,
        database: Database,
        _user: CurrentUser,
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
        _user: CurrentUser,
    ) -> list[dict[str, Any]]:
        return services.list_auction_lots(database, auction_id)

    @application.get("/api/v1/lots/{lot_id}", response_model=LotOut, tags=["lots"])
    def get_lot(
        lot_id: int,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.get_lot(database, lot_id)

    @application.post(
        "/api/v1/auctions/{auction_id}/open",
        response_model=AuctionOut,
        tags=["auctions"],
    )
    def open_auction(
        auction_id: int,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.open_auction(database, auction_id)

    @application.post(
        "/api/v1/auctions/{auction_id}/close",
        response_model=AuctionOut,
        tags=["auctions"],
    )
    def close_auction(
        auction_id: int,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.close_auction(database, auction_id)

    @application.post(
        "/api/v1/sales",
        response_model=SaleOut,
        status_code=status.HTTP_201_CREATED,
        tags=["sales"],
    )
    def create_sale(
        data: SaleCreate,
        database: Database,
        _user: CurrentUser,
    ) -> dict[str, Any]:
        return services.create_sale(database, data)

    @application.get(
        "/api/v1/reports/revenue",
        response_model=RevenueReportOut,
        tags=["reports"],
    )
    def revenue_report(
        database: Database,
        _user: CurrentUser,
        auction_id: Annotated[int | None, Query(gt=0)] = None,
    ) -> dict[str, Any]:
        return services.revenue_report(database, auction_id)


app = create_app()

"""Аутентификация оператора и серверные сессии."""

import base64
import binascii
import hashlib
import hmac
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas import AuthCredentials
from app.services import DomainError

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000


def _now() -> datetime:
    return datetime.now(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return (
        f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${_encode(salt)}${_encode(digest)}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected_digest = stored_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(digest, _decode(expected_digest))
    except (binascii.Error, TypeError, ValueError):
        return False


def _user_from_row(row: sqlite3.Row) -> dict[str, Any]:
    user = dict(row)
    user["is_active"] = bool(user["is_active"])
    user.pop("password_hash", None)
    user.pop("session_id", None)
    user.pop("session_expires_at", None)
    return user


def registration_is_open(connection: sqlite3.Connection) -> bool:
    return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def register_first_user(
    connection: sqlite3.Connection,
    credentials: AuthCredentials,
) -> dict[str, Any]:
    connection.execute("BEGIN IMMEDIATE")
    if not registration_is_open(connection):
        raise DomainError(
            409,
            "REGISTRATION_CLOSED",
            "Первый оператор уже зарегистрирован",
        )

    cursor = connection.execute(
        """
        INSERT INTO users (username, password_hash, role, created_at)
        VALUES (?, ?, 'OPERATOR', ?)
        """,
        (
            credentials.username.casefold(),
            hash_password(credentials.password),
            _now().isoformat(),
        ),
    )
    row = connection.execute(
        "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    if row is None:
        raise RuntimeError("SQLite did not return an inserted user")
    return _user_from_row(row)


def create_session(
    connection: sqlite3.Connection,
    credentials: AuthCredentials,
    ttl_hours: int,
) -> tuple[str, dict[str, Any]]:
    user_row = connection.execute(
        "SELECT * FROM users WHERE username = ?",
        (credentials.username.casefold(),),
    ).fetchone()
    if (
        user_row is None
        or not user_row["is_active"]
        or not verify_password(credentials.password, user_row["password_hash"])
    ):
        raise DomainError(
            401,
            "INVALID_CREDENTIALS",
            "Неверное имя пользователя или пароль",
        )

    now = _now()
    connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
    token = secrets.token_urlsafe(32)
    connection.execute(
        """
        INSERT INTO sessions (user_id, token_hash, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_row["id"],
            _token_hash(token),
            (now + timedelta(hours=ttl_hours)).isoformat(),
            now.isoformat(),
        ),
    )
    return token, _user_from_row(user_row)


def user_from_session(
    connection: sqlite3.Connection,
    token: str | None,
) -> dict[str, Any]:
    if not token:
        raise DomainError(401, "AUTH_REQUIRED", "Требуется вход в систему")

    row = connection.execute(
        """
        SELECT users.*,
               sessions.id AS session_id,
               sessions.expires_at AS session_expires_at
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ?
        """,
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        raise DomainError(401, "AUTH_REQUIRED", "Требуется вход в систему")

    if datetime.fromisoformat(row["session_expires_at"]) <= _now():
        connection.execute("DELETE FROM sessions WHERE id = ?", (row["session_id"],))
        raise DomainError(401, "SESSION_EXPIRED", "Сессия истекла, войдите снова")
    if not row["is_active"]:
        raise DomainError(403, "USER_INACTIVE", "Учётная запись отключена")

    return _user_from_row(row)


def delete_session(connection: sqlite3.Connection, token: str | None) -> None:
    if token:
        connection.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),)
        )

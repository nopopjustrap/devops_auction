"""Минимальная работа с SQLite без ORM."""

import os
import sqlite3
from pathlib import Path

DEFAULT_DATABASE_PATH = "data/auctions.db"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def database_path_from_env() -> str:
    """Возвращает путь к БД из окружения или безопасное локальное значение."""
    return os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH


def connect(database_path: str) -> sqlite3.Connection:
    """Открывает соединение и включает проверку внешних ключей SQLite."""
    if database_path != ":memory:":
        expanded_path = Path(database_path).expanduser()
        expanded_path.parent.mkdir(parents=True, exist_ok=True)
        database_path = str(expanded_path)

    connection = sqlite3.connect(database_path, timeout=5, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(database_path: str) -> None:
    """Создаёт таблицы. Повторный запуск безопасен благодаря IF NOT EXISTS."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect(database_path)
    try:
        connection.executescript(schema)
        connection.commit()
    finally:
        connection.close()

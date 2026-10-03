"""Минимальная работа с SQLite без ORM."""

import os
import sqlite3
from pathlib import Path

DEFAULT_DATABASE_PATH = "data/auctions.db"


def database_path_from_env() -> str:
    return os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH


def connect(database_path: str) -> sqlite3.Connection:
    """Open an existing database; a lost file must never silently reappear."""
    uri = Path(database_path).expanduser().resolve().as_uri() + "?mode=rw"
    connection = sqlite3.connect(uri, uri=True, timeout=5, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(database_path: str) -> None:
    from app.migrate import upgrade_database

    upgrade_database(database_path)

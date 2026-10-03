"""Versioned, transactional migration of a new or legacy SQLite database."""

import argparse
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
HEAD = "003"


def validate_legacy(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"
        )
    }
    if not tables or "alembic_version" in tables:
        return
    reference = sqlite3.connect(":memory:")
    try:
        reference.executescript((ROOT / "migrations/baseline.sql").read_text())
        query = "SELECT name, sql FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' ORDER BY name"

        def normalize(sql: str) -> str:
            return " ".join(sql.lower().split())

        expected = [(n, normalize(s)) for n, s in reference.execute(query)]
        actual = [(n, normalize(s)) for n, s in connection.execute(query)]
        if actual != expected:
            raise RuntimeError(
                "Unknown legacy schema: make a backup and inspect it first"
            )
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Legacy database contains broken foreign keys")
    finally:
        reference.close()


def upgrade_database(database_path: str, revision: str = "head") -> None:
    if database_path == ":memory:":
        raise ValueError("Migrations require a file database")
    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    try:
        validate_legacy(raw)
    finally:
        raw.close()
    engine = create_engine("sqlite:///" + str(path), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            try:
                command.upgrade(config, revision)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
    finally:
        engine.dispose()


def check_schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(version) != 1 or version[0][0] != HEAD:
        raise sqlite3.DatabaseError("Database migrations are not at head")
    connection.execute(
        "SELECT users.id, sessions.id, sellers.id, buyers.id, lots.id, "
        "auctions.commission_bps, sales.commission_kopecks "
        "FROM users, sessions, sellers, buyers, lots, auctions, sales LIMIT 0"
    )


def main() -> None:
    from app.db import database_path_from_env

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision", default="head", choices=["001", "002", "003", "head"]
    )
    args = parser.parse_args()
    path = database_path_from_env()
    upgrade_database(path, args.revision)
    print(f"Migrations applied to {path}: {args.revision}")


if __name__ == "__main__":
    main()

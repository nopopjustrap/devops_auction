"""Consistent SQLite snapshots; offline restore with an explicit overwrite flag."""

import argparse
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.db import database_path_from_env
from app.migrate import validate_legacy


def open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def validate_database(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Database integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Database has broken foreign keys")
    tables = {
        r[0]
        for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if (
        not {"users", "sessions", "sellers", "buyers", "auctions", "lots", "sales"}
        <= tables
    ):
        raise ValueError("Not an Auction Service database")
    if "alembic_version" in tables:
        versions = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        if versions not in [[("001",)], [("002",)], [("003",)]]:
            raise ValueError("Unsupported migration version")
        connection.execute("SELECT id, username, password_hash FROM users LIMIT 0")
        if versions[0][0] in {"002", "003"}:
            connection.execute("SELECT commission_bps FROM auctions LIMIT 0")
        if versions[0][0] == "003":
            connection.execute("SELECT commission_kopecks FROM sales LIMIT 0")
    else:
        validate_legacy(connection)


def backup_database(source: str, destination: str) -> Path:
    src, dst = (
        Path(source).expanduser().resolve(),
        Path(destination).expanduser().resolve(),
    )
    if src == dst or dst.exists():
        raise FileExistsError(
            "Backup destination must be a new file, separate from source"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".auction-backup-", dir=dst.parent)
    os.close(fd)
    try:
        with (
            closing(open_readonly(src)) as reader,
            closing(sqlite3.connect(temp)) as writer,
        ):
            reader.backup(writer)
            validate_database(writer)
        # Link refuses a concurrently created destination; the file keeps mode 0600.
        os.link(temp, dst)
    finally:
        Path(temp).unlink(missing_ok=True)
    return dst


def restore_database(
    source: str, destination: str, *, replace: bool = False
) -> Path | None:
    """Call only with the application stopped. Preserve the previous target bytes."""
    src, dst = (
        Path(source).expanduser().resolve(),
        Path(destination).expanduser().resolve(),
    )
    if src == dst:
        raise ValueError("Backup and target must be different files")
    if dst.exists() and not replace:
        raise FileExistsError(
            "Target exists; stop the app and explicitly request --replace"
        )
    if any(Path(str(dst) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError(
            "SQLite sidecar exists: stop the app and checkpoint/recover first"
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".auction-restore-", dir=dst.parent)
    os.close(fd)
    recovery = None
    try:
        with (
            closing(open_readonly(src)) as reader,
            closing(sqlite3.connect(temp)) as writer,
        ):
            reader.backup(writer)
            validate_database(writer)
        if dst.exists():
            fd, old = tempfile.mkstemp(
                prefix=dst.name + ".before-restore-", dir=dst.parent
            )
            with os.fdopen(fd, "wb") as output, dst.open("rb") as previous:
                shutil.copyfileobj(previous, output)
            recovery = Path(old)
            os.replace(temp, dst)
        else:
            os.link(temp, dst)
    finally:
        Path(temp).unlink(missing_ok=True)
    return recovery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--file")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--app-stopped", action="store_true")
    args = parser.parse_args()
    database = database_path_from_env()
    try:
        if args.action == "backup":
            name = args.file or (
                "backups/auction-"
                + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                + ".db"
            )
            print(f"Backup verified: {backup_database(database, name)}")
        else:
            if not args.file or not args.app_stopped:
                parser.error(
                    "restore requires --file and --app-stopped; stop the application first"
                )
            recovery = restore_database(args.file, database, replace=args.replace)
            print(f"Restored: {database}")
            if recovery:
                print(f"Previous target preserved: {recovery}")
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Operation failed: {error}\n")


if __name__ == "__main__":
    main()

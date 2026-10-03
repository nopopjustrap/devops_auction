import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.db import connect
from app.migrate import check_schema, upgrade_database

FIXTURE = Path(__file__).parent / "fixtures/v0_1_1.sql"


def seed_legacy(connection):
    connection.executescript("""
    INSERT INTO users VALUES (1, 'operator', 'legacy-hash', 'OPERATOR', 1, '2026-01-01');
    INSERT INTO sessions VALUES (1, 1, 'legacy-token-hash', '2099-01-01', '2026-01-01');
    INSERT INTO sellers VALUES (1, 'Seller', 's@example.com', NULL, 1, '2026-01-01');
    INSERT INTO buyers VALUES (1, 'Buyer', 'b@example.com', NULL, 1, '2026-01-01');
    INSERT INTO auctions VALUES (1, 'Old auction', NULL, '2026-01-01', '2026-01-02', 'CLOSED', '2026-01-01');
    INSERT INTO lots VALUES (1, 1, 1, 'Old lot', NULL, 10000, 'SOLD', '2026-01-01');
    INSERT INTO sales VALUES (1, 1, 1, 15000, '2026-01-01');
    """)


def test_three_sequential_migrations_with_data(tmp_path):
    path = str(tmp_path / "sequence.db")
    upgrade_database(path, "001")
    with closing(sqlite3.connect(path)) as c:
        seed_legacy(c)
        assert (
            c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "001"
        )
    upgrade_database(path, "002")
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("SELECT commission_bps FROM auctions").fetchone()[0] == 0
        assert (
            c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "002"
        )
    upgrade_database(path, "003")
    with closing(connect(path)) as c:
        check_schema(c)
        assert c.execute("SELECT commission_kopecks FROM sales").fetchone()[0] == 0
        assert c.execute("SELECT final_price_kopecks FROM sales").fetchone()[0] == 15000
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upgrade_legacy_preserves_all_data(tmp_path):
    path = str(tmp_path / "legacy.db")
    with closing(sqlite3.connect(path)) as c:
        c.executescript(FIXTURE.read_text())
        seed_legacy(c)
        tables = ("users", "sessions", "sellers", "buyers", "auctions", "lots", "sales")
        before = {t: list(c.execute(f"SELECT * FROM {t} ORDER BY id")) for t in tables}
    upgrade_database(path)
    upgrade_database(path)
    with closing(connect(path)) as c:
        check_schema(c)
        assert (
            c.execute("SELECT password_hash FROM users").fetchone()[0] == "legacy-hash"
        )
        assert (
            c.execute("SELECT token_hash FROM sessions").fetchone()[0]
            == "legacy-token-hash"
        )
        assert c.execute("SELECT title FROM lots").fetchone()[0] == "Old lot"
        assert c.execute("SELECT final_price_kopecks FROM sales").fetchone()[0] == 15000
        assert c.execute("SELECT commission_bps FROM auctions").fetchone()[0] == 0
        for table, old_rows in before.items():
            new_rows = [
                tuple(row)[: len(old_rows[0])]
                for row in c.execute(f"SELECT * FROM {table} ORDER BY id")
            ]
            assert new_rows == old_rows


def test_clean_database_and_idempotence(tmp_path):
    path = str(tmp_path / "clean.db")
    upgrade_database(path)
    with closing(connect(path)) as c:
        first = list(c.iterdump())
    upgrade_database(path)
    with closing(connect(path)) as c:
        assert list(c.iterdump()) == first
        check_schema(c)
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reject_unknown_legacy_without_modifying_it(tmp_path):
    path = tmp_path / "unknown.db"
    with closing(sqlite3.connect(path)) as c:
        c.execute("CREATE TABLE strangers (id INTEGER)")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="Unknown legacy"):
        upgrade_database(str(path))
    assert path.read_bytes() == before


def test_failed_migration_rolls_back_ddl_and_version(tmp_path, monkeypatch):
    from alembic import command

    path = str(tmp_path / "atomic.db")
    upgrade_database(path, "001")

    def broken(config, revision):
        c = config.attributes["connection"]
        c.exec_driver_sql("ALTER TABLE auctions ADD COLUMN should_rollback TEXT")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(command, "upgrade", broken)
    with pytest.raises(RuntimeError, match="simulated"):
        upgrade_database(path)
    with closing(connect(path)) as c:
        assert "should_rollback" not in [
            r[1] for r in c.execute("PRAGMA table_info(auctions)")
        ]
        assert (
            c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "001"
        )


def test_schema_check_rejects_old_version(tmp_path):
    path = str(tmp_path / "old.db")
    upgrade_database(path, "002")
    with closing(connect(path)) as c, pytest.raises(sqlite3.DatabaseError):
        check_schema(c)


def test_memory_migration_is_rejected():
    with pytest.raises(ValueError):
        upgrade_database(":memory:")

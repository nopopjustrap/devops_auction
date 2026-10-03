import sqlite3
from contextlib import closing

import pytest

from app.backup import backup_database, restore_database
from app.db import connect, init_db
from tests.test_migrations import FIXTURE, seed_legacy


def create_data(path):
    init_db(str(path))
    with closing(connect(str(path))) as c:
        c.execute(
            "INSERT INTO sellers(name,email,created_at) VALUES ('Original','s@example.com','2026-01-01')"
        )
        c.commit()


def test_backup_damage_restore_and_new_database(tmp_path):
    source, snapshot, fresh = [
        tmp_path / n for n in ("source.db", "snapshot.db", "fresh.db")
    ]
    create_data(source)
    backup_database(str(source), str(snapshot))
    with closing(connect(str(source))) as c:
        c.execute("UPDATE sellers SET name='Damaged'")
        c.commit()
    recovery = restore_database(str(snapshot), str(source), replace=True)
    assert recovery is not None and recovery.exists()
    with closing(connect(str(recovery))) as c:
        assert c.execute("SELECT name FROM sellers").fetchone()[0] == "Damaged"
    with closing(connect(str(source))) as c:
        assert c.execute("SELECT name FROM sellers").fetchone()[0] == "Original"
        c.execute("DELETE FROM sellers")
        c.commit()
    restore_database(str(snapshot), str(source), replace=True)
    restore_database(str(snapshot), str(fresh))
    with closing(connect(str(source))) as a, closing(connect(str(fresh))) as b:
        assert list(a.iterdump()) == list(b.iterdump())
        assert a.execute("SELECT COUNT(*) FROM sellers").fetchone()[0] == 1
    assert snapshot.stat().st_mode & 0o777 == 0o600


def test_online_wal_backup_includes_committed_data(tmp_path):
    source, snapshot = tmp_path / "wal.db", tmp_path / "snapshot.db"
    create_data(source)
    with closing(connect(str(source))) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("UPDATE sellers SET name='Committed in WAL'")
        c.commit()
        backup_database(str(source), str(snapshot))
    with closing(connect(str(snapshot))) as c:
        assert c.execute("SELECT name FROM sellers").fetchone()[0] == "Committed in WAL"


def test_legacy_backup_before_migration(tmp_path):
    source, snapshot = tmp_path / "old.db", tmp_path / "snapshot.db"
    with closing(sqlite3.connect(source)) as c:
        c.executescript(FIXTURE.read_text())
        seed_legacy(c)
    backup_database(str(source), str(snapshot))
    with closing(sqlite3.connect(snapshot)) as c:
        assert c.execute("SELECT final_price_kopecks FROM sales").fetchone()[0] == 15000


def test_restore_requires_explicit_overwrite(tmp_path):
    source, snapshot = tmp_path / "source.db", tmp_path / "snapshot.db"
    create_data(source)
    backup_database(str(source), str(snapshot))
    with pytest.raises(FileExistsError):
        restore_database(str(snapshot), str(source))
    with pytest.raises(ValueError):
        restore_database(str(source), str(source), replace=True)
    with pytest.raises(FileExistsError):
        backup_database(str(source), str(source))
    with pytest.raises(FileExistsError):
        backup_database(str(source), str(snapshot))


def test_corrupt_backup_leaves_target_unchanged(tmp_path):
    source, bad = tmp_path / "source.db", tmp_path / "bad.db"
    create_data(source)
    before = source.read_bytes()
    bad.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        restore_database(str(bad), str(source), replace=True)
    assert source.read_bytes() == before


def test_missing_source_does_not_create_empty_database(tmp_path):
    source = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        backup_database(str(source), str(tmp_path / "backup.db"))
    assert not source.exists()


def test_empty_database_is_not_a_valid_backup(tmp_path):
    source = tmp_path / "empty.db"
    source.touch()
    with pytest.raises(ValueError, match="Not an Auction"):
        backup_database(str(source), str(tmp_path / "backup.db"))


def test_restore_rejects_live_sqlite_sidecars(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    create_data(source)
    (tmp_path / "target.db-wal").touch()
    with pytest.raises(ValueError, match="sidecar"):
        restore_database(str(source), str(target))

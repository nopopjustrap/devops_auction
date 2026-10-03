from contextlib import closing

import pytest

from app import backup, migrate
from app.db import connect


def test_migrate_and_backup_restore_commands(tmp_path, monkeypatch, capsys):
    database, snapshot = tmp_path / "cli.db", tmp_path / "snapshot.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setattr("sys.argv", ["migrate"])
    migrate.main()
    with closing(connect(str(database))) as c:
        c.execute(
            "INSERT INTO sellers(name,email,created_at) VALUES ('Before','before@example.com','2026-01-01')"
        )
        c.commit()
    monkeypatch.setattr("sys.argv", ["backup", "backup", "--file", str(snapshot)])
    backup.main()
    with closing(connect(str(database))) as c:
        c.execute("DELETE FROM sellers")
        c.commit()
    monkeypatch.setattr(
        "sys.argv",
        ["backup", "restore", "--file", str(snapshot), "--replace", "--app-stopped"],
    )
    backup.main()
    with closing(connect(str(database))) as c:
        assert c.execute("SELECT name FROM sellers").fetchone()[0] == "Before"
    assert "Previous target preserved" in capsys.readouterr().out


def test_restore_cli_requires_stopped_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "untouched.db"))
    monkeypatch.setattr("sys.argv", ["backup", "restore", "--file", "snapshot.db"])
    with pytest.raises(SystemExit) as error:
        backup.main()
    assert error.value.code == 2
    assert not (tmp_path / "untouched.db").exists()


def test_backup_cli_missing_source_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "missing.db"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["backup", "backup"])
    with pytest.raises(SystemExit) as error:
        backup.main()
    assert error.value.code == 1
    assert not (tmp_path / "missing.db").exists()


def test_backup_cli_default_filename_and_restore_new(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    migrate.upgrade_database(str(source))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_PATH", str(source))
    monkeypatch.setattr("sys.argv", ["backup", "backup"])
    backup.main()
    snapshots = list((tmp_path / "backups").glob("*.db"))
    assert len(snapshots) == 1
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "restored.db"))
    monkeypatch.setattr(
        "sys.argv", ["backup", "restore", "--file", str(snapshots[0]), "--app-stopped"]
    )
    backup.main()
    with closing(connect(str(tmp_path / "restored.db"))) as c:
        migrate.check_schema(c)

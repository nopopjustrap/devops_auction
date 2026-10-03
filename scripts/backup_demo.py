"""Run real Make commands against disposable data; never touch the working DB."""

import os
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory(prefix="auction-backup-demo-") as directory:
        database = Path(directory) / "demo.db"
        snapshot = Path(directory) / "snapshot.db"
        env = os.environ.copy()

        def make(*arguments):
            subprocess.run(
                [
                    "make",
                    f"DATABASE_PATH={database}",
                    f"BACKUP_FILE={snapshot}",
                    *arguments,
                ],
                cwd=ROOT,
                env=env,
                check=True,
            )

        make("migrate")
        with closing(sqlite3.connect(database)) as c:
            c.execute(
                "INSERT INTO sellers(name,email,created_at) VALUES ('Restore demonstration','demo@example.com','2026-01-01')"
            )
            c.commit()
        make("backup")
        with closing(sqlite3.connect(database)) as c:
            c.execute("DELETE FROM sellers")
            c.commit()
            if c.execute("SELECT COUNT(*) FROM sellers").fetchone()[0] != 0:
                raise RuntimeError("Damage was not applied")
        print("After deliberate deletion: 0 sellers", flush=True)
        make("restore", "RESTORE_REPLACE=1", "APP_STOPPED=1")
        with closing(sqlite3.connect(database)) as c:
            if (
                c.execute("SELECT name FROM sellers").fetchone()[0]
                != "Restore demonstration"
            ):
                raise RuntimeError("Restored data differs")
        print("Restoration verified: 1 seller, original name preserved", flush=True)


if __name__ == "__main__":
    main()

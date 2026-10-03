"""Seven-table v0.1.1 baseline, including existing installations."""

from pathlib import Path

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[1] / "baseline.sql").read_text()
    for statement in sql.split(";"):
        if statement.strip():
            op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade is disabled; restore a verified backup")

"""Persist commission at sale time; historical sales retain zero commission."""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sales ADD COLUMN commission_kopecks INTEGER NOT NULL DEFAULT 0 "
        "CHECK (commission_kopecks >= 0 AND commission_kopecks <= final_price_kopecks)"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup instead of dropping financial data")

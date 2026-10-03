"""Commission rate: one basis point is 0.01 percent."""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auctions ADD COLUMN commission_bps INTEGER NOT NULL DEFAULT 0 "
        "CHECK (commission_bps BETWEEN 0 AND 10000)"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup instead of dropping financial data")

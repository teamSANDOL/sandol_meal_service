"""merge restaurant manager and vendor rename heads

Revision ID: e8b7f31c9a42
Revises: a7c9d2e4f681, c2d4a8f74f36
Create Date: 2026-07-16 00:10:00.000000

"""
from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "e8b7f31c9a42"
down_revision: str | Sequence[str] | None = (
    "a7c9d2e4f681",
    "c2d4a8f74f36",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the two current Alembic heads without schema changes."""


def downgrade() -> None:
    """Keep both parent revisions available when downgrading from the merge."""

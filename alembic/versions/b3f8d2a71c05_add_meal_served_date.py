"""add meal date

Revision ID: b3f8d2a71c05
Revises: e8b7f31c9a42
Create Date: 2026-07-23 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b3f8d2a71c05"
down_revision: str | Sequence[str] | None = "e8b7f31c9a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add, backfill, and de-duplicate the meal service date."""
    op.add_column("meal", sa.Column("date", sa.Date(), nullable=True))
    op.execute(
        sa.text(
            """
        UPDATE meal
        SET date = ((updated_at AT TIME ZONE 'Asia/Seoul') + interval '5 hours')::date
        WHERE date IS NULL
        """
        )
    )
    op.execute(
        sa.text(
            """
        DELETE FROM meal m
        USING meal n
        WHERE m.restaurant_id = n.restaurant_id
          AND m.meal_type_id = n.meal_type_id
          AND m.date = n.date
          AND (m.updated_at, m.registered_at, m.id)
              < (n.updated_at, n.registered_at, n.id)
        """
        )
    )
    op.alter_column("meal", "date", nullable=False)
    op.create_unique_constraint(
        "meal_restaurant_meal_type_date_unique",
        "meal",
        ["restaurant_id", "meal_type_id", "date"],
    )


def downgrade() -> None:
    """Remove the meal date; deleted duplicate rows are not restored."""
    op.drop_constraint("meal_restaurant_meal_type_date_unique", "meal", type_="unique")
    op.drop_column("meal", "date")

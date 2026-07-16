"""add restaurant manager applications

Revision ID: a7c9d2e4f681
Revises: f5f2d67168b1
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c9d2e4f681"
down_revision: Union[str, None] = "f5f2d67168b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """식당 manager 등록 신청 테이블을 추가합니다."""
    op.create_table(
        "RestaurantManagerApplication",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("applicant", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "submitted_time",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewer", sa.Integer(), nullable=True),
        sa.Column("reviewed_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["applicant"],
            ["User.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["Restaurant.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "restaurant_manager_application_restaurant_index",
        "RestaurantManagerApplication",
        ["restaurant_id"],
    )
    op.create_index(
        "restaurant_manager_application_applicant_index",
        "RestaurantManagerApplication",
        ["applicant"],
    )
    op.create_index(
        "restaurant_manager_application_status_index",
        "RestaurantManagerApplication",
        ["status"],
    )
    op.create_index(
        "restaurant_manager_application_pending_unique",
        "RestaurantManagerApplication",
        ["restaurant_id", "applicant"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """식당 manager 등록 신청 테이블을 제거합니다."""
    op.drop_index(
        "restaurant_manager_application_pending_unique",
        table_name="RestaurantManagerApplication",
    )
    op.drop_index(
        "restaurant_manager_application_status_index",
        table_name="RestaurantManagerApplication",
    )
    op.drop_index(
        "restaurant_manager_application_applicant_index",
        table_name="RestaurantManagerApplication",
    )
    op.drop_index(
        "restaurant_manager_application_restaurant_index",
        table_name="RestaurantManagerApplication",
    )
    op.drop_table("RestaurantManagerApplication")

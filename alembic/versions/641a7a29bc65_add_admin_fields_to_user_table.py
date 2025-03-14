"""Add admin fields to User table

Revision ID: 641a7a29bc65
Revises: 839cd699aac5
Create Date: 2025-03-14 15:11:28.032558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '641a7a29bc65'
down_revision: Union[str, None] = '839cd699aac5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """User 테이블에 admin 필드 추가"""
    op.add_column("User", sa.Column("meal_admin", sa.Boolean, nullable=False, server_default="0"))


def downgrade():
    """User 테이블에서 admin 필드 제거"""
    op.drop_column("User", "meal_admin")


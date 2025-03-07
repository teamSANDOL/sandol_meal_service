"""empty message

Revision ID: 428c090a94d0
Revises: e82435a31aa8
Create Date: 2025-03-07 12:29:08.003861

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import BOOLEAN
from sqlalchemy.sql import func

# revision identifiers, used by Alembic.
revision: str = "428c090a94d0"
down_revision: Union[str, None] = "e82435a31aa8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """새로운 Restaurant_submission 테이블을 생성하고 기존 데이터를 마이그레이션"""
    # 1️⃣ 새로운 테이블 생성
    op.create_table(
        "Restaurant_submission_new",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("submitter", sa.Integer, sa.ForeignKey("User.id"), nullable=False),
        sa.Column(
            "submitted_time",
            sa.DateTime(timezone=True),  # ✅ 변경: TIMESTAMP → DateTime(timezone=True)
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column("approver", sa.Integer, nullable=True),
        sa.Column(
            "approved_time",
            sa.DateTime(timezone=True),  # ✅ 변경: TIMESTAMP → DateTime(timezone=True)
            nullable=True,
            server_default=func.now(),
        ),
        sa.Column("establishment_type", sa.Text, nullable=False),
        sa.Column("is_campus", BOOLEAN, nullable=False),
        sa.Column("building_name", sa.Text, nullable=True),
        sa.Column("naver_map_link", sa.Text, nullable=True),
        sa.Column("kakao_map_link", sa.Text, nullable=True),
        sa.Column("latitude", sa.Float(53), nullable=True),
        sa.Column("longitude", sa.Float(53), nullable=True),
    )

    # 2️⃣ 기존 데이터 복사
    op.execute(
        """
        INSERT INTO Restaurant_submission_new 
        (id, name, status, submitter, submitted_time, approver, approved_time, 
         establishment_type, is_campus, building_name, naver_map_link, kakao_map_link, latitude, longitude)
        SELECT id, name, status, submitter, submitted_time, approver, approved_time, 
               establishment_type, is_campus, building_name, naver_map_link, kakao_map_link, latitude, longitude
        FROM Restaurant_submission;
        """
    )

    # 3️⃣ 기존 테이블 삭제
    op.drop_table("Restaurant_submission")

    # 4️⃣ 새로운 테이블을 기존 이름으로 변경
    op.rename_table("Restaurant_submission_new", "Restaurant_submission")


def downgrade():
    """이전 Restaurant_submission 테이블로 복구"""
    # 1️⃣ 원래 테이블 재생성
    op.create_table(
        "Restaurant_submission_old",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("submitter", sa.Integer, sa.ForeignKey("User.id"), nullable=False),
        sa.Column(
            "submitted_time",
            sa.TIMESTAMP(),  # ✅ 복구: DateTime(timezone=True) → TIMESTAMP
            nullable=False,
            server_default=func.now(),
        ),
        sa.Column("approver", sa.Integer, nullable=True),
        sa.Column(
            "approved_time",
            sa.TIMESTAMP(),  # ✅ 복구: DateTime(timezone=True) → TIMESTAMP
            nullable=True,
            server_default=func.now(),
        ),
        sa.Column("establishment_type", sa.Text, nullable=False),
        sa.Column("is_campus", BOOLEAN, nullable=False),
        sa.Column("building_name", sa.Text, nullable=True),
        sa.Column("naver_map_link", sa.Text, nullable=True),
        sa.Column("kakao_map_link", sa.Text, nullable=True),
        sa.Column("latitude", sa.Float(53), nullable=True),
        sa.Column("longitude", sa.Float(53), nullable=True),
    )

    # 2️⃣ 기존 데이터 복사
    op.execute(
        """
        INSERT INTO Restaurant_submission_old 
        (id, name, status, submitter, submitted_time, approver, approved_time, 
         establishment_type, is_campus, building_name, naver_map_link, kakao_map_link, latitude, longitude)
        SELECT id, name, status, submitter, submitted_time, approver, approved_time, 
               establishment_type, is_campus, building_name, naver_map_link, kakao_map_link, latitude, longitude
        FROM Restaurant_submission;
        """
    )

    # 3️⃣ 기존 테이블 삭제
    op.drop_table("Restaurant_submission")

    # 4️⃣ 원래 테이블 이름 복구
    op.rename_table("Restaurant_submission_old", "Restaurant_submission")

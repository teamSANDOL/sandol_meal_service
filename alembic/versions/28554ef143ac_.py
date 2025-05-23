"""empty message

Revision ID: 28554ef143ac
Revises: 3ac318667d15
Create Date: 2025-03-08 15:32:38.703257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28554ef143ac'
down_revision: Union[str, None] = '3ac318667d15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index('meal_meal_type_id_index', 'meal', ['meal_type_id'], unique=False)
    op.create_index('meal_updated_at_index', 'meal', ['updated_at'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('meal_updated_at_index', table_name='meal')
    op.drop_index('meal_meal_type_id_index', table_name='meal')
    # ### end Alembic commands ###

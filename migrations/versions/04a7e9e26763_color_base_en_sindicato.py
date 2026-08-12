"""color base en sindicato

Revision ID: 04a7e9e26763
Revises: e7120b09b9f2
Create Date: 2026-08-12 14:12:34.579145

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '04a7e9e26763'
down_revision: Union[str, None] = 'e7120b09b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default: ya hay sindicatos cargados y la columna es NOT NULL --
    # sin default, Postgres rechazaría el ALTER TABLE contra esas filas.
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('color_base', sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default='#0f1b2d'))


def downgrade() -> None:
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.drop_column('color_base')

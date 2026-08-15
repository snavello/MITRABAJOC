"""portada clara en sindicato

Revision ID: d4b7e5a1c923
Revises: a8c25f9b6d31
Create Date: 2026-08-15 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b7e5a1c923'
down_revision: Union[str, None] = 'a8c25f9b6d31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default 'false': ya hay sindicatos cargados y la columna es
    # NOT NULL -- grandfathering, ninguno cambia de aspecto el día del deploy.
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('portada_clara', sa.Boolean(),
                                       nullable=False, server_default='false'))


def downgrade() -> None:
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.drop_column('portada_clara')

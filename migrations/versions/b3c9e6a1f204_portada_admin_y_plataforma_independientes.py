"""portada clara independiente para admin y plataforma

Revision ID: b3c9e6a1f204
Revises: f19a7c3e2b40
Create Date: 2026-08-16 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c9e6a1f204'
down_revision: Union[str, None] = 'f19a7c3e2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default 'false': ya hay filas cargadas y las columnas son NOT
    # NULL -- grandfathering, nadie cambia de aspecto el día del deploy.
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('admin_portada_clara', sa.Boolean(),
                                       nullable=False, server_default='false'))
    with op.batch_alter_table('configuracionplataforma', schema=None) as batch_op:
        batch_op.add_column(sa.Column('portada_clara', sa.Boolean(),
                                       nullable=False, server_default='false'))


def downgrade() -> None:
    with op.batch_alter_table('configuracionplataforma', schema=None) as batch_op:
        batch_op.drop_column('portada_clara')
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.drop_column('admin_portada_clara')

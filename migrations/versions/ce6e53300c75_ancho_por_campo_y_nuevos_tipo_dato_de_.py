"""tramites: ancho por campo + nuevos tipo_dato (separador/booleano/opcion_unica/multiple)

Revision ID: ce6e53300c75
Revises: e3e6cedd8d87
Create Date: 2026-08-16 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'ce6e53300c75'
down_revision: Union[str, None] = 'e3e6cedd8d87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('campotramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ancho', sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default='completo'))
        batch_op.alter_column('etiqueta', existing_type=sqlmodel.sql.sqltypes.AutoString(),
                               nullable=False, server_default='')


def downgrade() -> None:
    with op.batch_alter_table('campotramite', schema=None) as batch_op:
        batch_op.alter_column('etiqueta', existing_type=sqlmodel.sql.sqltypes.AutoString(),
                               nullable=False, server_default=None)
        batch_op.drop_column('ancho')

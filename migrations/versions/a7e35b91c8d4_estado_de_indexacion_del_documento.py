"""estado de indexacion del documento de convenio

Revision ID: a7e35b91c8d4
Revises: f4d1a7c39e02
Create Date: 2026-08-23 02:10:47.663201

Sale de medir el bloque 2 antes de escribirlo: indexar un convenio entero
tarda ~9 minutos (246 fragmentos a 2,3 s cada uno). Ningún request HTTP
sobrevive eso, así que la indexación corre en segundo plano y el documento
necesita llevar su propio estado para que el panel pueda mostrar en qué anda.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a7e35b91c8d4'
down_revision: Union[str, None] = 'f4d1a7c39e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('documentoconvenio', schema=None) as b:
        b.add_column(sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(),
                               nullable=False, server_default='pendiente'))
        b.add_column(sa.Column('fragmentos_generados', sa.Integer(),
                               nullable=False, server_default='0'))
        b.add_column(sa.Column('error_detalle', sqlmodel.sql.sqltypes.AutoString(),
                               nullable=False, server_default=''))


def downgrade() -> None:
    with op.batch_alter_table('documentoconvenio', schema=None) as b:
        b.drop_column('error_detalle')
        b.drop_column('fragmentos_generados')
        b.drop_column('estado')

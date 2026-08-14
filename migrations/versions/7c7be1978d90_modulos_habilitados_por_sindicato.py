"""modulos habilitados por sindicato

Revision ID: 7c7be1978d90
Revises: a5fa211bace2
Create Date: 2026-08-14 14:28:08.003949

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# JSONB en Postgres, JSON común en SQLite -- mismo patrón que Concepto.alias.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# Lo que existe HOY (antes de este sistema de módulos). Sindicatos ya
# existentes quedan con todo esto habilitado -- nadie pierde nada el día
# del deploy (grandfathering acordado con el usuario). Ver modulos.py.
MODULOS_INICIALES = '["recibos", "aportes", "credencial", "capacitacion", "noticias", "beneficios"]'

# revision identifiers, used by Alembic.
revision: str = '7c7be1978d90'
down_revision: Union[str, None] = 'a5fa211bace2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.add_column(sa.Column('modulos_habilitados', JSON_TIPO, nullable=False,
                                       server_default='[]'))
    # Grandfathering: las filas que ya existían no arrancan vacías.
    op.execute(f"UPDATE sindicato SET modulos_habilitados = '{MODULOS_INICIALES}'")


def downgrade() -> None:
    with op.batch_alter_table('sindicato', schema=None) as batch_op:
        batch_op.drop_column('modulos_habilitados')

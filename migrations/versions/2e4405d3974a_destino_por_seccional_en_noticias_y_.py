"""destino por seccional en noticias y beneficios

Revision ID: 2e4405d3974a
Revises: b59a5ae7e164
Create Date: 2026-08-13 18:29:53.067420

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# JSONB en Postgres, JSON común en SQLite -- mismo patrón que Concepto.alias.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# revision identifiers, used by Alembic.
revision: str = '2e4405d3974a'
down_revision: Union[str, None] = 'b59a5ae7e164'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default '[]' porque la tabla puede tener filas y la columna
    # queda NOT NULL (mismo criterio que Concepto.alias en el esquema inicial).
    with op.batch_alter_table('noticia', schema=None) as batch_op:
        batch_op.add_column(sa.Column('destino_seccionales', JSON_TIPO, nullable=False,
                                       server_default='[]'))
    with op.batch_alter_table('beneficio', schema=None) as batch_op:
        batch_op.add_column(sa.Column('destino_seccionales', JSON_TIPO, nullable=False,
                                       server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('beneficio', schema=None) as batch_op:
        batch_op.drop_column('destino_seccionales')
    with op.batch_alter_table('noticia', schema=None) as batch_op:
        batch_op.drop_column('destino_seccionales')

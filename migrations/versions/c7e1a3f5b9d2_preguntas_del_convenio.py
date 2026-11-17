"""preguntas a la consulta con IA del convenio

PLAN_CONVENIO_ESCALAS.md, D34 y D37.6: cada pregunta hecha a la consulta con IA
del convenio, con su resultado y si se envió al equipo. Sin ninguna identidad.
Idempotente: la tabla se crea solo si falta.

Revision ID: c7e1a3f5b9d2
Revises: b6d9e2a4c8f1
Create Date: 2026-11-16 22:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = 'c7e1a3f5b9d2'
down_revision: Union[str, None] = 'b6d9e2a4c8f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'preguntaconvenio' in set(insp.get_table_names()):
        return
    op.create_table(
        'preguntaconvenio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('convenio', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('pregunta', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('resultado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('articulos', _JSON, nullable=False),
        sa.Column('frecuentes', _JSON, nullable=False),
        sa.Column('respuesta', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enviada', sa.Boolean(), nullable=False),
        sa.Column('enviada_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('modelo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_preguntaconvenio_convenio'), 'preguntaconvenio', ['convenio'], unique=False)
    op.create_index(op.f('ix_preguntaconvenio_enviada'), 'preguntaconvenio', ['enviada'], unique=False)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if 'preguntaconvenio' not in set(insp.get_table_names()):
        return
    op.drop_index(op.f('ix_preguntaconvenio_enviada'), table_name='preguntaconvenio')
    op.drop_index(op.f('ix_preguntaconvenio_convenio'), table_name='preguntaconvenio')
    op.drop_table('preguntaconvenio')

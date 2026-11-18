"""preguntas frecuentes del convenio en la base

PLAN_CONVENIO_ESCALAS.md, D41: las preguntas frecuentes pasan de un archivo a la
base para que el equipo las cure desde una pantalla (en Render no hay disco
persistente). Los archivos de data/convenios/ quedan como semilla. Dos tablas:
la pregunta y el historial de sus cambios. Sin identidad de afiliados.
Idempotente: cada tabla se crea solo si falta.

Revision ID: d8f2b4a6c0e1
Revises: c7e1a3f5b9d2
Create Date: 2026-11-18 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = 'd8f2b4a6c0e1'
down_revision: Union[str, None] = 'c7e1a3f5b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    if 'preguntafrecuente' not in existentes:
        op.create_table(
            'preguntafrecuente',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('convenio', _STR(), nullable=False),
            sa.Column('clave', _STR(), nullable=False),
            sa.Column('tema', _STR(), nullable=False),
            sa.Column('orden', sa.Float(), nullable=False),
            sa.Column('estado', _STR(), nullable=False),
            sa.Column('pregunta', _STR(), nullable=False),
            sa.Column('en_corto', _STR(), nullable=False),
            sa.Column('respuesta', _STR(), nullable=False),
            sa.Column('articulos', _JSON, nullable=False),
            sa.Column('segun_ley', _STR(), nullable=False),
            sa.Column('normas', _JSON, nullable=False),
            sa.Column('por_banco', _STR(), nullable=False),
            sa.Column('fuentes_banco', _JSON, nullable=False),
            sa.Column('nota_curador', _STR(), nullable=False),
            sa.Column('inspirada_en', _JSON, nullable=False),
            sa.Column('motivo_retiro', _STR(), nullable=False),
            sa.Column('detalle_retiro', _STR(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('creada', _STR(), nullable=False),
            sa.Column('modificada', _STR(), nullable=False),
            sa.Column('modificada_por', _STR(), nullable=False),
            sa.Column('revisada_por', _STR(), nullable=False),
            sa.Column('revisada_en', _STR(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('convenio', 'clave', name='uq_preguntafrecuente_clave'),
        )
        op.create_index(op.f('ix_preguntafrecuente_convenio'), 'preguntafrecuente', ['convenio'], unique=False)
        op.create_index(op.f('ix_preguntafrecuente_tema'), 'preguntafrecuente', ['tema'], unique=False)
        op.create_index(op.f('ix_preguntafrecuente_estado'), 'preguntafrecuente', ['estado'], unique=False)
    if 'preguntafrecuentecambio' not in existentes:
        op.create_table(
            'preguntafrecuentecambio',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('pregunta_id', sa.Integer(), nullable=False),
            sa.Column('cuando', _STR(), nullable=False),
            sa.Column('quien', _STR(), nullable=False),
            sa.Column('accion', _STR(), nullable=False),
            sa.Column('antes', _JSON, nullable=False),
            sa.Column('despues', _JSON, nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_preguntafrecuentecambio_pregunta_id'), 'preguntafrecuentecambio',
                        ['pregunta_id'], unique=False)


def downgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    if 'preguntafrecuentecambio' in existentes:
        op.drop_table('preguntafrecuentecambio')
    if 'preguntafrecuente' in existentes:
        op.drop_table('preguntafrecuente')

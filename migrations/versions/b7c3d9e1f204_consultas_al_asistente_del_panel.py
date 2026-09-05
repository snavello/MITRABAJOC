"""Consultas al Asistente del Panel Sindical

Registro de cada pregunta del admin al Asistente (docs/ASISTENTE_PANEL.md
§3): pregunta, respuesta, filtros que quedaron, costo en tokens. Sirve para
el tope diario, para auditar y para el set de frases de prueba. Tabla
propia, separada de consultaconvenio (el bot del trabajador) a propósito.

Revision ID: b7c3d9e1f204
Revises: a9d4e7f2c831
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7c3d9e1f204'
down_revision: Union[str, None] = 'a9d4e7f2c831'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# JSONB en Postgres, JSON común en SQLite -- mismo patrón que Concepto.alias.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'consultaasistente',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sindicato_id', sa.Integer(), sa.ForeignKey('sindicato.id'), nullable=False),
        sa.Column('usuario_id', sa.Integer(), sa.ForeignKey('usuariosindicato.id'), nullable=True),
        sa.Column('pregunta', sa.String(), nullable=False),
        sa.Column('respuesta', sa.String(), nullable=False),
        sa.Column('filtros', JSON_TIPO, nullable=True),
        sa.Column('tab', sa.String(), nullable=False),
        sa.Column('aplicado', sa.Boolean(), nullable=False),
        sa.Column('modelo', sa.String(), nullable=False),
        sa.Column('tokens_entrada', sa.Integer(), nullable=False),
        sa.Column('tokens_salida', sa.Integer(), nullable=False),
        sa.Column('llamadas', sa.Integer(), nullable=False),
        sa.Column('creado', sa.String(), nullable=False),
    )
    op.create_index('ix_consultaasistente_sindicato_id', 'consultaasistente', ['sindicato_id'])
    # El tope diario y cualquier listado van por sindicato + fecha.
    op.create_index('ix_consultaasistente_sid_creado', 'consultaasistente', ['sindicato_id', 'creado'])


def downgrade() -> None:
    op.drop_index('ix_consultaasistente_sid_creado', table_name='consultaasistente')
    op.drop_index('ix_consultaasistente_sindicato_id', table_name='consultaasistente')
    op.drop_table('consultaasistente')

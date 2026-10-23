"""registro del enmascarado: una fila por documento que pasó por el tapado

Revision ID: e5b2c8d4f1a7
Revises: c9e4a2f7b815
Create Date: 2026-09-24 00:00:00.000000

Tabla `registroenmascarado` (PLAN_ENMASCARADO.md, bloque 3): si se tapó, por
qué camino y, si no se pudo, por qué. Es el registro "para análisis
posterior" de la decisión de mejor esfuerzo, y la base del modo sombra.
Sin ningún dato personal a propósito (ver db.RegistroEnmascarado).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'e5b2c8d4f1a7'
down_revision: Union[str, None] = 'c9e4a2f7b815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    texto = sqlmodel.sql.sqltypes.AutoString
    op.create_table(
        'registroenmascarado',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fecha', texto(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=True),
        sa.Column('tipo', texto(), nullable=False),
        sa.Column('modo', texto(), nullable=False),
        sa.Column('camino', texto(), nullable=False),
        sa.Column('motivo', texto(), nullable=False),
        sa.Column('tapado', sa.Boolean(), nullable=False),
        sa.Column('cajas', sa.Integer(), nullable=False),
        sa.Column('fugas', sa.Integer(), nullable=False),
        sa.Column('cuil_encontrado', sa.Boolean(), nullable=True),
        sa.Column('pertenece', sa.Boolean(), nullable=True),
        sa.Column('espera_ms', sa.Integer(), nullable=False),
        sa.Column('lectura_ms', sa.Integer(), nullable=False),
        sa.Column('total_ms', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_registroenmascarado_sindicato_id'), 'registroenmascarado',
                    ['sindicato_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_registroenmascarado_sindicato_id'), table_name='registroenmascarado')
    op.drop_table('registroenmascarado')

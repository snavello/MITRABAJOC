"""XSII, bloque 5: hitos de la Mesa enlazados a tareas

Tabla `xsiihito`: el vinculo entre un hito de la Mesa (`implhito`) y una tarea
de XSII. Sin claves foraneas, idempotente como las otras tablas `xsii*`.

Revision ID: e5a7c9b1d3f6
Revises: d3f5a7b9c1e4
Create Date: 2026-11-28 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'e5a7c9b1d3f6'
down_revision: Union[str, None] = 'd3f5a7b9c1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    if 'xsiihito' in existentes:
        return
    op.create_table('xsiihito',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proyecto_id', sa.Integer(), nullable=False),
        sa.Column('hito_id', sa.Integer(), nullable=False),
        sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('quien_id', sa.Integer(), nullable=False),
        sa.Column('quien_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('activa', sa.Boolean(), nullable=False),
        sa.Column('retirado_por_id', sa.Integer(), nullable=False),
        sa.Column('retirado_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('retirado_cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    op.create_index(op.f('ix_xsiihito_proyecto_id'), 'xsiihito', ['proyecto_id'], unique=False)
    op.create_index('uq_xsiihito_activo', 'xsiihito', ['proyecto_id', 'hito_id', 'codigo'],
                    unique=True, postgresql_where=sa.text('activa'))


def downgrade() -> None:
    if 'xsiihito' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('xsiihito')

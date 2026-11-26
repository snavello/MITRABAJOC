"""XSII, bloque 1: decisiones, insumos y movimientos

Las tres tablas del registro de la implementacion inteligente (`xsii*`),
sin claves foraneas hacia el resto. Idempotente, como las de la Mesa: son
datos reales de Pruebas y un clonado de la demo puede dejar la marca de
Alembic atrasada con las tablas ya creadas.

Revision ID: a4c6e8b0d2f4
Revises: f7b1d3e5a9c2
Create Date: 2026-11-26 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = 'a4c6e8b0d2f4'
down_revision: Union[str, None] = 'f7b1d3e5a9c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())

    if 'xsiidecision' not in existentes:
        op.create_table('xsiidecision',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proyecto_id', sa.Integer(), nullable=False),
            sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('quien_id', sa.Integer(), nullable=False),
            sa.Column('quien_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('activa', sa.Boolean(), nullable=False),
            sa.Column('deshecha_por_id', sa.Integer(), nullable=False),
            sa.Column('deshecha_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('deshecha_cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('deshecha_motivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.PrimaryKeyConstraint('id'))
        op.create_index(op.f('ix_xsiidecision_proyecto_id'), 'xsiidecision', ['proyecto_id'], unique=False)
        op.create_index('uq_xsiidecision_activa', 'xsiidecision', ['proyecto_id', 'codigo', 'tipo'],
                        unique=True, postgresql_where=sa.text('activa'))

    if 'xsiiinsumo' not in existentes:
        op.create_table('xsiiinsumo',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proyecto_id', sa.Integer(), nullable=False),
            sa.Column('clave', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('tarjeta_id', sa.Integer(), nullable=True),
            sa.Column('archivo_id', sa.Integer(), nullable=True),
            sa.Column('nota', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('quien_id', sa.Integer(), nullable=False),
            sa.Column('quien_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('activa', sa.Boolean(), nullable=False),
            sa.Column('retirado_por_id', sa.Integer(), nullable=False),
            sa.Column('retirado_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('retirado_cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.PrimaryKeyConstraint('id'))
        op.create_index(op.f('ix_xsiiinsumo_proyecto_id'), 'xsiiinsumo', ['proyecto_id'], unique=False)
        op.create_index('uq_xsiiinsumo_activo', 'xsiiinsumo', ['proyecto_id', 'clave'],
                        unique=True, postgresql_where=sa.text('activa'))

    if 'xsiimovimiento' not in existentes:
        op.create_table('xsiimovimiento',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proyecto_id', sa.Integer(), nullable=False),
            sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('clave_insumo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('texto', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('cantidades', _JSON, nullable=False),
            sa.Column('quien_id', sa.Integer(), nullable=False),
            sa.Column('quien_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('cuando', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.PrimaryKeyConstraint('id'))
        op.create_index(op.f('ix_xsiimovimiento_proyecto_id'), 'xsiimovimiento', ['proyecto_id'], unique=False)
        op.create_index('ix_xsiimovimiento_proyecto_codigo', 'xsiimovimiento', ['proyecto_id', 'codigo'],
                        unique=False)


def downgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    for tabla in ('xsiimovimiento', 'xsiiinsumo', 'xsiidecision'):
        if tabla in existentes:
            op.drop_table(tabla)

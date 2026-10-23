"""imágenes de diagnóstico del enmascarado (TRANSITORIO, solo Pruebas)

Revision ID: f3a9d1c6b2e8
Revises: e5b2c8d4f1a7
Create Date: 2026-09-24 00:00:00.000000

Tabla `imagenenmascarado`: la imagen original y la que se mandó a la IA de
un documento del enmascarado, para revisar en Pruebas qué se tapó de verdad
(pedido de SDN, 2026-09-24). La original tiene datos personales: solo se
escribe en local/pruebas con ENMASCARADO_GUARDAR_IMAGENES=1, vence a los 7
días y se vacía desde la pantalla. Cuando termine la etapa de diagnóstico,
esta tabla y su código se sacan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'f3a9d1c6b2e8'
down_revision: Union[str, None] = 'e5b2c8d4f1a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'imagenenmascarado',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('registro_id', sa.Integer(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('original', sa.LargeBinary(), nullable=False),
        sa.Column('enviada', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['registro_id'], ['registroenmascarado.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_imagenenmascarado_registro_id'), 'imagenenmascarado',
                    ['registro_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_imagenenmascarado_registro_id'), table_name='imagenenmascarado')
    op.drop_table('imagenenmascarado')

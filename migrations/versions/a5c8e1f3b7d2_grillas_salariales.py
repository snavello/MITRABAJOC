"""grillas salariales en la base

Revision ID: a5c8e1f3b7d2
Revises: c4e7a9b2d6f1
Create Date: 2026-11-16 17:55:00.000000

PLAN_CONVENIO_ESCALAS.md, bloque 1 (D8, D17): tabla genérica por convenio con
las grillas salariales. Idempotente: si la tabla ya existe (restauración de un
dump sobre una revisión vieja) no se vuelve a crear.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

revision: str = 'a5c8e1f3b7d2'
down_revision: Union[str, None] = 'c4e7a9b2d6f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    if 'grillasalarial' in existentes:
        return
    op.create_table(
        'grillasalarial',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('convenio', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('periodo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('contenido', _JSON, nullable=False),
        sa.Column('fuente_nota', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fuente_pdf', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('publicada_sindicato', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('origen', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('controles', _JSON, nullable=False),
        sa.Column('creada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('resuelta_por', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('resuelta_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('nota', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_grillasalarial_convenio'), 'grillasalarial', ['convenio'], unique=False)
    op.create_index('uq_grillasalarial_publicada', 'grillasalarial', ['convenio', 'periodo'],
                    unique=True, postgresql_where=sa.text("estado = 'publicada'"))


def downgrade() -> None:
    op.drop_index('uq_grillasalarial_publicada', table_name='grillasalarial')
    op.drop_index(op.f('ix_grillasalarial_convenio'), table_name='grillasalarial')
    op.drop_table('grillasalarial')

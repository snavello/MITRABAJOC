"""tabla de beneficios

Revision ID: 227df29a4171
Revises: cf4127af2492
Create Date: 2026-08-13 15:37:18.993842

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '227df29a4171'
down_revision: Union[str, None] = 'cf4127af2492'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('beneficio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('rubro', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('descripcion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('link', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha_desde', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha_hasta', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creada', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('imagen_datos', sa.LargeBinary(), nullable=True),
        sa.Column('imagen_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('beneficio', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_beneficio_sindicato_id'), ['sindicato_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('beneficio', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_beneficio_sindicato_id'))
    op.drop_table('beneficio')

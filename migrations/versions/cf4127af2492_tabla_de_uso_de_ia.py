"""tabla de uso de IA

Revision ID: cf4127af2492
Revises: 6b111a3991b1
Create Date: 2026-08-12 19:55:15.396825

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'cf4127af2492'
down_revision: Union[str, None] = '6b111a3991b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('usoia',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=True),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('modelo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tokens_entrada', sa.Integer(), nullable=False),
        sa.Column('tokens_salida', sa.Integer(), nullable=False),
        sa.Column('fecha', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('usoia', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usoia_sindicato_id'), ['sindicato_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('usoia', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usoia_sindicato_id'))
    op.drop_table('usoia')

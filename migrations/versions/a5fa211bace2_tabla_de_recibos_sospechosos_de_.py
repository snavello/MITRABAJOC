"""tabla de recibos sospechosos de adulteracion

Revision ID: a5fa211bace2
Revises: 2e4405d3974a
Create Date: 2026-08-13 20:34:47.946216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a5fa211bace2'
down_revision: Union[str, None] = '2e4405d3974a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('recibosospechoso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=True),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('periodo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('motivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('archivo_datos', sa.LargeBinary(), nullable=False),
        sa.Column('archivo_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('archivo_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('recibosospechoso', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recibosospechoso_sindicato_id'), ['sindicato_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_recibosospechoso_cuil'), ['cuil'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('recibosospechoso', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recibosospechoso_cuil'))
        batch_op.drop_index(batch_op.f('ix_recibosospechoso_sindicato_id'))
    op.drop_table('recibosospechoso')

"""seccionales del sindicato

Revision ID: b59a5ae7e164
Revises: 227df29a4171
Create Date: 2026-08-13 17:03:57.543474

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b59a5ae7e164'
down_revision: Union[str, None] = '227df29a4171'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('seccional',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sindicato_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('direccion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['sindicato_id'], ['sindicato.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('seccional', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_seccional_sindicato_id'), ['sindicato_id'], unique=False)

    # Nullable: es un dato opcional, las filas existentes quedan sin seccional.
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seccional_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_trabajador_seccional_id'), ['seccional_id'], unique=False)
        batch_op.create_foreign_key('fk_trabajador_seccional_id_seccional', 'seccional', ['seccional_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trabajador_seccional_id_seccional', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_trabajador_seccional_id'))
        batch_op.drop_column('seccional_id')

    with op.batch_alter_table('seccional', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_seccional_sindicato_id'))
    op.drop_table('seccional')

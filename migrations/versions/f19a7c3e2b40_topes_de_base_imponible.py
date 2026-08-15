"""topes de base imponible

Revision ID: f19a7c3e2b40
Revises: d4b7e5a1c923
Create Date: 2026-08-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f19a7c3e2b40'
down_revision: Union[str, None] = 'd4b7e5a1c923'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'topebaseimponible',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vigencia_desde', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tope_maximo', sa.Float(), nullable=False),
        sa.Column('base_minima', sa.Float(), nullable=False),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fuente', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_topebaseimponible_vigencia_desde'), 'topebaseimponible', ['vigencia_desde'], unique=False)

    # server_default: ya hay fórmulas cargadas y la columna es NOT NULL.
    with op.batch_alter_table('formula', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sujeto_a_tope', sa.Boolean(), nullable=False, server_default='false'))

    # Grandfathering: sin este UPDATE, ningún sindicato existente se
    # beneficia del fix hasta que el admin tilde el checkbox a mano en cada
    # fórmula -- jubilación/INSSJP/obra social son justo las que están
    # sujetas a tope por defecto (ver db.crear_conceptos_universales).
    op.execute(
        "UPDATE formula SET sujeto_a_tope = true "
        "WHERE target IN ('JUBILACION', 'PAMI', 'OBRASOCIAL')"
    )


def downgrade() -> None:
    with op.batch_alter_table('formula', schema=None) as batch_op:
        batch_op.drop_column('sujeto_a_tope')
    op.drop_index(op.f('ix_topebaseimponible_vigencia_desde'), table_name='topebaseimponible')
    op.drop_table('topebaseimponible')

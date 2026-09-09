"""tabla test_carga -- corridas del test de estres desde /entornos

Revision ID: a1c8f5b2e934
Revises: 9c4e2f7a1b3d
Create Date: 2026-09-09 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a1c8f5b2e934'
down_revision: Union[str, None] = '9c4e2f7a1b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'testcarga',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entorno', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default='pruebas'),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default='lecturas'),
        sa.Column('estado', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default='pendiente'),
        sa.Column('parametros', sa.JSON(), nullable=False),
        sa.Column('resumen', sa.JSON(), nullable=True),
        sa.Column('avance', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default=''),
        sa.Column('error_detalle', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default=''),
        sa.Column('render_job_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default=''),
        sa.Column('creado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default=''),
        sa.Column('terminado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                   server_default=''),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('testcarga')

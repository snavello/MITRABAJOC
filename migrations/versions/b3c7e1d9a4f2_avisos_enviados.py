"""avisos enviados: el candado del resumen diario por Telegram

Revision ID: b3c7e1d9a4f2
Revises: a7e3f90b5c21
Create Date: 2026-09-23 00:00:00.000000

Una fila por (clave, fecha): "el resumen-telegram del 2026-09-23 ya salió".
El hilo `resumen_diario.py` intenta insertarla antes de mandar y solo manda
si ganó el INSERT (ON CONFLICT DO NOTHING): con varios workers despertando
en el mismo minuto, uno solo puede ganar. Es el mismo criterio que el
`ultimo_disparo` del planificador de planes, pero para avisos que se mandan
una vez por día y no por regla.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'b3c7e1d9a4f2'
down_revision: Union[str, None] = 'a7e3f90b5c21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'avisoenviado',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clave', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clave', 'fecha', name='uq_avisoenviado_clave_fecha'),
    )
    op.create_index(op.f('ix_avisoenviado_clave'), 'avisoenviado', ['clave'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_avisoenviado_clave'), table_name='avisoenviado')
    op.drop_table('avisoenviado')

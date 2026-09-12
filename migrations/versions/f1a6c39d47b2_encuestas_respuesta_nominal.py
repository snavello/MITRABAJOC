"""encuestas: el vinculo respuesta-persona de las nominales (Fase 2)

Revision ID: f1a6c39d47b2
Revises: d9e4b71c8a52
Create Date: 2026-09-12 00:20:00.000000

Fase 2 de SPRINT_ENCUESTAS.md. En una encuesta NOMINAL el afiliado responde
sabiendo que su nombre queda pegado a lo que contestó, y el sindicato tiene
que poder exportarlo (N20). Ese vínculo NO puede ser una columna de
`respuestaencuesta`: si lo fuera, la garantía de las anónimas pasaría a ser
"nos acordamos de dejarla en NULL", que es justo la clase de promesa que
este módulo evita.

Por eso va en su propia tabla y la flecha apunta al revés: de acá a la
respuesta, nunca de la respuesta a acá. La urna sigue sin ninguna columna
que lleve a una persona, y en una encuesta anónima esta tabla no tiene
filas -- hay un test que lo verifica.

Sin backfill: no hay ninguna encuesta respondida todavía.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'f1a6c39d47b2'
down_revision: Union[str, None] = 'd9e4b71c8a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('respuestanominal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('encuesta_id', sa.Integer(), nullable=False),
        sa.Column('respuesta_id', sa.Integer(), nullable=False),
        sa.Column('cuil', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['encuesta_id'], ['encuesta.id'], ),
        sa.ForeignKeyConstraint(['respuesta_id'], ['respuestaencuesta.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('respuestanominal', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_respuestanominal_encuesta_id'),
                              ['encuesta_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestanominal_respuesta_id'),
                              ['respuesta_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_respuestanominal_cuil'), ['cuil'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('respuestanominal', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_respuestanominal_cuil'))
        batch_op.drop_index(batch_op.f('ix_respuestanominal_respuesta_id'))
        batch_op.drop_index(batch_op.f('ix_respuestanominal_encuesta_id'))
    op.drop_table('respuestanominal')

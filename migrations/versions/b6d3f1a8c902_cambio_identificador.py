"""traza de la regularización de CUIL/CUIT (cambioidentificador)

Revision ID: b6d3f1a8c902
Revises: f3a9d1c6b2e8
Create Date: 2026-10-10 00:00:00.000000

Tabla `cambioidentificador` (PLAN_CUIT_MOD11.md, etapa 2): una fila por
número que `regularizar_cuit.py aplicar --si` convirtió, con el anterior, el
nuevo, quién y cuándo. La historia (bitácoras, textos libres, archivos) no se
reescribe, y esta tabla es lo que permite seguir un número viejo hasta la
persona. Solo agrega una tabla: no toca ni migra ningún dato.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision: str = 'b6d3f1a8c902'
down_revision: Union[str, None] = 'f3a9d1c6b2e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'cambioidentificador',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('anterior', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('nuevo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('origen', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('entorno', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('quien', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('filas', sa.Integer(), nullable=False),
        sa.Column('detalle', JSON_TIPO, nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cambioidentificador_anterior'), 'cambioidentificador',
                    ['anterior'], unique=False)
    op.create_index(op.f('ix_cambioidentificador_nuevo'), 'cambioidentificador',
                    ['nuevo'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cambioidentificador_nuevo'), table_name='cambioidentificador')
    op.drop_index(op.f('ix_cambioidentificador_anterior'), table_name='cambioidentificador')
    op.drop_table('cambioidentificador')

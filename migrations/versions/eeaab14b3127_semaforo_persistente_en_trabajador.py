"""semaforo persistente en trabajador

Revision ID: eeaab14b3127
Revises: 04a7e9e26763
Create Date: 2026-08-12 15:58:15.868914

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


# JSONB en Postgres (mismo patrón que Concepto.alias en el esquema inicial),
# JSON común en SQLite.
JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# revision identifiers, used by Alembic.
revision: str = 'eeaab14b3127'
down_revision: Union[str, None] = '04a7e9e26763'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ambas columnas nullable: filas existentes quedan en NULL (equivale a
    # "todavía no consultó ARCA"), no hace falta server_default.
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.add_column(sa.Column('semaforo_datos', JSON_TIPO, nullable=True))
        batch_op.add_column(sa.Column('semaforo_actualizado', sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('trabajador', schema=None) as batch_op:
        batch_op.drop_column('semaforo_actualizado')
        batch_op.drop_column('semaforo_datos')

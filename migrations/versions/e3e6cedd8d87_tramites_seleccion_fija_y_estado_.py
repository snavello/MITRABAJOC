"""tramites: campo Selección Fija + estado inicial "iniciado"

Revision ID: e3e6cedd8d87
Revises: b3c9e6a1f204
Create Date: 2026-08-16 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e3e6cedd8d87'
down_revision: Union[str, None] = 'b3c9e6a1f204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('campotramite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opciones', sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=''))

    # Rename: "enviado" (estado inicial) pasa a llamarse "iniciado" -- mismo
    # significado, sin eso los trámites ya presentados quedarían en un
    # estado que ESTADOS_TRAMITE ya no reconoce.
    op.execute("UPDATE tramite SET estado = 'iniciado' WHERE estado = 'enviado'")


def downgrade() -> None:
    op.execute("UPDATE tramite SET estado = 'enviado' WHERE estado = 'iniciado'")
    with op.batch_alter_table('campotramite', schema=None) as batch_op:
        batch_op.drop_column('opciones')

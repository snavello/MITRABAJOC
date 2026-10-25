"""tema de la empresa: el modelo de diseño que elige el empleador

PLAN_TEMAS.md, D2, llevado a la app de la empresa: el empleador guarda en su
cuenta (`cuentaempleador.tema`) el modelo que eligió, como el afiliado. Vacío =
vale el que el sindicato eligió para sus afiliados (`sindicato.tema_afiliados`),
así que las cuentas que ya existen siguen al sindicato sin que nadie haga nada.

Revision ID: b3e7f1c9a2d5
Revises: a9d4e7c2f1b8
Create Date: 2026-10-25 02:39:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3e7f1c9a2d5'
down_revision: Union[str, None] = 'a9d4e7c2f1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuentaempleador", sa.Column("tema", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("cuentaempleador", "tema")

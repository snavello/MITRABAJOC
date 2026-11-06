"""ingreso con Google

`google_sub` en `cuentatrabajador` y `cuentaempleador`: el identificador estable
de la cuenta de Google con que la persona ingresó la primera vez, para que las
próximas veces se la reconozca aunque cambie el mail. Vacío = nunca ingresó con
Google. Google solo identifica cuentas YA registradas con mail confirmado: no
crea cuentas (decisión de SDN, 2026-11-06).

Revision ID: a5c7e9b1d3f6
Revises: d3e5f7a9b1c4
Create Date: 2026-11-06 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'a5c7e9b1d3f6'
down_revision: Union[str, None] = 'd3e5f7a9b1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CUENTAS = ("cuentatrabajador", "cuentaempleador")


def upgrade() -> None:
    for tabla in CUENTAS:
        op.add_column(tabla, sa.Column("google_sub", sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=""))
        op.create_index(op.f(f"ix_{tabla}_google_sub"), tabla, ["google_sub"], unique=False)


def downgrade() -> None:
    for tabla in reversed(CUENTAS):
        op.drop_index(op.f(f"ix_{tabla}_google_sub"), table_name=tabla)
        op.drop_column(tabla, "google_sub")

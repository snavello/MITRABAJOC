"""ingreso con Google al panel del sindicato

`mail` y `google_sub` en `cuentapanel`: el mail de la PERSONA (como la clave, una
cuenta por CUIL) con el que Google la identifica para entrar al panel, y el
identificador estable de la cuenta de Google con que ingresó la primera vez.
Vacíos = sin mail / nunca ingresó con Google. Google solo identifica cuentas YA
creadas: no las crea.

Revision ID: c6e8a0b2d4f7
Revises: b2d4f6a8c0e2
Create Date: 2026-11-06 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'c6e8a0b2d4f7'
down_revision: Union[str, None] = 'b2d4f6a8c0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for columna in ("mail", "google_sub"):
        op.add_column("cuentapanel", sa.Column(columna, sqlmodel.sql.sqltypes.AutoString(),
                                               nullable=False, server_default=""))
        op.create_index(op.f(f"ix_cuentapanel_{columna}"), "cuentapanel", [columna], unique=False)


def downgrade() -> None:
    for columna in ("google_sub", "mail"):
        op.drop_index(op.f(f"ix_cuentapanel_{columna}"), table_name="cuentapanel")
        op.drop_column("cuentapanel", columna)

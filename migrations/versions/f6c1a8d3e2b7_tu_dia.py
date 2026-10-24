"""tu día en la portada del afiliado

Pedido «Tu día» (docs/chat/2026-10-24-pedido-tu-dia.md). `sindicato.tu_dia`:
qué rubros rotan y cada cuánto (NULL = los de tu_dia.py).
`cuentatrabajador.cumple_visto`: el año en que la persona ya vio su saludo de
cumpleaños. `cacheexterna`: lo que se pidió a los servicios de afuera (clima,
dólar oficial, centroides).

El módulo `tu_dia` reemplaza al widget de datos útiles que veían todos los
afiliados; para que nadie lo pierda al desplegar, se prende en los sindicatos
que ya existen (hoy, todos de demo y de pruebas). Los nuevos lo piden.

Revision ID: f6c1a8d3e2b7
Revises: e5b9f3a7c2d4
Create Date: 2026-10-24 01:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f6c1a8d3e2b7'
down_revision: Union[str, None] = 'e5b9f3a7c2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("sindicato", sa.Column("tu_dia", JSON_TIPO, nullable=True))
    op.add_column("cuentatrabajador", sa.Column("cumple_visto", sa.String(), nullable=False, server_default=""))
    op.create_table(
        "cacheexterna",
        sa.Column("clave", sa.String(), nullable=False),
        sa.Column("valor", JSON_TIPO, nullable=True),
        sa.Column("vence", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("clave"),
    )
    op.execute("""UPDATE sindicato SET modulos_habilitados = modulos_habilitados || '["tu_dia"]'::jsonb
                  WHERE NOT (modulos_habilitados ? 'tu_dia')""")


def downgrade() -> None:
    op.execute("UPDATE sindicato SET modulos_habilitados = modulos_habilitados - 'tu_dia'")
    op.drop_table("cacheexterna")
    op.drop_column("cuentatrabajador", "cumple_visto")
    op.drop_column("sindicato", "tu_dia")

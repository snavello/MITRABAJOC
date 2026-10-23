"""apariencia: dos modelos de diseño y la paleta

PLAN_TEMAS.md, bloque 1. La persona guarda en su cuenta el modelo que eligió
(`cuentatrabajador.tema`, `cuentapanel.tema`; vacío = vale el del sindicato) y
el sindicato elige el modelo por defecto de sus afiliados y de sus operadores
y la paleta. Las filas que ya existen arrancan en el modelo por defecto
(laguna) con los colores de Colm3na, que es lo que se acordó con SDN.

Revision ID: d4a8e2f6b1c3
Revises: c7e9a1d3f5b2
Create Date: 2026-10-23 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4a8e2f6b1c3'
down_revision: Union[str, None] = 'c7e9a1d3f5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cuentatrabajador", sa.Column("tema", sa.String(), nullable=False, server_default=""))
    op.add_column("cuentapanel", sa.Column("tema", sa.String(), nullable=False, server_default=""))
    op.add_column("sindicato", sa.Column("tema_afiliados", sa.String(), nullable=False, server_default="laguna"))
    op.add_column("sindicato", sa.Column("tema_panel", sa.String(), nullable=False, server_default="laguna"))
    op.add_column("sindicato", sa.Column("paleta_tema", sa.String(), nullable=False, server_default="colm3na"))


def downgrade() -> None:
    op.drop_column("sindicato", "paleta_tema")
    op.drop_column("sindicato", "tema_panel")
    op.drop_column("sindicato", "tema_afiliados")
    op.drop_column("cuentapanel", "tema")
    op.drop_column("cuentatrabajador", "tema")

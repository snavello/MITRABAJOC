"""biblioteca de fotos por modelo de diseño

PLAN_TEMAS.md, bloque 2. `fototema`: las fotos que carga plataforma para cada
modelo, guardadas ya normalizadas (gris, niveles y brillo parejos, webp).
`sindicato.fotos_portada`: la que eligió cada sindicato por modelo.

Revision ID: e5b9f3a7c2d4
Revises: d4a8e2f6b1c3
Create Date: 2026-10-23 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e5b9f3a7c2d4'
down_revision: Union[str, None] = 'd4a8e2f6b1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "fototema",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tema", sa.String(), nullable=False),
        sa.Column("datos", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("ancho", sa.Integer(), nullable=False),
        sa.Column("alto", sa.Integer(), nullable=False),
        sa.Column("foco_x", sa.Float(), nullable=False),
        sa.Column("foco_y", sa.Float(), nullable=False),
        sa.Column("descripcion", sa.String(), nullable=False),
        sa.Column("publicada", sa.Boolean(), nullable=False),
        sa.Column("todos_los_sindicatos", sa.Boolean(), nullable=False),
        sa.Column("sindicatos", JSON_TIPO, nullable=False),
        sa.Column("creada", sa.String(), nullable=False),
        sa.Column("subida_por", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fototema_tema"), "fototema", ["tema"], unique=False)
    op.add_column("sindicato", sa.Column("fotos_portada", JSON_TIPO, nullable=False,
                                         server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("sindicato", "fotos_portada")
    op.drop_index(op.f("ix_fototema_tema"), table_name="fototema")
    op.drop_table("fototema")

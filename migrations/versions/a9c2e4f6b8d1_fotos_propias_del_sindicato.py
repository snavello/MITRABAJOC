"""fotos de portada propias de cada sindicato

`fototema.sindicato_id` (2026-11-06, pedido de SDN): NULL = foto de la
biblioteca global de plataforma (todas las que ya existen, sin cambios de
comportamiento); con valor = foto PROPIA de ese sindicato, que sube su Super
Admin desde Apariencia y que solo ese sindicato lista, edita, borra y elige.

Revision ID: a9c2e4f6b8d1
Revises: d3e5f7a9b1c4
Create Date: 2026-11-06 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9c2e4f6b8d1'
down_revision: Union[str, None] = 'a5c7e9b1d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fototema", sa.Column("sindicato_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_fototema_sindicato_id", "fototema", "sindicato", ["sindicato_id"], ["id"])
    op.create_index("ix_fototema_sindicato_id", "fototema", ["sindicato_id"], unique=False)


def downgrade() -> None:
    # Las fotos propias no tienen a dónde volver: sin la columna no se sabría
    # de quién son y pasarían a la biblioteca global.
    op.execute("DELETE FROM fototema WHERE sindicato_id IS NOT NULL")
    op.drop_index("ix_fototema_sindicato_id", table_name="fototema")
    op.drop_constraint("fk_fototema_sindicato_id", "fototema", type_="foreignkey")
    op.drop_column("fototema", "sindicato_id")

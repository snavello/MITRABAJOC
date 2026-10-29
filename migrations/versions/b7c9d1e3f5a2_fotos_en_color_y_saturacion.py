"""fotos de los modelos en color y saturación por sindicato

Pedido de los sindicatos (2026-10-29): además de la normalizada en gris, la
biblioteca guarda la ORIGINAL en color (`fototema.datos_color`, NULL en las
fotos subidas antes, hasta que plataforma las vuelva a subir) y cada
sindicato elige por modelo cuánto color mostrar
(`sindicato.saturacion_fotos`: {"laguna": 0..100}, `fotos_tema.SATURACIONES`).

Revision ID: b7c9d1e3f5a2
Revises: a1b2c3d4e5f6
Create Date: 2026-10-29 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7c9d1e3f5a2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("fototema", sa.Column("datos_color", sa.LargeBinary(), nullable=True))
    op.add_column("fototema", sa.Column("mime_color", sa.String(), nullable=False,
                                        server_default="image/webp"))
    op.add_column("sindicato", sa.Column("saturacion_fotos", JSON_TIPO, nullable=False,
                                         server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("sindicato", "saturacion_fotos")
    op.drop_column("fototema", "mime_color")
    op.drop_column("fototema", "datos_color")

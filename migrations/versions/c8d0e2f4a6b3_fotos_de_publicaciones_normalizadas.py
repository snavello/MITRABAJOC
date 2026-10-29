"""fotos de noticias y beneficios normalizadas y su nivel de color

Lo mismo que b7c9d1e3f5a2 para las fotos de Noticias y Beneficios
(2026-10-29): se guarda la versión normalizada en gris de cada imagen
(`noticia.imagen1_norm` / `imagen2_norm`, `beneficio.imagen_norm`, NULL
hasta que se calcule: al subir o la primera vez que se pide) y cada
sindicato elige por modelo cuánto color mostrar en la portada
(`sindicato.saturacion_publicaciones`).

Revision ID: c8d0e2f4a6b3
Revises: b7c9d1e3f5a2
Create Date: 2026-10-29 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c8d0e2f4a6b3'
down_revision: Union[str, None] = 'b7c9d1e3f5a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("noticia", sa.Column("imagen1_norm", sa.LargeBinary(), nullable=True))
    op.add_column("noticia", sa.Column("imagen2_norm", sa.LargeBinary(), nullable=True))
    op.add_column("beneficio", sa.Column("imagen_norm", sa.LargeBinary(), nullable=True))
    op.add_column("sindicato", sa.Column("saturacion_publicaciones", JSON_TIPO, nullable=False,
                                         server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("sindicato", "saturacion_publicaciones")
    op.drop_column("beneficio", "imagen_norm")
    op.drop_column("noticia", "imagen2_norm")
    op.drop_column("noticia", "imagen1_norm")

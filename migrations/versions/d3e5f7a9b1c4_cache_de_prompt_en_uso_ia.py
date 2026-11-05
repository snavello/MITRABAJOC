"""tokens de caché de prompt en UsoIA

`usoia.tokens_cache_lectura` y `tokens_cache_escritura` (2026-11-05): lo que
la API devuelve en cache_read_input_tokens / cache_creation_input_tokens y NO
está incluido en `tokens_entrada`. 0 en todo lo anterior.

Revision ID: d3e5f7a9b1c4
Revises: c8d0e2f4a6b3
Create Date: 2026-11-05 03:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd3e5f7a9b1c4'
down_revision: Union[str, None] = 'c8d0e2f4a6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usoia", sa.Column("tokens_cache_lectura", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("usoia", sa.Column("tokens_cache_escritura", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("usoia", "tokens_cache_escritura")
    op.drop_column("usoia", "tokens_cache_lectura")

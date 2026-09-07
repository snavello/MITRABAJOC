"""recursos de la landing de entornos

Tabla Recurso (db.py): documentación del proyecto subida desde /entornos,
con los bytes del archivo y de la miniatura en la base (ver recursos.py).

Revision ID: 9c4e2f7a1b3d
Revises: b7c3d9e1f204
Create Date: 2026-09-07 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9c4e2f7a1b3d'
down_revision: Union[str, None] = 'b7c3d9e1f204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('recurso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('titulo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('descripcion', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('nombre_archivo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tamanio', sa.Integer(), nullable=False),
        sa.Column('archivo_datos', sa.LargeBinary(), nullable=True),
        sa.Column('miniatura_datos', sa.LargeBinary(), nullable=True),
        sa.Column('miniatura_mime', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('fragmento', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('creado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('recurso')

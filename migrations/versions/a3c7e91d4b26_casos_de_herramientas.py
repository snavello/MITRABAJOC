"""casos de herramientas: la Calculadora bancaria de /entornos guarda casos

Revision ID: a3c7e91d4b26
Revises: f2d3d0bcf179
Create Date: 2026-10-13 03:30:00

Tabla `casoherramienta`: cada caso que se guarda desde /entornos →
Herramientas (lo elegido, lo calculado, lo que decía el recibo real, las
diferencias y una nota), con un estado para revisarlo después. Las columnas
JSON van en JSONB, igual que db.JSON_TIPO.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import sqlmodel


revision = "a3c7e91d4b26"
down_revision = "f2d3d0bcf179"
branch_labels = None
depends_on = None

JSON_TIPO = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "casoherramienta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("herramienta", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("creado", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("quien", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("grilla", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("banco", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("nota", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("entrada", JSON_TIPO, nullable=False),
        sa.Column("esperado", JSON_TIPO, nullable=False),
        sa.Column("real", JSON_TIPO, nullable=False),
        sa.Column("diferencias", JSON_TIPO, nullable=False),
        sa.Column("distintos", sa.Integer(), nullable=False),
        sa.Column("estado", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("estado_cambiado", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("estado_quien", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_casoherramienta_herramienta", "casoherramienta", ["herramienta"])


def downgrade():
    op.drop_index("ix_casoherramienta_herramienta", table_name="casoherramienta")
    op.drop_table("casoherramienta")

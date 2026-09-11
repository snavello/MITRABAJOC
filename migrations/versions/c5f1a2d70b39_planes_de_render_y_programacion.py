"""Planes de Render: programación semanal y bitácora de cambios

Revision ID: c5f1a2d70b39
Revises: b7d4e1f92a06
Create Date: 2026-09-11

Dos tablas para la solapa "Planes" de /entornos: las reglas semanales que
sube y baja de plan sola, y el registro de todo cambio aplicado (a mano o
programado). Para las bases de datos Render no expone historial de planes,
así que sin esta bitácora no habría forma de saber por qué cambió el gasto.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "c5f1a2d70b39"
down_revision = "b7d4e1f92a06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planprogramado",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("destino", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("dias", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("hora", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("plan", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("instancias", sa.Integer(), nullable=True),
        sa.Column("ajustar_workers", sa.Boolean(), nullable=False),
        sa.Column("nota", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ultimo_disparo", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("creado_en", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cambioplan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cuando", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("origen", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("programado_id", sa.Integer(), nullable=True),
        sa.Column("destino", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("plan_anterior", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("plan_nuevo", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("detalle", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("cambioplan")
    op.drop_table("planprogramado")

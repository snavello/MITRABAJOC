"""fechas de las fases del plan de la mesa de implementacion

ImplEtapa.fecha_desde / fecha_hasta (texto ISO, NULL = sin fecha) y
ImplProyecto.fechas_acordadas (False = tentativas). Idempotente: las tablas
`impl*` pueden venir de un clonado con la marca de Alembic atrasada.

Revision ID: f7b1d3e5a9c2
Revises: e3a5c7d9b1f2
Create Date: 2026-11-26 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'f7b1d3e5a9c2'
down_revision: Union[str, None] = 'e3a5c7d9b1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columnas(tabla: str) -> set:
    insp = sa.inspect(op.get_bind())
    if tabla not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(tabla)}


def upgrade() -> None:
    cols = _columnas("impletapa")
    if cols:
        for nombre in ("fecha_desde", "fecha_hasta"):
            if nombre not in cols:
                op.add_column("impletapa", sa.Column(nombre, sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    if _columnas("implproyecto") and "fechas_acordadas" not in _columnas("implproyecto"):
        op.add_column("implproyecto", sa.Column("fechas_acordadas", sa.Boolean(), nullable=False,
                                                server_default=sa.false()))
        op.alter_column("implproyecto", "fechas_acordadas", server_default=None)


def downgrade() -> None:
    for tabla, nombre in (("impletapa", "fecha_desde"), ("impletapa", "fecha_hasta"),
                          ("implproyecto", "fechas_acordadas")):
        if nombre in _columnas(tabla):
            op.drop_column(tabla, nombre)

"""indices compuestos del dashboard

Todos los agregados del Panel Sindical filtran por sindicato_id + rango de
fecha (docs/DASHBOARD.md §2.2): índices compuestos que empiezan por
sindicato_id y siguen por la columna de fecha de cada fuente. El de
trabajador (sindicato_id, cuil) cubre el join a seccional que hacen casi
todas las consultas.

Revision ID: d4a78e3fc144
Revises: c3f67d2eb033
Create Date: 2026-08-29

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'd4a78e3fc144'
down_revision: Union[str, None] = 'c3f67d2eb033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICES = [
    ("ix_reciboverificado_sind_procesado", "reciboverificado", ["sindicato_id", "procesado_en"]),
    ("ix_tramite_sind_creado", "tramite", ["sindicato_id", "creado"]),
    ("ix_notificacion_sind_enviado", "notificacion", ["sindicato_id", "enviado_en"]),
    ("ix_consultaconvenio_sind_creado", "consultaconvenio", ["sindicato_id", "creado"]),
    ("ix_trabajador_sind_cuil", "trabajador", ["sindicato_id", "cuil"]),
]


def upgrade() -> None:
    for nombre, tabla, columnas in INDICES:
        op.create_index(nombre, tabla, columnas, unique=False)


def downgrade() -> None:
    for nombre, tabla, _ in INDICES:
        op.drop_index(nombre, table_name=tabla)

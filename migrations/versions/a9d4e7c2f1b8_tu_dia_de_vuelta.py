"""tu día de vuelta en todos los sindicatos

Guardar la ficha de un sindicato en /plataforma reemplazaba la lista entera de
módulos por las casillas del formulario; una pantalla abierta antes del
despliegue de «Tu día» no lo tenía y se lo sacó a La Bancaria en Pruebas. El
formulario ya no puede apagar un módulo que no mostró
(`main._modulos_tras_editar`); esto devuelve «Tu día» a donde se perdió. Tenía
horas de vida: nadie lo apagó a propósito.

Revision ID: a9d4e7c2f1b8
Revises: f6c1a8d3e2b7
Create Date: 2026-10-24 02:45:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a9d4e7c2f1b8'
down_revision: Union[str, None] = 'f6c1a8d3e2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""UPDATE sindicato SET modulos_habilitados = modulos_habilitados || '["tu_dia"]'::jsonb
                  WHERE NOT (modulos_habilitados ? 'tu_dia')""")


def downgrade() -> None:
    pass

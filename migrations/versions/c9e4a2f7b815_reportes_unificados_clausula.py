"""reportes unificados: cláusula de confidencialidad y contrato del sindicato

Revision ID: c9e4a2f7b815
Revises: b3c7e1d9a4f2
Create Date: 2026-09-24 00:00:00.000000

Dos cosas del mismo bloque:

1. Columnas nuevas en `sindicato`: la cláusula de confidencialidad (tilde,
   cuándo y quién la cargó) y el contrato firmado (bytes en la base). Nacen
   en falso/vacío: ningún sindicato queda aceptando nada que no firmó.

2. Las pestañas Reportes y Cotizantes del panel se unieron en una sola, así
   que la sección de permiso "cotizantes" desaparece del catálogo. Quien la
   tenía (por área o como agregado individual) pasa a tener "reportes", y un
   bloqueo de "cotizantes" pasa a bloquear "reportes": nadie gana ni pierde
   acceso a esos recibos con el cambio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'c9e4a2f7b815'
down_revision: Union[str, None] = 'b3c7e1d9a4f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sindicato', sa.Column('clausula_confidencialidad', sa.Boolean(),
                                         nullable=False, server_default=sa.false()))
    op.add_column('sindicato', sa.Column('clausula_aceptada_en', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default=''))
    op.add_column('sindicato', sa.Column('clausula_aceptada_por', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default=''))
    op.add_column('sindicato', sa.Column('contrato_datos', sa.LargeBinary(), nullable=True))
    op.add_column('sindicato', sa.Column('contrato_mime', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default=''))
    op.add_column('sindicato', sa.Column('contrato_nombre', sqlmodel.sql.sqltypes.AutoString(),
                                         nullable=False, server_default=''))

    # Permisos de área: "cotizantes" -> "reportes", sin duplicar la fila si
    # el área ya tenía las dos.
    op.execute("""
        INSERT INTO permisoarea (area_id, seccion)
        SELECT DISTINCT pa.area_id, 'reportes' FROM permisoarea pa
        WHERE pa.seccion = 'cotizantes'
          AND NOT EXISTS (SELECT 1 FROM permisoarea x
                          WHERE x.area_id = pa.area_id AND x.seccion = 'reportes')
    """)
    op.execute("DELETE FROM permisoarea WHERE seccion = 'cotizantes'")
    # Ajustes individuales: mismo criterio, respetando el tipo (agregar o
    # bloquear).
    op.execute("""
        INSERT INTO permisousuario (usuario_id, seccion, tipo)
        SELECT DISTINCT pu.usuario_id, 'reportes', pu.tipo FROM permisousuario pu
        WHERE pu.seccion = 'cotizantes'
          AND NOT EXISTS (SELECT 1 FROM permisousuario x
                          WHERE x.usuario_id = pu.usuario_id AND x.seccion = 'reportes'
                            AND x.tipo = pu.tipo)
    """)
    op.execute("DELETE FROM permisousuario WHERE seccion = 'cotizantes'")


def downgrade() -> None:
    # Los permisos no se re-separan: después de la unión no hay forma de
    # saber quién tenía solo una de las dos secciones.
    op.drop_column('sindicato', 'contrato_nombre')
    op.drop_column('sindicato', 'contrato_mime')
    op.drop_column('sindicato', 'contrato_datos')
    op.drop_column('sindicato', 'clausula_aceptada_por')
    op.drop_column('sindicato', 'clausula_aceptada_en')
    op.drop_column('sindicato', 'clausula_confidencialidad')

"""Costo y duración de cada llamada a la IA, y el modelo elegido por uso

Revision ID: e7b3c9a15f28
Revises: d2c8f04a6b31
Create Date: 2026-09-13

Dos cosas para la solapa "Uso de IA" de /plataforma:

1. `usoia` guarda ahora cuánto tardó la llamada y los dólares por millón de
   tokens que regían en ese momento. Se congela el PRECIO y no el costo ya
   multiplicado (precios_ia.py): el precio es el hecho del momento, el costo
   se deriva, y así actualizar la lista de precios no reescribe el gasto de
   los meses anteriores. Las filas viejas quedan en 0, que la pantalla lee
   como "no se congeló" y muestra estimado con los precios de hoy.

2. `configuracionplataforma` guarda qué modelo usa cada parte de la app.
   Vacío = el default escrito en el módulo (extractor.MODELO,
   rag.MODELO_RESPUESTA, asistente.MODELO); la columna solo existe para
   apartarse de él.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "e7b3c9a15f28"
down_revision = "d2c8f04a6b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default en las cinco: las dos tablas ya tienen filas y las
    # columnas son NOT NULL.
    with op.batch_alter_table("usoia") as batch_op:
        batch_op.add_column(sa.Column("duracion_ms", sa.Integer(), nullable=False,
                                       server_default="0"))
        batch_op.add_column(sa.Column("precio_entrada", sa.Float(), nullable=False,
                                       server_default="0"))
        batch_op.add_column(sa.Column("precio_salida", sa.Float(), nullable=False,
                                       server_default="0"))
    with op.batch_alter_table("configuracionplataforma") as batch_op:
        batch_op.add_column(sa.Column("modelo_recibos", sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=""))
        batch_op.add_column(sa.Column("modelo_convenio", sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=""))
        batch_op.add_column(sa.Column("modelo_asistente", sqlmodel.sql.sqltypes.AutoString(),
                                       nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("configuracionplataforma") as batch_op:
        batch_op.drop_column("modelo_asistente")
        batch_op.drop_column("modelo_convenio")
        batch_op.drop_column("modelo_recibos")
    with op.batch_alter_table("usoia") as batch_op:
        batch_op.drop_column("precio_salida")
        batch_op.drop_column("precio_entrada")
        batch_op.drop_column("duracion_ms")

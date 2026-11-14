"""codigos y relaciones de la mesa de implementacion

Revision ID: c4e7a9b2d6f1
Revises: 3be99db601b1
Create Date: 2026-11-14 16:00:00.000000

Códigos de tarjetas (PE0001...), archivos (AR000001) e hitos (HI0001), el
orden de cada mensaje en su tarjeta, los contadores por proyecto y prefijo y
la tabla de relaciones. Lo que ya exista se completa con un backfill
determinista: por id, dentro de cada proyecto.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'c4e7a9b2d6f1'
down_revision: Union[str, None] = '3be99db601b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Copia deliberada de implementacion.py: una migración no depende del código
# que después cambie.
PREFIJOS_TARJETA = {"pedido": "PE", "consulta": "CO", "entrega": "EN",
                    "aprobacion": "AP", "error": "ER", "aviso": "AV"}


def upgrade() -> None:
    # Idempotente: lo que ya existe no se vuelve a crear. Pasa cuando
    # `clonar_demo_a_pruebas.py` restaura un dump de la demo (sin las tablas
    # `impl*`, excluidas a propósito) sobre Pruebas: `alembic_version` vuelve a
    # una revisión vieja con las tablas de la mesa, ya completas, en su lugar.
    cx = op.get_bind()
    insp = sa.inspect(cx)
    tablas = set(insp.get_table_names())

    def columnas(tabla):
        return {c['name'] for c in insp.get_columns(tabla)} if tabla in tablas else set()

    contador_nuevo = 'implcontador' not in tablas
    if contador_nuevo:
        op.create_table(
            'implcontador',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proyecto_id', sa.Integer(), nullable=False),
            sa.Column('prefijo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('ultimo', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('proyecto_id', 'prefijo', name='uq_implcontador_proyecto_prefijo'),
        )
    if 'implrelacion' not in tablas:
        op.create_table(
            'implrelacion',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('proyecto_id', sa.Integer(), nullable=False),
            sa.Column('origen_tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('origen_id', sa.Integer(), nullable=False),
            sa.Column('destino_tipo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('destino_id', sa.Integer(), nullable=False),
            sa.Column('clase', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('solo_equipo', sa.Boolean(), nullable=False),
            sa.Column('creada_en', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('creada_por_lado', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('creada_por_id', sa.Integer(), nullable=False),
            sa.Column('creada_por_nombre', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('proyecto_id', 'origen_tipo', 'origen_id', 'destino_tipo', 'destino_id', 'clase',
                                name='uq_implrelacion_par'),
        )
        op.create_index('ix_implrelacion_origen', 'implrelacion', ['proyecto_id', 'origen_tipo', 'origen_id'])
        op.create_index('ix_implrelacion_destino', 'implrelacion', ['proyecto_id', 'destino_tipo', 'destino_id'])

    # Columnas nuevas: con default de servidor para las filas que ya hay.
    con_codigo = [t for t in ('impltarjeta', 'implarchivo', 'implhito') if 'codigo' not in columnas(t)]
    for tabla in con_codigo:
        op.add_column(tabla, sa.Column('codigo', sqlmodel.sql.sqltypes.AutoString(), nullable=False,
                                       server_default=''))
    con_orden = 'orden' not in columnas('implmensaje')
    if con_orden:
        op.add_column('implmensaje', sa.Column('orden', sa.Integer(), nullable=False, server_default='0'))

    # El backfill solo si las columnas se agregaron ahora (si ya estaban, ya tienen
    # sus códigos y sus contadores: repetirlo duplicaría filas de `implcontador`).
    if con_codigo or con_orden:
        _backfill(cx)

    for tabla in con_codigo:
        op.alter_column(tabla, 'codigo', server_default=None)
        op.create_index(op.f(f'ix_{tabla}_codigo'), tabla, ['codigo'], unique=False)
        op.create_unique_constraint(f'uq_{tabla}_proyecto_codigo', tabla, ['proyecto_id', 'codigo'])
    if con_orden:
        op.alter_column('implmensaje', 'orden', server_default=None)


def _backfill(cx) -> None:
    contadores = {}                      # (proyecto, prefijo) -> último

    def siguiente(proyecto, prefijo):
        n = contadores.get((proyecto, prefijo), 0) + 1
        contadores[(proyecto, prefijo)] = n
        return n

    for id_, proyecto, tipo in cx.execute(sa.text(
            "SELECT id, proyecto_id, tipo FROM impltarjeta ORDER BY proyecto_id, id")).all():
        prefijo = PREFIJOS_TARJETA.get(tipo, "PE")
        cx.execute(sa.text("UPDATE impltarjeta SET codigo = :c WHERE id = :i"),
                   {"c": f"{prefijo}{siguiente(proyecto, prefijo):04d}", "i": id_})
    for id_, proyecto in cx.execute(sa.text("SELECT id, proyecto_id FROM implarchivo ORDER BY proyecto_id, id")).all():
        cx.execute(sa.text("UPDATE implarchivo SET codigo = :c WHERE id = :i"),
                   {"c": f"AR{siguiente(proyecto, 'AR'):06d}", "i": id_})
    for id_, proyecto in cx.execute(sa.text("SELECT id, proyecto_id FROM implhito ORDER BY proyecto_id, id")).all():
        cx.execute(sa.text("UPDATE implhito SET codigo = :c WHERE id = :i"),
                   {"c": f"HI{siguiente(proyecto, 'HI'):04d}", "i": id_})
    cx.execute(sa.text(
        "UPDATE implmensaje m SET orden = x.rn FROM ("
        "SELECT id, row_number() OVER (PARTITION BY tarjeta_id ORDER BY id) AS rn FROM implmensaje) x "
        "WHERE m.id = x.id"))
    for (proyecto, prefijo), ultimo in sorted(contadores.items()):
        cx.execute(sa.text("INSERT INTO implcontador (proyecto_id, prefijo, ultimo) VALUES (:p, :f, :u)"),
                   {"p": proyecto, "f": prefijo, "u": ultimo})


def downgrade() -> None:
    for tabla in ('impltarjeta', 'implarchivo', 'implhito'):
        op.drop_constraint(f'uq_{tabla}_proyecto_codigo', tabla, type_='unique')
        op.drop_index(op.f(f'ix_{tabla}_codigo'), table_name=tabla)
        op.drop_column(tabla, 'codigo')
    op.drop_column('implmensaje', 'orden')
    op.drop_index('ix_implrelacion_destino', table_name='implrelacion')
    op.drop_index('ix_implrelacion_origen', table_name='implrelacion')
    op.drop_table('implrelacion')
    op.drop_table('implcontador')

"""columnas analiticas de reciboverificado (Panel Sindical)

Los agregados del dashboard se calculan en SQL; lo que estaba solo adentro
del JSON `detalle` (y la fecha en formato "dd/mm/AAAA HH:MM", no ordenable)
se persiste en columnas propias. El backfill parsea `detalle` fila por fila
con la MISMA lógica que dashboard.campos_analiticos -- replicada acá a
propósito: una migración no importa código de la app, tiene que poder correr
igual aunque la app cambie.

Reversible: downgrade borra las columnas; `detalle` y `fecha` quedan
intactos, así que no se pierde ningún dato original.

Revision ID: a1d45b0c9e11
Revises: 958e950a78f0
Create Date: 2026-08-29

"""
import json
import re
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = 'a1d45b0c9e11'
down_revision: Union[str, None] = '958e950a78f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _a_numero(valor):
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, str):
        limpio = re.sub(r"[^0-9,.\-]", "", valor).replace(".", "").replace(",", ".")
        try:
            return float(limpio)
        except ValueError:
            return None
    return None


def _fecha_iso_de_ar(valor):
    if not valor or not isinstance(valor, str):
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(valor.strip(), formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _procesado_en_de(fecha):
    """"dd/mm/AAAA HH:MM" (como guardaba main.py) -> "AAAA-MM-DD HH:MM"."""
    for formato in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime((fecha or "").strip(), formato).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None


def upgrade() -> None:
    with op.batch_alter_table('reciboverificado', schema=None) as batch_op:
        batch_op.add_column(sa.Column('procesado_en', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('cuit_empleador', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('categoria', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('formato', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('bruto', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('monto_diferencia', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('fecha_ultimo_deposito', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # ---- Backfill ----
    conn = op.get_bind()
    filas = conn.execute(sa.text(
        "SELECT id, fecha, detalle FROM reciboverificado")).fetchall()
    for fila in filas:
        rid, fecha, detalle = fila
        if isinstance(detalle, str):  # SQLite guarda el JSON como texto
            try:
                detalle = json.loads(detalle)
            except ValueError:
                detalle = {}
        detalle = detalle or {}
        recibo = detalle.get("recibo") or {}
        resultado = detalle.get("resultado") or {}

        monto = 0.0
        for fv in resultado.get("formulas_validadas") or []:
            if not fv.get("ok"):
                dif = _a_numero(fv.get("diferencia"))
                if dif is not None:
                    monto += abs(dif)
        deposito = recibo.get("ultimo_deposito")
        conn.execute(sa.text("""
            UPDATE reciboverificado SET
                procesado_en = :procesado_en, cuit_empleador = :cuit,
                categoria = :categoria, formato = :formato, bruto = :bruto,
                monto_diferencia = :monto, fecha_ultimo_deposito = :deposito
            WHERE id = :rid"""), {
            "rid": rid,
            "procesado_en": _procesado_en_de(fecha),
            "cuit": re.sub(r"[^0-9]", "", (recibo.get("empleador") or {}).get("cuit") or ""),
            "categoria": ((recibo.get("empleado") or {}).get("categoria") or "").strip(),
            "formato": recibo.get("formato") or "",
            "bruto": _a_numero((resultado.get("totales") or {}).get("ingresos")),
            "monto": round(monto, 2),
            "deposito": _fecha_iso_de_ar(deposito.get("fecha") if isinstance(deposito, dict) else None),
        })


def downgrade() -> None:
    with op.batch_alter_table('reciboverificado', schema=None) as batch_op:
        batch_op.drop_column('fecha_ultimo_deposito')
        batch_op.drop_column('monto_diferencia')
        batch_op.drop_column('bruto')
        batch_op.drop_column('formato')
        batch_op.drop_column('categoria')
        batch_op.drop_column('cuit_empleador')
        batch_op.drop_column('procesado_en')

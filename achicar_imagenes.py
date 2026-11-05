# -*- coding: utf-8 -*-
"""Achicar las imágenes que YA están guardadas en la base (plan SDN
2026-11-05: toda imagen se achica en el servidor; esto es lo de antes).

`imagenes.py` achica lo que se sube desde ahora; los logos, firmas, fotos,
imágenes de noticias y beneficios y adjuntos que ya estaban cargados pesan lo
que pesaban al subirse (el logo de La Bancaria, ~1 MB). Esta herramienta los
pasa por la MISMA función (`imagenes.achicar`) con el perfil de cada columna.

    python achicar_imagenes.py diagnostico
        Solo lectura. Por columna: filas con imagen, peso total y máximo, y
        cuántas superan el peso objetivo del perfil. Todo con octet_length en
        SQL: no se traen los bytes de las filas.

    python achicar_imagenes.py aplicar [--si --quien SDN] [--tabla T]
        SIN --si es un ensayo: lee cada fila candidata, calcula y dice
        «peso antes -> después», sin escribir. CON --si escribe (exige
        --quien). Una transacción POR FILA con su commit: un Job de Render no
        puede sostener una transacción con la base más de 30 s
        (idle_in_transaction_session_timeout). Cada fila queda en el log.

Reglas:
  - Solo se tocan las filas por ENCIMA del peso objetivo de su perfil.
  - Solo se escribe si el resultado pesa menos que el original (un 10 % como
    mínimo): una segunda corrida no vuelve a tocar nada.
  - SVG se deja tal cual; lo que `ImagenInvalida` rechaza se deja como está y
    se lista al final. Los adjuntos que no son imagen (PDF) no se tocan.
  - Noticias y Beneficios: se regenera la versión normalizada (`*_norm`) a
    partir de la achicada con `fotos_tema.normalizar_imagen`.
  - Sin tabla de trazas (evita una migración): el log del Job es la traza, y
    el respaldo es el backup diario de Render + la recuperación a un punto en
    el tiempo (ver DESPLIEGUE_RENDER.md, «Achicar las imágenes ya cargadas»).
Importable: `diagnosticar()`, `aplicar()`; los tests los llaman sin subprocess.
"""
import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional

import sqlalchemy as sa

import db

KB = 1024
GANANCIA_MINIMA = 0.90          # se escribe solo si el nuevo pesa <= 90 % del viejo


@dataclass(frozen=True)
class Col:
    tabla: str
    datos: str
    mime: str
    perfil: str
    objetivo: int                       # bytes
    norm: Optional[str] = None          # columna normalizada a regenerar
    solo_imagenes: bool = False         # adjuntos: filtrar por mime image/*

    @property
    def nombre(self) -> str:
        return f"{self.tabla}.{self.datos}"


COLUMNAS = [
    Col("sindicato", "logo_datos", "logo_mime", "logo", 100 * KB),
    Col("sindicato", "firma_datos", "firma_mime", "firma", 150 * KB),
    Col("configuracionplataforma", "logo_datos", "logo_mime", "logo", 100 * KB),
    Col("configuracionplataforma", "logo_datos_oscuro", "logo_mime_oscuro", "logo", 100 * KB),
    Col("cuentatrabajador", "foto_datos", "foto_mime", "perfil", 100 * KB),
    Col("cuentaempleador", "foto_datos", "foto_mime", "perfil", 100 * KB),
    Col("noticia", "imagen1_datos", "imagen1_mime", "publicacion", 400 * KB, norm="imagen1_norm"),
    Col("noticia", "imagen2_datos", "imagen2_mime", "publicacion", 400 * KB, norm="imagen2_norm"),
    Col("beneficio", "imagen_datos", "imagen_mime", "publicacion", 400 * KB, norm="imagen_norm"),
    Col("notificacion", "adjunto_datos", "adjunto_mime", "adjunto", 400 * KB, solo_imagenes=True),
    Col("notificacionempleador", "adjunto_datos", "adjunto_mime", "adjunto", 400 * KB, solo_imagenes=True),
    Col("notatramite", "adjunto_datos", "adjunto_mime", "adjunto", 400 * KB, solo_imagenes=True),
    Col("notatramiteempleador", "adjunto_datos", "adjunto_mime", "adjunto", 400 * KB, solo_imagenes=True),
    Col("respuestatramite", "archivo_datos", "archivo_mime", "adjunto", 400 * KB, solo_imagenes=True),
    Col("respuestatramiteempleador", "archivo_datos", "archivo_mime", "adjunto", 400 * KB, solo_imagenes=True),
]


def _filtro(c: Col) -> str:
    f = f"{c.datos} IS NOT NULL AND octet_length({c.datos}) > 0"
    if c.solo_imagenes:
        f += f" AND lower(coalesce({c.mime}, '')) LIKE 'image/%'"
    return f


def _mb(n) -> str:
    return f"{(n or 0) / (KB * KB):.2f} MB"


def _kb(n) -> str:
    return f"{(n or 0) / KB:.0f} KB"


def diagnosticar(salida=print, engine=None) -> list:
    """Solo lectura. Devuelve una lista de dicts, uno por columna."""
    engine = engine or db.engine
    filas = []
    with engine.connect() as cx:
        for c in COLUMNAS:
            r = cx.execute(sa.text(
                f"SELECT count(*), coalesce(sum(octet_length({c.datos})), 0), "
                f"coalesce(max(octet_length({c.datos})), 0), "
                f"count(*) FILTER (WHERE octet_length({c.datos}) > :obj) "
                f"FROM {c.tabla} WHERE {_filtro(c)}"), {"obj": c.objetivo}).one()
            filas.append({"columna": c.nombre, "perfil": c.perfil, "objetivo": c.objetivo,
                          "filas": r[0], "total": int(r[1]), "maximo": int(r[2]), "sobre_objetivo": r[3]})
    salida(f"{'columna':46} {'perfil':12} {'filas':>6} {'total':>10} {'máximo':>10} {'> objetivo':>10}")
    for f in filas:
        salida(f"{f['columna']:46} {f['perfil']:12} {f['filas']:>6} {_mb(f['total']):>10} "
               f"{_kb(f['maximo']):>10} {f['sobre_objetivo']:>6} (>{f['objetivo'] // KB} KB)")
    salida(f"TOTAL: {_mb(sum(f['total'] for f in filas))} en {sum(f['filas'] for f in filas)} imágenes; "
           f"{sum(f['sobre_objetivo'] for f in filas)} sobre su objetivo.")
    return filas


def aplicar(escribir: bool = False, tabla: str = "", salida=print, engine=None) -> dict:
    """Ensayo (escribir=False) o corrida real. Devuelve el resumen."""
    import fotos_tema
    import imagenes
    engine = engine or db.engine
    res = {"cambiadas": 0, "sin_ganancia": 0, "rechazadas": [], "bytes_antes": 0, "bytes_despues": 0}
    for c in COLUMNAS:
        if tabla and tabla not in (c.tabla, c.nombre):
            continue
        with engine.connect() as cx:
            ids = [r[0] for r in cx.execute(sa.text(
                f"SELECT id FROM {c.tabla} WHERE {_filtro(c)} AND octet_length({c.datos}) > :obj "
                f"ORDER BY id"), {"obj": c.objetivo})]
        salida(f"\n== {c.nombre} (perfil {c.perfil}, objetivo {c.objetivo // KB} KB): {len(ids)} filas")
        for fid in ids:
            with engine.connect() as cx:        # lectura corta, sin transacción abierta después
                datos, mime = cx.execute(sa.text(
                    f"SELECT {c.datos}, coalesce({c.mime}, '') FROM {c.tabla} WHERE id = :i"),
                    {"i": fid}).one()
            datos = bytes(datos)
            if (mime or "").lower().startswith("image/svg"):
                salida(f"  id {fid}: SVG, se deja tal cual")
                continue
            try:
                r = imagenes.achicar(datos, c.perfil, nombre=f"{c.nombre}#{fid}")
            except imagenes.ImagenInvalida as e:
                res["rechazadas"].append((c.nombre, fid, str(e)))
                salida(f"  id {fid}: RECHAZADA ({e}); se deja como está")
                continue
            nuevo = bytes(r["datos"])
            if len(nuevo) > len(datos) * GANANCIA_MINIMA:
                res["sin_ganancia"] += 1
                salida(f"  id {fid}: {_kb(len(datos))} -> {_kb(len(nuevo))} sin ganancia suficiente, no se toca")
                continue
            sets = {c.datos: nuevo, c.mime: r["mime"]}
            if c.norm:
                try:
                    sets[c.norm] = fotos_tema.normalizar_imagen(nuevo)["datos"]
                except fotos_tema.FotoInvalida:
                    sets[c.norm] = None         # se recalcula al pedirla (db.imagen_normalizada)
            res["bytes_antes"] += len(datos)
            res["bytes_despues"] += len(nuevo)
            salida(f"  id {fid}: {_kb(len(datos))} -> {_kb(len(nuevo))} "
                   f"({r.get('ancho')}x{r.get('alto')}, {r['mime']})" + ("" if escribir else "  [ensayo]"))
            if escribir:
                cols = ", ".join(f"{k} = :{k}" for k in sets)
                with engine.begin() as cx:      # una transacción por fila, con su commit
                    cx.execute(sa.text(f"UPDATE {c.tabla} SET {cols} WHERE id = :_id"), {**sets, "_id": fid})
            res["cambiadas"] += 1
    salida(f"\nRESUMEN ({'ESCRITO' if escribir else 'ENSAYO, nada escrito'}): {res['cambiadas']} imágenes, "
           f"{_mb(res['bytes_antes'])} -> {_mb(res['bytes_despues'])}; "
           f"{res['sin_ganancia']} sin ganancia; {len(res['rechazadas'])} rechazadas.")
    for t, i, m in res["rechazadas"]:
        salida(f"  RECHAZADA {t} id {i}: {m}")
    return res


def _cabecera() -> None:
    u = db.engine.url
    print(f"Base: {u.host}/{u.database}  ENTORNO={os.getenv('ENTORNO', '(sin definir)')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("diagnostico", help="solo lectura")
    a = sub.add_parser("aplicar", help="ensayo; con --si escribe")
    a.add_argument("--si", action="store_true")
    a.add_argument("--quien", default="")
    a.add_argument("--tabla", default="", help="limitar a una tabla o tabla.columna")
    args = ap.parse_args(argv)
    _cabecera()
    if args.cmd == "diagnostico":
        diagnosticar()
        return 0
    if args.si and not args.quien:
        print("ABORTADO: con --si hace falta --quien <iniciales>.")
        return 2
    if args.si:
        print(f"Quien: {args.quien}")
    aplicar(escribir=args.si, tabla=args.tabla)
    if not args.si:
        print("Para aplicarlo de verdad: el mismo comando con --si --quien <iniciales>.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

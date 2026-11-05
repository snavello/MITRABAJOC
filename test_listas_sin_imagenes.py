# -*- coding: utf-8 -*-
"""Las listas de noticias y beneficios NO traen las imágenes de la base.

La portada del afiliado y Novedades piden la lista entera del sindicato en
cada pedido; si la consulta trae los bytes de cada foto (original + copia
normalizada), el tráfico con la base se multiplica por la cantidad de filas.
Medido el 2026-11-05 en Pruebas con La Bancaria (37 noticias, 3 MB de fotos):
con 200 personas navegando, la base se pasaba el tiempo mandando bytes que
nadie usaba y las pantallas tardaban 7 s. Este test captura el SQL que
ejecuta cada lista y falla si una columna de bytes viaja en el SELECT."""
import re

from sqlalchemy import event
from sqlmodel import Session

import db
from db import Beneficio, Noticia, Sindicato

BYTES_NOTICIA = {"imagen1_datos", "imagen2_datos", "imagen1_norm", "imagen2_norm"}
BYTES_BENEFICIO = {"imagen_datos", "imagen_norm"}


def _sindicato(nombre):
    with Session(db.engine) as s:
        sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"))
        s.add(sind)
        s.commit()
        return sind.id


def _sql_capturado(funcion, *args):
    frases = []

    def _oir(conn, cursor, statement, parameters, context, executemany):
        frases.append(statement)
    event.listen(db.engine, "before_cursor_execute", _oir)
    try:
        resultado = funcion(*args)
    finally:
        event.remove(db.engine, "before_cursor_execute", _oir)
    return resultado, frases


def _columnas_seleccionadas(sql: str) -> set:
    """Nombres de columna que viajan en el SELECT (antes del FROM), sin
    contar las que solo aparecen adentro de octet_length(...)."""
    sql = re.sub(r"\s+", " ", sql)
    cabeza = sql.split(" FROM ", 1)[0]
    cabeza = re.sub(r"octet_length\([^)]*\)", "", cabeza)
    return set(re.findall(r"\.(\w+)", cabeza))


def _columnas(frases, tabla):
    return set().union(set(), *(_columnas_seleccionadas(f) for f in frases if tabla in f))


def test_lista_de_noticias_no_trae_bytes():
    sid = _sindicato("Sin fotos A")
    with Session(db.engine) as s:
        s.add(Noticia(sindicato_id=sid, titulo="Con foto", fecha_desde="2020-01-01", fecha_hasta="2099-12-31",
                      imagen1_datos=b"\x89PNG" + b"x" * 5000, imagen1_mime="image/png"))
        s.add(Noticia(sindicato_id=sid, titulo="Sin foto", fecha_desde="2020-01-01", fecha_hasta="2099-12-31"))
        s.commit()
    lista, frases = _sql_capturado(db.noticias_del_sindicato, sid)
    por_titulo = {n["titulo"]: n for n in lista}
    assert por_titulo["Con foto"]["tiene_imagen1"] is True
    assert por_titulo["Con foto"]["tiene_imagen2"] is False
    assert por_titulo["Sin foto"]["tiene_imagen1"] is False
    assert not _columnas(frases, "noticia") & BYTES_NOTICIA, _columnas(frases, "noticia")
    # Las vigentes salen de la misma lista: tampoco cargan nada después.
    vigentes, frases2 = _sql_capturado(db.noticias_vigentes, sid)
    assert {n["titulo"] for n in vigentes} == {"Con foto", "Sin foto"}
    assert not _columnas(frases2, "noticia") & BYTES_NOTICIA


def test_lista_de_beneficios_no_trae_bytes():
    sid = _sindicato("Sin fotos B")
    with Session(db.engine) as s:
        s.add(Beneficio(sindicato_id=sid, rubro="Con foto", descripcion="d", fecha_desde="2020-01-01",
                        fecha_hasta="2099-12-31", imagen_datos=b"\x89PNG" + b"y" * 5000, imagen_mime="image/png"))
        s.add(Beneficio(sindicato_id=sid, rubro="Sin foto", descripcion="d", fecha_desde="2020-01-01",
                        fecha_hasta="2099-12-31"))
        s.commit()
    lista, frases = _sql_capturado(db.beneficios_del_sindicato, sid)
    por_rubro = {b["rubro"]: b for b in lista}
    assert por_rubro["Con foto"]["tiene_imagen"] is True
    assert por_rubro["Sin foto"]["tiene_imagen"] is False
    assert not _columnas(frases, "beneficio") & BYTES_BENEFICIO, _columnas(frases, "beneficio")
    assert len(db.beneficios_vigentes(sid)) == 2


def test_la_noticia_sola_sigue_sabiendo_si_tiene_imagen():
    sid = _sindicato("Sin fotos C")
    with Session(db.engine) as s:
        n = Noticia(sindicato_id=sid, titulo="Una", fecha_desde="2020-01-01", fecha_hasta="2099-12-31",
                    imagen1_datos=b"abc", imagen1_mime="image/png")
        s.add(n)
        s.commit()
        nid = n.id
    assert db.noticia_por_id(nid)["tiene_imagen1"] is True

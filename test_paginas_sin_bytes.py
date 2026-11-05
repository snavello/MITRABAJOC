# -*- coding: utf-8 -*-
"""Ninguna pantalla de uso diario trae columnas de bytes de la base.

El logo de La Bancaria pesa 1 MB y la fila del sindicato (logo + firma +
contrato, 1,2 MB) se leía entera en CADA pantalla, tres veces por portada;
la foto de perfil se traía para saber si existía; las noticias y beneficios
venían con sus imágenes. Medido el 2026-11-05 en Pruebas con 200 personas
navegando: la base se pasaba el tiempo mandando bytes que nadie usaba
(PLAN_PRUEBAS_BANCARIA.md, sección R). Las imágenes se sirven por sus
rutas (/logo/{id}, /app/foto-perfil, /noticia-imagen/...), de a una.

Este test captura TODO el SQL que ejecuta cada pantalla y falla si una
columna de bytes viaja en un SELECT (contar su largo con octet_length sí
vale: es cómo se pregunta por una imagen sin traerla)."""
import re

from fastapi.testclient import TestClient
from sqlalchemy import LargeBinary, event
from sqlmodel import Session, SQLModel

import auth
import db
import main
from db import Beneficio, Noticia, Sindicato, Trabajador, UsuarioSindicato
from modulos import MODULOS_INICIALES

CUIL = "20111111119"
GRANDE = b"\x89PNG" + b"\x00" * (1024 * 1024)

db.crear_tablas()
with db.get_session() as s:
    sind = Sindicato(nombre="Logo Pesado", slug="logo-pesado", modulos_habilitados=sorted(set(MODULOS_INICIALES) | {"notificaciones", "noticias", "beneficios", "tu_dia", "dashboard", "tramites"}),
                     logo_datos=GRANDE, logo_mime="image/png", firma_datos=GRANDE[:50000], firma_mime="image/png",
                     contrato_datos=GRANDE[:200000], contrato_mime="application/pdf")
    s.add(sind); s.commit(); s.refresh(sind); SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Admin",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID, cuil=CUIL, activo=True, registrado=True))
    db.guardar_datos_personales(s, CUIL, nombre="Juan")
    s.add(Noticia(sindicato_id=SID, titulo="Con foto", fecha_desde="2020-01-01", fecha_hasta="2099-12-31",
                  imagen1_datos=GRANDE[:300000], imagen1_mime="image/png", imagen2_datos=GRANDE[:300000],
                  imagen2_mime="image/png"))
    s.add(Beneficio(sindicato_id=SID, rubro="Descuento", descripcion="d", fecha_desde="2020-01-01",
                    fecha_hasta="2099-12-31", imagen_datos=GRANDE[:300000], imagen_mime="image/png"))
    s.commit()
db.guardar_foto_trabajador(CUIL, GRANDE[:100000], "image/jpeg")
db.set_marca_plataforma("#152238", "#1a7a6b", "#b23a2e", logo_datos=GRANDE[:200000], logo_mime="image/png",
                        logo_flag="si", logo_datos_oscuro=GRANDE[:200000], logo_mime_oscuro="image/png",
                        logo_oscuro_flag="si")

COLUMNAS_BYTES = {c.key for m in SQLModel.metadata.tables.values() for c in m.columns
                  if isinstance(c.type, LargeBinary)}

trab = TestClient(main.app)
trab.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=CUIL))
trab.cookies.set("cuil_trab", CUIL)
admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})


def _sql_de(cliente, ruta):
    frases = []

    def _oir(conn, cursor, statement, parameters, context, executemany):
        frases.append(statement)
    event.listen(db.engine, "before_cursor_execute", _oir)
    try:
        r = cliente.get(ruta)
    finally:
        event.remove(db.engine, "before_cursor_execute", _oir)
    return r, frases


def _bytes_seleccionados(sql: str) -> set:
    sql = re.sub(r"\s+", " ", sql)
    cabeza = sql.split(" FROM ", 1)[0]
    cabeza = re.sub(r"octet_length\([^)]*\)", "", cabeza)
    cabeza = re.sub(r"\.\w+ IS (NOT )?NULL", "", cabeza)   # «¿tiene foto?» sin traerla
    return set(re.findall(r"\.(\w+)", cabeza)) & COLUMNAS_BYTES


def _verificar(cliente, ruta, esperado=(200,)):
    r, frases = _sql_de(cliente, ruta)
    assert r.status_code in esperado, (ruta, r.status_code)
    culpables = {(c, f[:120]) for f in frases if f.lstrip().upper().startswith("SELECT")
                 for c in _bytes_seleccionados(f)}
    assert not culpables, (ruta, sorted(culpables))
    assert len(frases) > 0, ruta


def test_portada_del_afiliado():
    _verificar(trab, "/app/inicio")


def test_tu_recibo():
    _verificar(trab, "/app")


def test_novedades():
    _verificar(trab, "/app/notificaciones")


def test_tu_dia():
    _verificar(trab, "/api/tu-dia", esperado=(200, 403))


def test_portada_y_panel_del_sindicato():
    _verificar(admin, "/admin/inicio")
    _verificar(admin, "/admin")


def test_el_sello_del_logo_sigue_siendo_su_largo():
    marca = db.marca_sindicato(SID)
    assert marca["logo_v"] == len(GRANDE)
    assert marca["firma_v"] == 50000
    assert db.tiene_foto_trabajador(CUIL) is True
    assert db.tiene_foto_trabajador("20000000001") is False

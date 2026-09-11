"""Responder y cambiar estado, un solo acto -- Fase 5 (decisión N9).

El problema que resuelve es de PERCEPCIÓN, no de datos: antes eran dos rutas
y cada una escribía su línea en el log, así que una sola respuesta del
sindicato aparecía DOS VECES en el chat del afiliado.

Por eso la mitad de estos tests miran el log y el chat, no el estado: que el
estado cambie ya funcionaba. Lo que había que arreglar es que se viera una
sola vez.

Correr con: python -m pytest test_areas_estado.py -q
"""
import json
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import (Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea,
                Trabajador, TipoTramite, Tramite, CampoTramite)
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Estado", slug="uom-estado", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    sec = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(sec); s.commit(); s.refresh(sec)
    SEC = sec.id
    mesa = Area(sindicato_id=SID, seccional_id=SEC, nombre="Mesa de Entradas")
    s.add(mesa); s.commit(); s.refresh(mesa)
    AREA = mesa.id
    s.add(PermisoArea(area_id=AREA, seccion="tramites_recibidos"))
    s.add(Trabajador(sindicato_id=SID, cuil="20300000001", nombre="Afiliado",
                     seccional_id=SEC, activo=True, registrado=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", cuil="20111111110",
                           nombre="Marta", clave_hash=auth.hashear_clave("marta"),
                           debe_cambiar_clave=False, es_super_admin=True, seccional_id=SEC))
    s.commit()


def _admin():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "20111111110", "clave": "marta"},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def _trab():
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", "20300000001")
    c.cookies.set("sind_elegido", str(SID))
    return c


def _tramite_nuevo(codigo):
    c = _admin()
    r = c.post("/admin/tramite-tipo", data={
        "titulo": codigo, "codigo": codigo,
        "campos_json": json.dumps([{"etiqueta": "Motivo", "tipo_dato": "texto",
                                    "obligatorio": True}]),
        "area_destino_default_id": str(AREA)}, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        tipo = s.exec(select(TipoTramite).where(TipoTramite.codigo == codigo)).first()
        campo = s.exec(select(CampoTramite).where(
            CampoTramite.tipo_tramite_id == tipo.id)).first()
    r = _trab().post("/api/tramite", data={"tipo_tramite_id": str(tipo.id),
                                           f"campo_{campo.id}": "porque sí"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- No hay estado sin mensaje ----------

def test_la_ruta_de_estado_suelto_ya_no_existe():
    """La prueba más directa de la decisión: no quedó ninguna forma de mover
    el estado por afuera del mensaje."""
    rutas = {getattr(r, "path", "") for r in main.app.routes}
    assert "/admin/tramite/{tramite_id}/estado" not in rutas
    assert "/admin/tramite/{tramite_id}/nota" in rutas
    # Y tampoco quedó declarada en el registro de permisos.
    assert "/admin/tramite/{tramite_id}/estado" not in main.PERMISOS_RUTAS
    print("OK  test_la_ruta_de_estado_suelto_ya_no_existe")


def test_responder_y_estado_viajan_juntos():
    tr = _tramite_nuevo("F01")
    r = _admin().post(f"/admin/tramite/{tr}/nota",
                      data={"texto": "lo estamos viendo", "estado": "en_tratamiento"})
    assert r.status_code == 200
    d = db.tramite_detalle(tr)
    assert d["estado"] == "en_tratamiento"
    assert d["notas"][-1]["texto"] == "lo estamos viendo"
    assert d["notas"][-1]["estado_nuevo"] == "en_tratamiento"
    print("OK  test_responder_y_estado_viajan_juntos")


def test_un_acto_deja_UN_movimiento_en_el_chat():
    """El corazón de la fase. Antes: dos eventos (nota_admin +
    cambio_estado) por una sola respuesta."""
    tr = _tramite_nuevo("F02")
    antes = len(db.tramite_detalle(tr)["log"])
    _admin().post(f"/admin/tramite/{tr}/nota",
                  data={"texto": "necesitamos el recibo", "estado": "espera_info"})
    log = db.tramite_detalle(tr)["log"]
    assert len(log) == antes + 1, [l["evento"] for l in log]
    assert not any(l["evento"] == "cambio_estado" for l in log)
    ultimo = log[-1]
    assert ultimo["evento"] == "nota_admin"
    # El renglón lleva las dos cosas: qué se dijo y a qué estado pasó.
    assert "necesitamos el recibo" in ultimo["detalle"]
    assert "A la espera de información del afiliado" in ultimo["detalle"]
    print("OK  test_un_acto_deja_UN_movimiento_en_el_chat")


def test_responder_sin_mover_el_estado_sigue_siendo_valido():
    """Contestar sin cambiar de estado es un caso normal, no un borde."""
    tr = _tramite_nuevo("F03")
    _admin().post(f"/admin/tramite/{tr}/nota", data={"texto": "seguimos con esto"})
    d = db.tramite_detalle(tr)
    assert d["estado"] == "iniciado"
    assert d["notas"][-1]["estado_nuevo"] == ""
    assert "Estado:" not in d["log"][-1]["detalle"]
    print("OK  test_responder_sin_mover_el_estado_sigue_siendo_valido")


def test_mandar_el_mismo_estado_no_ensucia_el_hilo():
    """Si el <select> viene con el estado actual (que es lo que hace la
    pantalla), no tiene que registrar un cambio que no ocurrió."""
    tr = _tramite_nuevo("F04")
    _admin().post(f"/admin/tramite/{tr}/nota", data={"texto": "hola", "estado": "iniciado"})
    d = db.tramite_detalle(tr)
    assert d["notas"][-1]["estado_nuevo"] == "", "no cambió nada, no marca nada"
    assert "Estado:" not in d["log"][-1]["detalle"]
    print("OK  test_mandar_el_mismo_estado_no_ensucia_el_hilo")


def test_un_estado_invalido_no_pierde_el_mensaje():
    """Escribir es lo que el admin quiso hacer: perderle el mensaje por un
    valor mal formado sería peor que no mover el estado."""
    tr = _tramite_nuevo("F05")
    r = _admin().post(f"/admin/tramite/{tr}/nota",
                      data={"texto": "igual te escribo", "estado": "inventado"})
    assert r.status_code == 200
    d = db.tramite_detalle(tr)
    assert d["estado"] == "iniciado"
    assert d["notas"][-1]["texto"] == "igual te escribo"
    assert d["notas"][-1]["estado_nuevo"] == ""
    print("OK  test_un_estado_invalido_no_pierde_el_mensaje")


def test_terminar_es_responder():
    tr = _tramite_nuevo("F06")
    _admin().post(f"/admin/tramite/{tr}/nota",
                  data={"texto": "resuelto, te transferimos", "estado": "terminado"})
    d = db.tramite_detalle(tr)
    assert d["estado"] == "terminado"
    with Session(db.engine) as s:
        assert s.get(Tramite, tr).resuelto_en, "se registra cuándo se cerró"
    # Y terminado sigue bloqueando todo.
    r = _admin().post(f"/admin/tramite/{tr}/nota",
                      data={"texto": "otra cosa", "estado": "en_tratamiento"})
    assert r.status_code == 400
    assert db.tramite_detalle(tr)["estado"] == "terminado"
    print("OK  test_terminar_es_responder")


# ---------- Lo que ve el trabajador ----------

def test_el_trabajador_ve_un_solo_movimiento_con_el_estado_adentro():
    tr = _tramite_nuevo("F07")
    _admin().post(f"/admin/tramite/{tr}/nota",
                  data={"texto": "ya lo derivamos", "estado": "en_tratamiento"})
    with Session(db.engine) as s:
        numero = s.get(Tramite, tr).numero_expediente
    d = _trab().get(f"/api/tramite/{numero}").json()
    del_sindicato = [n for n in d["notas"] if n["autor"] == "admin"]
    assert len(del_sindicato) == 1
    assert del_sindicato[0]["estado_nuevo_label"] == "En tratamiento"
    assert not any(l["evento"] == "cambio_estado" for l in d["log"])
    print("OK  test_el_trabajador_ve_un_solo_movimiento_con_el_estado_adentro")


def test_el_chat_de_las_dos_apps_pinta_el_estado_en_la_burbuja():
    """Test de PLANTILLA: el estado viaja en el JSON, pero si el chat no lo
    dibuja el afiliado no se entera de que su trámite avanzó. Es el mismo
    tipo de hueco que en la Fase 4 dejó el pase fuera del chat."""
    for archivo in ("templates/admin.html", "templates/trabajador.html"):
        with open(archivo, encoding="utf-8") as f:
            html = f.read()
        assert "htmlEstadoDeMensaje" in html, f"{archivo} no pinta el estado del mensaje"
        assert "estado_nuevo_label" in html, archivo
    print("OK  test_el_chat_de_las_dos_apps_pinta_el_estado_en_la_burbuja")


if __name__ == "__main__":
    test_la_ruta_de_estado_suelto_ya_no_existe()
    test_responder_y_estado_viajan_juntos()
    test_un_acto_deja_UN_movimiento_en_el_chat()
    test_responder_sin_mover_el_estado_sigue_siendo_valido()
    test_mandar_el_mismo_estado_no_ensucia_el_hilo()
    test_un_estado_invalido_no_pierde_el_mensaje()
    test_terminar_es_responder()
    test_el_trabajador_ve_un_solo_movimiento_con_el_estado_adentro()
    test_el_chat_de_las_dos_apps_pinta_el_estado_en_la_burbuja()
    print("\nTodos los tests de N9 pasaron.")

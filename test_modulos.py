"""Sistema de módulos habilitables por sindicato (Fase 1 del plan de
Módulos + Notificaciones + Trámites): alta/edición desde /plataforma,
grandfathering, y que portada/trabajador/admin oculten tarjetas/pestañas
según el catálogo -- más el bloqueo real en el backend (403) aunque se
arme el request a mano sin pasar por la UI.

Correr con: .venv/Scripts/python.exe test_modulos.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador
from modulos import MODULOS, MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

with db.get_session() as s:
    full = Sindicato(nombre="UOM Modulos Full", slug="uom-modulos-full",
                      color_base="#0f1b2d", modulos_habilitados=list(MODULOS_INICIALES))
    solo_noticias = Sindicato(nombre="Fega Solo Noticias", slug="fega-solo-noticias",
                               color_base="#0d2027", modulos_habilitados=["noticias"])
    solo_recibos = Sindicato(nombre="Sind Solo Recibos", slug="sind-solo-recibos",
                              color_base="#111111", modulos_habilitados=["recibos"])
    s.add(full); s.add(solo_noticias); s.add(solo_recibos)
    s.commit(); s.refresh(full); s.refresh(solo_noticias); s.refresh(solo_recibos)
    SID_FULL, SID_NOTICIAS, SID_RECIBOS = full.id, solo_noticias.id, solo_recibos.id

    s.add(UsuarioSindicato(sindicato_id=SID_FULL, usuario="20111111110", nombre="Admin Full",
                            clave_hash=auth.hashear_clave("full-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_NOTICIAS, usuario="20222222220", nombre="Admin Noticias",
                            clave_hash=auth.hashear_clave("noticias-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_RECIBOS, usuario="20333333330", nombre="Admin Recibos",
                            clave_hash=auth.hashear_clave("recibos-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(Trabajador(sindicato_id=SID_FULL, cuil="20111111119", nombre="Juan Full",
                      activo=True, registrado=True))
    s.add(Trabajador(sindicato_id=SID_NOTICIAS, cuil="20444444440", nombre="Ana Noticias",
                      activo=True, registrado=True))
    s.commit()

plataforma_client = TestClient(main.app)
plataforma_client.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})


def _admin_client(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


# ---------- Alta / edición desde plataforma ----------

def test_alta_sindicato_con_catalogo_elegido():
    r = plataforma_client.post("/plataforma/sindicato", data={
        "nombre": "Sindicato Test Modulos Alta", "descripcion": "", "cuit": "", "direccion": "",
        "mail": "", "telefonos": "", "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d",
        # Elegimos un subconjunto puntual + uno inválido, que debe descartarse en silencio.
        "modulos_habilitados": ["recibos", "notificaciones", "no-existe"],
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Modulos Alta")).first()
        assert sind is not None
        assert set(sind.modulos_habilitados) == {"recibos", "notificaciones"}
    print("OK  test_alta_sindicato_con_catalogo_elegido")


def test_alta_sin_marcar_ningun_modulo_queda_vacio():
    r = plataforma_client.post("/plataforma/sindicato", data={
        "nombre": "Sindicato Test Modulos Vacio", "descripcion": "", "cuit": "", "direccion": "",
        "mail": "", "telefonos": "", "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d",
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Modulos Vacio")).first()
        assert sind.modulos_habilitados == []
    print("OK  test_alta_sin_marcar_ningun_modulo_queda_vacio")


def test_edicion_cambia_modulos():
    with Session(db.engine) as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == "Sindicato Test Modulos Alta")).first()
        sid = sind.id
    r = plataforma_client.post("/plataforma/sindicato/editar", data={
        "id": sid, "nombre": "Sindicato Test Modulos Alta", "descripcion": "",
        "cuit": "", "direccion": "", "mail": "", "telefonos": "",
        "autoridad": "", "cargo_autoridad": "",
        "color_primario": "#152238", "color_secundario": "#1a7a6b", "color_acento": "#b23a2e",
        "color_base": "#0f1b2d",
        "modulos_habilitados": ["beneficios"],
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        sind = s.get(Sindicato, sid)
        assert sind.modulos_habilitados == ["beneficios"]
    print("OK  test_edicion_cambia_modulos")


def test_grandfathering_helpers():
    """Simula una fila ya migrada (grandfathered): todo lo que existía antes
    del sistema de módulos queda habilitado, los 2 módulos nuevos no."""
    assert set(db.modulos_habilitados(SID_FULL)) == set(MODULOS_INICIALES)
    for clave in MODULOS_INICIALES:
        assert db.modulo_habilitado(SID_FULL, clave)
    assert not db.modulo_habilitado(SID_FULL, "notificaciones")
    assert not db.modulo_habilitado(SID_FULL, "tramites")
    print("OK  test_grandfathering_helpers")


# ---------- Portada del trabajador ----------

def test_portada_oculta_tarjetas_y_secciones_sin_modulo():
    c = _sesion_trabajador("20444444440")  # sindicato "solo noticias"
    r = c.get("/app/inicio")
    assert r.status_code == 200
    assert 'href="/app"' not in r.text  # tarjeta "Tu recibo"
    assert 'href="/app?tab=aportes"' not in r.text
    assert 'href="/app?tab=credencial"' not in r.text
    assert 'href="/app?tab=capacitacion"' not in r.text
    assert "Novedades" in r.text  # sección de noticias sí, es el único módulo habilitado
    print("OK  test_portada_oculta_tarjetas_y_secciones_sin_modulo")


def test_portada_muestra_todo_con_catalogo_completo():
    c = _sesion_trabajador("20111111119")  # sindicato "full"
    r = c.get("/app/inicio")
    assert r.status_code == 200
    assert 'href="/app"' in r.text
    assert 'href="/app?tab=aportes"' in r.text
    assert 'href="/app?tab=credencial"' in r.text
    assert 'href="/app?tab=capacitacion"' in r.text
    print("OK  test_portada_muestra_todo_con_catalogo_completo")


# ---------- Tabbar de trabajador.html (/app) ----------

def test_tabbar_oculta_pestanas_sin_modulo():
    c = _sesion_trabajador("20444444440")  # sindicato "solo noticias"
    r = c.get("/app")
    assert r.status_code == 200
    assert 'data-tp="recibo"' not in r.text
    assert 'data-tp="aportes"' not in r.text
    assert 'data-tp="credencial"' not in r.text
    assert 'data-tp="capacitacion"' not in r.text
    assert 'data-tp="novedades"' in r.text
    print("OK  test_tabbar_oculta_pestanas_sin_modulo")


def test_tabbar_completa_con_catalogo_completo():
    c = _sesion_trabajador("20111111119")  # sindicato "full"
    r = c.get("/app")
    assert r.status_code == 200
    for tp in ["recibo", "aportes", "credencial", "novedades", "capacitacion"]:
        assert f'data-tp="{tp}"' in r.text, tp
    print("OK  test_tabbar_completa_con_catalogo_completo")


# ---------- Pestañas de /admin ----------

def test_admin_oculta_pestanas_sin_modulo():
    c = _admin_client("20222222220", "noticias-demo")  # sindicato "solo noticias"
    r = c.get("/admin")
    assert r.status_code == 200
    assert 'data-panel="reportes"' not in r.text
    assert 'data-panel="formulas"' not in r.text
    assert 'data-panel="conceptos"' not in r.text
    assert 'data-panel="aprendizaje"' not in r.text
    assert 'data-panel="cotizantes"' not in r.text
    assert 'data-panel="beneficios"' not in r.text
    assert 'data-panel="noticias"' in r.text
    # Trabajadores y Seccionales quedan SIEMPRE visibles, no dependen de ningún módulo.
    assert 'data-panel="trabajadores"' in r.text
    assert 'data-panel="seccionales"' in r.text
    print("OK  test_admin_oculta_pestanas_sin_modulo")


def test_admin_completo_con_catalogo_completo():
    c = _admin_client("20111111110", "full-demo")  # sindicato "full"
    r = c.get("/admin")
    assert r.status_code == 200
    for panel in ["reportes", "formulas", "conceptos", "aprendizaje", "cotizantes",
                  "noticias", "beneficios", "trabajadores", "seccionales"]:
        assert f'data-panel="{panel}"' in r.text, panel
    print("OK  test_admin_completo_con_catalogo_completo")


# ---------- Bloqueo real en el backend (403), no solo esconder el botón ----------

def test_ruta_noticia_bloqueada_403_con_modulo_apagado():
    c = _admin_client("20333333330", "recibos-demo")  # sindicato "solo recibos" -- sin noticias
    r = c.post("/admin/noticia", data={
        "titulo": "Aviso", "bajada": "", "texto_completo": "",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
    })
    assert r.status_code == 403
    print("OK  test_ruta_noticia_bloqueada_403_con_modulo_apagado")


def test_ruta_beneficio_bloqueada_403_con_modulo_apagado():
    c = _admin_client("20333333330", "recibos-demo")  # sindicato "solo recibos" -- sin beneficios
    r = c.post("/admin/beneficio", data={
        "rubro": "Descuento", "descripcion": "", "link": "",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
    })
    assert r.status_code == 403
    print("OK  test_ruta_beneficio_bloqueada_403_con_modulo_apagado")


def test_ruta_aprender_bloqueada_403_con_modulo_apagado():
    c = _admin_client("20222222220", "noticias-demo")  # sindicato "solo noticias" -- sin recibos
    r = c.post("/admin/aprender", files={"archivos": ("recibo.png", b"fake", "image/png")})
    assert r.status_code == 403
    print("OK  test_ruta_aprender_bloqueada_403_con_modulo_apagado")


def test_ruta_noticia_permitida_con_modulo_prendido():
    c = _admin_client("20222222220", "noticias-demo")  # sindicato "solo noticias" -- CON noticias
    r = c.post("/admin/noticia", data={
        "titulo": "Aviso permitido", "bajada": "", "texto_completo": "",
        "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31",
    }, follow_redirects=False)
    assert r.status_code == 303
    print("OK  test_ruta_noticia_permitida_con_modulo_prendido")


if __name__ == "__main__":
    test_alta_sindicato_con_catalogo_elegido()
    test_alta_sin_marcar_ningun_modulo_queda_vacio()
    test_edicion_cambia_modulos()
    test_grandfathering_helpers()
    test_portada_oculta_tarjetas_y_secciones_sin_modulo()
    test_portada_muestra_todo_con_catalogo_completo()
    test_tabbar_oculta_pestanas_sin_modulo()
    test_tabbar_completa_con_catalogo_completo()
    test_admin_oculta_pestanas_sin_modulo()
    test_admin_completo_con_catalogo_completo()
    test_ruta_noticia_bloqueada_403_con_modulo_apagado()
    test_ruta_beneficio_bloqueada_403_con_modulo_apagado()
    test_ruta_aprender_bloqueada_403_con_modulo_apagado()
    test_ruta_noticia_permitida_con_modulo_prendido()
    print("\nTodos los tests de módulos pasaron.")

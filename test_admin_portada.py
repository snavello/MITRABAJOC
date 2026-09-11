"""Portada de /admin (landing con tarjetas, GET /admin/inicio): requiere
sesión de sindicato, muestra una tarjeta por sección habilitada según
`modulos_habilitados` (mismo criterio que ya usa la barra de pestañas de
admin.html), Trabajadores y Seccionales siempre visibles, y el login exitoso
redirige ahí en vez de a /admin.

Correr con: .venv/Scripts/python.exe test_admin_portada.py
"""
import os
import tempfile

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE
os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, TipoTramite, Tramite, TipoTramiteEmpleador, TramiteEmpleador
from modulos import MODULOS
import main
from fastapi.testclient import TestClient

db.crear_tablas()

with db.get_session() as s:
    full = Sindicato(nombre="UOM Portada Full", slug="uom-portada-full",
                      color_base="#0f1b2d", modulos_habilitados=list(MODULOS.keys()))
    solo_recibos = Sindicato(nombre="Sind Portada Solo Recibos", slug="sind-portada-solo-recibos",
                              color_base="#111111", modulos_habilitados=["recibos"])
    s.add(full); s.add(solo_recibos)
    s.commit(); s.refresh(full); s.refresh(solo_recibos)
    SID_FULL, SID_RECIBOS = full.id, solo_recibos.id

    s.add(UsuarioSindicato(sindicato_id=SID_FULL, usuario="20777777770", nombre="Juan Pérez",
                            clave_hash=auth.hashear_clave("full-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID_RECIBOS, usuario="20888888880", nombre="Admin Recibos",
                            clave_hash=auth.hashear_clave("recibos-demo"), debe_cambiar_clave=False, es_super_admin=True))
    s.commit()

    tipo = TipoTramite(sindicato_id=SID_FULL, titulo="Reintegro", codigo="F01")
    s.add(tipo); s.commit(); s.refresh(tipo)
    for i in range(2):
        s.add(Tramite(sindicato_id=SID_FULL, tipo_tramite_id=tipo.id,
                       numero_expediente=f"F01-2026-00000{i}", cuil="20111111119", estado="iniciado"))
    s.add(Tramite(sindicato_id=SID_FULL, tipo_tramite_id=tipo.id,
                   numero_expediente="F01-2026-000002", cuil="20111111119", estado="terminado"))
    s.commit()

    tipo_emp = TipoTramiteEmpleador(sindicato_id=SID_FULL, titulo="Nómina", codigo="F01EMP")
    s.add(tipo_emp); s.commit(); s.refresh(tipo_emp)
    s.add(TramiteEmpleador(sindicato_id=SID_FULL, tipo_tramite_id=tipo_emp.id,
                            numero_expediente="F01EMP-2026-000000", cuit="30111222339", estado="iniciado"))
    s.commit()


def _admin_client(usuario, clave):
    c = TestClient(main.app)
    c.post("/admin/login", data={"usuario": usuario, "clave": clave})
    return c


def test_sin_sesion_sirve_login():
    c = TestClient(main.app)
    r = c.get("/admin/inicio")
    assert r.status_code == 200
    assert "clave" in r.text.lower()
    assert 'href="/admin#reportes"' not in r.text
    print("OK  test_sin_sesion_sirve_login")


def test_login_exitoso_redirige_a_inicio():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "20777777770", "clave": "full-demo"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/inicio"
    print("OK  test_login_exitoso_redirige_a_inicio")


def test_sindicato_con_todos_los_modulos_ve_las_12_tarjetas():
    c = _admin_client("20777777770", "full-demo")
    r = c.get("/admin/inicio")
    assert r.status_code == 200
    for panel in ("reportes", "formulas", "conceptos", "trabajadores", "aprendizaje",
                  "cotizantes", "noticias", "beneficios", "notificaciones",
                  "tramites", "seccionales", "administradores"):
        assert f'href="/admin#{panel}"' in r.text, panel
    print("OK  test_sindicato_con_todos_los_modulos_ve_las_12_tarjetas")


def test_sindicato_solo_recibos_no_ve_modulos_apagados_pero_si_los_fijos():
    c = _admin_client("20888888880", "recibos-demo")
    r = c.get("/admin/inicio")
    assert r.status_code == 200
    for panel in ("reportes", "formulas", "conceptos", "aprendizaje", "cotizantes"):
        assert f'href="/admin#{panel}"' in r.text, panel
    for panel in ("noticias", "beneficios", "notificaciones", "tramites"):
        assert f'href="/admin#{panel}"' not in r.text, panel
    # Trabajadores, Seccionales y Administradores no dependen de ningún módulo.
    assert 'href="/admin#trabajadores"' in r.text
    assert 'href="/admin#seccionales"' in r.text
    assert 'href="/admin#administradores"' in r.text
    print("OK  test_sindicato_solo_recibos_no_ve_modulos_apagados_pero_si_los_fijos")


def test_saluda_con_el_nombre_del_admin_logueado():
    c = _admin_client("20777777770", "full-demo")
    r = c.get("/admin/inicio")
    assert "Hola, <em>Juan</em>" in r.text
    print("OK  test_saluda_con_el_nombre_del_admin_logueado")


def test_globo_de_tramites_nuevos_cuenta_solo_estado_iniciado():
    c = _admin_client("20777777770", "full-demo")
    r = c.get("/admin/inicio")
    assert db.contar_tramites_nuevos(SID_FULL) == 2
    assert '<span class="badge-noleidas">2</span>' in r.text
    print("OK  test_globo_de_tramites_nuevos_cuenta_solo_estado_iniciado")


def test_sin_tramites_no_muestra_globo():
    c = _admin_client("20888888880", "recibos-demo")  # módulo 'tramites' apagado
    r = c.get("/admin/inicio")
    assert '<span class="badge-noleidas">' not in r.text
    print("OK  test_sin_tramites_no_muestra_globo")


def test_globo_de_empleadores_se_propaga_a_la_tarjeta():
    """El globo de "Ver trámites" de Empleadores (sub-pestaña más profunda,
    ver test_tramites_empresa.py) también tiene que llegar hasta acá -- el
    nivel más alto de la portada de admin."""
    c = _admin_client("20777777770", "full-demo")
    r = c.get("/admin/inicio")
    assert db.contar_tramites_empleador_nuevos(SID_FULL) == 1
    assert '<span class="badge-noleidas">1</span>' in r.text
    print("OK  test_globo_de_empleadores_se_propaga_a_la_tarjeta")


if __name__ == "__main__":
    test_sin_sesion_sirve_login()
    test_login_exitoso_redirige_a_inicio()
    test_sindicato_con_todos_los_modulos_ve_las_12_tarjetas()
    test_sindicato_solo_recibos_no_ve_modulos_apagados_pero_si_los_fijos()
    test_saluda_con_el_nombre_del_admin_logueado()
    test_globo_de_tramites_nuevos_cuenta_solo_estado_iniciado()
    test_sin_tramites_no_muestra_globo()
    test_globo_de_empleadores_se_propaga_a_la_tarjeta()
    print("\nTodos los tests de admin_portada pasaron.")

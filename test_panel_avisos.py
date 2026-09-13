"""Los avisos del panel: que cada rechazo del servidor tenga su cartel, y
que el cartel aparezca DONDE está el formulario que lo provocó.

Nace de dos cosas reportadas probando el panel (2026-09-13):

1. Un Admin de Seccional veía la pestaña "Seccionales" entera -- asistente
   de alta en tres pasos, la lista de TODAS las delegaciones y un botón
   "Borrar" en cada una. El servidor rechazaba todo (bien), pero recién al
   apretar Guardar, y con el JSON crudo en pantalla completa. La pantalla
   ofrecía lo que no se podía hacer.

2. Editar un usuario "no se podía". En realidad se guardaba: lo que pasaba
   es que el panel volvía SIEMPRE a la sub-pestaña "Áreas", sin ningún
   aviso de éxito, con el formulario reseteado -- indistinguible de que el
   botón no hizo nada. Y cuando sí fallaba, el cartel o estaba en el
   sub-panel equivocado o directamente no existía: `err=sinarea` no lo
   renderizaba nadie, así que bajar a un administrador a usuario de área sin
   elegirle un área rebotaba en silencio.

El primer test de acá es el que más vale a futuro: ata la lista de `err=`
que EMITE main.py con la que RENDERIZA la plantilla. El agujero de fondo no
era `sinarea`, era que nada obligaba a que esas dos listas coincidieran.

Correr con: python -m pytest test_panel_avisos.py -q
"""
import os
import re

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea
import main
from modulos import MODULOS
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlmodel import Session, select

RAIZ = os.path.dirname(os.path.abspath(__file__))
FUENTE_MAIN = open(os.path.join(RAIZ, "main.py"), encoding="utf-8").read()
PLANTILLA = open(os.path.join(RAIZ, "templates", "admin.html"), encoding="utf-8").read()

db.crear_tablas()

DOMICILIO = {"provincia": "Buenos Aires", "localidad": "Lomas de Zamora",
             "calle": "Meeks", "numero": "450", "piso_depto": "", "codigo_postal": "1832",
             "latitud": "-34.760000", "longitud": "-58.400000", "precision_geo": "exacta"}

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Avisos", slug="uom-avisos", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True,
                        provincia="Buenos Aires", localidad="CABA", calle="Independencia",
                        numero="1200", latitud=-34.61, longitud=-58.38, precision_geo="exacta")
    lomas = Seccional(sindicato_id=SID, nombre="Lomas de Zamora", ve_todas=False,
                      provincia="Buenos Aires", localidad="Lomas de Zamora", calle="Meeks",
                      numero="450", latitud=-34.76, longitud=-58.40, precision_geo="exacta")
    s.add(central); s.add(lomas); s.commit(); s.refresh(central); s.refresh(lomas)
    SEC_CENTRAL, SEC_LOMAS = central.id, lomas.id
    area = Area(sindicato_id=SID, seccional_id=SEC_LOMAS, nombre="Mesa de Entradas")
    s.add(area); s.commit(); s.refresh(area)
    AREA_LOMAS = area.id
    s.add(PermisoArea(area_id=AREA_LOMAS, seccion="tramites_recibidos"))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="27999999999", cuil="27999999999",
                           nombre="Super", clave_hash=auth.hashear_clave("super"),
                           debe_cambiar_clave=False, es_super_admin=True,
                           seccional_id=SEC_CENTRAL))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="25111111111", cuil="25111111111",
                           nombre="Admin Lomas", clave_hash=auth.hashear_clave("lomas"),
                           debe_cambiar_clave=False, es_admin_seccional=True,
                           seccional_id=SEC_LOMAS))
    s.commit()

with db.get_session() as s:
    U_LOCAL = s.exec(select(UsuarioSindicato).where(
        UsuarioSindicato.usuario == "25111111111")).first().id


def _cli(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _super():
    return _cli("27999999999", "super")


def _local():
    return _cli("25111111111", "lomas")


# ---------- 1. Cada err= tiene su cartel, y cada cartel su err= ----------

def _errores_emitidos():
    """Los `err=` que manda main.py, en sus dos formas de escritura."""
    literales = set(re.findall(r'\?err=([a-z_]+)', FUENTE_MAIN))
    porhelper = set(re.findall(r'err="([a-z_]+)"', FUENTE_MAIN))
    return literales | porhelper


def _errores_renderizados():
    return set(re.findall(r"get\('err'\) == '([a-z_]+)'", PLANTILLA))


def test_todo_error_que_manda_el_servidor_tiene_cartel():
    """El agujero de fondo. Un `err=` sin cartel es una pantalla que vuelve
    al panel sin decir nada: el que apretó Guardar no tiene forma de saber
    si guardó, si falló, ni por qué."""
    sin_cartel = _errores_emitidos() - _errores_renderizados()
    assert not sin_cartel, f"err= sin cartel en admin.html: {sorted(sin_cartel)}"
    print("OK  test_todo_error_que_manda_el_servidor_tiene_cartel")


def test_no_hay_carteles_muertos():
    """El otro lado: un cartel que nadie dispara es código que miente sobre
    lo que la pantalla puede llegar a mostrar. Así estaba `datosadmin`."""
    huerfanos = _errores_renderizados() - _errores_emitidos()
    assert not huerfanos, f"carteles que nadie emite: {sorted(huerfanos)}"
    print("OK  test_no_hay_carteles_muertos")


def test_sinarea_tiene_cartel():
    """Regresión puntual del que faltaba, por si el test general se afloja."""
    assert "sinarea" in _errores_renderizados()
    print("OK  test_sinarea_tiene_cartel")


# ---------- 2. Los 403 vuelven al panel, no al JSON crudo ----------

def test_una_ruta_sin_clasificar_da_403_y_no_revienta():
    """El "falla cerrado" de PERMISOS_RUTAS. Estaba roto: `_sin_permiso` se
    usaba una línea antes de su propio `def` (era una función anidada), así
    que este camino moría con UnboundLocalError y devolvía 500."""
    class RutaFalsa:
        path = "/admin/ruta-que-nadie-clasifico"
    req = type("R", (), {"scope": {"route": RutaFalsa()}})()
    try:
        main._exigir_permiso_de_ruta(req, {"uid": U_LOCAL})
    except HTTPException as e:
        assert e.status_code == 403
        assert getattr(e, "codigo", None) == "sinpermiso"
    else:
        raise AssertionError("una ruta sin clasificar tiene que rechazar")
    print("OK  test_una_ruta_sin_clasificar_da_403_y_no_revienta")


def test_el_403_del_admin_local_no_deja_json_crudo():
    """Navegando (no por fetch), el rechazo tiene que volver al panel con un
    aviso. Antes `_exigir_super_admin` no marcaba el 403 y el admin local se
    comía el JSON en pantalla completa."""
    r = _local().post("/admin/seccional",
                      data={"id": "", "nombre": "Quilmes", **DOMICILIO},
                      headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303, r.status_code
    assert "err=sinpermiso" in r.headers["location"]
    print("OK  test_el_403_del_admin_local_no_deja_json_crudo")


def test_pero_una_api_sigue_recibiendo_json():
    """El arreglo no puede convertir toda respuesta de API en un redirect."""
    r = _local().post("/admin/seccional/borrar", data={"id": str(SEC_CENTRAL)},
                      headers={"Accept": "application/json"}, follow_redirects=False)
    assert r.status_code == 403, r.status_code
    assert r.json()["detail"]
    print("OK  test_pero_una_api_sigue_recibiendo_json")


# ---------- 3. Las prohibiciones siguen siendo prohibiciones ----------

def test_el_admin_local_sigue_sin_poder_crear_ni_borrar_seccionales():
    """Lo de arriba es cosmética; esto es la regla. Que el cartel sea lindo
    no puede haber abierto la puerta."""
    c = _local()
    antes = {x["id"] for x in db.seccionales_del_sindicato(SID)}
    c.post("/admin/seccional", data={"id": "", "nombre": "Quilmes", **DOMICILIO},
           follow_redirects=False)
    c.post("/admin/seccional/borrar", data={"id": str(SEC_CENTRAL)}, follow_redirects=False)
    c.post("/admin/seccional", data={"id": str(SEC_LOMAS), "nombre": "Lomas de Zamora",
                                     "ve_todas": "1", **DOMICILIO}, follow_redirects=False)
    with Session(db.engine) as s:
        assert not s.exec(select(Seccional).where(
            Seccional.sindicato_id == SID, Seccional.nombre == "Quilmes")).all()
        assert s.get(Seccional, SEC_CENTRAL) is not None
        assert s.get(Seccional, SEC_LOMAS).ve_todas is False
    assert {x["id"] for x in db.seccionales_del_sindicato(SID)} == antes
    print("OK  test_el_admin_local_sigue_sin_poder_crear_ni_borrar_seccionales")


# ---------- 4. La pantalla ya no ofrece lo que el servidor rechaza ----------

def test_al_admin_local_no_le_llega_el_alta_de_seccional_abierta():
    html = _local().get("/admin").text
    assert 'id="sec-card"' in html, "el formulario tiene que existir: edita la suya"
    caja = html[html.index('id="sec-card"') - 60:html.index('id="sec-card"') + 20]
    assert "oculto" in caja, "al admin local el alta le tiene que nacer cerrada"
    # El encabezado VISIBLE, no la cadena suelta: el texto "Dar de alta una
    # seccional" también vive adentro del JS (la rama para el otro rol), y
    # buscarlo en todo el HTML daba un falso positivo.
    assert '<h2 id="seccionales-titulo">Seccionales</h2>' in html
    print("OK  test_al_admin_local_no_le_llega_el_alta_de_seccional_abierta")


def test_al_super_admin_si_le_llega_abierta():
    html = _super().get("/admin").text
    assert '<h2 id="seccionales-titulo">Dar de alta una seccional</h2>' in html
    caja = html[html.index('id="sec-card"') - 60:html.index('id="sec-card"') + 20]
    assert "oculto" not in caja
    print("OK  test_al_super_admin_si_le_llega_abierta")


def test_el_admin_local_no_ve_borrar_ni_las_seccionales_ajenas():
    """El recorte lo hace el servidor: si viviera en el JS, la fila de la
    otra delegación viajaría igual en el HTML."""
    html = _local().get("/admin").text
    assert "/admin/seccional/borrar" not in html
    assert "Lomas de Zamora" in html
    tabla = html[html.index("Seccionales cargadas"):]
    tabla = tabla[:tabla.index("</table>")]
    assert "Sede Central" not in tabla, "no tiene por qué ver la delegación ajena"
    print("OK  test_el_admin_local_no_ve_borrar_ni_las_seccionales_ajenas")


def test_el_super_admin_ve_todas_y_con_borrar():
    html = _super().get("/admin").text
    tabla = html[html.index("Seccionales cargadas"):]
    tabla = tabla[:tabla.index("</table>")]
    assert "Sede Central" in tabla and "Lomas de Zamora" in tabla
    assert "/admin/seccional/borrar" in html
    print("OK  test_el_super_admin_ve_todas_y_con_borrar")


# ---------- 5. Guardar un usuario vuelve donde estabas, y lo dice ----------

def test_guardar_un_usuario_vuelve_a_su_sub_pestana_con_aviso():
    r = _super().post("/admin/usuario/editar",
                      data={"id": str(U_LOCAL), "nombre": "Admin Lomas",
                            "rol": "seccional", "seccional_id": str(SEC_LOMAS),
                            "area_id": ""}, follow_redirects=False)
    assert r.status_code == 303
    destino = r.headers["location"]
    assert "sub=usuarios" in destino, destino
    assert "ok=usuario" in destino, destino
    print("OK  test_guardar_un_usuario_vuelve_a_su_sub_pestana_con_aviso")


def test_bajarlo_a_usuario_de_area_sin_area_avisa_en_vez_de_rebotar_mudo():
    """El caso exacto del reporte: era el único que fallaba de verdad, y era
    el único sin cartel."""
    r = _super().post("/admin/usuario/editar",
                      data={"id": str(U_LOCAL), "nombre": "Admin Lomas",
                            "rol": "area", "seccional_id": str(SEC_LOMAS),
                            "area_id": ""}, follow_redirects=False)
    assert r.status_code == 303
    destino = r.headers["location"]
    assert "err=sinarea" in destino, destino
    assert "sub=usuarios" in destino, destino
    with Session(db.engine) as s:
        assert s.get(UsuarioSindicato, U_LOCAL).es_admin_seccional, "no debió cambiar"
    print("OK  test_bajarlo_a_usuario_de_area_sin_area_avisa_en_vez_de_rebotar_mudo")


def test_los_avisos_de_usuarios_estan_en_el_sub_panel_de_usuarios():
    """Estaban en el de áreas: el cartel aparecía arriba del formulario
    equivocado. Un test de PLANTILLA, porque el bug vive en el HTML."""
    sub_areas = PLANTILLA[PLANTILLA.index('id="au-sub-areas"'):
                          PLANTILLA.index('id="au-sub-usuarios"')]
    sub_usuarios = PLANTILLA[PLANTILLA.index('id="au-sub-usuarios"'):]
    for codigo in ("sinarea", "sinseccional", "areaajena", "ultimoadmin", "usuarioexiste"):
        assert codigo in sub_usuarios, f"{codigo} no está en el sub-panel de usuarios"
        assert codigo not in sub_areas, f"{codigo} sigue en el sub-panel de áreas"
    assert "datosarea" in sub_areas
    print("OK  test_los_avisos_de_usuarios_estan_en_el_sub_panel_de_usuarios")


def test_el_panel_abre_la_sub_pestana_que_pide_el_servidor():
    assert "abrirSubDesdeURL" in PLANTILLA
    assert "get('sub')" in PLANTILLA
    print("OK  test_el_panel_abre_la_sub_pestana_que_pide_el_servidor")


# ---------- 6. El formulario dice qué está haciendo ----------

def test_el_titulo_del_formulario_de_usuario_cambia_al_editar():
    """Antes lo que cambiaba era el título del PANEL, y este seguía diciendo
    "Dar de alta un usuario" con los datos de la persona adentro."""
    assert 'id="usuario-titulo"' in PLANTILLA
    assert "getElementById('usuario-titulo').textContent = 'Editar usuario: '" in PLANTILLA
    assert "getElementById('administradores-titulo').textContent" not in PLANTILLA, \
        "el título del panel no es el del formulario"
    print("OK  test_el_titulo_del_formulario_de_usuario_cambia_al_editar")


def test_los_tres_formularios_dicen_alta_o_edicion():
    """Áreas y Seccionales ya lo hacían; Usuarios era el que faltaba."""
    for titulo, editar in [("area-titulo", "'Editar área: '"),
                           ("seccionales-titulo", "'Editar seccional: '"),
                           ("usuario-titulo", "'Editar usuario: '")]:
        assert f"getElementById('{titulo}').textContent = {editar}" in PLANTILLA, titulo
    print("OK  test_los_tres_formularios_dicen_alta_o_edicion")


def test_se_explica_por_que_un_administrador_no_muestra_permisos():
    assert 'id="usu-sin-permisos"' in PLANTILLA
    assert "usu-sin-permisos').classList.toggle('oculto', !esAdmin)" in PLANTILLA
    print("OK  test_se_explica_por_que_un_administrador_no_muestra_permisos")


def test_avisa_cuando_un_admin_local_queda_con_alcance_de_todo_el_sindicato():
    assert 'id="usu-aviso-alcance"' in PLANTILLA
    assert "function avisoAlcanceTotal()" in PLANTILLA
    assert 'data-ve-todas=' in PLANTILLA
    print("OK  test_avisa_cuando_un_admin_local_queda_con_alcance_de_todo_el_sindicato")


if __name__ == "__main__":
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            fn()
    print("\nTodos los tests de avisos del panel pasaron.")

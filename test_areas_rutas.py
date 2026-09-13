"""Gateo por permisos de las rutas del panel -- Fase 2 de SPRINT_AREAS.md.

Dos clases de test, y la primera es la que más vale a futuro:

1. COBERTURA: recorre app.routes y exige que TODA ruta /admin esté
   clasificada en PERMISOS_RUTAS o listada como exenta. Son ~50 rutas y van
   a seguir creciendo; sin este test, la forma normal de abrir un agujero
   es agregar una ruta y olvidarse de clasificarla. El gateo falla cerrado
   igual (una ruta sin clasificar rechaza), así que el riesgo real no es
   una puerta abierta sino una ruta que deja de andar sin que nadie sepa
   por qué -- este test lo dice en el momento.

2. COMPORTAMIENTO: que un usuario de área reciba 403 donde no le
   corresponde, aunque arme el request a mano sin pasar por la UI (mismo
   criterio defensivo que el sistema de módulos).

Correr con: python -m pytest test_areas_rutas.py -q
"""
import os

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import db
import auth
from db import Sindicato, UsuarioSindicato, Seccional, Area, PermisoArea
import main
from permisos import SECCIONES, SECCION_SUPER_ADMIN
from modulos import MODULOS
from fastapi.testclient import TestClient
from sqlmodel import Session, select

# Una seccional no se guarda sin dirección completa y ubicada (2026-09-13, ver
# geo.OBLIGATORIOS_SECCIONAL). Acá se manda un domicilio VÁLIDO a propósito:
# lo que estos tests miran es el permiso, y con un POST inválido el rechazo
# vendría de otro lado y dirían que el permiso funciona sin haberlo probado.
DOMICILIO_SEC = {"provincia": "Santa Fe", "localidad": "Rosario", "calle": "San Martín",
                 "numero": "850", "piso_depto": "", "codigo_postal": "2000",
                 "latitud": "-32.947338", "longitud": "-60.636893",
                 "precision_geo": "exacta"}

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Rutas", slug="uom-rutas", color_base="#0f1b2d",
                     modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id

    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(central); s.commit(); s.refresh(central)
    SEC = central.id

    legales = Area(sindicato_id=SID, seccional_id=SEC, nombre="Secretaría Legal")
    s.add(legales); s.commit(); s.refresh(legales)
    AREA = legales.id
    # Puede responder trámites y tocar el padrón. NADA más: ni fórmulas, ni
    # noticias, ni crear formularios de trámite, ni usuarios.
    for seccion in ("tramites_recibidos", "trabajadores"):
        s.add(PermisoArea(area_id=AREA, seccion=seccion))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111110", nombre="Jefa",
                           clave_hash=auth.hashear_clave("jefa"), debe_cambiar_clave=False,
                           es_super_admin=True, seccional_id=SEC))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111111", nombre="Gabriel Chávez",
                           clave_hash=auth.hashear_clave("gabriel"), debe_cambiar_clave=False,
                           area_id=AREA, seccional_id=SEC))
    s.commit()


def _cliente(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave},
               follow_redirects=False)
    assert r.status_code == 303, "el login de la fixture tiene que funcionar"
    return c


def _rutas_admin():
    """[(path, {métodos})] de todas las rutas /admin registradas en la app."""
    salida = []
    for r in main.app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/admin"):
            salida.append((path, set(getattr(r, "methods", set()) or set())))
    return salida


# ---------- Cobertura ----------

def test_toda_ruta_admin_esta_clasificada():
    """El test que evita el agujero por olvido."""
    sin_clasificar = [
        p for p, _ in _rutas_admin()
        if p not in main.PERMISOS_RUTAS and p not in main.RUTAS_ADMIN_SIN_PERMISO
    ]
    assert not sin_clasificar, (
        "Rutas /admin sin permiso declarado. Agregalas a PERMISOS_RUTAS "
        f"(o a RUTAS_ADMIN_SIN_PERMISO si de verdad no llevan permiso): {sin_clasificar}")
    print("OK  test_toda_ruta_admin_esta_clasificada")


def test_no_hay_entradas_muertas_en_el_registro():
    """Una ruta renombrada deja su entrada vieja apuntando a la nada, y la
    ruta nueva sin clasificar -- que falla cerrada y parece un bug raro."""
    reales = {p for p, _ in _rutas_admin()}
    muertas = [p for p in main.PERMISOS_RUTAS if p not in reales]
    assert not muertas, f"entradas de PERMISOS_RUTAS que ya no existen como ruta: {muertas}"
    exentas_muertas = [p for p in main.RUTAS_ADMIN_SIN_PERMISO if p not in reales]
    assert not exentas_muertas, f"exenciones que ya no existen como ruta: {exentas_muertas}"
    print("OK  test_no_hay_entradas_muertas_en_el_registro")


def test_las_secciones_del_registro_existen_en_el_catalogo():
    desconocidas = sorted({
        sec for sec in main.PERMISOS_RUTAS.values()
        if sec != SECCION_SUPER_ADMIN and sec not in SECCIONES
    })
    assert not desconocidas, f"secciones que no están en permisos.SECCIONES: {desconocidas}"
    print("OK  test_las_secciones_del_registro_existen_en_el_catalogo")


def test_las_exentas_son_solo_entrar_salir_y_las_pantallas():
    """Que la lista de exentas no crezca por descuido: cada agregado ahí es
    una ruta que deja de pedir permiso.

    Son PANTALLAS, no endpoints: se arman con lo que cada uno puede ver, y
    resuelven la falta de permiso redirigiendo en vez de tirar un 403 seco.
    /admin/dashboard está acá por esa razón y no por descuido -- sus
    endpoints de datos (/admin/dashboard/*) sí están todos gateados, y eso
    lo fija test_los_datos_del_dashboard_si_estan_gateados."""
    assert main.RUTAS_ADMIN_SIN_PERMISO == {
        "/admin", "/admin/inicio", "/admin/login", "/admin/salir",
        "/admin/dashboard"}
    print("OK  test_las_exentas_son_solo_entrar_salir_y_las_pantallas")


def test_los_datos_del_dashboard_si_estan_gateados():
    """La pantalla del Panel Sindical no lleva datos: los pide el JS a los
    endpoints de agregados. Si la pantalla está exenta y los endpoints
    también, el permiso no existiría."""
    endpoints = [p for p, _ in _rutas_admin()
                 if p.startswith("/admin/dashboard/")]
    assert endpoints, "tiene que haber endpoints de datos del dashboard"
    sin_gatear = [p for p in endpoints if main.PERMISOS_RUTAS.get(p) != "dashboard"]
    assert not sin_gatear, f"endpoints del dashboard sin la sección 'dashboard': {sin_gatear}"
    print("OK  test_los_datos_del_dashboard_si_estan_gateados")


def test_la_gestion_de_usuarios_es_solo_de_super_admin():
    de_usuarios = {p: sec for p, sec in main.PERMISOS_RUTAS.items()
                   if p.startswith("/admin/usuario")}
    assert de_usuarios, "tiene que haber rutas de gestión de usuarios"
    for p, sec in de_usuarios.items():
        assert sec == SECCION_SUPER_ADMIN, f"{p} debería ser exclusiva del Super Admin, es {sec}"
    print("OK  test_la_gestion_de_usuarios_es_solo_de_super_admin")


# ---------- Comportamiento ----------

def test_super_admin_pasa_donde_el_de_area_no():
    c = _cliente("20111111110", "jefa")
    r = c.post("/admin/seccional", data={"nombre": "Rosario", **DOMICILIO_SEC},
               follow_redirects=False)
    assert r.status_code == 303, "el Super Admin tiene todo lo contratado"
    print("OK  test_super_admin_pasa_donde_el_de_area_no")


def test_usuario_de_area_pasa_donde_si_tiene_permiso():
    c = _cliente("20111111111", "gabriel")
    r = c.post("/admin/trabajador", data={"cuil": "20999999990", "nombre": "Ana Test"},
               follow_redirects=False)
    assert r.status_code == 303, "tiene el permiso de trabajadores por su área"
    print("OK  test_usuario_de_area_pasa_donde_si_tiene_permiso")


def test_usuario_de_area_403_en_seccion_que_no_tiene():
    """Aunque arme el POST a mano: esconder la pestaña no es el control."""
    c = _cliente("20111111111", "gabriel")
    for ruta, datos in [
        ("/admin/seccional", {"nombre": "Trucha", "direccion": ""}),
        ("/admin/noticia",   {"titulo": "T", "bajada": "B", "texto_completo": "X",
                              "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"}),
        ("/admin/formula",   {"target": "jubilacion", "descripcion": "D", "expr": "1"}),
        ("/admin/beneficio", {"rubro": "R", "descripcion": "D",
                              "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"}),
        ("/admin/empleador", {"cuit": "30999888776", "razon_social": "Empresa"}),
    ]:
        r = c.post(ruta, data=datos, follow_redirects=False)
        assert r.status_code == 403, f"{ruta} debería dar 403, dio {r.status_code}"
    print("OK  test_usuario_de_area_403_en_seccion_que_no_tiene")


def test_usuario_de_area_no_puede_crear_usuarios():
    """El caso que motivó todo: 'no es lo mismo crear trámites que crear
    usuarios'. Ni siquiera dándole todos los permisos asignables."""
    c = _cliente("20111111111", "gabriel")
    r = c.post("/admin/usuario", data={
        "usuario": "20777777770", "nombre": "Colado", "clave_inicial": "x"},
        follow_redirects=False)
    assert r.status_code == 403
    with Session(db.engine) as s:
        assert s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20777777770")).first() is None
    print("OK  test_usuario_de_area_no_puede_crear_usuarios")


def test_responder_tramites_no_habilita_crear_formularios():
    """La apertura de Trámites en dos, probada de punta a punta: si con
    'tramites_recibidos' pudiera crear formularios, podría elegir el área
    receptora y autoasignarse trabajo."""
    c = _cliente("20111111111", "gabriel")
    r = c.get("/admin/tramites-nuevos-cantidad")
    assert r.status_code == 200, "sí puede ver los trámites recibidos"
    r = c.post("/admin/tramite-tipo", data={"titulo": "F99", "codigo": "F99",
                                            "campos_json": "[]"},
               follow_redirects=False)
    assert r.status_code == 403, "no puede diseñar formularios"
    print("OK  test_responder_tramites_no_habilita_crear_formularios")


def test_quitar_el_permiso_vale_sin_volver_a_loguearse():
    """Los permisos se leen de la base en cada request, no del token: si
    viajaran en la cookie, revocar no tendría efecto hasta que venza."""
    c = _cliente("20111111111", "gabriel")
    r = c.post("/admin/trabajador", data={"cuil": "20999999991", "nombre": "Antes"},
               follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        p = s.exec(select(PermisoArea).where(
            PermisoArea.area_id == AREA, PermisoArea.seccion == "trabajadores")).first()
        s.delete(p); s.commit()
    r = c.post("/admin/trabajador", data={"cuil": "20999999992", "nombre": "Despues"},
               follow_redirects=False)
    assert r.status_code == 403, "la MISMA sesión tiene que quedar sin acceso ya"
    with db.get_session() as s:
        s.add(PermisoArea(area_id=AREA, seccion="trabajadores")); s.commit()
    print("OK  test_quitar_el_permiso_vale_sin_volver_a_loguearse")


def test_desactivar_el_area_deja_a_todo_el_equipo_afuera():
    c = _cliente("20111111111", "gabriel")
    with db.get_session() as s:
        a = s.get(Area, AREA)
        a.activo = False
        s.add(a); s.commit()
    r = c.post("/admin/trabajador", data={"cuil": "20999999993", "nombre": "Nadie"},
               follow_redirects=False)
    assert r.status_code == 403
    with db.get_session() as s:
        a = s.get(Area, AREA)
        a.activo = True
        s.add(a); s.commit()
    print("OK  test_desactivar_el_area_deja_a_todo_el_equipo_afuera")


def test_formulas_y_conceptos_ahora_respetan_el_modulo_recibos():
    """Endurecimiento que trajo el gateo, vale la pena dejarlo fijado.

    26 rutas de /admin ya llamaban a _exigir_modulo, pero /admin/formula y
    /admin/concepto* no: las pestañas Fórmulas y Conceptos se escondían con
    {% if 'recibos' in modulos %} y las rutas quedaban abiertas igual --
    justo lo que la regla del proyecto dice que no puede pasar. Ahora esas
    secciones exigen el módulo recibos como todas las demás, incluso para
    un Super Admin.
    """
    with db.get_session() as s:
        otro = Sindicato(nombre="Sin Recibos", slug="sin-recibos", color_base="#111111",
                         modulos_habilitados=["noticias"])
        s.add(otro); s.commit(); s.refresh(otro)
        s.add(UsuarioSindicato(sindicato_id=otro.id, usuario="20555555550", nombre="Jefe Sin Recibos",
                               clave_hash=auth.hashear_clave("sinrec"), debe_cambiar_clave=False,
                               es_super_admin=True))
        s.commit()
    c = _cliente("20555555550", "sinrec")
    r = c.post("/admin/formula", data={"target": "jubilacion", "descripcion": "D", "expr": "1"},
               follow_redirects=False)
    assert r.status_code == 403, "sin el módulo recibos, Fórmulas queda cerrada"
    r = c.post("/admin/noticia", data={"titulo": "T", "bajada": "B", "texto_completo": "X",
                                       "fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31"},
               follow_redirects=False)
    assert r.status_code == 303, "el módulo que sí tiene sigue andando"
    print("OK  test_formulas_y_conceptos_ahora_respetan_el_modulo_recibos")


# ---------- Las secciones que llegaron a main después del sprint ----------

def test_usuario_de_area_no_entra_al_panel_sindical():
    """Panel Sindical y Convenio no existían cuando se diseñó el catálogo.
    Se sumaron como secciones propias, así que se gatean como el resto: un
    usuario de área sin esas secciones no ve los números del sindicato
    entero ni toca los documentos del convenio."""
    c = _cliente("20111111111", "gabriel")
    r = c.get("/admin/dashboard/kpis")
    assert r.status_code == 403, "los datos del panel exigen la sección dashboard"
    r = c.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 303, "la PANTALLA redirige en vez de tirar 403"
    assert r.headers.get("location") == "/admin"
    print("OK  test_usuario_de_area_no_entra_al_panel_sindical")


def test_usuario_de_area_no_toca_los_documentos_del_convenio():
    c = _cliente("20111111111", "gabriel")
    r = c.post("/admin/convenio", data={"nombre": "Trucho"}, follow_redirects=False)
    assert r.status_code == 403
    print("OK  test_usuario_de_area_no_toca_los_documentos_del_convenio")


def test_darle_la_seccion_le_abre_el_panel_sindical():
    """El contrapeso del test anterior: que el 403 venga del permiso y no
    de otra cosa (un módulo apagado, por ejemplo)."""
    with db.get_session() as s:
        s.add(PermisoArea(area_id=AREA, seccion="dashboard")); s.commit()
    c = _cliente("20111111111", "gabriel")
    r = c.get("/admin/dashboard/kpis")
    # Lo que importa es que YA NO sea 403: el endpoint pide filtros por
    # query string y sin ellos contesta 422, que es la prueba de que el
    # request pasó el gate y murió más adelante, en la validación.
    assert r.status_code != 403, "con la sección, el gate deja pasar"
    r = c.get("/admin/dashboard", follow_redirects=False)
    assert r.status_code == 200, "y la pantalla ya no redirige"
    with db.get_session() as s:
        p = s.exec(select(PermisoArea).where(
            PermisoArea.area_id == AREA, PermisoArea.seccion == "dashboard")).first()
        s.delete(p); s.commit()
    print("OK  test_darle_la_seccion_le_abre_el_panel_sindical")


# ---------- Guard del último Super Admin ----------

def test_no_se_puede_desactivar_al_ultimo_super_admin():
    """Antes el guard contaba usuarios ACTIVOS: con un usuario de área
    presente, habría dejado desactivar al único Super Admin y el sindicato
    quedaba sin nadie que pudiera administrarlo."""
    with Session(db.engine) as s:
        jefa = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20111111110")).first()
        gabriel = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20111111111")).first()
        jefa_id, gabriel_id = jefa.id, gabriel.id
        assert gabriel.activo, "el usuario de área está activo: hay 2 usuarios activos"

    c = _cliente("20111111110", "jefa")
    r = c.post("/admin/usuario/baja", data={"id": str(jefa_id)}, follow_redirects=False)
    assert r.status_code == 303
    assert "err=ultimoadmin" in r.headers.get("location", ""), "tiene que rebotar"
    with Session(db.engine) as s:
        assert s.get(UsuarioSindicato, jefa_id).activo, "la Jefa sigue activa"
    print("OK  test_no_se_puede_desactivar_al_ultimo_super_admin")


def test_se_puede_desactivar_un_super_admin_si_queda_otro():
    c = _cliente("20111111110", "jefa")
    r = c.post("/admin/usuario", data={
        "usuario": "20111111112", "nombre": "Segunda Jefa", "clave_inicial": "otra",
        "rol": "super"},
        follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        jefa_id = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20111111110")).first().id
    r = c.post("/admin/usuario/baja", data={"id": str(jefa_id)}, follow_redirects=False)
    assert "err=ultimoadmin" not in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert not s.get(UsuarioSindicato, jefa_id).activo
        # Se deja como estaba para no afectar a otros tests.
        u = s.get(UsuarioSindicato, jefa_id)
        u.activo = True
        s.add(u); s.commit()
    print("OK  test_se_puede_desactivar_un_super_admin_si_queda_otro")


def test_desactivar_un_usuario_de_area_no_toca_el_guard():
    """El guard es sobre Super Admins: un usuario de área se puede dar de
    baja siempre, aunque sea el último de su área."""
    c = _cliente("20111111110", "jefa")
    with Session(db.engine) as s:
        gid = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == "20111111111")).first().id
    r = c.post("/admin/usuario/baja", data={"id": str(gid)}, follow_redirects=False)
    assert "err=ultimoadmin" not in r.headers.get("location", "")
    with Session(db.engine) as s:
        assert not s.get(UsuarioSindicato, gid).activo
        u = s.get(UsuarioSindicato, gid)
        u.activo = True
        s.add(u); s.commit()
    print("OK  test_desactivar_un_usuario_de_area_no_toca_el_guard")


if __name__ == "__main__":
    test_toda_ruta_admin_esta_clasificada()
    test_no_hay_entradas_muertas_en_el_registro()
    test_las_secciones_del_registro_existen_en_el_catalogo()
    test_las_exentas_son_solo_entrar_salir_y_las_pantallas()
    test_los_datos_del_dashboard_si_estan_gateados()
    test_la_gestion_de_usuarios_es_solo_de_super_admin()
    test_super_admin_pasa_donde_el_de_area_no()
    test_usuario_de_area_pasa_donde_si_tiene_permiso()
    test_usuario_de_area_403_en_seccion_que_no_tiene()
    test_usuario_de_area_no_puede_crear_usuarios()
    test_responder_tramites_no_habilita_crear_formularios()
    test_quitar_el_permiso_vale_sin_volver_a_loguearse()
    test_desactivar_el_area_deja_a_todo_el_equipo_afuera()
    test_formulas_y_conceptos_ahora_respetan_el_modulo_recibos()
    test_usuario_de_area_no_entra_al_panel_sindical()
    test_usuario_de_area_no_toca_los_documentos_del_convenio()
    test_darle_la_seccion_le_abre_el_panel_sindical()
    test_no_se_puede_desactivar_al_ultimo_super_admin()
    test_se_puede_desactivar_un_super_admin_si_queda_otro()
    test_desactivar_un_usuario_de_area_no_toca_el_guard()
    print("\nTodos los tests de gateo de rutas pasaron.")

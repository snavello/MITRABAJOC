"""QA del panel del registro confirmado (PLAN_REGISTRO.md §4.4, §4.5 y D3):
confirmar identidad, restablecer clave, nivel 3 en /api/validar e interruptor.

No es regresión del desarrollador: es la evidencia de la revisión de QA. Los
tests marcados ROJO afirman lo que la seguridad o el plan piden y HOY FALLAN;
cada uno cita su hallazgo (QD-n) del reporte. Los demás documentan que lo
revisado está bien y evitan que se rompa.

Correr con: python -m pytest test_qa_registro_panel.py -q
"""
import os
import re
from pathlib import Path

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from fastapi.testclient import TestClient
from sqlmodel import select

import auth
import db
import main
from db import (Area, CuentaEmpleador, CuentaTrabajador, Empleador, PermisoArea,
                Seccional, Sindicato, Trabajador, UsuarioSindicato)

db.crear_tablas()

CLAVE = "clave-inicial-1"

# Todos con dígito verificador válido.
V_ALTA_A = "20512345671"       # víctima de QD-1: cuenta nivel 4 en el padrón de B
V_CONF_A = "27534567893"       # víctima de QD-1 (confirmar identidad)
V_FUGA = "20606060603"         # QD-6 (fuga de nivel entre sindicatos)
V_DATOS = "20700000002"        # alta que pisa datos personales
PLURI = "27712345670"          # empadronado en A (Rosario) y en B
FORJA = "20812345673"          # afiliado de A nivel 1 (QD-2)
SEC2 = "27912345675"           # empadronado en A, seccional Mendoza
SIN_SECCIONAL = "23999999999"  # en A, sin seccional
SIN_FILA = "27888888883"       # en el padrón de A, SIN fila de persona
CUIT_VICTIMA = "30712345671"   # empresa con cuenta, empleadora solo en B
CUIT_PROPIO = "30700000016"    # empresa con cuenta, empleadora en A


def _validos(*numeros):
    import cuit
    for n in numeros:
        assert cuit.es_valido(n), n


_validos(V_ALTA_A, V_CONF_A, V_FUGA, V_DATOS, PLURI, FORJA, SEC2, SIN_SECCIONAL, SIN_FILA,
         CUIT_VICTIMA, CUIT_PROPIO)


def _cuenta(s, cuil, nombre, nivel=1, origen="cuil_padron"):
    db.guardar_datos_personales(s, cuil, nombre=nombre, mail=f"{nombre.split()[0].lower()}@ejemplo.com")
    c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
    c.clave_hash = auth.hashear_clave(CLAVE)
    c.nivel_fiabilidad, c.nivel_origen = nivel, origen
    s.add(c)


with db.get_session() as s:
    sa = Sindicato(nombre="QD Sindicato A", slug="qd-a", color_base="#0f1b2d",
                   modulos_habilitados=["recibos", "empleadores"])
    sb = Sindicato(nombre="QD Sindicato B", slug="qd-b", color_base="#0f1b2d",
                   modulos_habilitados=["recibos", "empleadores"])
    sc = Sindicato(nombre="QD Sindicato C sin empleadores", slug="qd-c", color_base="#0f1b2d",
                   modulos_habilitados=["recibos"])
    s.add(sa); s.add(sb); s.add(sc); s.commit()
    for x in (sa, sb, sc):
        s.refresh(x)
    A, B, C = sa.id, sb.id, sc.id
    ros = Seccional(sindicato_id=A, nombre="Rosario")
    men = Seccional(sindicato_id=A, nombre="Mendoza")
    s.add(ros); s.add(men); s.commit(); s.refresh(ros); s.refresh(men)
    ROS, MEN = ros.id, men.id

    # Víctimas: viven en el padrón de B, nunca en el de A.
    for cuil, nom in ((V_ALTA_A, "Vilma Victima"), (V_CONF_A, "Vera Victima"),
                      (V_FUGA, "Valeria Victima"), (V_DATOS, "Vicky Victima")):
        s.add(Trabajador(sindicato_id=B, cuil=cuil, registrado=True))
        _cuenta(s, cuil, nom, nivel=4, origen="presencial")
    # Pluriempleo: la misma persona en A y en B.
    s.add(Trabajador(sindicato_id=A, cuil=PLURI, seccional_id=ROS, registrado=True))
    s.add(Trabajador(sindicato_id=B, cuil=PLURI, registrado=True))
    _cuenta(s, PLURI, "Pluri Empleado")
    s.add(Trabajador(sindicato_id=A, cuil=FORJA, seccional_id=ROS, registrado=True))
    _cuenta(s, FORJA, "Fabian Forja")
    s.add(Trabajador(sindicato_id=A, cuil=SEC2, seccional_id=MEN, registrado=True))
    _cuenta(s, SEC2, "Sergio Segundo")
    s.add(Trabajador(sindicato_id=A, cuil=SIN_SECCIONAL, registrado=True))
    _cuenta(s, SIN_SECCIONAL, "Sofia Sinseccional")
    s.add(Trabajador(sindicato_id=A, cuil=SIN_FILA, seccional_id=ROS))  # sin CuentaTrabajador

    s.add(Empleador(sindicato_id=B, cuit=CUIT_VICTIMA, razon_social="Victima SA"))
    s.add(CuentaEmpleador(cuit=CUIT_VICTIMA, clave_hash=auth.hashear_clave(CLAVE),
                          nivel_fiabilidad=4, nivel_origen="presencial"))
    s.add(Empleador(sindicato_id=A, cuit=CUIT_PROPIO, razon_social="Propia SA"))
    s.add(CuentaEmpleador(cuit=CUIT_PROPIO, clave_hash=auth.hashear_clave(CLAVE)))

    def usuario(sid, cuil, clave, **kw):
        s.add(UsuarioSindicato(sindicato_id=sid, usuario=cuil, nombre=cuil,
                               clave_hash=auth.hashear_clave(clave), debe_cambiar_clave=False, **kw))
    usuario(A, "20577777771", "super-a", es_super_admin=True)
    usuario(C, "20577777772", "super-c", es_super_admin=True)
    usuario(A, "20588888882", "ros-a", es_admin_seccional=True, seccional_id=ROS)
    a_trab = Area(sindicato_id=A, seccional_id=ROS, nombre="Padrón Rosario")
    a_emp = Area(sindicato_id=A, seccional_id=ROS, nombre="Empresas Rosario")
    s.add(a_trab); s.add(a_emp); s.commit(); s.refresh(a_trab); s.refresh(a_emp)
    s.add(PermisoArea(area_id=a_trab.id, seccion="trabajadores"))
    s.add(PermisoArea(area_id=a_emp.id, seccion="emp_empresas"))
    usuario(A, "20599999993", "padron-a", area_id=a_trab.id, seccional_id=ROS)
    usuario(A, "20599999994", "emp-a", area_id=a_emp.id, seccional_id=ROS)
    s.commit()


def _admin(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _afiliado(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


def _cuenta_de(cuil):
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        return None if c is None else (c.clave_hash, c.nivel_fiabilidad, c.nivel_origen,
                                       c.clave_temporal, c.nombre, c.mail)


def _cuenta_emp(cuit):
    with db.get_session() as s:
        c = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
        return c.clave_hash, c.nivel_fiabilidad, c.clave_temporal


def _alta_en_a(admin, cuil, nombre="Impostor Alta"):
    """El alta manual del padrón de A: cualquier CUIL con verificador válido."""
    r = admin.post("/admin/trabajador", data={
        "cuil": cuil, "nombre": nombre, "provincia": "Santa Fe", "localidad": "Rosario",
        "seccional_id": str(ROS)}, follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers
    return r


SUPER_A = _admin("20577777771", "super-a")


# ================= QD-1  ROJO: tomar la cuenta de OTRO sindicato =================
# El restablecer/confirmar valida "el CUIL está en el padrón de ESTE sindicato",
# pero el padrón lo llena el propio admin con un alta manual de cualquier CUIL
# válido (el CUIL es un dato público). Alta + restablecer = tomar la cuenta de
# una persona que nunca estuvo en el sindicato del atacante.

def test_qd1_roja_un_admin_no_toma_la_cuenta_de_alguien_que_solo_esta_en_otro_sindicato():
    antes = _cuenta_de(V_ALTA_A)
    _alta_en_a(SUPER_A, V_ALTA_A)
    r = SUPER_A.post("/admin/trabajador/restablecer-clave", data={"cuil": V_ALTA_A},
                     follow_redirects=False)
    despues = _cuenta_de(V_ALTA_A)
    assert despues[0] == antes[0], (
        "QD-1: el admin de A dio de alta el CUIL de una persona de B y le cambió la clave "
        f"(HTTP {r.status_code}); ahora puede entrar a la cuenta de B como esa persona")


def test_qd1_roja_un_admin_no_sube_a_nivel_4_la_cuenta_de_otro_sindicato():
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == V_CONF_A)).first()
        c.nivel_fiabilidad, c.nivel_origen = 2, "mail_declarado"   # un impostor llegó primero
        s.add(c); s.commit()
    _alta_en_a(SUPER_A, V_CONF_A)
    SUPER_A.post("/admin/trabajador/confirmar-identidad", data={"cuil": V_CONF_A},
                 follow_redirects=False)
    assert _cuenta_de(V_CONF_A)[1:3] == (2, "mail_declarado"), (
        "QD-1: A 'confirmó en persona' a alguien que no es de A; B lo verá como 4 · confirmado")


def test_qd1_roja_lo_mismo_con_una_empresa_que_solo_es_empleadora_de_otro_sindicato():
    antes = _cuenta_emp(CUIT_VICTIMA)
    SUPER_A.post("/admin/empleador", data={"cuit": CUIT_VICTIMA, "razon_social": "Alta de A"},
                 follow_redirects=False)
    r = SUPER_A.post("/admin/empleador/restablecer-clave", data={"cuit": CUIT_VICTIMA},
                     follow_redirects=False)
    assert _cuenta_emp(CUIT_VICTIMA)[0] == antes[0], (
        f"QD-1: A tomó la cuenta de empresa de B (HTTP {r.status_code})")


def test_qd1_roja_el_alta_de_a_tampoco_pisa_nombre_ni_mail_de_la_persona_de_b():
    """Preexistente pero lo vuelve explotable: el MAIL del padrón es el canal de
    recuperación de la Etapa 4. Alta de A con mail propio = secuestro de la recuperación."""
    antes = _cuenta_de(V_DATOS)
    SUPER_A.post("/admin/trabajador", data={
        "cuil": V_DATOS, "nombre": "Nombre Falso", "provincia": "Santa Fe", "localidad": "Rosario",
        "mail": "atacante@ejemplo.com", "seccional_id": str(ROS)}, follow_redirects=False)
    despues = _cuenta_de(V_DATOS)
    assert (despues[4], despues[5]) == (antes[4], antes[5]), (
        f"QD-1b: el alta de A reescribió nombre/mail de una cuenta ajena: {antes[4:]} -> {despues[4:]}")


def test_qd6_roja_el_panel_de_a_no_revela_el_nivel_de_una_cuenta_de_otro_sindicato():
    """Con el alta de un CUIL ajeno, el atacante lee si tiene cuenta y su nivel/origen."""
    _alta_en_a(SUPER_A, V_FUGA)
    html = SUPER_A.get("/admin").text
    fila = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % V_FUGA, html, re.S).group(0)
    assert "confirmado" not in fila and "restablecer-clave" not in fila, (
        "QD-6: el panel de A muestra '4 · confirmado' y los botones de una cuenta que es de B")


# ================= QD-2  ROJO: el nivel 3 se falsifica con un POST =================

def test_qd2_roja_un_recibo_inventado_no_sube_a_nivel_3():
    """/api/validar recibe el recibo del CLIENTE (CLAUDE.md: 'esa ruta se puede
    llamar sola con cualquier payload'). El nivel 3 se otorga mirando
    recibo.empleado.cuil, que el atacante escribe: un impostor que solo conoce el
    CUIL (público) llega a 3 sin tener ningún documento."""
    antes = _cuenta_de(FORJA)[1:3]
    forjado = {"recibo": {"periodo": "2026-08", "empleado": {"cuil": FORJA},
                          "empleador": {"nombre": "Nada SA", "cuit": None},
                          "lineas": [], "totales_impresos": {}}, "conceptos_nuevos": []}
    r = _afiliado(FORJA).post("/api/validar", json=forjado)
    assert r.status_code == 200, r.text
    assert _cuenta_de(FORJA)[1:3] == antes, (
        "QD-2: con un JSON armado a mano la cuenta pasó a nivel 3 'recibo propio'; "
        "el nivel no acredita nada")


# ================= QD-3  ROJO: la clave temporal no obliga a nada =================

def test_qd3_roja_algo_lee_clave_temporal_al_entrar():
    fuente = Path(main.__file__).read_text(encoding="utf-8")
    usos = [ln for ln in fuente.splitlines()
            if "clave_temporal" in ln and "clave_temporal = True" not in ln
            and "_clave_temporal_nueva" not in ln and "_pagina_clave_temporal" not in ln
            and "clave_temporal.html" not in ln
            and not ln.strip().startswith(("#", '"""', "def "))]
    assert usos, ("QD-3: ninguna ruta lee `clave_temporal`: el login no fuerza el cambio y la "
                  "pantalla promete 'al entrar tiene que cambiarla'")


def test_qd3_roja_existe_alguna_ruta_para_que_el_afiliado_cambie_su_clave():
    rutas = {getattr(r, "path", "") for r in main.app.routes}
    candidatas = [p for p in rutas if "clave" in p and "restablecer" not in p and "publica" not in p
                  and not p.startswith(("/plataforma", "/admin", "/entornos"))]
    assert candidatas, ("QD-3: no hay ninguna ruta de afiliado/empresa para cambiar la clave; "
                        "la 'temporal' queda como definitiva")


# ================= QD-4  ROJO: pluriempleo, el aviso =================

def test_qd4_roja_la_pantalla_avisa_que_la_clave_es_unica_para_todos_los_sindicatos():
    html = SUPER_A.get("/admin").text
    form = re.search(r'<form[^>]*restablecer-clave[^>]*>.*?name="cuil" value="%s"' % PLURI,
                     html, re.S)
    assert form, "el botón debería existir para una cuenta con clave"
    r = SUPER_A.post("/admin/trabajador/restablecer-clave", data={"cuil": PLURI})
    texto = form.group(0) + r.text
    assert re.search(r"(otros|todos los) (sindicatos|gremios)", texto, re.I), (
        "QD-4: restablecer la clave de un CUIL pluriempleado le cambia la clave en los demás "
        "sindicatos y ni la confirmación ni la pantalla de la clave lo dicen")
    # la consecuencia que el aviso debería anunciar
    assert _cuenta_de(PLURI)[3] is True


# ================= QD-5  ROJO: Admin de Seccional ve botones fuera de su alcance =================

def test_qd5_roja_el_admin_de_seccional_no_ve_botones_de_otra_seccional():
    html = _admin("20588888882", "ros-a").get("/admin").text
    m = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % SEC2, html, re.S)
    fila = m.group(0) if m else ""
    assert "restablecer-clave" not in fila and "confirmar-identidad" not in fila, (
        "QD-5: el Admin de Seccional Rosario ve (y toca, para recibir 403) los botones de Mendoza, "
        "y el nivel de sus cuentas")


# ================= Lo que está bien (documentado) =================

def test_ok_admin_de_seccional_y_alcance():
    ros = _admin("20588888882", "ros-a")
    for cuil in (SEC2, SIN_SECCIONAL):     # otra seccional / sin seccional: fail-closed
        for ruta in ("confirmar-identidad", "restablecer-clave"):
            antes = _cuenta_de(cuil)
            r = ros.post(f"/admin/trabajador/{ruta}", data={"cuil": cuil}, follow_redirects=False)
            assert r.status_code == 403, (cuil, ruta, r.status_code)
            assert _cuenta_de(cuil) == antes


def test_ok_usuario_de_area_con_trabajadores_respeta_la_seccional_y_no_toca_empleadores():
    pad = _admin("20599999993", "padron-a")
    assert pad.post("/admin/trabajador/restablecer-clave", data={"cuil": SEC2},
                    follow_redirects=False).status_code == 403
    for ruta in ("confirmar-identidad", "restablecer-clave"):
        assert pad.post(f"/admin/empleador/{ruta}", data={"cuit": CUIT_PROPIO},
                        follow_redirects=False).status_code == 403
    emp = _admin("20599999994", "emp-a")
    for ruta in ("confirmar-identidad", "restablecer-clave"):
        assert emp.post(f"/admin/trabajador/{ruta}", data={"cuil": FORJA},
                        follow_redirects=False).status_code == 403


def test_ok_las_cuatro_rutas_estan_clasificadas_en_la_seccion_correcta():
    for ruta in ("confirmar-identidad", "restablecer-clave"):
        assert main.PERMISOS_RUTAS[f"/admin/trabajador/{ruta}"] == "trabajadores"
        assert main.PERMISOS_RUTAS[f"/admin/empleador/{ruta}"] == "emp_empresas"


def test_ok_sin_el_modulo_empleadores_las_rutas_de_empresa_dan_403():
    c = _admin("20577777772", "super-c")
    for ruta in ("confirmar-identidad", "restablecer-clave"):
        assert c.post(f"/admin/empleador/{ruta}", data={"cuit": CUIT_PROPIO},
                      follow_redirects=False).status_code == 403


def test_ok_sin_sesion_no_se_puede():
    anon = TestClient(main.app)
    for ruta in ("/admin/trabajador/confirmar-identidad", "/admin/trabajador/restablecer-clave",
                 "/admin/empleador/confirmar-identidad", "/admin/empleador/restablecer-clave"):
        r = anon.post(ruta, data={"cuil": FORJA, "cuit": CUIT_PROPIO}, follow_redirects=False)
        assert r.status_code in (303, 401, 403), (ruta, r.status_code)
        assert _cuenta_de(FORJA)[3] is False


def test_ok_recargar_genera_otra_clave_y_la_anterior_deja_de_servir():
    r1 = SUPER_A.post("/admin/trabajador/restablecer-clave", data={"cuil": FORJA})
    k1 = re.search(r'id="clave-temporal">([^<]+)<', r1.text).group(1)
    r2 = SUPER_A.post("/admin/trabajador/restablecer-clave", data={"cuil": FORJA})
    k2 = re.search(r'id="clave-temporal">([^<]+)<', r2.text).group(1)
    assert k1 != k2
    h = _cuenta_de(FORJA)[0]
    assert auth.verificar_clave(k2, h) and not auth.verificar_clave(k1, h)
    assert h.startswith("pbkdf2") or "$" in h and k2 not in h
    for r in (r1, r2):
        assert "no-store" in r.headers["cache-control"]
        assert "location" not in r.headers
        assert k2 not in str(r.headers) and k1 not in str(r.headers)


def test_ok_la_clave_no_aparece_en_el_panel_al_volver():
    r = SUPER_A.post("/admin/trabajador/restablecer-clave", data={"cuil": FORJA})
    k = re.search(r'id="clave-temporal">([^<]+)<', r.text).group(1)
    assert k not in SUPER_A.get("/admin").text
    assert k not in SUPER_A.get("/admin?ok=identidad").text


def test_ok_restablecer_a_alguien_sin_fila_de_persona_no_crea_nada():
    r = SUPER_A.post("/admin/trabajador/restablecer-clave", data={"cuil": SIN_FILA},
                     follow_redirects=False)
    assert r.status_code == 303 and "err=sincuenta" in r.headers["location"]
    assert _cuenta_de(SIN_FILA) is None
    r = SUPER_A.post("/admin/trabajador/confirmar-identidad", data={"cuil": SIN_FILA},
                     follow_redirects=False)
    assert "err=sincuenta" in r.headers["location"] and _cuenta_de(SIN_FILA) is None
    # y el panel con una fila así no se rompe
    assert SUPER_A.get("/admin").status_code == 200


def test_ok_un_nivel_4_no_baja_con_un_recibo_propio_forjado_o_real():
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == SEC2)).first()
        c.nivel_fiabilidad, c.nivel_origen = 4, "presencial"
        s.add(c); s.commit()
    payload = {"recibo": {"periodo": "2026-08", "empleado": {"cuil": SEC2}, "empleador": {},
                          "lineas": [], "totales_impresos": {}}, "conceptos_nuevos": []}
    assert _afiliado(SEC2).post("/api/validar", json=payload).status_code == 200
    assert _cuenta_de(SEC2)[1:3] == (4, "presencial")


def test_ok_un_recibo_de_otro_cuil_se_corta_y_no_toca_ningun_nivel():
    """E-RECIBO-04 corta antes del enganche: ni la cuenta de la sesión ni la del
    CUIL que dice el recibo cambian de nivel."""
    antes_s, antes_o = _cuenta_de(SIN_SECCIONAL)[1:3], _cuenta_de(PLURI)[1:3]
    r = _afiliado(SIN_SECCIONAL).post("/api/validar", json={"recibo": {
        "periodo": "2026-08", "empleado": {"cuil": PLURI}, "empleador": {},
        "lineas": [], "totales_impresos": {}}, "conceptos_nuevos": []})
    assert r.json().get("estado") == "CUIL_NO_COINCIDE"
    assert _cuenta_de(SIN_SECCIONAL)[1:3] == antes_s and _cuenta_de(PLURI)[1:3] == antes_o


def test_ok_el_default_del_modelo_y_del_formulario_coinciden():
    assert Sindicato(nombre="x").acepta_mail_declarado is True
    html = Path("templates/plataforma.html").read_text(encoding="utf-8")
    assert re.search(r'id="sind-acepta-mail-declarado" checked', html)
    assert "s.acepta_mail_declarado !== false" in html

"""Registro confirmado por mail, lado del panel (PLAN_REGISTRO.md, etapa 3 y D6):
nivel 3 automático, nivel 4 a mano, restablecer clave y el interruptor por sindicato.

Cubre:
- /api/validar: un recibo propio sube la cuenta a nivel 3; un nivel 4 no baja;
  un recibo AJENO se corta antes y no toca el nivel; un recibo sin CUIL leído no
  acredita nada.
- Confirmar identidad (nivel 4) dentro del alcance de seccional: el Admin de
  Seccional no confirma a un afiliado de otra seccional; un usuario de área sin
  la sección `trabajadores` recibe 403; un CUIL de otro sindicato es 404; una
  persona sin cuenta no se confirma.
- Restablecer clave: la clave temporal entra, marca `clave_temporal`, se
  muestra UNA vez en el cuerpo y NUNCA en una URL; la anterior deja de servir.
- Empleadores: lo mismo con el CUIT y la sección `emp_empresas`.
- Interruptor "acepta mail declarado" en el alta y la edición del sindicato.
- La columna Nivel de /admin con la etiqueta que corresponde.

Correr con: .venv/Scripts/python.exe -m pytest test_registro_panel.py -q
"""
import os
import re

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

from fastapi.testclient import TestClient
from sqlmodel import select

import auth
import db
import main
from db import (Area, CuentaEmpleador, CuentaTrabajador, Empleador, PermisoArea,
                Seccional, Sindicato, Trabajador, UsuarioPlataforma, UsuarioSindicato)

db.crear_tablas()

# Todos con dígito verificador válido (los que importan para altas; acá se cargan directo).
CUIL_PROPIO = "20511111115"      # SEC_1, cuenta nivel 1
CUIL_NIVEL4 = "27522222226"      # SEC_1, cuenta nivel 4
CUIL_OTRA_SEC = "20533333339"    # SEC_2, cuenta nivel 1
CUIL_SIN_CUENTA = "27544444440"  # SEC_1, en el padrón, sin clave
CUIL_DECLARADO = "20555555552"   # SEC_1, nivel 2 mail declarado
CUIL_AJENO = "20566666668"       # padrón de OTRO sindicato
CUIT_EMP = "30711111110"         # empleador con cuenta
CUIT_EMP_SIN = "30722222221"     # empleador sin cuenta

CLAVE_INICIAL = "clave-inicial-1"


def _cuenta(s, cuil, nombre, nivel=1, origen="cuil_padron", con_clave=True):
    db.guardar_datos_personales(s, cuil, nombre=nombre)
    c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
    if con_clave:
        c.clave_hash = auth.hashear_clave(CLAVE_INICIAL)
    c.nivel_fiabilidad, c.nivel_origen = nivel, origen
    s.add(c)


with db.get_session() as s:
    sind = Sindicato(nombre="Reg Panel", slug="reg-panel", color_base="#0f1b2d",
                     modulos_habilitados=["recibos", "empleadores"])
    otro = Sindicato(nombre="Reg Panel Ajeno", slug="reg-panel-ajeno", color_base="#0f1b2d",
                     modulos_habilitados=["recibos"])
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID, SID_OTRO = sind.id, otro.id

    sec_1 = Seccional(sindicato_id=SID, nombre="Rosario")
    sec_2 = Seccional(sindicato_id=SID, nombre="Mendoza")
    s.add(sec_1); s.add(sec_2); s.commit(); s.refresh(sec_1); s.refresh(sec_2)
    SEC_1, SEC_2 = sec_1.id, sec_2.id

    for cuil, sec in ((CUIL_PROPIO, SEC_1), (CUIL_NIVEL4, SEC_1), (CUIL_OTRA_SEC, SEC_2),
                      (CUIL_SIN_CUENTA, SEC_1), (CUIL_DECLARADO, SEC_1)):
        s.add(Trabajador(sindicato_id=SID, cuil=cuil, seccional_id=sec, registrado=True))
    s.add(Trabajador(sindicato_id=SID_OTRO, cuil=CUIL_AJENO, registrado=True))
    _cuenta(s, CUIL_PROPIO, "Pablo Propio")
    _cuenta(s, CUIL_NIVEL4, "Nora Nivelcuatro", nivel=4, origen="presencial")
    _cuenta(s, CUIL_OTRA_SEC, "Omar Otrasec")
    _cuenta(s, CUIL_SIN_CUENTA, "Sara Sincuenta", con_clave=False)
    _cuenta(s, CUIL_DECLARADO, "Dora Declarada", nivel=2, origen="mail_declarado")
    _cuenta(s, CUIL_AJENO, "Ajeno Total")

    s.add(Empleador(sindicato_id=SID, cuit=CUIT_EMP, razon_social="Con Cuenta SA"))
    s.add(Empleador(sindicato_id=SID, cuit=CUIT_EMP_SIN, razon_social="Sin Cuenta SRL"))
    s.add(CuentaEmpleador(cuit=CUIT_EMP, clave_hash=auth.hashear_clave(CLAVE_INICIAL)))

    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20577777771", nombre="Super",
                           clave_hash=auth.hashear_clave("super-demo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20588888882", nombre="Admin Rosario",
                           clave_hash=auth.hashear_clave("ros-demo"), debe_cambiar_clave=False,
                           es_admin_seccional=True, seccional_id=SEC_1))
    area = Area(sindicato_id=SID, seccional_id=SEC_1, nombre="Tesorería Rosario")
    s.add(area); s.commit(); s.refresh(area)
    s.add(PermisoArea(area_id=area.id, seccion="reportes"))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20599999993", nombre="Tesorera",
                           clave_hash=auth.hashear_clave("teso-demo"), debe_cambiar_clave=False,
                           area_id=area.id, seccional_id=SEC_1))
    s.add(UsuarioPlataforma(usuario="opera", nombre="Operadora",
                            clave_hash=auth.hashear_clave("claveLarga2026"), rol="superadmin",
                            debe_cambiar_clave=False, debe_completar_datos=False, creado_por="test"))
    s.commit()


def _admin(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _plataforma():
    c = TestClient(main.app)
    r = c.post("/plataforma/login", data={"usuario": "opera", "clave": "claveLarga2026"},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _afiliado(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


def _nivel(cuil):
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        return c.nivel_fiabilidad, c.nivel_origen


def _nivel_emp(cuit):
    with db.get_session() as s:
        c = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
        return c.nivel_fiabilidad, c.nivel_origen


def _payload(cuil_recibo):
    empleado = {"cuil": cuil_recibo} if cuil_recibo is not None else {}
    return {"recibo": {"periodo": "2026-08", "empleado": empleado,
                       "empleador": {"nombre": "Algo SA", "cuit": None},
                       "lineas": [], "totales_impresos": {}},
            "conceptos_nuevos": []}


SUPER = _admin("20577777771", "super-demo")


# ---------- 1. Nivel 3 automático (/api/validar) ----------

def test_recibo_propio_sube_a_nivel_3():
    assert _nivel(CUIL_PROPIO) == (1, "cuil_padron")
    r = _afiliado(CUIL_PROPIO).post("/api/validar", json=_payload(CUIL_PROPIO))
    assert r.status_code == 200, r.text
    assert r.json().get("estado") != "CUIL_NO_COINCIDE"
    assert _nivel(CUIL_PROPIO) == (3, "recibo_propio")
    print("OK  test_recibo_propio_sube_a_nivel_3")


def test_un_nivel_4_no_baja_con_un_recibo_propio():
    r = _afiliado(CUIL_NIVEL4).post("/api/validar", json=_payload(CUIL_NIVEL4))
    assert r.status_code == 200, r.text
    assert _nivel(CUIL_NIVEL4) == (4, "presencial")
    print("OK  test_un_nivel_4_no_baja_con_un_recibo_propio")


def test_un_recibo_ajeno_se_corta_y_no_toca_el_nivel():
    antes = _nivel(CUIL_OTRA_SEC)
    r = _afiliado(CUIL_OTRA_SEC).post("/api/validar", json=_payload(CUIL_PROPIO))
    assert r.status_code == 200
    assert r.json()["estado"] == "CUIL_NO_COINCIDE"
    assert _nivel(CUIL_OTRA_SEC) == antes == (1, "cuil_padron")
    print("OK  test_un_recibo_ajeno_se_corta_y_no_toca_el_nivel")


def test_un_recibo_sin_cuil_leido_no_acredita_nada():
    """Pasa el corte de pertenencia (no hay un CUIL distinto que comparar), pero
    sin el CUIL leído no hay nada que acredite que el recibo es de la persona."""
    antes = _nivel(CUIL_DECLARADO)
    r = _afiliado(CUIL_DECLARADO).post("/api/validar", json=_payload(None))
    assert r.status_code == 200, r.text
    assert _nivel(CUIL_DECLARADO) == antes == (2, "mail_declarado")
    print("OK  test_un_recibo_sin_cuil_leido_no_acredita_nada")


# ---------- 2. Confirmar identidad (nivel 4) ----------

def test_confirmar_identidad_sube_a_4():
    r = SUPER.post("/admin/trabajador/confirmar-identidad", data={"cuil": CUIL_DECLARADO},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin?ok=identidad")
    assert _nivel(CUIL_DECLARADO) == (4, "presencial")
    print("OK  test_confirmar_identidad_sube_a_4")


def test_admin_de_seccional_no_confirma_fuera_de_su_seccional():
    ros = _admin("20588888882", "ros-demo")
    r = ros.post("/admin/trabajador/confirmar-identidad", data={"cuil": CUIL_OTRA_SEC},
                 follow_redirects=False)
    assert r.status_code == 403, r.text
    assert _nivel(CUIL_OTRA_SEC) == (1, "cuil_padron")
    # y la clave tampoco se restablece
    with db.get_session() as s:
        antes = s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.cuil == CUIL_OTRA_SEC)).first().clave_hash
    r = ros.post("/admin/trabajador/restablecer-clave", data={"cuil": CUIL_OTRA_SEC},
                 follow_redirects=False)
    assert r.status_code == 403
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_OTRA_SEC)).first()
        assert c.clave_hash == antes and c.clave_temporal is False
    print("OK  test_admin_de_seccional_no_confirma_fuera_de_su_seccional")


def test_admin_de_seccional_si_confirma_dentro_de_la_suya():
    ros = _admin("20588888882", "ros-demo")
    r = ros.post("/admin/trabajador/confirmar-identidad", data={"cuil": CUIL_PROPIO},
                 follow_redirects=False)
    assert r.status_code == 303, r.text
    assert _nivel(CUIL_PROPIO) == (4, "presencial")
    print("OK  test_admin_de_seccional_si_confirma_dentro_de_la_suya")


def test_usuario_de_area_sin_la_seccion_trabajadores_recibe_403():
    teso = _admin("20599999993", "teso-demo")
    for ruta in ("/admin/trabajador/confirmar-identidad", "/admin/trabajador/restablecer-clave"):
        r = teso.post(ruta, data={"cuil": CUIL_NIVEL4}, follow_redirects=False)
        assert r.status_code == 403, f"{ruta} dio {r.status_code}"
    for ruta in ("/admin/empleador/confirmar-identidad", "/admin/empleador/restablecer-clave"):
        r = teso.post(ruta, data={"cuit": CUIT_EMP}, follow_redirects=False)
        assert r.status_code == 403, f"{ruta} dio {r.status_code}"
    print("OK  test_usuario_de_area_sin_la_seccion_trabajadores_recibe_403")


def test_un_cuil_de_otro_sindicato_es_404():
    for ruta in ("/admin/trabajador/confirmar-identidad", "/admin/trabajador/restablecer-clave"):
        r = SUPER.post(ruta, data={"cuil": CUIL_AJENO}, follow_redirects=False)
        assert r.status_code == 404, f"{ruta} dio {r.status_code}"
    assert _nivel(CUIL_AJENO) == (1, "cuil_padron")
    print("OK  test_un_cuil_de_otro_sindicato_es_404")


def test_sin_cuenta_no_hay_nada_que_confirmar_ni_restablecer():
    for ruta in ("/admin/trabajador/confirmar-identidad", "/admin/trabajador/restablecer-clave"):
        r = SUPER.post(ruta, data={"cuil": CUIL_SIN_CUENTA}, follow_redirects=False)
        assert r.status_code == 303 and "err=sincuenta" in r.headers["location"], ruta
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_SIN_CUENTA)).first()
        assert c.clave_hash == "" and c.nivel_fiabilidad == 1 and not c.clave_temporal
    print("OK  test_sin_cuenta_no_hay_nada_que_confirmar_ni_restablecer")


# ---------- 3. Restablecer clave ----------

def _clave_de(texto: str) -> str:
    m = re.search(r'id="clave-temporal">([^<]+)<', texto)
    assert m, texto
    return m.group(1)


def test_restablecer_clave_trabajador():
    r = SUPER.post("/admin/trabajador/restablecer-clave", data={"cuil": CUIL_OTRA_SEC},
                   follow_redirects=False)
    assert r.status_code == 200, r.text
    assert "location" not in r.headers          # nada de redirect con la clave en la URL
    assert "no-store" in r.headers["cache-control"]
    tmp = _clave_de(r.text)
    assert len(tmp) == 8 and not set(tmp) & set("0O1lI"), tmp
    assert r.text.count(tmp) == 1               # se muestra una sola vez
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_OTRA_SEC)).first()
        assert c.clave_temporal is True
        assert auth.verificar_clave(tmp, c.clave_hash)
        assert not auth.verificar_clave(CLAVE_INICIAL, c.clave_hash)
        assert tmp not in c.clave_hash          # no se guarda en claro
    # entra en el login del afiliado
    login = TestClient(main.app).post("/trabajador/login", data={"cuil": CUIL_OTRA_SEC, "clave": tmp},
                                      follow_redirects=False)
    assert login.status_code == 303 and "error" not in login.headers["location"]
    print("OK  test_restablecer_clave_trabajador")


def test_restablecer_clave_empleador():
    r = SUPER.post("/admin/empleador/restablecer-clave", data={"cuit": CUIT_EMP},
                   follow_redirects=False)
    assert r.status_code == 200, r.text
    assert "location" not in r.headers
    tmp = _clave_de(r.text)
    assert r.text.count(tmp) == 1
    with db.get_session() as s:
        c = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == CUIT_EMP)).first()
        assert c.clave_temporal is True and auth.verificar_clave(tmp, c.clave_hash)
    print("OK  test_restablecer_clave_empleador")


# ---------- 4. Empleadores: nivel 4 ----------

def test_confirmar_identidad_empleador():
    assert _nivel_emp(CUIT_EMP)[0] == 1
    r = SUPER.post("/admin/empleador/confirmar-identidad", data={"cuit": CUIT_EMP},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin?ok=identidad")
    assert _nivel_emp(CUIT_EMP) == (4, "presencial")
    # una empresa sin cuenta no se confirma
    r = SUPER.post("/admin/empleador/confirmar-identidad", data={"cuit": CUIT_EMP_SIN},
                   follow_redirects=False)
    assert r.status_code == 303 and "err=sincuenta" in r.headers["location"]
    # un CUIT que no es empleador de este sindicato: 404
    r = SUPER.post("/admin/empleador/confirmar-identidad", data={"cuit": "30799999994"},
                   follow_redirects=False)
    assert r.status_code == 404
    print("OK  test_confirmar_identidad_empleador")


# ---------- 5. Interruptor por sindicato ----------

def _acepta(sid):
    with db.get_session() as s:
        return s.get(Sindicato, sid).acepta_mail_declarado


def test_interruptor_en_alta_y_edicion():
    p = _plataforma()
    base = {"nombre": "Sind Interruptor A", "color_base": "#0f1b2d"}
    # alta con el checkbox tildado
    r = p.post("/plataforma/sindicato", data={**base, "acepta_mail_declarado": "true"},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    with db.get_session() as s:
        a = s.exec(select(Sindicato).where(Sindicato.nombre == "Sind Interruptor A")).first().id
    assert _acepta(a) is True
    # alta con el checkbox destildado (el navegador no manda nada)
    r = p.post("/plataforma/sindicato", data={"nombre": "Sind Interruptor B", "color_base": "#0f1b2d"},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    with db.get_session() as s:
        b = s.exec(select(Sindicato).where(Sindicato.nombre == "Sind Interruptor B")).first().id
    assert _acepta(b) is False
    # edición en los dos sentidos
    r = p.post("/plataforma/sindicato/editar",
               data={"id": a, "nombre": "Sind Interruptor A", "color_base": "#0f1b2d"},
               follow_redirects=False)
    assert r.status_code == 303 and _acepta(a) is False
    r = p.post("/plataforma/sindicato/editar",
               data={"id": a, "nombre": "Sind Interruptor A", "color_base": "#0f1b2d",
                     "acepta_mail_declarado": "true"}, follow_redirects=False)
    assert r.status_code == 303 and _acepta(a) is True
    print("OK  test_interruptor_en_alta_y_edicion")


def test_la_ficha_del_sindicato_trae_el_interruptor_nacido_tildado():
    r = _plataforma().get("/plataforma")
    assert r.status_code == 200
    assert 'name="acepta_mail_declarado"' in r.text
    assert re.search(r'id="sind-acepta-mail-declarado" checked', r.text)
    print("OK  test_la_ficha_del_sindicato_trae_el_interruptor_nacido_tildado")


# ---------- 6. La columna Nivel ----------

def test_la_columna_nivel_aparece_en_trabajadores_y_empleadores():
    # (el orden de los tests deja a CUIL_PROPIO en 4, a OTRA_SEC en 1 y a SIN_CUENTA sin cuenta)
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_OTRA_SEC)).first()
        c.nivel_fiabilidad, c.nivel_origen = 3, "recibo_propio"
        s.add(c); s.commit()
    r = SUPER.get("/admin")
    assert r.status_code == 200
    html = r.text
    assert "<th>Nivel</th>" in html
    assert "3 · recibo" in html and "4 · confirmado" in html
    assert "Declarados sin recibo" in html
    # una fila sin cuenta no lleva botones de cuenta
    fila = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % CUIL_SIN_CUENTA,
                     html, re.S).group(0)
    assert "restablecer-clave" not in fila and "confirmar-identidad" not in fila
    # la de nivel 4 no ofrece confirmar de nuevo, pero sí restablecer la clave
    fila4 = re.search(r'<tr class="fila-trabajador" data-cuil="%s".*?</tr>' % CUIL_NIVEL4,
                      html, re.S).group(0)
    assert "confirmar-identidad" not in fila4 and "restablecer-clave" in fila4
    # empleadores
    assert "4 · confirmado" in html.split("Empleadores cargados")[1]
    print("OK  test_la_columna_nivel_aparece_en_trabajadores_y_empleadores")


def test_el_filtro_de_declarados_marca_solo_nivel_2_mail_declarado():
    with db.get_session() as s:
        c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_SIN_CUENTA)).first()
        # fila sin cuenta con datos de nivel 2 declarado de más: no cuenta (no tiene cuenta)
        c.nivel_fiabilidad, c.nivel_origen = 2, "mail_declarado"
        s.add(c)
        d = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_DECLARADO)).first()
        d.nivel_fiabilidad, d.nivel_origen = 2, "mail_declarado"
        s.add(d); s.commit()
    html = SUPER.get("/admin").text
    marcadas = re.findall(r'data-cuil="(\d+)" data-nombre="[^"]*" data-declarado="1"', html)
    assert marcadas == [CUIL_DECLARADO], marcadas
    assert "2 · mail declarado" in html
    print("OK  test_el_filtro_de_declarados_marca_solo_nivel_2_mail_declarado")

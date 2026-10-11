"""Recuperación de clave, cambio de la clave temporal y confirmación del mail de
las cuentas viejas (PLAN_REGISTRO.md, D6 y D10; §4.3 y §4.6).

Lo que se cuida:

1. La recuperación autoservicio manda el código SOLO al mail del padrón; con el
   código la clave cambia y la vieja deja de servir. Con solo mail declarado, sin
   cuenta, sin clave o con el canal apagado, el servidor contesta LO MISMO, byte
   por byte, y no crea ningún código.
2. Un código de otra persona (o un token de otro propósito) no sirve; el cupo
   (3 por hora), el captcha y el freno por IP responden con sus códigos.
3. Una clave temporal obliga a elegir la propia ANTES de abrir la sesión: el
   login no deja cookie, el cambio exige la temporal y un token vencido no sirve.
4. Confirmar el mail sube de 1 a 2 (`mail_padron` o `mail_declarado`), el mail
   declarado NUNCA pisa `mail` (que es del sindicato), la portada ofrece la
   tarjeta solo al nivel 1 con el canal prendido, y sin sesión no se entra.
5. Los espejos de la empresa.

`correo.enviar` y `captcha.verificar` van simulados: ningún test sale a la red.

Correr con: python -m pytest test_recuperacion_clave.py -q
"""
import os
import re

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import captcha
import correo
import db
import main
from db import (CodigoVerificacion, CuentaEmpleador, CuentaTrabajador, Empleador,
                Sindicato, Trabajador)
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES
from sqlmodel import select

db.crear_tablas()

for _v in ("RESEND_API_KEY", "MAIL_REMITENTE", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
    os.environ.pop(_v, None)

with db.get_session() as s:
    _sind = Sindicato(nombre="Sindicato Recuperacion", slug="sindicato-recuperacion",
                      color_base="#0f1b2d", modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    _estricto = Sindicato(nombre="Sindicato Estricto", slug="sindicato-estricto-rec",
                          color_base="#0f1b2d", acepta_mail_declarado=False,
                          modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    s.add(_sind)
    s.add(_estricto)
    s.commit()
    s.refresh(_sind)
    s.refresh(_estricto)
    SID, SID_ESTRICTO = _sind.id, _estricto.id

VIEJA = "clave-vieja-1"
NUEVA = "clave-nueva-9"
MAIL = "ana.perez@ejemplo.com"


@pytest.fixture(autouse=True)
def canal(monkeypatch):
    """Canal de mail prendido y simulado; captcha apagado; frenos limpios."""
    enviados = []
    monkeypatch.setattr(correo, "habilitado", lambda: True)
    monkeypatch.setattr(correo, "enviar",
                        lambda destino, asunto, texto: enviados.append((destino, asunto, texto)) or True)
    monkeypatch.setattr(captcha, "verificar", lambda token, ip: True)
    main._intentos_registro.clear()
    main._intentos_login.clear()
    return enviados


def _codigo_de(enviados, indice=-1):
    return re.search(r"\b(\d{6})\b", enviados[indice][2]).group(1)


def _cuenta(cuil, mail="", declarado="", clave=VIEJA, sid=None, temporal=False, nivel=1,
            origen=""):
    """Un afiliado empadronado y registrado."""
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid or SID, cuil=cuil, activo=True, registrado=True))
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(clave) if clave else "",
                               mail=mail, mail_declarado=declarado, clave_temporal=temporal,
                               nivel_fiabilidad=nivel, nivel_origen=origen))
        s.commit()


def _empresa(cuit, mail="", clave=VIEJA, temporal=False):
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=SID, cuit=cuit, razon_social="Empresa Test", mail=mail,
                        activo=True, registrado=True))
        s.add(CuentaEmpleador(cuit=cuit, clave_hash=auth.hashear_clave(clave), clave_temporal=temporal))
        s.commit()


def _cuenta_db(cuil):
    with db.get_session() as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _empresa_db(cuit):
    with db.get_session() as s:
        return s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()


def _codigos(identificador):
    with db.get_session() as s:
        return s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == identificador)).all()


def _iniciar(c, cuil, base="/ingresar", campo="cuil"):
    return c.post(f"{base}/recuperar/iniciar", data={campo: cuil})


def _confirmar(c, token, codigo, clave=NUEVA, clave2=None, base="/ingresar"):
    return c.post(f"{base}/recuperar", follow_redirects=False,
                  data={"token": token, "codigo": codigo, "clave": clave,
                        "clave2": clave if clave2 is None else clave2})


def _login(c, cuil, clave):
    return c.post("/trabajador/login", data={"cuil": cuil, "clave": clave}, follow_redirects=False)


def _sesion(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


# ===========================================================================
# 1. Recuperación de clave del afiliado
# ===========================================================================
def test_recuperacion_completa_con_mail_del_padron(canal):
    _cuenta("20400000001", mail=MAIL)
    c = TestClient(main.app)
    r = _iniciar(c, "20400000001")
    assert r.status_code == 200
    d = r.json()
    assert d["paso"] == "codigo" and d["pista"] == "a***@ejemplo.com" and d["token"]
    assert len(canal) == 1 and canal[0][0] == MAIL
    # el código se guarda con el propósito y el origen del plan
    fila = _codigos("20400000001")[0]
    assert (fila.proposito, fila.origen_destino, fila.tipo) == ("recuperacion", "padron", "trabajador")

    r = _confirmar(c, d["token"], _codigo_de(canal))
    assert r.status_code == 303 and r.headers["location"] == "/ingresar?ok=clave"
    assert _login(c, "20400000001", VIEJA).headers["location"] == "/ingresar?error=login"
    ok = _login(c, "20400000001", NUEVA)
    assert ok.headers["location"] == "/app/inicio"
    assert _cuenta_db("20400000001").clave_temporal is False


def test_recuperar_desactiva_la_clave_temporal(canal):
    _cuenta("20400000002", mail=MAIL, temporal=True)
    c = TestClient(main.app)
    d = _iniciar(c, "20400000002").json()
    _confirmar(c, d["token"], _codigo_de(canal))
    assert _cuenta_db("20400000002").clave_temporal is False
    assert _login(c, "20400000002", NUEVA).headers["location"] == "/app/inicio"


def test_solo_mail_declarado_no_manda_codigo(canal):
    _cuenta("20400000003", mail="", declarado="otro@ejemplo.com", nivel=2, origen="mail_declarado")
    r = _iniciar(TestClient(main.app), "20400000003")
    assert r.status_code == 200 and r.json()["paso"] == "sindicato"
    assert canal == [] and _codigos("20400000003") == []


def test_la_respuesta_es_identica_haya_o_no_cuenta(canal):
    _cuenta("20400000004", mail="", declarado="otro@ejemplo.com")         # solo declarado
    _cuenta("20400000005", mail=MAIL, clave="")                            # padrón, pero sin clave
    c = TestClient(main.app)
    inexistente = _iniciar(c, "20499999999")
    declarado = _iniciar(c, "20400000004")
    sin_clave = _iniciar(c, "20400000005")
    assert inexistente.status_code == declarado.status_code == sin_clave.status_code == 200
    assert inexistente.content == declarado.content == sin_clave.content
    assert inexistente.json()["paso"] == "sindicato"
    assert canal == []


def test_canal_apagado_responde_lo_mismo_y_no_crea_codigo(canal, monkeypatch):
    _cuenta("20400000006", mail=MAIL)
    c = TestClient(main.app)
    de_referencia = _iniciar(c, "20499999998").content
    monkeypatch.setattr(correo, "habilitado", lambda: False)
    r = _iniciar(c, "20400000006")
    assert r.status_code == 200 and r.json()["paso"] == "sindicato"
    assert r.content == de_referencia
    assert canal == [] and _codigos("20400000006") == []


def test_un_codigo_de_otro_cuil_no_sirve(canal):
    _cuenta("20400000007", mail="uno@ejemplo.com")
    _cuenta("20400000008", mail="dos@ejemplo.com")
    c = TestClient(main.app)
    token_a = _iniciar(c, "20400000007").json()["token"]
    _iniciar(c, "20400000008")
    codigo_b = _codigo_de(canal)                      # el último, el de B
    assert canal[-1][0] == "dos@ejemplo.com"
    r = _confirmar(c, token_a, codigo_b)
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _login(c, "20400000007", VIEJA).headers["location"] == "/app/inicio"
    assert _login(c, "20400000008", VIEJA).headers["location"] == "/app/inicio"


def test_token_de_otro_proposito_o_alterado_no_sirve(canal):
    _cuenta("20400000009", mail=MAIL)
    c = TestClient(main.app)
    d = _iniciar(c, "20400000009").json()
    codigo = _codigo_de(canal)
    ajeno = auth.firmar_paso({"cuil": "20400000009", "codigo_id": 1}, proposito="cambio_clave")
    for token in (ajeno, d["token"] + "x", "", "basura"):
        r = _confirmar(c, token, codigo)
        assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _login(c, "20400000009", VIEJA).headers["location"] == "/app/inicio"


def test_codigo_incorrecto_cuenta_intentos_y_agota(canal):
    _cuenta("20400000010", mail=MAIL)
    c = TestClient(main.app)
    d = _iniciar(c, "20400000010").json()
    bueno = _codigo_de(canal)
    malo = "000000" if bueno != "000000" else "111111"
    for _ in range(db.CODIGO_MAX_INTENTOS):
        r = _confirmar(c, d["token"], malo)
        assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    # ya gastó los 5 intentos: ni el correcto sirve
    r = _confirmar(c, d["token"], bueno)
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _login(c, "20400000010", VIEJA).headers["location"] == "/app/inicio"


def test_claves_mal_no_gastan_el_codigo(canal):
    _cuenta("20400000011", mail=MAIL)
    c = TestClient(main.app)
    d = _iniciar(c, "20400000011").json()
    codigo = _codigo_de(canal)
    distintas = _confirmar(c, d["token"], codigo, clave=NUEVA, clave2="otra-clave-1")
    corta = _confirmar(c, d["token"], codigo, clave="abc", clave2="abc")
    assert distintas.status_code == 400 and corta.status_code == 400
    # el código sigue vivo: con las claves bien, anda
    assert _confirmar(c, d["token"], codigo).status_code == 303
    assert _login(c, "20400000011", NUEVA).headers["location"] == "/app/inicio"


def test_el_codigo_se_usa_una_sola_vez(canal):
    _cuenta("20400000012", mail=MAIL)
    c = TestClient(main.app)
    d = _iniciar(c, "20400000012").json()
    codigo = _codigo_de(canal)
    assert _confirmar(c, d["token"], codigo).status_code == 303
    r = _confirmar(c, d["token"], codigo, clave="otra-clave-77")
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _login(c, "20400000012", NUEVA).headers["location"] == "/app/inicio"


def test_cupo_de_codigos_por_hora(canal):
    _cuenta("20400000013", mail=MAIL)
    c = TestClient(main.app)
    for _ in range(db.CODIGOS_POR_HORA):
        assert _iniciar(c, "20400000013").json()["paso"] == "codigo"
    r = _iniciar(c, "20400000013")
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-03"
    assert len(canal) == db.CODIGOS_POR_HORA


def test_captcha_malo_es_e_registro_01(canal, monkeypatch):
    _cuenta("20400000014", mail=MAIL)
    monkeypatch.setattr(captcha, "verificar", lambda token, ip: False)
    r = _iniciar(TestClient(main.app), "20400000014")
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-01"
    assert canal == [] and _codigos("20400000014") == []


def test_mail_que_no_sale_es_e_registro_06(monkeypatch):
    _cuenta("20400000015", mail=MAIL)
    monkeypatch.setattr(correo, "enviar", lambda *a: False)
    r = _iniciar(TestClient(main.app), "20400000015")
    assert r.status_code == 503 and r.json()["codigo"] == "E-REGISTRO-06"


def test_freno_por_ip_con_su_propia_tabla(canal, monkeypatch):
    monkeypatch.setattr(main, "LOGIN_MAX_FALLOS", 3)
    c = TestClient(main.app)
    for _ in range(3):
        assert _iniciar(c, "20499999997").status_code == 200
    r = _iniciar(c, "20499999997")
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-05"
    # la tabla de los logins no se tocó: se puede seguir ingresando
    assert _login(c, "20499999997", "x").headers["location"] == "/ingresar?error=login"


def test_las_pantallas_y_el_enlace_olvide_mi_clave():
    c = TestClient(main.app)
    r = c.get("/ingresar/recuperar")
    assert r.status_code == 200 and "Recuperar mi clave" in r.text
    assert 'var BASE = "/ingresar"' in r.text and "'/recuperar/iniciar'" in r.text and 'name="cuil"' in r.text
    r = c.get("/ingresar-empresa/recuperar")
    assert r.status_code == 200 and 'name="cuit"' in r.text
    assert 'var BASE = "/ingresar-empresa"' in r.text
    assert "/ingresar/recuperar" in c.get("/ingresar").text
    assert "/ingresar-empresa/recuperar" in c.get("/ingresar-empresa").text
    assert "Listo, entrá con tu clave nueva" in c.get("/ingresar?ok=clave").text
    assert "Listo, entrá con tu clave nueva" in c.get("/ingresar-empresa?ok=clave").text
    assert "Listo, entrá con tu clave nueva" not in c.get("/ingresar").text


# ===========================================================================
# 2. Clave temporal
# ===========================================================================
def test_login_con_clave_temporal_no_abre_sesion_y_manda_a_cambiarla():
    _cuenta("20400000020", clave="temporal-1", temporal=True)
    c = TestClient(main.app)
    r = _login(c, "20400000020", "temporal-1")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ingresar/cambiar-clave?token=")
    assert main.COOKIE_TRABAJADOR not in r.headers.get("set-cookie", "")
    assert c.cookies.get(main.COOKIE_TRABAJADOR) is None
    token = r.headers["location"].split("token=", 1)[1]
    assert auth.leer_paso(token, "cambio_clave") == {"cuil": "20400000020"}
    # y la pantalla de cambio responde
    assert c.get(r.headers["location"]).status_code == 200
    # con la clave equivocada sigue siendo un login fallido, sin token
    assert _login(c, "20400000020", "mala").headers["location"] == "/ingresar?error=login"


def test_cambiar_clave_temporal_exige_la_temporal_y_abre_sesion():
    _cuenta("20400000021", clave="temporal-2", temporal=True)
    c = TestClient(main.app)
    token = _login(c, "20400000021", "temporal-2").headers["location"].split("token=", 1)[1]

    def cambiar(**campos):
        datos = {"token": token, "clave_actual": "temporal-2", "clave": NUEVA, "clave2": NUEVA}
        datos.update(campos)
        return c.post("/ingresar/cambiar-clave", data=datos, follow_redirects=False)

    # temporal equivocada, claves distintas, corta, igual a la temporal: nada cambia
    for r in (cambiar(clave_actual="otra"), cambiar(clave2="distinta-1"),
              cambiar(clave="abc", clave2="abc"), cambiar(clave="temporal-2", clave2="temporal-2")):
        assert r.status_code == 400
        assert main.COOKIE_TRABAJADOR not in r.headers.get("set-cookie", "")
    assert _cuenta_db("20400000021").clave_temporal is True

    r = cambiar()
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    assert main.COOKIE_TRABAJADOR in r.headers.get("set-cookie", "")
    assert c.cookies.get(main.COOKIE_TRABAJADOR)
    assert _cuenta_db("20400000021").clave_temporal is False
    # la temporal ya no entra y la nueva sí, y sin más desvío
    assert _login(TestClient(main.app), "20400000021", "temporal-2").headers["location"] == "/ingresar?error=login"
    assert _login(TestClient(main.app), "20400000021", NUEVA).headers["location"] == "/app/inicio"
    # la sesión abierta es la del CUIL (identidad firmada)
    assert auth.leer_sesion(c.cookies.get(main.COOKIE_TRABAJADOR))["ident"] == "20400000021"


def test_el_token_de_cambio_vencido_no_sirve(monkeypatch):
    import time
    _cuenta("20400000022", clave="temporal-3", temporal=True)
    c = TestClient(main.app)
    token = _login(c, "20400000022", "temporal-3").headers["location"].split("token=", 1)[1]
    ahora = time.time()
    monkeypatch.setattr(auth.time, "time", lambda: ahora + 11 * 60)
    pagina = c.get(f"/ingresar/cambiar-clave?token={token}")
    assert pagina.status_code == 200 and "venció" in pagina.text and token not in pagina.text
    r = c.post("/ingresar/cambiar-clave", follow_redirects=False,
               data={"token": token, "clave_actual": "temporal-3", "clave": NUEVA, "clave2": NUEVA})
    assert main.COOKIE_TRABAJADOR not in r.headers.get("set-cookie", "")
    assert "venció" in r.text
    assert _cuenta_db("20400000022").clave_temporal is True


def test_un_token_de_otro_proposito_no_cambia_la_clave():
    _cuenta("20400000023", clave="temporal-4", temporal=True)
    c = TestClient(main.app)
    ajeno = auth.firmar_paso({"cuil": "20400000023"}, minutos=10, proposito="recuperacion")
    r = c.post("/ingresar/cambiar-clave", follow_redirects=False,
               data={"token": ajeno, "clave_actual": "temporal-4", "clave": NUEVA, "clave2": NUEVA})
    assert main.COOKIE_TRABAJADOR not in r.headers.get("set-cookie", "")
    assert _cuenta_db("20400000023").clave_temporal is True


def test_el_cambio_solo_vale_para_cuentas_con_clave_temporal():
    """Un token de cambio de una cuenta que NO es temporal no sirve para
    elegir clave sabiendo la actual: ese camino es el del perfil, no este."""
    _cuenta("20400000024", clave="normal-123", temporal=False)
    c = TestClient(main.app)
    token = auth.firmar_paso({"cuil": "20400000024"}, minutos=10, proposito="cambio_clave")
    r = c.post("/ingresar/cambiar-clave", follow_redirects=False,
               data={"token": token, "clave_actual": "normal-123", "clave": NUEVA, "clave2": NUEVA})
    assert main.COOKIE_TRABAJADOR not in r.headers.get("set-cookie", "")
    assert _login(c, "20400000024", "normal-123").headers["location"] == "/app/inicio"


# ===========================================================================
# 3. Confirmar el mail de una cuenta ya registrada
# ===========================================================================
def test_confirmar_con_mail_del_padron_sube_a_nivel_2(canal):
    _cuenta("20400000030", mail=MAIL)
    c = _sesion("20400000030")
    d = c.post("/app/confirmar-mail/iniciar").json()
    assert d["paso"] == "codigo" and d["pista"] == "a***@ejemplo.com"
    assert canal[-1][0] == MAIL
    assert _codigos("20400000030")[0].origen_destino == "padron"
    r = c.post("/app/confirmar-mail", data={"token": d["token"], "codigo": _codigo_de(canal)})
    assert r.status_code == 200 and r.json() == {"ok": True, "nivel": 2}
    cuenta = _cuenta_db("20400000030")
    assert (cuenta.nivel_fiabilidad, cuenta.nivel_origen) == (2, "mail_padron")
    assert cuenta.mail == MAIL and cuenta.mail_declarado == ""


def test_confirmar_con_mail_declarado_no_pisa_el_del_sindicato(canal):
    _cuenta("20400000031")
    c = _sesion("20400000031")
    d = c.post("/app/confirmar-mail/iniciar", data={"mail": "propio@ejemplo.com"}).json()
    assert d["paso"] == "codigo" and canal[-1][0] == "propio@ejemplo.com"
    assert _codigos("20400000031")[0].origen_destino == "declarado"
    r = c.post("/app/confirmar-mail", data={"token": d["token"], "codigo": _codigo_de(canal)})
    assert r.status_code == 200
    cuenta = _cuenta_db("20400000031")
    assert (cuenta.nivel_fiabilidad, cuenta.nivel_origen) == (2, "mail_declarado")
    assert cuenta.mail_declarado == "propio@ejemplo.com" and cuenta.mail_declarado_confirmado
    assert cuenta.mail == ""                       # el mail del sindicato queda intacto


def test_sindicato_estricto_sin_mail_del_padron_manda_a_pedirselo(canal):
    _cuenta("20400000032", sid=SID_ESTRICTO)
    c = _sesion("20400000032")
    d = c.post("/app/confirmar-mail/iniciar", data={"mail": "propio@ejemplo.com"}).json()
    assert d["paso"] == "sindicato" and "sindicato" in d["mensaje"]
    assert canal == [] and _codigos("20400000032") == []
    assert _cuenta_db("20400000032").nivel_fiabilidad == 1


def test_sin_mail_ni_padron_pide_que_cargue_el_mail(canal):
    _cuenta("20400000033")
    d = _sesion("20400000033").post("/app/confirmar-mail/iniciar").json()
    assert d["paso"] == "sindicato" and canal == []


def test_mail_declarado_invalido_se_rechaza(canal):
    _cuenta("20400000034")
    r = _sesion("20400000034").post("/app/confirmar-mail/iniciar", data={"mail": "no-es-un-mail"})
    assert r.status_code == 400 and canal == [] and _codigos("20400000034") == []


def test_una_cuenta_de_nivel_alto_no_pide_codigo(canal):
    _cuenta("20400000035", mail=MAIL, nivel=3, origen="recibo_propio")
    d = _sesion("20400000035").post("/app/confirmar-mail/iniciar").json()
    assert d["paso"] == "listo" and canal == []


def test_el_nivel_no_baja_al_confirmar(canal):
    """Una cuenta que el sindicato ya confirmó (4) y que por algún camino llega
    con un código válido de mail sigue en 4."""
    _cuenta("20400000036", mail=MAIL, nivel=1)
    c = _sesion("20400000036")
    d = c.post("/app/confirmar-mail/iniciar").json()
    with db.get_session() as s:
        cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == "20400000036")).first()
        db.subir_nivel(s, cuenta, "presencial")
        s.commit()
    r = c.post("/app/confirmar-mail", data={"token": d["token"], "codigo": _codigo_de(canal)})
    assert r.status_code == 200 and r.json()["nivel"] == 4
    assert _cuenta_db("20400000036").nivel_origen == "presencial"


def test_confirmar_codigo_ajeno_o_token_ajeno_no_sirve(canal):
    _cuenta("20400000037", mail="uno@ejemplo.com")
    _cuenta("20400000038", mail="dos@ejemplo.com")
    a, b = _sesion("20400000037"), _sesion("20400000038")
    token_a = a.post("/app/confirmar-mail/iniciar").json()["token"]
    token_b = b.post("/app/confirmar-mail/iniciar").json()["token"]
    codigo_b = _codigo_de(canal)
    # B intenta usar el token de A; A intenta usar el código de B
    r = b.post("/app/confirmar-mail", data={"token": token_a, "codigo": codigo_b})
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    r = a.post("/app/confirmar-mail", data={"token": token_a, "codigo": codigo_b})
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _cuenta_db("20400000037").nivel_fiabilidad == 1
    assert _cuenta_db("20400000038").nivel_fiabilidad == 1
    assert token_b


def test_confirmar_mail_cupo_y_canal_apagado(canal, monkeypatch):
    _cuenta("20400000039", mail=MAIL)
    c = _sesion("20400000039")
    for _ in range(db.CODIGOS_POR_HORA):
        assert c.post("/app/confirmar-mail/iniciar").json()["paso"] == "codigo"
    r = c.post("/app/confirmar-mail/iniciar")
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-03"
    monkeypatch.setattr(correo, "habilitado", lambda: False)
    r = c.post("/app/confirmar-mail/iniciar")
    assert r.status_code == 503 and r.json()["codigo"] == "E-REGISTRO-06"


def test_sin_sesion_no_se_confirma_nada():
    c = TestClient(main.app)
    r = c.get("/app/confirmar-mail", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ingresar"
    assert c.post("/app/confirmar-mail/iniciar").status_code == 403
    assert c.post("/app/confirmar-mail", data={"token": "x", "codigo": "123456"}).status_code == 403
    # una cookie plana de CUIL (sin sesión firmada) tampoco alcanza
    c.cookies.set("cuil_trab", "20400000030")
    assert c.post("/app/confirmar-mail/iniciar").status_code == 403


def test_la_pantalla_de_confirmar_segun_el_caso():
    _cuenta("20400000040", mail=MAIL)
    _cuenta("20400000041")
    _cuenta("20400000042", sid=SID_ESTRICTO)
    _cuenta("20400000043", mail=MAIL, nivel=2, origen="mail_padron")
    t = _sesion("20400000040").get("/app/confirmar-mail").text
    assert "Confirmá tu mail" in t and "a***@ejemplo.com" in t and "/app/confirmar-mail/iniciar" in t
    assert 'name="mail"' in _sesion("20400000041").get("/app/confirmar-mail").text
    estricto = _sesion("20400000042").get("/app/confirmar-mail").text
    assert 'name="mail"' not in estricto and "Pedile a tu sindicato" in estricto
    assert "ya tiene el mail confirmado" in _sesion("20400000043").get("/app/confirmar-mail").text


def test_la_portada_ofrece_la_tarjeta_solo_al_nivel_1_con_canal(monkeypatch):
    _cuenta("20400000050", mail=MAIL, nivel=1)
    _cuenta("20400000051", mail=MAIL, nivel=3, origen="recibo_propio")
    nivel1 = _sesion("20400000050").get("/app/inicio").text
    assert "Confirmá tu mail para proteger tu cuenta" in nivel1 and 'href="/app/confirmar-mail"' in nivel1
    assert "Confirmá tu mail" not in _sesion("20400000051").get("/app/inicio").text
    monkeypatch.setattr(correo, "habilitado", lambda: False)
    assert "Confirmá tu mail" not in _sesion("20400000050").get("/app/inicio").text


# ===========================================================================
# 4. Espejos de la empresa
# ===========================================================================
def test_recuperacion_de_la_empresa_con_mail_del_padron(canal):
    _empresa("30400000001", mail="rrhh@empresa.com")
    c = TestClient(main.app)
    d = _iniciar(c, "30400000001", base="/ingresar-empresa", campo="cuit").json()
    assert d["paso"] == "codigo" and d["pista"] == "r***@empresa.com"
    fila = _codigos("30400000001")[0]
    assert (fila.tipo, fila.proposito, fila.origen_destino) == ("empleador", "recuperacion", "padron")
    r = _confirmar(c, d["token"], _codigo_de(canal), base="/ingresar-empresa")
    assert r.status_code == 303 and r.headers["location"] == "/ingresar-empresa?ok=clave"
    mal = c.post("/empresa/login", data={"cuit": "30400000001", "clave": VIEJA}, follow_redirects=False)
    assert mal.headers["location"] == "/ingresar-empresa?error=login"
    ok = c.post("/empresa/login", data={"cuit": "30400000001", "clave": NUEVA}, follow_redirects=False)
    assert ok.headers["location"] == "/empresa/inicio"


def test_empresa_sin_mail_o_sin_cuenta_responde_igual(canal):
    _empresa("30400000002", mail="")
    c = TestClient(main.app)
    sin_mail = _iniciar(c, "30400000002", base="/ingresar-empresa", campo="cuit")
    inexistente = _iniciar(c, "30499999999", base="/ingresar-empresa", campo="cuit")
    assert sin_mail.status_code == inexistente.status_code == 200
    assert sin_mail.content == inexistente.content and sin_mail.json()["paso"] == "sindicato"
    assert canal == [] and _codigos("30400000002") == []


def test_codigo_de_la_empresa_no_sirve_en_el_afiliado(canal):
    """Los códigos de empleador y de trabajador son de tablas de personas
    distintas: el token de uno no alcanza para el otro."""
    _empresa("30400000003", mail="rrhh@empresa.com")
    _cuenta("20400000060", mail=MAIL)
    c = TestClient(main.app)
    token_emp = _iniciar(c, "30400000003", base="/ingresar-empresa", campo="cuit").json()["token"]
    codigo = _codigo_de(canal)
    r = _confirmar(c, token_emp, codigo)                 # ruta del afiliado
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _login(c, "20400000060", VIEJA).headers["location"] == "/app/inicio"


def test_clave_temporal_de_la_empresa():
    _empresa("30400000004", clave="temporal-e1", temporal=True)
    c = TestClient(main.app)
    r = c.post("/empresa/login", data={"cuit": "30400000004", "clave": "temporal-e1"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ingresar-empresa/cambiar-clave?token=")
    assert main.COOKIE_EMPLEADOR not in r.headers.get("set-cookie", "")
    assert c.get(r.headers["location"]).status_code == 200
    token = r.headers["location"].split("token=", 1)[1]
    assert auth.leer_paso(token, "cambio_clave") == {"cuit": "30400000004"}

    mala = c.post("/ingresar-empresa/cambiar-clave", follow_redirects=False,
                  data={"token": token, "clave_actual": "otra", "clave": NUEVA, "clave2": NUEVA})
    assert mala.status_code == 400 and main.COOKIE_EMPLEADOR not in mala.headers.get("set-cookie", "")
    assert _empresa_db("30400000004").clave_temporal is True

    ok = c.post("/ingresar-empresa/cambiar-clave", follow_redirects=False,
                data={"token": token, "clave_actual": "temporal-e1", "clave": NUEVA, "clave2": NUEVA})
    assert ok.status_code == 303 and ok.headers["location"] == "/empresa/inicio"
    assert main.COOKIE_EMPLEADOR in ok.headers.get("set-cookie", "")
    assert _empresa_db("30400000004").clave_temporal is False
    assert auth.leer_sesion(c.cookies.get(main.COOKIE_EMPLEADOR))["ident"] == "30400000004"
    # el token del afiliado no sirve en la empresa (le falta la clave "cuit")
    ajeno = auth.firmar_paso({"cuil": "30400000004"}, minutos=10, proposito="cambio_clave")
    r = TestClient(main.app).post("/ingresar-empresa/cambiar-clave", follow_redirects=False,
                                  data={"token": ajeno, "clave_actual": NUEVA, "clave": "tercera-77", "clave2": "tercera-77"})
    assert main.COOKIE_EMPLEADOR not in r.headers.get("set-cookie", "")

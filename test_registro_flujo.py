"""El registro en tres pasos de punta a punta (PLAN_REGISTRO.md §4.1 y §4.2).

Paso 1 `/iniciar` (número + captcha) -> paso 2 `/mail` (solo si hay que declarar
uno) -> paso 3 el POST de siempre con `token` y `codigo`. Acá se prueba el
recorrido con el servidor real y la base descartable; `correo.enviar` y
`captcha.verificar` van simulados (ningún test sale a la red).

Lo que se cuida:

1. La cuenta NO tiene clave hasta el paso 3, y nace con el nivel que acredita
   el camino: mail del padrón (2), mail declarado (2, y `persona.mail` intacto)
   o canal apagado (1, `cuil_padron`).
2. Un sindicato que no acepta mail declarado frena en `E-REGISTRO-04`, y manda
   el más estricto cuando la persona está en dos.
3. Cinco códigos incorrectos agotan el código: ni el correcto sirve después.
4. Un código de OTRO número no crea la cuenta (token manipulado o reutilizado).
5. Cupo de 3 códigos por hora, mail que no sale, captcha malo: cada uno con su
   código de error, y todo fallo posterior al captcha cuenta para el freno.
6. El redirect `domicilio` ya no distingue afiliados de no afiliados.
7. El espejo de la empresa, en sus dos caminos.

Correr con: python -m pytest test_registro_flujo.py -q
"""
import os
import re

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import captcha
import correo
import cuit
import db
import main
from db import (CodigoVerificacion, CuentaEmpleador, CuentaTrabajador, Empleador,
                Sindicato, Trabajador)
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

db.crear_tablas()

for _v in ("RESEND_API_KEY", "MAIL_REMITENTE", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
    os.environ.pop(_v, None)

_contador = [100]


def _cuil():
    _contador[0] += 1
    return cuit.corregir("20%08d0" % _contador[0])


def _cuit():
    _contador[0] += 1
    return cuit.corregir("30%08d0" % _contador[0])


def _sindicato(nombre, acepta=True):
    with db.get_session() as s:
        sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"),
                         color_base="#0f1b2d", acepta_mail_declarado=acepta)
        s.add(sind)
        s.commit()
        s.refresh(sind)
        return sind.id


SID = _sindicato("Flujo Abierto")
SID_ESTRICTO = _sindicato("Flujo Estricto", acepta=False)

DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}


def _afiliado(cuil, sid=SID, mail=""):
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid, cuil=cuil, activo=True))
        db.guardar_datos_personales(s, cuil, nombre="Persona de Prueba")
        if mail:
            # El mail que cargó el SINDICATO: columna `mail_padron`, aparte del
            # `mail` de contacto que la persona edita en su perfil.
            cuenta = db.asegurar_cuenta(s, cuil)
            cuenta.mail_padron = mail
            s.add(cuenta)
        s.commit()


def _empresa(cuit_, sid=SID, mail=""):
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=sid, cuit=cuit_, razon_social="Empresa Flujo SA", mail_padron=mail))
        s.commit()


def _persona(cuil):
    with Session(db.engine) as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _cuenta_emp(cuit_):
    with Session(db.engine) as s:
        return s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit_)).first()


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Canal de mail PRENDIDO por default (cada test que lo quiera apagado lo
    dice), captcha simulado ("ok" pasa, cualquier otra cosa no) y frenos en
    cero. `correo.enviar` guarda lo que se mandó en `salida`."""
    main._intentos_login.clear()
    main._intentos_registro.clear()
    # El cupo por MAIL de destino (QA-REG-03) es de la base y los tests comparten
    # direcciones: cada uno empieza sin pedidos de la última hora.
    with db.get_session() as s:
        s.exec(delete(CodigoVerificacion))
        s.commit()
    monkeypatch.setenv("RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <no-responder@avisos.example.com>")
    class Salida(list):
        resultado = {"ok": True}

    salida = Salida()
    resultado = salida.resultado

    def enviar(destino, asunto, texto):
        salida.append((destino, asunto, texto))
        return resultado["ok"]

    monkeypatch.setattr(correo, "enviar", enviar)
    monkeypatch.setattr(captcha, "verificar", lambda token, ip: token == "ok")
    return salida


def _codigo_de(salida):
    """El código de 6 dígitos del último mail mandado."""
    return re.search(r"\b(\d{6})\b", salida[-1][1]).group(1)


def _iniciar(c, cuil, captcha_="ok", ruta="/trabajador/registro/iniciar", campo="cuil"):
    return c.post(ruta, data={campo: cuil, "cf-turnstile-response": captcha_})


def _final(c, cuil, token="", codigo="", clave="secreta", **extra):
    datos = {"cuil": cuil, "clave": clave, "nombre": "Persona de Prueba", **DOM,
             "token": token, "codigo": codigo}
    datos.update(extra)
    return c.post("/trabajador/registro", data=datos, follow_redirects=False)


def _final_emp(c, cuit_, token="", codigo="", clave="secreta", **extra):
    datos = {"cuit": cuit_, "clave": clave, "token": token, "codigo": codigo}
    datos.update(extra)
    return c.post("/empresa/registro", data=datos, follow_redirects=False)


# ---------------------------------------------------------------------------
# Afiliado: mail del padrón
# ---------------------------------------------------------------------------
def test_flujo_completo_con_mail_del_padron(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="juan.perez@gmail.com")
    c = TestClient(main.app)
    r = _iniciar(c, cuil)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["paso"] == "codigo" and d["pista"] == "j***@gmail.com" and d["token"]
    assert len(entorno) == 1 and entorno[0][0] == "juan.perez@gmail.com"
    # la cuenta todavía no tiene clave: no se crea hasta el paso 3
    assert not _persona(cuil).clave_hash
    with Session(db.engine) as s:
        fila = s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == cuil)).one()
        assert fila.origen_destino == "padron" and fila.tipo == "trabajador"
    r = _final(c, cuil, d["token"], _codigo_de(entorno))
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    p = _persona(cuil)
    assert p.clave_hash
    assert (p.nivel_fiabilidad, p.nivel_origen) == (2, "mail_padron")
    assert p.mail_padron == "juan.perez@gmail.com" and p.mail_declarado == ""
    assert "testclient" not in main._intentos_registro


# ---------------------------------------------------------------------------
# Afiliado: mail declarado
# ---------------------------------------------------------------------------
def test_flujo_completo_con_mail_declarado(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    assert d["paso"] == "mail" and entorno == []
    r = c.post("/trabajador/registro/mail", data={"token": d["token"], "mail": "laura@ejemplo.com"})
    assert r.status_code == 200, r.text
    d2 = r.json()
    assert d2["paso"] == "codigo" and d2["pista"] == "l***@ejemplo.com"
    assert entorno[-1][0] == "laura@ejemplo.com"
    # el campo `mail` del form ya no se escribe: tampoco pisa el del padrón
    r = _final(c, cuil, d2["token"], _codigo_de(entorno), mail="otro@ejemplo.com")
    assert r.status_code == 303 and "error=" not in r.headers["location"]
    p = _persona(cuil)
    assert (p.nivel_fiabilidad, p.nivel_origen) == (2, "mail_declarado")
    assert p.mail == "" and p.mail_padron == "", "el mail del padrón y el de contacto quedan como estaban"
    assert p.mail_declarado == "laura@ejemplo.com" and p.mail_declarado_confirmado


def test_mail_declarado_mal_escrito_o_con_salto_de_linea(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    tok = _iniciar(c, cuil).json()["token"]
    for malo in ("sin-arroba", "a@b", "a@b.com\nBcc: x@y.com", "a b@c.com", "x" * 250 + "@a.com", ""):
        r = c.post("/trabajador/registro/mail", data={"token": tok, "mail": malo})
        assert r.status_code == 422 and r.json()["error"] == "mail", malo
    assert entorno == []


def test_el_token_del_paso_codigo_no_sirve_para_declarar_otro_mail(entorno):
    """`/mail` solo acepta el token que dijo `paso: mail`: con el del padrón (que
    ya trae un código) o uno inventado, no manda nada."""
    cuil = _cuil()
    _afiliado(cuil, mail="padron@ejemplo.com")
    c = TestClient(main.app)
    tok = _iniciar(c, cuil).json()["token"]
    r = c.post("/trabajador/registro/mail", data={"token": tok, "mail": "intruso@ejemplo.com"})
    assert r.status_code == 400 and r.json()["error"] == "paso"
    r = c.post("/trabajador/registro/mail", data={"token": "x.y", "mail": "intruso@ejemplo.com"})
    assert r.status_code == 400
    assert [m[0] for m in entorno] == ["padron@ejemplo.com"]


# ---------------------------------------------------------------------------
# Política por sindicato
# ---------------------------------------------------------------------------
def test_sindicato_que_no_acepta_mail_declarado_y_no_hay_mail(entorno):
    cuil = _cuil()
    _afiliado(cuil, sid=SID_ESTRICTO)
    r = _iniciar(TestClient(main.app), cuil)
    assert r.status_code == 403 and r.json()["codigo"] == "E-REGISTRO-04"
    assert entorno == []


def test_en_dos_sindicatos_manda_el_mas_estricto(entorno):
    cuil = _cuil()
    _afiliado(cuil, sid=SID)
    _afiliado(cuil, sid=SID_ESTRICTO)
    r = _iniciar(TestClient(main.app), cuil)
    assert r.status_code == 403 and r.json()["codigo"] == "E-REGISTRO-04"


def test_aunque_arme_el_post_a_mano_el_estricto_no_deja_declarar(entorno):
    """El token de `paso: mail` solo sale de `/iniciar`; si la política cambia
    entre medio, `/mail` la vuelve a mirar."""
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    tok = _iniciar(c, cuil).json()["token"]
    _afiliado(cuil, sid=SID_ESTRICTO)           # se empadrona en un gremio estricto
    r = c.post("/trabajador/registro/mail", data={"token": tok, "mail": "a@ejemplo.com"})
    assert r.status_code == 403 and r.json()["codigo"] == "E-REGISTRO-04"
    assert entorno == []


# ---------------------------------------------------------------------------
# El código
# ---------------------------------------------------------------------------
def test_cinco_codigos_incorrectos_agotan_el_codigo(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    tok = _iniciar(c, cuil).json()["token"]
    bueno = _codigo_de(entorno)
    malo = "000000" if bueno != "000000" else "111111"
    for _ in range(db.CODIGO_MAX_INTENTOS):
        r = _final(c, cuil, tok, malo)
        assert r.status_code == 303 and r.headers["location"].endswith("error=codigo")
    # ya agotado: ni el correcto sirve
    r = _final(c, cuil, tok, bueno)
    assert r.headers["location"].endswith("error=codigo")
    assert not _persona(cuil).clave_hash
    with Session(db.engine) as s:
        fila = s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == cuil)).one()
        assert fila.intentos == db.CODIGO_MAX_INTENTOS and fila.usado_en == ""


def test_un_codigo_se_usa_una_sola_vez(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    tok = _iniciar(c, cuil).json()["token"]
    cod = _codigo_de(entorno)
    assert _final(c, cuil, tok, cod).headers["location"] == "/app/inicio"
    # la cuenta ya tiene clave: repetir el mismo registro no la pisa
    r = _final(c, cuil, tok, cod, clave="otra-clave")
    assert r.headers["location"].endswith("error=yaexiste")


def test_el_codigo_de_otro_cuil_no_crea_la_cuenta(entorno):
    a, b = _cuil(), _cuil()
    _afiliado(a, mail="a@ejemplo.com")
    _afiliado(b, mail="b@ejemplo.com")
    c = TestClient(main.app)
    tok_a = _iniciar(c, a).json()["token"]
    cod_a = _codigo_de(entorno)
    # (1) el token de A usado con el número de B
    r = _final(c, b, tok_a, cod_a, **{"cf-turnstile-response": "ok"})
    assert r.headers["location"].endswith("error=paso")
    # (2) un token fabricado para B que apunta al código de A
    with Session(db.engine) as s:
        fila_a = s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == a)).one()
        fila_a_id = fila_a.id
    falso = auth.firmar_paso({"id": b, "tipo": "trabajador", "codigo_id": fila_a_id,
                              "origen": "mail_padron"}, proposito="registro")
    r = _final(c, b, falso, cod_a)
    assert r.headers["location"].endswith("error=codigo")
    assert not _persona(b).clave_hash
    # y el código de A sigue sin gastarse: A puede terminar su registro
    assert _final(c, a, tok_a, cod_a).headers["location"] == "/app/inicio"


def test_cupo_de_codigos_por_hora(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    for _ in range(db.CODIGOS_POR_HORA):
        assert _iniciar(c, cuil).status_code == 200
    r = _iniciar(c, cuil)
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-03"
    assert len(entorno) == db.CODIGOS_POR_HORA


def test_si_el_mail_no_sale_es_e_registro_06_y_no_se_crea_nada(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    entorno.resultado["ok"] = False
    r = _iniciar(TestClient(main.app), cuil)
    assert r.status_code == 503 and r.json()["codigo"] == "E-REGISTRO-06"
    assert not _persona(cuil).clave_hash
    with Session(db.engine) as s:      # el código queda: es traza (y cuenta para el cupo)
        assert len(s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == cuil)).all()) == 1


def test_captcha_malo_es_e_registro_01(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    r = _iniciar(TestClient(main.app), cuil, captcha_="malo")
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-01"
    assert entorno == []


# ---------------------------------------------------------------------------
# Canal apagado (D9)
# ---------------------------------------------------------------------------
def test_canal_apagado_salta_el_codigo_y_la_cuenta_nace_nivel_1(entorno, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY")
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    assert d["paso"] == "datos" and "pista" not in d and entorno == []
    r = _final(c, cuil, d["token"])
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    p = _persona(cuil)
    assert p.clave_hash and (p.nivel_fiabilidad, p.nivel_origen) == (1, "cuil_padron")


def test_canal_apagado_y_sin_token_el_registro_sigue_como_hoy(entorno, monkeypatch):
    """Un cliente viejo (o un fetch roto) que manda el form sin pasar por
    `/iniciar`: con el canal apagado se registra igual, nivel 1."""
    monkeypatch.delenv("RESEND_API_KEY")
    cuil = _cuil()
    _afiliado(cuil)
    r = _final(TestClient(main.app), cuil, **{"cf-turnstile-response": "ok"})
    assert r.headers["location"] == "/app/inicio"
    assert _persona(cuil).nivel_origen == "cuil_padron"


def test_canal_prendido_sin_token_no_crea_la_cuenta(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    r = _final(TestClient(main.app), cuil, **{"cf-turnstile-response": "ok"})
    assert r.headers["location"].endswith("error=paso")
    assert not _persona(cuil).clave_hash


def test_token_del_canal_apagado_no_alcanza_si_el_canal_se_prende(entorno, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY")
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    tok = _iniciar(c, cuil).json()["token"]
    monkeypatch.setenv("RESEND_API_KEY", "clave-de-prueba")
    assert _final(c, cuil, tok).headers["location"].endswith("error=paso")
    assert not _persona(cuil).clave_hash


# ---------------------------------------------------------------------------
# Paso 1: validaciones y freno
# ---------------------------------------------------------------------------
def test_paso_1_distingue_los_casos_y_todos_cuentan_para_el_freno(entorno):
    c = TestClient(main.app)
    cuil = _cuil()
    # número sin verificador válido
    r = _iniciar(c, "20111111110")
    assert r.status_code == 422 and r.json()["codigo"] == "E-IDENT-01"
    # válido y fuera del padrón
    r = _iniciar(c, _cuil())
    assert r.status_code == 403 and r.json()["error"] == "nohabilitado"
    # ya tiene clave
    _afiliado(cuil, mail="a@ejemplo.com")
    with db.get_session() as s:
        db.asegurar_cuenta(s, cuil).clave_hash = auth.hashear_clave("x")
        s.commit()
    r = _iniciar(c, cuil)
    assert r.status_code == 409 and r.json()["error"] == "yaexiste"
    # sindicato estricto sin mail
    estricto = _cuil()
    _afiliado(estricto, sid=SID_ESTRICTO)
    assert _iniciar(c, estricto).json()["codigo"] == "E-REGISTRO-04"
    # captcha malo
    assert _iniciar(c, cuil, captcha_="malo").json()["codigo"] == "E-REGISTRO-01"
    assert main._intentos_registro["testclient"][0] == 5
    assert entorno == []


def test_paso_1_se_frena_tras_demasiados_fallos(entorno):
    c = TestClient(main.app)
    for _ in range(main.LOGIN_MAX_FALLOS):
        _iniciar(c, _cuil())            # fuera del padrón
    r = _iniciar(c, _cuil())
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-05"


def test_el_camino_feliz_del_paso_1_no_limpia_el_freno(entorno):
    c = TestClient(main.app)
    _iniciar(c, _cuil())
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    assert _iniciar(c, cuil).status_code == 200
    # el fallo de antes y este pedido, que salió bien, suman (QA-REG-04); no se limpia
    assert main._intentos_registro["testclient"][0] == 2


def test_el_redirect_domicilio_ya_no_enumera_afiliados(entorno, monkeypatch):
    """Sin provincia, un CUIL afiliado y uno que no lo es dan el MISMO redirect,
    y los dos cuentan para el freno. Con el canal prendido y sin token corta antes
    (`paso`, QA-REG-01); el redirect `domicilio` es el del camino sin canal."""
    monkeypatch.delenv("RESEND_API_KEY")
    afiliado, ajeno = _cuil(), _cuil()
    _afiliado(afiliado)
    c = TestClient(main.app)
    sin_dom = {"clave": "secreta", "nombre": "X", "provincia": "", "localidad": "",
               "token": "", "codigo": "", "cf-turnstile-response": "ok"}
    r1 = c.post("/trabajador/registro", data={"cuil": afiliado, **sin_dom}, follow_redirects=False)
    r2 = c.post("/trabajador/registro", data={"cuil": ajeno, **sin_dom}, follow_redirects=False)
    assert r1.headers["location"] == r2.headers["location"] == "/ingresar?error=domicilio"
    assert main._intentos_registro["testclient"][0] == 2


def test_la_pantalla_trae_los_tres_pasos():
    html = TestClient(main.app).get("/ingresar").text
    assert "/trabajador/registro" in html and 'data-reg="2c"' in html and 'data-reg="3"' in html
    html = TestClient(main.app).get("/ingresar-empresa").text
    assert "/empresa/registro" in html and 'data-reg="2m"' in html


# ---------------------------------------------------------------------------
# Empresa (espejo)
# ---------------------------------------------------------------------------
def test_empresa_con_mail_del_padron(entorno):
    cuit_ = _cuit()
    _empresa(cuit_, mail="rrhh@empresa.com")
    c = TestClient(main.app)
    r = _iniciar(c, cuit_, ruta="/empresa/registro/iniciar", campo="cuit")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["paso"] == "codigo" and d["pista"] == "r***@empresa.com"
    assert entorno[0][0] == "rrhh@empresa.com"
    assert _cuenta_emp(cuit_) is None, "la cuenta no existe antes del paso 3"
    r = _final_emp(c, cuit_, d["token"], _codigo_de(entorno))
    assert r.status_code == 303 and r.headers["location"] == "/empresa/inicio"
    cuenta = _cuenta_emp(cuit_)
    assert cuenta.clave_hash and (cuenta.nivel_fiabilidad, cuenta.nivel_origen) == (2, "mail_padron")
    assert cuenta.mail_declarado == ""
    with Session(db.engine) as s:
        assert all(e.registrado for e in s.exec(select(Empleador).where(Empleador.cuit == cuit_)).all())
        assert s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == cuit_)).one().tipo == "empleador"


def test_empresa_con_mail_declarado(entorno):
    cuit_ = _cuit()
    _empresa(cuit_)
    c = TestClient(main.app)
    d = _iniciar(c, cuit_, ruta="/empresa/registro/iniciar", campo="cuit").json()
    assert d["paso"] == "mail"
    r = c.post("/empresa/registro/mail", data={"token": d["token"], "mail": "gerencia@empresa.com"})
    assert r.status_code == 200 and r.json()["pista"] == "g***@empresa.com"
    r = _final_emp(c, cuit_, r.json()["token"], _codigo_de(entorno))
    assert r.headers["location"] == "/empresa/inicio"
    cuenta = _cuenta_emp(cuit_)
    assert (cuenta.nivel_fiabilidad, cuenta.nivel_origen) == (2, "mail_declarado")
    assert cuenta.mail_declarado == "gerencia@empresa.com" and cuenta.mail_declarado_confirmado


def test_empresa_estricta_codigo_incorrecto_y_canal_apagado(entorno, monkeypatch):
    estricta = _cuit()
    _empresa(estricta, sid=SID_ESTRICTO)
    c = TestClient(main.app)
    r = _iniciar(c, estricta, ruta="/empresa/registro/iniciar", campo="cuit")
    assert r.status_code == 403 and r.json()["codigo"] == "E-REGISTRO-04"
    # el código de un CUIT no sirve para otro
    a, b = _cuit(), _cuit()
    _empresa(a, mail="a@empresa.com")
    _empresa(b, mail="b@empresa.com")
    tok_a = _iniciar(c, a, ruta="/empresa/registro/iniciar", campo="cuit").json()["token"]
    assert _final_emp(c, b, tok_a, _codigo_de(entorno), **{"cf-turnstile-response": "ok"}
                      ).headers["location"].endswith("error=paso")
    assert _final_emp(c, a, tok_a, "000000" if _codigo_de(entorno) != "000000" else "111111"
                      ).headers["location"].endswith("error=codigo")
    assert _cuenta_emp(a) is None and _cuenta_emp(b) is None
    # canal apagado: nivel 1
    monkeypatch.delenv("RESEND_API_KEY")
    libre = _cuit()
    _empresa(libre)
    d = _iniciar(c, libre, ruta="/empresa/registro/iniciar", campo="cuit").json()
    assert d["paso"] == "datos"
    assert _final_emp(c, libre, d["token"]).headers["location"] == "/empresa/inicio"
    assert _cuenta_emp(libre).nivel_origen == "cuil_padron"


def test_empresa_captcha_malo_y_mail_que_no_sale(entorno):
    cuit_ = _cuit()
    _empresa(cuit_, mail="a@empresa.com")
    c = TestClient(main.app)
    r = _iniciar(c, cuit_, captcha_="malo", ruta="/empresa/registro/iniciar", campo="cuit")
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-01"
    entorno.resultado["ok"] = False
    r = _iniciar(c, cuit_, ruta="/empresa/registro/iniciar", campo="cuit")
    assert r.status_code == 503 and r.json()["codigo"] == "E-REGISTRO-06"
    assert _cuenta_emp(cuit_) is None


# ---------------------------------------------------------------------------
# Contrato de la tanda de QA (QA-REG-01 a 07)
# ---------------------------------------------------------------------------
def _filas_codigo(identificador):
    with Session(db.engine) as s:
        return s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == identificador)).all()


def test_todos_los_tokens_del_registro_llevan_el_tipo(entorno, monkeypatch):
    """QA-REG-02: sin el tipo, el `{id}` del afiliado sirve en la empresa."""
    c = TestClient(main.app)
    con_mail, sin_mail, empresa = _cuil(), _cuil(), _cuit()
    _afiliado(con_mail, mail="a@ejemplo.com")
    _afiliado(sin_mail)
    _empresa(empresa, mail="e@empresa.com")
    d = _iniciar(c, con_mail).json()
    assert auth.leer_paso(d["token"], "registro")["tipo"] == "trabajador"           # paso: codigo
    d = _iniciar(c, sin_mail).json()
    assert d["paso"] == "mail"
    assert auth.leer_paso(d["token"], "registro") == {"id": sin_mail, "tipo": "trabajador"}
    d2 = c.post("/trabajador/registro/mail", data={"token": d["token"], "mail": "yo@ejemplo.com"}).json()
    assert auth.leer_paso(d2["token"], "registro")["tipo"] == "trabajador"           # tras declarar el mail
    d3 = _iniciar(c, empresa, ruta="/empresa/registro/iniciar", campo="cuit").json()
    assert auth.leer_paso(d3["token"], "registro")["tipo"] == "empleador"
    monkeypatch.delenv("RESEND_API_KEY")
    libre = _cuil()
    _afiliado(libre)
    d4 = _iniciar(c, libre).json()
    assert d4["paso"] == "datos" and auth.leer_paso(d4["token"], "registro")["tipo"] == "trabajador"


def test_token_sin_tipo_o_con_otro_tipo_no_sirve_en_el_paso_mail(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    for datos in ({"id": cuil}, {"id": cuil, "tipo": "empleador"}, {"id": cuil, "tipo": "trabajador", "x": 1}):
        r = c.post("/trabajador/registro/mail",
                   data={"token": auth.firmar_paso(datos, proposito="registro"), "mail": "yo@ejemplo.com"})
        assert r.status_code == 400 and r.json()["error"] == "paso", datos
    assert entorno == [] and _filas_codigo(cuil) == []


def test_cupo_por_destino_en_la_base(entorno):
    """QA-REG-03: el cupo por mail de destino cuenta pedidos de cualquier persona
    y propósito, sin distinguir mayúsculas, y `crear_codigo` lo aplica solo."""
    from errores import ErrorApp
    assert db.CODIGOS_POR_HORA_DESTINO == 5
    with db.get_session() as s:
        for i in range(db.CODIGOS_POR_HORA_DESTINO):
            db.crear_codigo(s, "trabajador", f"2000000000{i}", "registro", "Ajeno@Ejemplo.com", "declarado", "1.1.1.1")
        s.commit()
        assert db.codigos_recientes_destino(s, "ajeno@ejemplo.com") == db.CODIGOS_POR_HORA_DESTINO
        assert db.codigos_recientes_destino(s, "otro@ejemplo.com") == 0
        with pytest.raises(ErrorApp) as e:
            db.crear_codigo(s, "empleador", "30999999990", "recuperacion", "ajeno@ejemplo.com", "padron", "1.1.1.1")
        assert "E-REGISTRO-03" in str(e.value) or getattr(e.value, "codigo", "") == "E-REGISTRO-03"
        db.crear_codigo(s, "empleador", "30999999990", "recuperacion", "otro@ejemplo.com", "padron", "1.1.1.1")


def test_clave_corta_no_gasta_el_codigo(entorno):
    """QA-REG-07: la clave mínima se exige ANTES de consumir el código."""
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    cod = _codigo_de(entorno)
    r = _final(c, cuil, d["token"], cod, clave="a" * (main.CLAVE_MINIMA - 1))
    assert r.headers["location"] == "/ingresar?error=clave"
    fila = _filas_codigo(cuil)[0]
    assert not fila.usado_en and fila.intentos == 0
    assert _final(c, cuil, d["token"], cod, clave="a" * main.CLAVE_MINIMA).headers["location"] == "/app/inicio"


def test_clave_corta_de_la_empresa_tampoco_gasta_el_codigo(entorno):
    cuit_ = _cuit()
    _empresa(cuit_, mail="e@empresa.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuit_, ruta="/empresa/registro/iniciar", campo="cuit").json()
    cod = _codigo_de(entorno)
    r = _final_emp(c, cuit_, d["token"], cod, clave="abc")
    assert r.headers["location"] == "/ingresar-empresa?error=clave"
    assert not _filas_codigo(cuit_)[0].usado_en and _cuenta_emp(cuit_) is None
    assert _final_emp(c, cuit_, d["token"], cod).headers["location"] == "/empresa/inicio"


def test_las_pantallas_piden_la_misma_clave_minima_que_el_servidor():
    for ruta in ("/ingresar", "/ingresar-empresa"):
        html = TestClient(main.app).get(ruta).text
        assert html.count(f'minlength="{main.CLAVE_MINIMA}"') >= 2, ruta
        assert 'minlength="4"' not in html


def test_mail_invalido_en_el_paso_mail_es_422_sin_fila_ni_cupo(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    for mail in ("a,b@ejemplo.com", "<a@ejemplo.com>", "a@ejemplo.c"):
        r = c.post("/trabajador/registro/mail", data={"token": token, "mail": mail})
        assert r.status_code == 422 and r.json()["error"] == "mail", mail
    assert _filas_codigo(cuil) == [] and entorno == []
    assert not hasattr(main, "_mail_declarable") and not hasattr(main, "_RX_MAIL")


def test_cada_pedido_que_sale_bien_suma_al_freno_y_el_exito_final_lo_limpia(entorno):
    """QA-REG-04: una IP no puede pedir códigos sin límite aunque salgan bien; la
    cuenta creada limpia el contador."""
    c = TestClient(main.app)
    for _ in range(3):
        cuil = _cuil()
        _afiliado(cuil, mail="a@ejemplo.com")
        assert _iniciar(c, cuil).status_code == 200
    assert main._intentos_registro["testclient"][0] == 3
    cuil = _cuil()
    _afiliado(cuil, mail="b@ejemplo.com")
    d = _iniciar(c, cuil).json()
    assert _final(c, cuil, d["token"], _codigo_de(entorno)).headers["location"] == "/app/inicio"
    assert "testclient" not in main._intentos_registro

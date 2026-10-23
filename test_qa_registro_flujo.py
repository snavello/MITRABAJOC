"""QA del registro en tres pasos (PLAN_REGISTRO.md §4.1 y §4.2, desarrollador C).

Casos que el `test_registro_flujo.py` del desarrollo no cubre. Los que dicen
"ROJO" son EVIDENCIA de un hallazgo abierto (QA-REG-n del reporte): fallan hoy
y tienen que pasar cuando se corrija. Los demás son GUARDAS verdes: el ataque
se intentó y el código lo frena; quedan para que no se rompa.

Cada test usa la misma maqueta que el del desarrollo: canal de mail prendido y
simulado (`correo.enviar` anota en `salida`, nada sale a la red), captcha
simulado ("ok" pasa, otra cosa no) y frenos en cero.

Correr con: python -m pytest test_qa_registro_flujo.py -q
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

_contador = [700]


def _cuil():
    _contador[0] += 1
    return cuit.corregir("20%08d0" % _contador[0])


def _sindicato(nombre, acepta=True):
    with db.get_session() as s:
        sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"),
                         color_base="#0f1b2d", acepta_mail_declarado=acepta)
        s.add(sind)
        s.commit()
        s.refresh(sind)
        return sind.id


SID = _sindicato("QA Registro Abierto")
DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}


def _afiliado(cuil, sid=SID, mail=""):
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid, cuil=cuil, activo=True))
        db.guardar_datos_personales(s, cuil, nombre="Persona de Prueba")
        if mail:
            cuenta = db.asegurar_cuenta(s, cuil)
            cuenta.mail_padron = mail
            s.add(cuenta)
        s.commit()


def _empresa(cuit_, sid=SID, mail=""):
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=sid, cuit=cuit_, razon_social="Empresa QA SA", mail_padron=mail))
        s.commit()


def _persona(cuil):
    with Session(db.engine) as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _cuenta_emp(cuit_):
    with Session(db.engine) as s:
        return s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit_)).first()


def _filas_codigo(identificador):
    with Session(db.engine) as s:
        return s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == identificador)).all()


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    main._intentos_login.clear()
    main._intentos_registro.clear()
    # El cupo por MAIL de destino (QA-REG-03) es de la base y los tests comparten
    # direcciones: cada uno empieza sin pedidos de la última hora.
    with db.get_session() as s:
        s.exec(delete(CodigoVerificacion))
        s.commit()
    monkeypatch.setenv("RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <no-responder@avisos.example.com>")
    salida = []

    def enviar(destino, asunto, texto):
        salida.append((destino, asunto, texto))
        return True

    monkeypatch.setattr(correo, "enviar", enviar)
    monkeypatch.setattr(captcha, "verificar", lambda token, ip: token == "ok")
    return salida


def _codigo_de(salida):
    return re.search(r"\b(\d{6})\b", salida[-1][1]).group(1)


def _iniciar(c, cuil, captcha_="ok", ruta="/trabajador/registro/iniciar", campo="cuil", **headers):
    return c.post(ruta, data={campo: cuil, "cf-turnstile-response": captcha_}, headers=headers)


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
# 1. TOKENS DE PASO
# ---------------------------------------------------------------------------
def test_token_de_otro_cuil_no_saltea_el_captcha_ni_enumera_el_padron(entorno):
    """ROJO (QA-REG-01). Un token válido de CUALQUIER número saltea el captcha del
    POST final (`leer_paso(token) is not None`), y como `_registro_confirmar`
    recién compara el número del token DESPUÉS de mirar el padrón, el redirect
    distingue `nohabilitado` / `yaexiste` / `paso`. Con un solo captcha
    resuelto el atacante enumera afiliados sin captcha (solo lo frena el freno
    por IP). Lo correcto: con un token que no es de ese número, mismo redirect
    y mismo trato que sin token (captcha exigido)."""
    propio, afiliado, ajeno, con_cuenta = _cuil(), _cuil(), _cuil(), _cuil()
    _afiliado(propio, mail="a@ejemplo.com")
    _afiliado(afiliado, mail="b@ejemplo.com")
    _afiliado(con_cuenta)
    with db.get_session() as s:
        db.asegurar_cuenta(s, con_cuenta).clave_hash = auth.hashear_clave("x")
        s.commit()
    c = TestClient(main.app)
    token = _iniciar(c, propio).json()["token"]
    mala = {"cf-turnstile-response": "malo"}          # captcha que NO pasa
    destinos = {_final(c, n, token, "", **mala).headers["location"]
                for n in (afiliado, ajeno, con_cuenta)}
    assert len(destinos) == 1, f"el redirect distingue afiliados de no afiliados: {destinos}"
    assert destinos.pop().endswith(("error=captcha", "error=paso"))


def test_empresa_token_de_otro_cuit_no_saltea_el_captcha_ni_enumera(entorno):
    """ROJO (QA-REG-01), espejo de la empresa."""
    propio, empleador, ajeno = _cuil(), _cuil(), _cuil()
    _empresa(propio, mail="a@empresa.com")
    _empresa(empleador, mail="b@empresa.com")
    c = TestClient(main.app)
    token = _iniciar(c, propio, ruta="/empresa/registro/iniciar", campo="cuit").json()["token"]
    mala = {"cf-turnstile-response": "malo"}
    destinos = {_final_emp(c, n, token, "", **mala).headers["location"] for n in (empleador, ajeno)}
    assert len(destinos) == 1, f"el redirect distingue empleadores de no empleadores: {destinos}"


def test_token_del_paso_mail_de_un_tipo_no_sirve_en_el_otro(entorno):
    """ROJO (QA-REG-02). El token no lleva el TIPO (trabajador/empleador). El
    `{id}` que emite `/trabajador/registro/iniciar` ("este CUIL no tiene mail
    en el padrón") se acepta en `/empresa/registro/mail`: si el mismo número es
    también un empleador CON mail del padrón, el atacante se salta el código al
    mail del padrón de la empresa y declara el suyo. Lo correcto: 400 `paso`."""
    x = _cuil()
    _afiliado(x)                                     # trabajador sin mail del padrón
    _empresa(x, mail="padron@empresa.com")           # el mismo número, empleador CON mail
    c = TestClient(main.app)
    token = _iniciar(c, x).json()["token"]           # paso: mail (del lado del trabajador)
    r = c.post("/empresa/registro/mail", data={"token": token, "mail": "atacante@ejemplo.com"})
    assert r.status_code == 400 and r.json()["error"] == "paso", r.text
    assert entorno == [], "no debió salir ningún código"


def test_token_del_paso_mail_de_la_empresa_no_sirve_en_el_trabajador(entorno):
    """ROJO (QA-REG-02), el sentido inverso."""
    x = _cuil()
    _empresa(x)
    _afiliado(x, mail="padron@ejemplo.com")
    c = TestClient(main.app)
    token = _iniciar(c, x, ruta="/empresa/registro/iniciar", campo="cuit").json()["token"]
    r = c.post("/trabajador/registro/mail", data={"token": token, "mail": "atacante@ejemplo.com"})
    assert r.status_code == 400 and r.json()["error"] == "paso", r.text
    assert entorno == []


def test_token_del_paso_mail_no_crea_la_cuenta_con_el_canal_prendido(entorno):
    """El `{id}` del paso 2 no sirve en el paso 3: sin código no hay cuenta."""
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    assert _final(c, cuil, token, "").headers["location"].endswith("error=paso")
    assert not _persona(cuil).clave_hash


def test_token_de_otro_proposito_no_sirve_en_el_registro(entorno):
    """Un token de recuperación / confirmación de mail no es un token de registro."""
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    for proposito in ("recuperacion", "confirmar_mail", "cambio_clave", ""):
        tok = auth.firmar_paso({"id": cuil}, proposito=proposito)
        r = _final(c, cuil, tok, "", **{"cf-turnstile-response": "ok"})
        assert r.headers["location"].endswith("error=paso"), proposito
        assert not _persona(cuil).clave_hash


def test_token_vencido_no_sirve_con_el_canal_prendido(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    cod = _codigo_de(entorno)
    with Session(db.engine) as s:
        fila = s.exec(select(CodigoVerificacion).where(CodigoVerificacion.identificador == cuil)).one()
        fila_id = fila.id
    viejo = auth.firmar_paso({"id": cuil, "codigo_id": fila_id, "origen": "mail_padron"},
                             minutos=-1, proposito="registro")
    r = _final(c, cuil, viejo, cod, **{"cf-turnstile-response": "ok"})
    assert r.headers["location"].endswith("error=paso")
    assert not _persona(cuil).clave_hash
    # y con el token bueno el mismo código sigue sirviendo (no se gastó)
    assert _final(c, cuil, d["token"], cod).headers["location"] == "/app/inicio"


def test_codigo_de_recuperacion_del_mismo_cuil_no_sirve_para_registrar(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    with db.get_session() as s:
        fila, codigo = db.crear_codigo(s, "trabajador", cuil, "recuperacion",
                                       "a@ejemplo.com", "padron", "1.2.3.4")
        fila_id = fila.id
        s.commit()
    falso = auth.firmar_paso({"id": cuil, "tipo": "trabajador", "codigo_id": fila_id,
                              "origen": "mail_padron"}, proposito="registro")
    r = _final(TestClient(main.app), cuil, falso, codigo)
    assert r.headers["location"].endswith("error=codigo")
    assert not _persona(cuil).clave_hash


def test_codigo_de_empleador_con_el_mismo_numero_no_sirve_para_el_trabajador(entorno):
    x = _cuil()
    _afiliado(x, mail="a@ejemplo.com")
    _empresa(x, mail="e@empresa.com")
    c = TestClient(main.app)
    d = _iniciar(c, x, ruta="/empresa/registro/iniciar", campo="cuit").json()
    cod = _codigo_de(entorno)
    r = _final(c, x, d["token"], cod, **{"cf-turnstile-response": "ok"})   # token y código son de la empresa
    # Antes llegaba hasta "codigo"; desde QA-REG-01 el token de otro TIPO es "sin
    # token" y con el canal prendido corta antes de mirar el padrón: `paso`.
    assert r.headers["location"].endswith("error=paso")
    assert not _persona(x).clave_hash
    assert _final_emp(c, x, d["token"], cod).headers["location"] == "/empresa/inicio"


def test_si_otra_persona_se_registra_entre_el_paso_1_y_el_3_no_se_pisa_ni_se_gasta_el_codigo(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    cod = _codigo_de(entorno)
    with db.get_session() as s:                    # otro llegó primero (canal de otro tipo)
        db.asegurar_cuenta(s, cuil).clave_hash = auth.hashear_clave("del-otro")
        s.commit()
    hash_otro = _persona(cuil).clave_hash
    r = _final(c, cuil, d["token"], cod, clave="la-mia-123")
    assert r.headers["location"].endswith("error=yaexiste")
    assert _persona(cuil).clave_hash == hash_otro
    fila = _filas_codigo(cuil)[0]
    assert not fila.usado_en, "el código no se gasta si la cuenta ya existía"


def test_el_token_no_se_reutiliza_para_crear_dos_cuentas(entorno):
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    cod = _codigo_de(entorno)
    assert _final(c, cuil, d["token"], cod).headers["location"] == "/app/inicio"
    hash_1 = _persona(cuil).clave_hash
    assert _final(c, cuil, d["token"], cod, clave="otra-clave").headers["location"].endswith("error=yaexiste")
    assert _persona(cuil).clave_hash == hash_1


# ---------------------------------------------------------------------------
# 2. CÓDIGOS
# ---------------------------------------------------------------------------
def test_intentos_erroneos_se_persisten_y_agotan_mezclando_rutas(entorno):
    """El intento fallido se commitea (la ruta no hace rollback después) y los 5
    se cuentan juntos aunque lleguen por tokens/pedidos distintos."""
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    bueno = _codigo_de(entorno)
    malo = "000000" if bueno != "000000" else "111111"
    for n in range(1, db.CODIGO_MAX_INTENTOS + 1):
        assert _final(c, cuil, d["token"], malo).headers["location"].endswith("error=codigo")
        assert _filas_codigo(cuil)[0].intentos == n
        main._intentos_registro.clear()
    # agotado: ni el código correcto sirve
    assert _final(c, cuil, d["token"], bueno).headers["location"].endswith("error=codigo")
    assert not _persona(cuil).clave_hash


def test_mails_por_hora_que_un_tercero_puede_provocar_con_solo_el_cuil(entorno):
    """DOCUMENTA el límite aceptado por el plan (D2): sabiendo un CUIL, cualquiera
    manda como mucho CODIGOS_POR_HORA mails por hora al mail del padrón de esa
    persona (la 4.ª es E-REGISTRO-03), y cada pedido VENCE el código anterior:
    con 3 pedidos por hora mantiene afuera a la víctima (su 4.º intento ya es
    429). Verde = el cupo anda; la fricción es de diseño."""
    cuil = _cuil()
    _afiliado(cuil, mail="victima@ejemplo.com")
    atacante, victima = TestClient(main.app), TestClient(main.app)
    d_victima = _iniciar(victima, cuil).json()
    cod_victima = _codigo_de(entorno)
    for _ in range(db.CODIGOS_POR_HORA - 1):
        assert _iniciar(atacante, cuil).status_code == 200
    assert _iniciar(atacante, cuil).json()["codigo"] == "E-REGISTRO-03"
    assert len([m for m in entorno if m[0] == "victima@ejemplo.com"]) == db.CODIGOS_POR_HORA
    # el código de la víctima fue invalidado por el pedido siguiente del atacante
    assert _final(victima, cuil, d_victima["token"], cod_victima).headers["location"].endswith("error=codigo")


def test_cupo_compartido_entre_iniciar_y_mail(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    for i in range(db.CODIGOS_POR_HORA):
        assert c.post("/trabajador/registro/mail", data={"token": token, "mail": f"m{i}@ejemplo.com"}).status_code == 200
    r = c.post("/trabajador/registro/mail", data={"token": token, "mail": "otro@ejemplo.com"})
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-03"
    assert len(entorno) == db.CODIGOS_POR_HORA


def test_un_mismo_destino_no_recibe_codigos_de_muchos_cuiles(entorno):
    """ROJO (QA-REG-03). El cupo es POR CUIL, no por destino: con N afiliados
    sin mail en el padrón, un atacante manda 3 mails por CUIL al mismo mail
    ajeno (a nombre de Colm3na) y, de paso, agota los 3.000 mails/mes de Resend
    (D8). Lo correcto: tope por destino también."""
    victima = "tercero@ejemplo.com"
    c = TestClient(main.app)
    for _ in range(6):
        main._intentos_registro.clear()        # acá se prueba el cupo por destino, no el freno de la IP
        cuil = _cuil()
        _afiliado(cuil)
        token = _iniciar(c, cuil).json()["token"]
        for _ in range(db.CODIGOS_POR_HORA):
            c.post("/trabajador/registro/mail", data={"token": token, "mail": victima})
    recibidos = [m for m in entorno if m[0] == victima]
    # El tope es por DESTINO (CODIGOS_POR_HORA_DESTINO), aparte del de cada CUIL.
    assert len(recibidos) == db.CODIGOS_POR_HORA_DESTINO, f"{len(recibidos)} mails al mismo destino en una hora"


def test_pedir_codigos_con_exito_tambien_cuenta_para_el_freno_de_la_ip(entorno):
    """ROJO (QA-REG-04). El freno (`_login_fallo`) solo suma FALLOS: los pedidos de
    código que salen bien no cuestan nada, así que desde una IP se puede
    mandar un mail por segundo a afiliados distintos (y averiguar quién está
    afiliado, más la pista del mail) sin llegar nunca a E-REGISTRO-05."""
    c = TestClient(main.app)
    estados = []
    for _ in range(main.LOGIN_MAX_FALLOS * 2):
        cuil = _cuil()
        _afiliado(cuil, mail="a@ejemplo.com")
        estados.append(_iniciar(c, cuil).status_code)
    assert 429 in estados, f"{len(entorno)} códigos mandados desde una IP sin ningún freno"


@pytest.mark.xfail(strict=True, reason=(
    "BACKLOG / H-0008: el freno por IP toma el primer X-Forwarded-For, que escribe el "
    "cliente. Se cierra en el perimetro (Cloudflare: usar la IP que el perimetro firma), "
    "no en la app."))
def test_el_freno_por_ip_no_se_evade_cambiando_x_forwarded_for(entorno):
    """ROJO (QA-REG-05, ya conocido: H-0008 Parcial). `_ip_de` toma el PRIMER valor
    de X-Forwarded-For, que lo escribe el cliente; Render agrega la IP real al
    final. Rotando el header no hay freno, y el captcha apagado + la enumeración
    quedan sin costo."""
    c = TestClient(main.app)
    for i in range(main.LOGIN_MAX_FALLOS + 5):
        r = _iniciar(c, _cuil(), **{"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 403
    r = _iniciar(c, _cuil(), **{"X-Forwarded-For": "10.0.1.1"})
    assert r.status_code == 429, "el freno se evade con solo cambiar el header"


# ---------------------------------------------------------------------------
# 3. CANAL APAGADO (D9)
# ---------------------------------------------------------------------------
def test_canal_apagado_con_token_del_paso_mail_tambien_crea_nivel_1(entorno, monkeypatch):
    """Con el canal apagado un `{id}` o ningún token valen igual (D9)."""
    monkeypatch.delenv("MAIL_REMITENTE")
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = auth.firmar_paso({"id": cuil, "tipo": "trabajador"}, proposito="registro")
    assert _final(c, cuil, token, "").headers["location"] == "/app/inicio"
    p = _persona(cuil)
    assert (p.nivel_fiabilidad, p.nivel_origen) == (1, "cuil_padron")


def test_canal_prendido_sin_token_no_distingue_afiliados_de_ajenos(entorno):
    """ROJO (QA-REG-01 b). Con el canal prendido y SIN token, el POST final igual
    responde distinto para un CUIL afiliado (`paso`) que para uno ajeno
    (`nohabilitado`): el padrón se mira antes de exigir el token. Para que el
    redirect no sea un oráculo, lo que falta (el token) tiene que cortar primero."""
    afiliado, ajeno = _cuil(), _cuil()
    _afiliado(afiliado, mail="a@ejemplo.com")
    c = TestClient(main.app)
    a = _final(c, afiliado, "", "", **{"cf-turnstile-response": "ok"}).headers["location"]
    b = _final(c, ajeno, "", "", **{"cf-turnstile-response": "ok"}).headers["location"]
    assert a == b, f"afiliado -> {a}, ajeno -> {b}"


# ---------------------------------------------------------------------------
# 4. MAIL DECLARADO
# ---------------------------------------------------------------------------
INVALIDOS_QUE_EL_CORREO_RECHAZA = [
    "a,b@ejemplo.com",              # dos destinatarios
    "a;b@ejemplo.com",
    "<a@ejemplo.com>",
    "a@ejemplo.com>",
    'a"b@ejemplo.com',
    "a(b)@ejemplo.com",
    "a@ejemplo.c",                  # TLD de una letra
    "x" * 65 + "@ejemplo.com",      # parte local de más de 64
]
INVALIDOS_QUE_YA_SE_RECHAZAN = [
    "a@@ejemplo.com", "a@b@ejemplo.com", "a b@ejemplo.com", "a@ejemplo.com\nBcc: x@y.com",
    "sin-arroba", "a@sinpunto", "@ejemplo.com", "a@.com",
    "a" * 250 + "@e.com",         # 256 caracteres
]


@pytest.mark.parametrize("mail", INVALIDOS_QUE_EL_CORREO_RECHAZA)
def test_mail_declarado_que_correo_no_acepta_se_corta_en_la_ruta(entorno, mail):
    """ROJO (QA-REG-06). `_mail_declarable` usa su propia regex en vez de
    `correo.destino_valido` (D1/plan): estos mails pasan la ruta, gastan 1 de
    los 3 códigos del CUIL, dejan una fila en CodigoVerificacion y recién ahí
    `correo.enviar` los rechaza, y la persona lee E-REGISTRO-06 ("no pudimos
    mandar el mail, probá más tarde") en vez de "escribí un mail válido"."""
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    r = c.post("/trabajador/registro/mail", data={"token": token, "mail": mail})
    assert r.status_code == 422 and r.json()["error"] == "mail", (r.status_code, r.text)
    assert _filas_codigo(cuil) == [], "no debió gastarse un código del cupo"


@pytest.mark.parametrize("mail", INVALIDOS_QUE_YA_SE_RECHAZAN)
def test_mail_declarado_invalido_es_422_y_no_gasta_cupo(entorno, mail):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    r = c.post("/trabajador/registro/mail", data={"token": token, "mail": mail})
    assert r.status_code == 422 and r.json()["error"] == "mail"
    assert _filas_codigo(cuil) == [] and entorno == []


def test_mail_declarado_con_unicode_valido_se_acepta_y_queda_en_su_columna(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    r = c.post("/trabajador/registro/mail", data={"token": token, "mail": "  ñandú@ejemplo.com.ar "})
    assert r.status_code == 200, r.text
    d = r.json()
    r = _final(c, cuil, d["token"], _codigo_de(entorno))
    assert r.headers["location"] == "/app/inicio"
    p = _persona(cuil)
    assert p.mail_declarado == "ñandú@ejemplo.com.ar" and p.mail == "" and p.mail_padron == ""


def test_el_mail_pisado_en_el_form_final_no_cambia_el_declarado_confirmado(entorno):
    """El `mail` del POST final no entra a ninguna columna, y el que cuenta es el
    de la FILA del código (no el del token ni el del form)."""
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    d = c.post("/trabajador/registro/mail", data={"token": token, "mail": "real@ejemplo.com"}).json()
    # token con otro mail embebido: no se usa
    falso = auth.firmar_paso({"id": cuil, "tipo": "trabajador", "codigo_id": _filas_codigo(cuil)[0].id,
                              "origen": "mail_declarado", "mail": "falso@ejemplo.com"},
                             proposito="registro")
    assert d["token"]
    r = _final(c, cuil, falso, _codigo_de(entorno), mail="otro@ejemplo.com")
    assert r.headers["location"] == "/app/inicio"
    assert _persona(cuil).mail_declarado == "real@ejemplo.com"


def test_paso_mail_tambien_cuenta_para_el_freno_si_el_mail_es_malo_o_el_token_no_sirve(entorno):
    cuil = _cuil()
    _afiliado(cuil)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    antes = main._intentos_registro["testclient"][0]      # el iniciar que salió bien ya sumó (QA-REG-04)
    c.post("/trabajador/registro/mail", data={"token": token, "mail": "mal"})
    c.post("/trabajador/registro/mail", data={"token": "basura", "mail": "a@ejemplo.com"})
    assert main._intentos_registro["testclient"][0] == antes + 2


# ---------------------------------------------------------------------------
# 5. CLAVE
# ---------------------------------------------------------------------------
def test_el_registro_exige_la_clave_minima_como_el_resto_de_la_app(entorno):
    """ROJO (QA-REG-07). `CLAVE_MINIMA` (6) se exige al recuperar y al cambiar la
    clave, pero el POST final del registro acepta cualquier cosa: la pantalla
    dice `minlength=4` (otro número) y el servidor ni mira. Un cliente que
    arma el POST crea una cuenta con clave de un carácter (o vacía)."""
    cuil = _cuil()
    _afiliado(cuil, mail="a@ejemplo.com")
    c = TestClient(main.app)
    d = _iniciar(c, cuil).json()
    r = _final(c, cuil, d["token"], _codigo_de(entorno), clave="a")
    assert not _persona(cuil).clave_hash, "se creó la cuenta con una clave de 1 carácter"
    assert r.headers["location"] != "/app/inicio"


# ---------------------------------------------------------------------------
# 6. PANTALLA
# ---------------------------------------------------------------------------
def test_la_pantalla_cubre_todos_los_errores_del_registro():
    """Cada `?error=` que redirige el POST final tiene mensaje y deja abierta la
    pestaña de registro en las dos pantallas."""
    c = TestClient(main.app)
    casos = {"/ingresar": ("captcha", "cuil", "domicilio", "nohabilitado", "yaexiste", "paso", "codigo", "espera_registro"),
             "/ingresar-empresa": ("captcha", "cuit", "nohabilitado", "yaexiste", "paso", "codigo", "espera_registro")}
    for ruta, errores in casos.items():
        base = c.get(ruta).text
        lista = re.search(r"\[((?:'[a-z_]+',?\s*)+)\]\.indexOf\(err\)", base).group(1)
        for err in errores:
            html = c.get(f"{ruta}?error={err}").text
            assert html.count('<div class="error">') > base.count('<div class="error">'), (ruta, err)
            assert f"'{err}'" in lista, (ruta, err)


def test_los_controles_ocultos_del_registro_estan_disabled_al_cargar():
    """`regPaso('1')` deshabilita todo lo que no es del paso 1; el campo `mail`
    desapareció de la pestaña del afiliado (se confirma en el paso 2)."""
    html = TestClient(main.app).get("/ingresar").text
    form = html.split('id="form-registro"')[1].split("</form>")[0]
    assert 'name="mail"' not in form
    assert 'name="token"' in form and 'name="codigo"' in form
    assert "regPaso('1');" in html
    assert 'type="hidden" name="token"' in form and 'type="hidden" name="codigo"' in form


def test_el_codigo_pegado_con_espacios_se_puede_enviar():
    """ROJO (QA-REG-08, menor). El input del código tiene `maxlength=6` y
    `pattern="[0-9]{6}"`, y el JS recién después le saca los espacios
    (`replace(/\\s+/g,'')`): un código copiado como "123 456" queda truncado o
    bloqueado por la validación del navegador antes de llegar al JS. La
    limpieza es código muerto; hay que quitar `pattern`/`maxlength` o
    limpiar en el evento `input`."""
    for ruta in ("/ingresar", "/ingresar-empresa"):
        html = TestClient(main.app).get(ruta).text
        entrada = re.search(r'<input id="reg-codigo"[^>]*>', html).group(0)
        assert "pattern=" not in entrada and "maxlength" not in entrada, entrada

"""QA de la recuperación de clave, la clave temporal y la confirmación del mail
(PLAN_REGISTRO.md, D6, D10, §4.3 y §4.6; desarrollador E).

No es regresión del desarrollador: es la evidencia de la revisión de QA. Los
tests marcados ROJO afirman lo que la seguridad o el plan piden y HOY FALLAN;
cada uno cita su hallazgo (QR-n) del reporte. Los marcados DOCUMENTA pasan y
dejan escrito lo que el sistema revela o permite a propósito (riesgo residual),
para que un cambio no lo mueva sin que alguien lo decida. Los OK evitan que se
rompa lo revisado y estaba bien.

`correo.enviar` y `captcha.verificar` van simulados: ningún test sale a la red.

Correr con: python -m pytest test_qa_recuperacion_clave.py -q
"""
import itertools
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
                Sindicato, Trabajador, UsuarioSindicato)
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES
from sqlmodel import select

db.crear_tablas()

for _v in ("RESEND_API_KEY", "MAIL_REMITENTE", "TURNSTILE_SITE_KEY", "TURNSTILE_SECRET"):
    os.environ.pop(_v, None)

VIEJA = "clave-vieja-1"
NUEVA = "clave-nueva-9"
MAIL = "ana.perez@ejemplo.com"
MAIL_ATACANTE = "atacante@ejemplo.com"
_enviar_real = correo.enviar

with db.get_session() as s:
    _a = Sindicato(nombre="QR Sindicato A", slug="qr-a", color_base="#0f1b2d",
                   modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    _b = Sindicato(nombre="QR Sindicato B", slug="qr-b", color_base="#0f1b2d",
                   modulos_habilitados=list(MODULOS_INICIALES) + ["empleadores"])
    _estricto = Sindicato(nombre="QR Estricto", slug="qr-estricto", color_base="#0f1b2d",
                          acepta_mail_declarado=False,
                          modulos_habilitados=list(MODULOS_INICIALES))
    s.add(_a); s.add(_b); s.add(_estricto)
    s.commit()
    for _x in (_a, _b, _estricto):
        s.refresh(_x)
    A, B, ESTRICTO = _a.id, _b.id, _estricto.id
    s.add(UsuarioSindicato(sindicato_id=B, usuario="20577777771", nombre="Admin B",
                           clave_hash=auth.hashear_clave("super-b"), es_super_admin=True,
                           debe_cambiar_clave=False))
    s.commit()

_contador = itertools.count(1)


def _nuevo(prefijo="20") -> str:
    """Un CUIL/CUIT con verificador válido y que ningún otro test usa."""
    n = next(_contador)
    return cuit.corregir(f"{prefijo}{n + 5000000:08d}0")


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
            origen="", contacto=""):
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid or A, cuil=cuil, activo=True, registrado=True))
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(clave) if clave else "",
                               mail=contacto, mail_padron=mail, mail_declarado=declarado,
                               mail_declarado_confirmado="2026-10-01 10:00" if declarado else "",
                               clave_temporal=temporal, nivel_fiabilidad=nivel, nivel_origen=origen))
        s.commit()


def _empresa(cuit_, mail="", sid=None, clave=VIEJA, activo=True):
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=sid or A, cuit=cuit_, razon_social="Empresa QR", mail_padron=mail,
                        activo=activo, registrado=True))
        s.add(CuentaEmpleador(cuit=cuit_, clave_hash=auth.hashear_clave(clave)))
        s.commit()


def _cuenta_db(cuil):
    with db.get_session() as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _codigos(identificador):
    with db.get_session() as s:
        return s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == identificador)).all()


def _iniciar(c, numero, base="/ingresar", campo="cuil", **kw):
    return c.post(f"{base}/recuperar/iniciar", data={campo: numero}, **kw)


def _confirmar(c, token, codigo, clave=NUEVA, base="/ingresar"):
    return c.post(f"{base}/recuperar", follow_redirects=False,
                  data={"token": token, "codigo": codigo, "clave": clave, "clave2": clave})


def _login(c, cuil, clave):
    return c.post("/trabajador/login", data={"cuil": cuil, "clave": clave}, follow_redirects=False)


def _sesion(cuil, **kw):
    c = TestClient(main.app, **kw)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    return c


def _admin_b():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "20577777771", "clave": "super-b"},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return c


def _huella(r):
    """Todo lo que un observador ve de una respuesta, menos la hora."""
    cab = {k: v for k, v in r.headers.items() if k.lower() not in ("date",)}
    return r.status_code, r.content, cab


# ===========================================================================
# 1. Recuperación: lo que revela y lo que no
# ===========================================================================
def test_ok_las_respuestas_sin_mail_del_padron_son_identicas_byte_a_byte(canal, monkeypatch):
    """Cuerpo, status y cabeceras: CUIL inexistente, cuenta SIN clave (aun con
    mail del padrón), solo mail de contacto, solo mail declarado y canal apagado."""
    c = TestClient(main.app)
    inexistente = _nuevo()
    sin_clave = _nuevo(); _cuenta(sin_clave, mail=MAIL, clave="")
    contacto = _nuevo(); _cuenta(contacto, contacto="contacto@ejemplo.com")
    declarado = _nuevo(); _cuenta(declarado, declarado="declarado@ejemplo.com")
    apagado = _nuevo(); _cuenta(apagado, mail=MAIL)
    base = _huella(_iniciar(c, inexistente))
    assert base[0] == 200 and b'"paso":"sindicato"' in base[1]
    for nombre, cuil in (("sin clave con mail del padrón", sin_clave), ("solo contacto", contacto),
                         ("solo declarado", declarado)):
        assert _huella(_iniciar(c, cuil)) == base, nombre
    monkeypatch.setattr(correo, "habilitado", lambda: False)
    assert _huella(_iniciar(c, apagado)) == base, "canal apagado"
    assert not canal, "ninguno de estos casos manda un mail"
    for cuil in (inexistente, sin_clave, contacto, declarado, apagado):
        assert not _codigos(cuil), cuil


def test_ok_lo_mismo_en_la_empresa(canal):
    c = TestClient(main.app)
    inexistente = _nuevo("30")
    sin_mail = _nuevo("30"); _empresa(sin_mail)
    base = _huella(_iniciar(c, inexistente, "/ingresar-empresa", "cuit"))
    assert _huella(_iniciar(c, sin_mail, "/ingresar-empresa", "cuit")) == base
    assert not canal


def test_documenta_la_respuesta_con_mail_del_padron_es_distinta_y_da_una_pista(canal):
    """RIESGO RESIDUAL ACEPTADO (D11), QR-9: con mail del padrón la respuesta cambia
    de forma (paso 'codigo', token y pista 'a***@dominio'). Cualquiera con un CUIL y
    el captcha averigua que ese CUIL tiene cuenta, que el sindicato le cargó un mail
    y la PRIMERA LETRA Y EL DOMINIO de ese mail. Además la rama larga manda un mail
    de verdad (tarda más que la corta) y el pedido no cuenta para el freno."""
    c = TestClient(main.app)
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL)
    miss = _iniciar(c, _nuevo())
    hit = _iniciar(c, cuil)
    assert hit.status_code == miss.status_code == 200
    assert hit.content != miss.content
    d = hit.json()
    assert d["paso"] == "codigo" and d["pista"] == "a***@ejemplo.com"
    assert canal and canal[-1][0] == MAIL


def test_documenta_el_cupo_solo_existe_si_hay_mail_del_padron(canal):
    """El E-REGISTRO-03 no revela nada que el primer 'codigo' no haya revelado ya:
    sin mail del padrón nunca se crea una fila, así que nunca se llega al cupo."""
    c = TestClient(main.app)
    con = _nuevo(); _cuenta(con, mail=MAIL)
    sin = _nuevo(); _cuenta(sin)
    for _ in range(3):
        assert _iniciar(c, con).json()["paso"] == "codigo"
        assert _iniciar(c, sin).json()["paso"] == "sindicato"
    r = _iniciar(c, con)
    assert r.status_code == 429 and r.json()["codigo"] == "E-REGISTRO-03"
    assert _iniciar(c, sin).status_code == 200


def test_rojo_qr4_otro_pedido_no_deberia_invalidar_el_codigo_vivo_de_la_persona(canal):
    """QR-4 (Medio, disponibilidad). `crear_codigo` vence el código pendiente de la
    persona al emitir otro, y el cupo es por CUIL (3 por hora) y no por IP: quien
    resuelva el captcha 3 veces por hora deja a un afiliado sin poder recuperar su
    clave, o le pisa el código que acaba de pedir. Se pide que el pedido de un
    tercero no mate el código vivo (p. ej. reusar el vivo en vez de emitir otro)."""
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL)
    persona = TestClient(main.app)
    token = _iniciar(persona, cuil).json()["token"]
    codigo = _codigo_de(canal)
    tercero = TestClient(main.app)
    tercero.headers["x-forwarded-for"] = "203.0.113.77"
    assert _iniciar(tercero, cuil).json()["paso"] == "codigo"
    r = _confirmar(persona, token, codigo)
    assert r.status_code == 303, (
        "el pedido de un tercero invalidó el código de la persona (E-REGISTRO-02)")


def test_rojo_qr5_los_pedidos_que_aciertan_no_cuentan_para_el_freno(canal):
    """QR-5 (Bajo, igual que el registro). El freno cuenta solo los pedidos SIN mail
    del padrón; los que tienen mail (los que de verdad se quiere ocultar) son gratis.
    Barrer una lista de CUIL contra el padrón de un sindicato sale solo del captcha
    (apagado hoy en Pruebas) y del cupo por CUIL. Se pide un tope por IP que cuente
    TODOS los pedidos de `iniciar`."""
    c = TestClient(main.app)
    cuiles = []
    for _ in range(30):
        cuil = _nuevo(); _cuenta(cuil, mail=f"p{len(cuiles)}@ejemplo.com"); cuiles.append(cuil)
    estados = [_iniciar(c, cuil).status_code for cuil in cuiles]
    assert 429 in estados, "30 CUIL con mail respondidos desde la misma IP sin ningún freno"


# ===========================================================================
# 2. Recuperación: el código, el token y la clave
# ===========================================================================
def test_ok_un_token_de_registro_o_de_confirmar_mail_no_sirve_para_recuperar(canal):
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]
    codigo = _codigo_de(canal)
    fila = _codigos(cuil)[-1]
    for proposito in ("registro", "confirmar_mail", "cambio_clave"):
        falso = auth.firmar_paso({"cuil": cuil, "codigo_id": fila.id}, proposito=proposito)
        r = _confirmar(c, falso, codigo)
        assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02", proposito
    # el token de recuperación sigue sirviendo: ninguno de los intentos gastó el código
    assert _confirmar(c, token, codigo).status_code == 303


def test_ok_el_codigo_de_un_cuil_con_el_token_de_otro_no_sirve(canal):
    uno, otro = _nuevo(), _nuevo()
    _cuenta(uno, mail="uno@ejemplo.com"); _cuenta(otro, mail="otro@ejemplo.com")
    c = TestClient(main.app)
    t_uno = _iniciar(c, uno).json()["token"]; cod_uno = _codigo_de(canal)
    _iniciar(c, otro); id_otro = _codigos(otro)[-1].id
    mezcla = auth.firmar_paso({"cuil": uno, "codigo_id": id_otro}, proposito="recuperacion")
    r = _confirmar(c, mezcla, _codigo_de(canal))
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _confirmar(c, t_uno, cod_uno).status_code == 303
    assert auth.verificar_clave(NUEVA, _cuenta_db(uno).clave_hash)
    assert auth.verificar_clave(VIEJA, _cuenta_db(otro).clave_hash)


def test_ok_clave_corta_o_distinta_se_rechaza_y_la_vieja_sigue_hasta_el_final(canal):
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL, temporal=True)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]; codigo = _codigo_de(canal)
    corta = c.post("/ingresar/recuperar", data={"token": token, "codigo": codigo,
                                                "clave": "12345", "clave2": "12345"})
    distinta = c.post("/ingresar/recuperar", data={"token": token, "codigo": codigo,
                                                   "clave": NUEVA, "clave2": NUEVA + "x"})
    assert corta.status_code == distinta.status_code == 400
    assert _codigos(cuil)[-1].usado_en == "" and _codigos(cuil)[-1].intentos == 0
    assert _confirmar(c, token, codigo).status_code == 303
    cuenta = _cuenta_db(cuil)
    assert cuenta.clave_temporal is False
    assert auth.verificar_clave(NUEVA, cuenta.clave_hash) and not auth.verificar_clave(VIEJA, cuenta.clave_hash)
    assert _login(TestClient(main.app), cuil, VIEJA).headers["location"].startswith("/ingresar?error=")


def test_ok_cinco_intentos_agotan_el_codigo_aunque_despues_venga_el_bueno(canal):
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL)
    c = TestClient(main.app)
    token = _iniciar(c, cuil).json()["token"]; bueno = _codigo_de(canal)
    malo = "000000" if bueno != "000000" else "111111"
    for _ in range(5):
        main._intentos_registro.clear()          # que sea el código y no el freno el que corta
        assert _confirmar(c, token, malo).status_code == 400
    main._intentos_registro.clear()
    assert _confirmar(c, token, bueno).status_code == 400
    assert auth.verificar_clave(VIEJA, _cuenta_db(cuil).clave_hash)


def test_rojo_qr1_la_sesion_abierta_antes_sobrevive_a_la_recuperacion(canal):
    """QR-1 (Medio). Las sesiones son tokens firmados sin estado: cambiar la clave
    (recuperación autoservicio, clave temporal o reset del sindicato) no corta una
    sesión ya abierta, y mientras el impostor la use no vence (15 min de INACTIVIDAD).
    Es justo el caso que D6 quiere resolver: el impostor llegó primero y el afiliado
    real recupera su cuenta; el impostor sigue adentro. Se pide atar la sesión a la
    clave (p. ej. una huella corta de `clave_hash` firmada en el token)."""
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL)
    impostor = _sesion(cuil)
    assert impostor.get("/app/inicio", follow_redirects=False).status_code == 200
    real = TestClient(main.app)
    token = _iniciar(real, cuil).json()["token"]
    assert _confirmar(real, token, _codigo_de(canal)).status_code == 303
    despues = impostor.get("/app/inicio", follow_redirects=False)
    assert despues.status_code in (303, 401, 403), (
        "tras cambiar la clave la sesión vieja sigue abierta (HTTP %s)" % despues.status_code)


# ===========================================================================
# 3. El mail del padrón como canal: quién lo puede escribir (cruza tenants)
# ===========================================================================
def test_rojo_qr2_un_sindicato_ajeno_se_queda_con_la_recuperacion_de_una_persona(canal):
    """QR-2 (ALTO, cruza sindicatos; mismo origen que QD-1b del QA del panel). La
    recuperación confía en `CuentaTrabajador.mail_padron`, que es UNO por persona
    (no por sindicato) y lo escribe cualquier sindicato que tenga ese CUIL en su
    padrón, y el padrón de B lo llena el propio admin de B con cualquier CUIL con
    verificador válido. Cadena: alta en B con mail propio -> recuperar -> el código
    llega al atacante -> clave nueva -> entra a la cuenta de la víctima en A."""
    victima = _nuevo(); _cuenta(victima, mail=MAIL, sid=A)
    b = _admin_b()
    r = b.post("/admin/trabajador", data={
        "cuil": victima, "nombre": "Atacante", "provincia": "Santa Fe", "localidad": "Rosario",
        "mail": MAIL_ATACANTE}, follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers
    c = TestClient(main.app)
    _iniciar(c, victima)
    destinos = [e[0] for e in canal]
    assert MAIL_ATACANTE not in destinos, (
        "el código de recuperación de la víctima (sindicato A) salió al mail que cargó el admin de B")


def test_rojo_qr3_la_empresa_tiene_el_mismo_problema_con_el_alta_de_empleador_ajena(canal):
    """QR-3 (ALTO). `mail_padron_de_empresa` toma el primer `Empleador.mail_padron`
    no vacío entre las altas del CUIT en CUALQUIER sindicato (activas primero, luego
    la más vieja). Un sindicato con el módulo empleadores da de alta cualquier CUIT
    válido con su propio mail: si el legítimo no tiene mail cargado (o su alta está
    dada de baja), la recuperación de la empresa va al atacante."""
    victima = _nuevo("30")
    _empresa(victima, mail="", sid=A)          # alta legítima de A, sin mail del padrón
    b = _admin_b()
    r = b.post("/admin/empleador", data={"cuit": victima, "razon_social": "Alta de B",
                                         "mail": MAIL_ATACANTE}, follow_redirects=False)
    assert r.status_code == 303 and "error=" not in r.headers["location"], r.headers
    c = TestClient(main.app)
    _iniciar(c, victima, "/ingresar-empresa", "cuit")
    assert MAIL_ATACANTE not in [e[0] for e in canal], (
        "el código de la empresa (cuenta de A) salió al mail que cargó otro sindicato")


# ===========================================================================
# 4. Clave temporal
# ===========================================================================
def _token_de_cambio(location: str) -> str:
    return re.search(r"token=([^&]+)", location).group(1)


def test_ok_login_con_temporal_no_deja_ninguna_cookie_y_el_token_solo_revela_el_cuil():
    cuil = _nuevo(); _cuenta(cuil, temporal=True)
    c = TestClient(main.app)
    r = _login(c, cuil, VIEJA)
    assert r.status_code == 303 and r.headers["location"].startswith("/ingresar/cambiar-clave?token=")
    assert not r.headers.get_list("set-cookie")
    assert not c.cookies.get(main.COOKIE_TRABAJADOR) and not c.cookies.get("cuil_trab")
    d = auth.leer_paso(_token_de_cambio(r.headers["location"]), "cambio_clave")
    assert d == {"cuil": cuil}
    assert auth.leer_paso(_token_de_cambio(r.headers["location"]), "recuperacion") is None


def test_ok_el_token_de_un_cuil_con_la_temporal_de_otro_no_cambia_nada():
    uno, otro = _nuevo(), _nuevo()
    _cuenta(uno, clave="temporal-uno", temporal=True); _cuenta(otro, clave="temporal-otro", temporal=True)
    c = TestClient(main.app)
    token = _token_de_cambio(_login(c, uno, "temporal-uno").headers["location"])
    r = c.post("/ingresar/cambiar-clave", data={
        "token": token, "clave_actual": "temporal-otro", "clave": NUEVA, "clave2": NUEVA})
    assert r.status_code == 400 and not r.headers.get_list("set-cookie")
    assert auth.verificar_clave("temporal-uno", _cuenta_db(uno).clave_hash)
    assert auth.verificar_clave("temporal-otro", _cuenta_db(otro).clave_hash)


def test_ok_cambiar_la_temporal_cuenta_para_el_freno_de_los_logins():
    cuil = _nuevo(); _cuenta(cuil, clave="temporal-ok", temporal=True)
    c = TestClient(main.app)
    token = _token_de_cambio(_login(c, cuil, "temporal-ok").headers["location"])
    for _ in range(main.LOGIN_MAX_FALLOS):
        r = c.post("/ingresar/cambiar-clave", data={
            "token": token, "clave_actual": "adivinando", "clave": NUEVA, "clave2": NUEVA})
        assert r.status_code == 400
    r = c.post("/ingresar/cambiar-clave", data={
        "token": token, "clave_actual": "temporal-ok", "clave": NUEVA, "clave2": NUEVA})
    assert r.status_code == 429 and not r.headers.get_list("set-cookie")
    assert _cuenta_db(cuil).clave_temporal is True


def test_ok_cambio_exitoso_abre_la_misma_sesion_que_el_login_y_la_temporal_no_sirve_dos_veces():
    cuil = _nuevo(); _cuenta(cuil, clave="temporal-ok", temporal=True)
    c = TestClient(main.app)
    token = _token_de_cambio(_login(c, cuil, "temporal-ok").headers["location"])
    r = c.post("/ingresar/cambiar-clave", follow_redirects=False, data={
        "token": token, "clave_actual": "temporal-ok", "clave": NUEVA, "clave2": NUEVA})
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    sesion = auth.leer_sesion(c.cookies.get(main.COOKIE_TRABAJADOR))
    assert sesion["rol"] == "trabajador" and sesion["ident"] == cuil
    assert c.cookies.get("cuil_trab") == cuil
    again = TestClient(main.app).post("/ingresar/cambiar-clave", data={
        "token": token, "clave_actual": "temporal-ok", "clave": "otra-clave-1", "clave2": "otra-clave-1"})
    assert not again.headers.get_list("set-cookie")


# ===========================================================================
# 5. Confirmación del mail (cuentas viejas)
# ===========================================================================
def test_rojo_qr6_el_mail_declarado_pasa_un_filtro_mas_laxo_que_el_del_envio_y_gasta_el_cupo(canal, monkeypatch):
    """QR-6 (Bajo). `main._RX_MAIL` es más laxa que `correo.destino_valido`: deja
    pasar 'a@b.com;c.com'. `correo.enviar` lo rechaza (no hay inyección), pero
    ANTES se creó y se comprometió la fila del código (cupo gastado) y la persona
    ve un 503 'no pudimos mandar el mail' en vez de 'escribí un mail válido'. Se pide
    validar con `correo.destino_valido` antes de crear el código."""
    cuil = _nuevo(); _cuenta(cuil)
    monkeypatch.setenv("RESEND_API_KEY", "x"); monkeypatch.setenv("MAIL_REMITENTE", "Colm3na <a@b.com>")
    monkeypatch.setattr(correo, "enviar", _enviar_real)
    monkeypatch.setattr(correo, "habilitado", lambda: True)

    def _nunca_sale(*a, **k):
        raise AssertionError("no tiene que haber salida a la red con un destino inválido")
    monkeypatch.setattr("urllib.request.urlopen", _nunca_sale)
    r = _sesion(cuil).post("/app/confirmar-mail/iniciar", data={"mail": "a@b.com;c.com"})
    assert r.status_code == 400, f"HTTP {r.status_code} {r.text[:120]}"
    assert not _codigos(cuil), "se gastó cupo y quedó una fila con un destino imposible"


def test_ok_pluriempleo_con_un_sindicato_estricto_no_acepta_el_mail_declarado(canal):
    cuil = _nuevo(); _cuenta(cuil, sid=A)
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=ESTRICTO, cuil=cuil, activo=True, registrado=True)); s.commit()
    c = _sesion(cuil)
    r = c.post("/app/confirmar-mail/iniciar", data={"mail": "otro@ejemplo.com"})
    assert r.json()["paso"] == "sindicato" and not canal and not _codigos(cuil)


def test_ok_el_mail_declarado_no_toca_mail_ni_mail_padron_y_el_cuil_sale_de_la_sesion(canal):
    cuil, ajeno = _nuevo(), _nuevo()
    _cuenta(cuil, contacto="contacto@ejemplo.com"); _cuenta(ajeno, mail=MAIL)
    c = _sesion(cuil)
    d = c.post("/app/confirmar-mail/iniciar",
               data={"mail": "nuevo@ejemplo.com", "cuil": ajeno}).json()
    assert canal[-1][0] == "nuevo@ejemplo.com"          # el CUIL del form se ignora
    assert not _codigos(ajeno)
    assert c.post("/app/confirmar-mail", data={"token": d["token"], "codigo": _codigo_de(canal)}).json()["nivel"] == 2
    cuenta = _cuenta_db(cuil)
    assert (cuenta.mail, cuenta.mail_padron) == ("contacto@ejemplo.com", "")
    assert cuenta.mail_declarado == "nuevo@ejemplo.com" and cuenta.mail_declarado_confirmado
    assert cuenta.nivel_origen == "mail_declarado"
    assert _cuenta_db(ajeno).nivel_fiabilidad == 1


def test_ok_un_token_de_recuperacion_no_sirve_para_confirmar_el_mail(canal):
    cuil = _nuevo(); _cuenta(cuil, mail=MAIL)
    token = _iniciar(TestClient(main.app), cuil).json()["token"]
    r = _sesion(cuil).post("/app/confirmar-mail", data={"token": token, "codigo": _codigo_de(canal)})
    assert r.status_code == 400 and r.json()["codigo"] == "E-REGISTRO-02"
    assert _cuenta_db(cuil).nivel_fiabilidad == 1


# ===========================================================================
# 6. Pantallas y CSP
# ===========================================================================
def test_ok_la_csp_ensanchada_cubre_la_recuperacion_y_no_la_confirmacion_del_mail(monkeypatch):
    assert main._csp_para("/ingresar/recuperar") == main.CSP_INGRESOS
    assert main._csp_para("/ingresar/cambiar-clave") == main.CSP_INGRESOS
    assert main._csp_para("/ingresar-empresa/recuperar") == main.CSP_INGRESOS
    assert main._csp_para("/ingresar-empresa/cambiar-clave") == main.CSP_INGRESOS
    assert main._csp_para("/app/confirmar-mail") == main.CSP
    assert main._csp_para("/app/inicio") == main.CSP
    con = main._armar_csp(True)
    assert "challenges.cloudflare.com" in con and "challenges.cloudflare.com" not in main._armar_csp(False)
    c = TestClient(main.app)
    assert c.get("/ingresar/recuperar").headers["content-security-policy"] == main.CSP_INGRESOS
    assert _sesion(_nuevo()).get("/app/confirmar-mail", follow_redirects=False).headers[
        "content-security-policy"] == main.CSP


def test_ok_las_pantallas_no_cargan_nada_externo_salvo_el_captcha_y_confirmar_sigue_el_esquema_interior():
    base = open("templates/_clave_base.html", encoding="utf-8").read()
    for t in ("recuperar_clave", "cambiar_clave"):
        html = base + open(f"templates/{t}.html", encoding="utf-8").read()
        assert not re.findall(r'(?:src|href)=["\']https?://', html), t
    assert "https://" in open("templates/_captcha.html", encoding="utf-8").read()   # el único externo
    conf = open("templates/confirmar_mail.html", encoding="utf-8").read()
    for marca in ('{% include "_encabezado.html" %}', 'class="mesa franja"', "mesa-cont",
                  "titulo-pagina", "?v={{ sello_static('marca.css') }}"):
        assert marca in conf, marca
    portada = open("templates/portada.html", encoding="utf-8").read()
    assert 'class="pt-fila pt-vid pt-aviso"' in portada


def test_rojo_qr7_la_pantalla_de_clave_pide_static_sin_el_sello_de_version():
    """QR-7 (Bajo, coherencia con CLAUDE.md: 'Todo lo que sale de /static/ va con
    sello ?v=, sin excepción'). `_clave_base.html` copia de los logins el
    `url('/static/fonts/barlow-condensed-bold.woff2')` y el
    `/static/logo_mitrabajo.svg` sin sello: un cambio tarda hasta 1 h en llegar. Los
    logins existentes tienen el mismo defecto (no es un problema nuevo de E)."""
    html = open("templates/_clave_base.html", encoding="utf-8").read()
    sin_sello = [m.group(0) for m in re.finditer(r"/static/[A-Za-z0-9_./-]+(?!\?v=)", html)
                 if not html[m.end():].startswith("?v=")]
    assert not sin_sello, f"sin sello: {sin_sello}"


# ===========================================================================
# 7. Entradas rotas: nada puede dar 500
# ===========================================================================
@pytest.mark.parametrize("basura", ["", " ", "x", "a.b", "..", "x" * 5000, "eyJ.eyJ", "%00", "';--"])
def test_ok_ningun_campo_roto_produce_un_500(basura, canal):
    c = TestClient(main.app, raise_server_exceptions=False)
    for base, campo in (("/ingresar", "cuil"), ("/ingresar-empresa", "cuit")):
        assert _iniciar(c, basura, base, campo).status_code == 200
        r = c.post(f"{base}/recuperar", data={"token": basura, "codigo": basura,
                                              "clave": basura, "clave2": basura})
        assert r.status_code < 500, (base, r.status_code)
        assert c.get(f"{base}/cambiar-clave", params={"token": basura}).status_code == 200
        r = c.post(f"{base}/cambiar-clave", data={"token": basura, "clave_actual": basura,
                                                   "clave": basura, "clave2": basura})
        assert r.status_code < 500, (base, r.status_code)
    s = _sesion(_nuevo(), raise_server_exceptions=False)
    assert s.post("/app/confirmar-mail", data={"token": basura, "codigo": basura}).status_code < 500
    assert s.post("/app/confirmar-mail/iniciar", data={"mail": basura}).status_code < 500


@pytest.mark.parametrize("metodo,ruta,campo", [
    ("GET", "/ingresar/cambiar-clave", "params"),
    ("POST", "/ingresar/cambiar-clave", "data"),
    ("POST", "/ingresar/recuperar", "data"),
    ("POST", "/ingresar-empresa/cambiar-clave", "data"),
    ("POST", "/ingresar-empresa/recuperar", "data"),
])
def test_rojo_qr8_un_token_con_caracteres_no_ascii_da_500(metodo, ruta, campo):
    """QR-8 (Medio: error no previsto que cualquiera dispara sin sesión ni captcha,
    y cada 500 va a Sentry y a Telegram). `auth.leer_paso` compara la firma con
    `hmac.compare_digest(str, str)`, que levanta TypeError si algún string tiene
    caracteres no ASCII ('é.é'). El token llega tal cual del formulario o de la URL.
    `auth.leer_sesion` (línea 134) tiene el mismo defecto con una cookie no ASCII.
    Cambio mínimo: comparar `firma.encode()` con `esperada.encode()` (bytes) o
    devolver None si `firma` no es ASCII."""
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.request(metodo, ruta, **{campo: {"token": "é.é", "codigo": "1", "clave_actual": "x",
                                           "clave": "x", "clave2": "x"}})
    assert r.status_code < 500, f"{metodo} {ruta} -> {r.status_code}"


def test_rojo_qr8_leer_sesion_y_leer_paso_no_deberian_levantar_con_texto_no_ascii():
    """QR-8, la misma causa vista sin HTTP: ninguna de las dos funciones puede
    levantar una excepcion con un token mal formado; tienen que devolver None."""
    assert auth.leer_paso("\u00e9.\u00e9", "recuperacion") is None
    assert auth.leer_sesion("\u00e9.\u00e9") is None

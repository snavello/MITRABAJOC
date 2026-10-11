"""Registro confirmado por mail: el modelo de datos y sus helpers (PLAN_REGISTRO.md §3).

Es la capa de abajo de la serie H-0017: nivel de fiabilidad de cada cuenta,
mail declarado aparte del del padrón, política por sindicato y los códigos de
verificación. Las rutas del registro (main.py) se prueban en otro archivo;
acá solo lo que decide `db.py`.

Lo que se cuida:

1. El nivel SUBE y no baja (`subir_nivel` es la única escritura): un recibo
   propio (3) posterior a la confirmación del sindicato (4) no la rebaja.
2. El mail del padrón se lee sin mezclarse con el declarado, y la política
   "acepta mail declarado" la manda el sindicato MÁS estricto de la persona.
3. Un código se guarda hasheado, vive 15 minutos, admite 5 intentos, un solo
   código vivo por persona y propósito, y el cupo cuenta la última hora.
4. Los códigos de error nuevos existen y no dicen "probá con otra foto".

Correr con: .venv/Scripts/python.exe -m pytest test_registro_modelo.py -q
"""
import hashlib
import hmac
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

import auth
import db
import errores
import fechas
from db import (CodigoVerificacion, CuentaEmpleador, CuentaTrabajador, Empleador,
                Sindicato, Trabajador)

db.crear_tablas()

FORMATO = "%Y-%m-%d %H:%M"


def _sindicato(s, nombre, acepta=True, activo=True):
    sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"),
                     color_base="#101b2c", acepta_mail_declarado=acepta, activo=activo)
    s.add(sind)
    s.commit()
    s.refresh(sind)
    return sind


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
def test_constantes_del_plan():
    assert db.CODIGO_VIGENCIA_MINUTOS == 15
    assert db.CODIGO_MAX_INTENTOS == 5
    assert db.CODIGOS_POR_HORA == 3
    assert db.NIVELES_FIABILIDAD == {1: "CUIL en el padrón", 2: "mail confirmado",
                                     3: "recibo propio verificado",
                                     4: "confirmado por el sindicato"}
    assert db.ORIGENES_NIVEL == {"cuil_padron": 1, "mail_padron": 2, "mail_declarado": 2,
                                 "recibo_propio": 3, "presencial": 4}
    # todo origen apunta a un nivel que tiene nombre
    assert set(db.ORIGENES_NIVEL.values()) <= set(db.NIVELES_FIABILIDAD)


def test_columnas_nuevas_nacen_en_nivel_1():
    with db.get_session() as s:
        for cuenta in (CuentaTrabajador(cuil="20100000001"), CuentaEmpleador(cuit="30100000001")):
            s.add(cuenta)
            s.commit()
            s.refresh(cuenta)
            assert cuenta.nivel_fiabilidad == 1
            assert cuenta.nivel_origen == "" and cuenta.nivel_actualizado == ""
            assert cuenta.mail_declarado == "" and cuenta.mail_declarado_confirmado == ""
            assert cuenta.clave_temporal is False
        assert _sindicato(s, "Politica Default").acepta_mail_declarado is True
        # el mail del sindicato (Q-6) nace vacío, en el afiliado y en la empresa
        s.add(CuentaTrabajador(cuil="20100000002"))
        s.add(Empleador(sindicato_id=_sindicato(s, "Mail Padron Default").id, cuit="30100000002"))
        s.commit()
        assert s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == "20100000002")).first().mail_padron == ""
        assert s.exec(select(Empleador).where(Empleador.cuit == "30100000002")).first().mail_padron == ""


# ---------------------------------------------------------------------------
# subir_nivel
# ---------------------------------------------------------------------------
def test_subir_nivel_sube_y_no_baja():
    with db.get_session() as s:
        c = CuentaTrabajador(cuil="20200000001")
        s.add(c)
        s.commit()
        assert db.subir_nivel(s, c, "mail_declarado") is True
        assert (c.nivel_fiabilidad, c.nivel_origen) == (2, "mail_declarado")
        assert c.nivel_actualizado == fechas.ahora_texto()
        assert db.subir_nivel(s, c, "presencial") is True
        assert (c.nivel_fiabilidad, c.nivel_origen) == (4, "presencial")
        # un recibo propio posterior NO baja de 4 a 3, y no toca nada
        antes = c.nivel_actualizado
        c.nivel_actualizado = "2026-01-01 00:00"
        assert db.subir_nivel(s, c, "recibo_propio") is False
        assert (c.nivel_fiabilidad, c.nivel_origen) == (4, "presencial")
        assert c.nivel_actualizado == "2026-01-01 00:00" != antes
        # el mismo nivel tampoco cuenta como subida
        assert db.subir_nivel(s, c, "presencial") is False
        s.commit()
        s.refresh(c)
        assert c.nivel_fiabilidad == 4


def test_subir_nivel_no_hace_commit_y_sirve_para_empresas():
    with db.get_session() as s:
        c = CuentaEmpleador(cuit="30200000001")
        s.add(c)
        s.commit()
        assert db.subir_nivel(s, c, "mail_padron") is True
        s.rollback()      # no hubo commit: el cambio se pierde
        s.refresh(c)
        assert c.nivel_fiabilidad == 1
        assert db.subir_nivel(s, c, "mail_padron") is True
        s.commit()
        s.refresh(c)
        assert (c.nivel_fiabilidad, c.nivel_origen) == (2, "mail_padron")


def test_subir_nivel_origen_invalido_falla():
    with db.get_session() as s:
        c = CuentaTrabajador(cuil="20200000002")
        s.add(c)
        s.commit()
        with pytest.raises(ValueError):
            db.subir_nivel(s, c, "porque_si")
        assert c.nivel_fiabilidad == 1


# ---------------------------------------------------------------------------
# Mail del padrón
# ---------------------------------------------------------------------------
def test_mail_padron_de():
    with db.get_session() as s:
        s.add(CuentaTrabajador(cuil="20300000001", mail_padron="  ana@ejemplo.com "))
        s.add(CuentaTrabajador(cuil="20300000002", mail_padron=""))
        s.add(CuentaTrabajador(cuil="20300000003", mail_padron="", mail_declarado="otro@ejemplo.com"))
        # el mail de CONTACTO tampoco es el del padrón (Q-6)
        s.add(CuentaTrabajador(cuil="20300000004", mail="contacto@ejemplo.com"))
        s.commit()
        assert db.mail_padron_de(s, "20300000001") == "ana@ejemplo.com"
        assert db.mail_padron_de(s, "20300000002") == ""
        # el mail declarado NO cuenta como mail del padrón
        assert db.mail_padron_de(s, "20300000003") == ""
        assert db.mail_padron_de(s, "20300000004") == ""
        assert db.mail_padron_de(s, "20399999999") == ""


def test_mail_padron_de_empresa_toma_el_primero_no_vacio_activas_primero():
    with db.get_session() as s:
        a = _sindicato(s, "Mail Empresa A")
        b = _sindicato(s, "Mail Empresa B")
        c = _sindicato(s, "Mail Empresa C")
        cuit = "30300000001"
        s.add(Empleador(sindicato_id=a.id, cuit=cuit, mail_padron="", activo=True))
        s.add(Empleador(sindicato_id=b.id, cuit=cuit, mail_padron="baja@empresa.com", activo=False))
        s.add(Empleador(sindicato_id=c.id, cuit=cuit, mail_padron=" activa@empresa.com ", activo=True))
        s.add(Empleador(sindicato_id=a.id, cuit="30300000002", mail_padron="   ", mail="contacto@empresa.com"))
        s.commit()
        assert db.mail_padron_de_empresa(s, cuit) == "activa@empresa.com"
        assert db.mail_padron_de_empresa(s, "30300000002") == ""
        assert db.mail_padron_de_empresa(s, "30399999999") == ""
        # si solo queda una dada de baja, igual se usa (es el único mail que hay)
        s.add(Empleador(sindicato_id=a.id, cuit="30300000003", mail_padron="vieja@empresa.com", activo=False))
        s.commit()
        assert db.mail_padron_de_empresa(s, "30300000003") == "vieja@empresa.com"


# ---------------------------------------------------------------------------
# Política por sindicato
# ---------------------------------------------------------------------------
def test_acepta_mail_declarado_manda_el_mas_estricto():
    with db.get_session() as s:
        flojo = _sindicato(s, "Politica Floja", acepta=True)
        estricto = _sindicato(s, "Politica Estricta", acepta=False)
        inactivo = _sindicato(s, "Politica Inactiva", acepta=False, activo=False)
        s.add(Trabajador(sindicato_id=flojo.id, cuil="20400000001"))
        s.add(Trabajador(sindicato_id=flojo.id, cuil="20400000002"))
        s.add(Trabajador(sindicato_id=estricto.id, cuil="20400000002"))
        s.add(Trabajador(sindicato_id=flojo.id, cuil="20400000003"))
        s.add(Trabajador(sindicato_id=inactivo.id, cuil="20400000003"))
        s.add(Trabajador(sindicato_id=inactivo.id, cuil="20400000004"))
        s.commit()
        assert db.acepta_mail_declarado(s, "20400000001") is True
        # dos sindicatos y uno estricto -> manda el estricto
        assert db.acepta_mail_declarado(s, "20400000002") is False
        # un sindicato inactivo no cuenta
        assert db.acepta_mail_declarado(s, "20400000003") is True
        # solo en un sindicato inactivo, o sin empadronamientos: False
        assert db.acepta_mail_declarado(s, "20400000004") is False
        assert db.acepta_mail_declarado(s, "20499999999") is False


def test_acepta_mail_declarado_empresa():
    with db.get_session() as s:
        flojo = _sindicato(s, "Politica Emp Floja", acepta=True)
        estricto = _sindicato(s, "Politica Emp Estricta", acepta=False)
        s.add(Empleador(sindicato_id=flojo.id, cuit="30400000001"))
        s.add(Empleador(sindicato_id=flojo.id, cuit="30400000002"))
        s.add(Empleador(sindicato_id=estricto.id, cuit="30400000002"))
        # el alta del sindicato estricto está dada de baja: ya no cuenta
        s.add(Empleador(sindicato_id=flojo.id, cuit="30400000003"))
        s.add(Empleador(sindicato_id=estricto.id, cuit="30400000003", activo=False))
        s.commit()
        assert db.acepta_mail_declarado_empresa(s, "30400000001") is True
        assert db.acepta_mail_declarado_empresa(s, "30400000002") is False
        assert db.acepta_mail_declarado_empresa(s, "30400000003") is True
        assert db.acepta_mail_declarado_empresa(s, "30499999999") is False


# ---------------------------------------------------------------------------
# Códigos de verificación
# ---------------------------------------------------------------------------
def _crear(s, ident="20500000001", proposito="registro", tipo="trabajador"):
    fila, codigo = db.crear_codigo(s, tipo, ident, proposito, "ana@ejemplo.com", "padron", "1.2.3.4")
    s.commit()
    return fila, codigo


def test_crear_codigo():
    with db.get_session() as s:
        fila, codigo = _crear(s)
        assert len(codigo) == 6 and codigo.isdigit()
        assert fila.id is not None
        # HMAC-SHA256 con el secreto del servidor (Q-4), no un sha256 a secas
        assert fila.codigo_hash == hmac.new(
            auth.SECRETO.encode(), f"{codigo}:{fila.identificador}:{fila.creado}".encode(),
            hashlib.sha256).hexdigest()
        assert fila.codigo_hash != hashlib.sha256(
            f"{codigo}:{fila.identificador}:{fila.creado}".encode()).hexdigest()
        assert codigo not in fila.codigo_hash      # nunca se guarda en claro
        assert (fila.tipo, fila.proposito, fila.destino, fila.origen_destino, fila.ip) == \
            ("trabajador", "registro", "ana@ejemplo.com", "padron", "1.2.3.4")
        assert fila.intentos == 0 and fila.usado_en == ""
        creado = datetime.strptime(fila.creado, FORMATO)
        vence = datetime.strptime(fila.vence, FORMATO)
        assert vence - creado == timedelta(minutes=15)
        assert fila.creado == fechas.ahora_texto() or \
            datetime.strptime(fechas.ahora_texto(), FORMATO) - creado <= timedelta(minutes=1)


def test_el_codigo_conserva_los_ceros_a_la_izquierda(monkeypatch):
    monkeypatch.setattr(db.secrets, "randbelow", lambda n: 42)
    with db.get_session() as s:
        _, codigo = _crear(s, ident="20500000009")
        assert codigo == "000042"


def test_un_codigo_nuevo_vence_el_pendiente_anterior():
    with db.get_session() as s:
        ident = "20500000002"
        primero, c1 = _crear(s, ident)
        otro_proposito, c_otro = _crear(s, ident, proposito="recuperacion")
        otra_persona, c_ajeno = _crear(s, "20500000003")
        segundo, c2 = _crear(s, ident)
        for f in (primero, otro_proposito, otra_persona, segundo):
            s.refresh(f)
        # el primero quedó vencido (y NO se borró: es la traza)
        assert primero.vence <= fechas.ahora_texto()
        assert db.verificar_codigo(s, primero.id, c1) == "vencido"
        # los de otro propósito y otra persona siguen vivos
        assert otro_proposito.vence > fechas.ahora_texto()
        assert otra_persona.vence > fechas.ahora_texto()
        assert db.verificar_codigo(s, segundo.id, c2) == "ok"
        assert len(s.exec(select(CodigoVerificacion).where(
            CodigoVerificacion.identificador == ident)).all()) == 3


def test_verificar_codigo_los_seis_estados():
    with db.get_session() as s:
        # inexistente
        assert db.verificar_codigo(s, 99999999, "123456") == "inexistente"

        # ok, y después usado
        fila, codigo = _crear(s, "20600000001")
        malo = "000000" if codigo != "000000" else "111111"
        assert db.verificar_codigo(s, fila.id, malo) == "incorrecto"
        assert fila.intentos == 1
        assert db.verificar_codigo(s, fila.id, codigo) == "ok"
        assert fila.usado_en == fechas.ahora_texto()
        assert db.verificar_codigo(s, fila.id, codigo) == "usado"

        # vencido
        fila, codigo = _crear(s, "20600000002")
        fila.vence = "2000-01-01 00:00"
        s.add(fila)
        s.commit()
        assert db.verificar_codigo(s, fila.id, codigo) == "vencido"
        assert fila.intentos == 0      # un vencido no gasta intentos

        # agotado: el 5.º intento incorrecto sigue siendo "incorrecto"; el siguiente
        # ya es "agotado", aunque sea el código bueno
        fila, codigo = _crear(s, "20600000003")
        malo = "000000" if codigo != "000000" else "111111"
        for _ in range(db.CODIGO_MAX_INTENTOS):
            assert db.verificar_codigo(s, fila.id, malo) == "incorrecto"
        assert fila.intentos == 5
        assert db.verificar_codigo(s, fila.id, codigo) == "agotado"
        assert db.verificar_codigo(s, fila.id, malo) == "agotado"
        assert fila.usado_en == "" and fila.intentos == 5


def test_verificar_codigo_incorrecto_persiste_con_commit():
    with db.get_session() as s:
        fila, codigo = _crear(s, "20600000004")
        malo = "000000" if codigo != "000000" else "111111"
        assert db.verificar_codigo(s, fila.id, malo) == "incorrecto"
        s.commit()
        fid = fila.id
    with db.get_session() as s:
        assert s.get(CodigoVerificacion, fid).intentos == 1
        # espacios alrededor no cuentan
        assert db.verificar_codigo(s, fid, f" {codigo} ") == "ok"


def test_el_hash_depende_de_la_persona():
    """El mismo código en claro no sirve contra la fila de otra persona."""
    with db.get_session() as s:
        a, ca = _crear(s, "20600000005")
        b, cb = _crear(s, "20600000006")
        if ca != cb:
            assert db.verificar_codigo(s, b.id, ca) == "incorrecto"
        assert db.verificar_codigo(s, b.id, cb) == "ok"
        assert a.codigo_hash != b.codigo_hash


def test_codigos_recientes_cuenta_solo_la_ultima_hora():
    with db.get_session() as s:
        ident = "20700000001"
        assert db.codigos_recientes(s, "trabajador", ident, "registro") == 0
        for _ in range(2):
            _crear(s, ident)
        viejo, _ = _crear(s, ident)
        viejo.creado = fechas.a_texto(fechas.ahora() - timedelta(minutes=90))
        s.add(viejo)
        # otro propósito, otro tipo y otra persona no suman
        _crear(s, ident, proposito="recuperacion")
        _crear(s, ident, tipo="empleador")
        _crear(s, "20700000002")
        s.commit()
        assert db.codigos_recientes(s, "trabajador", ident, "registro") == 2
        assert db.codigos_recientes(s, "trabajador", ident, "registro", horas=2) == 3
        assert db.codigos_recientes(s, "trabajador", ident, "recuperacion") == 1
        assert db.codigos_recientes(s, "empleador", ident, "registro") == 1
        # un código usado igual cuenta para el cupo: se cuentan pedidos
        fila, codigo = _crear(s, "20700000003")
        assert db.verificar_codigo(s, fila.id, codigo) == "ok"
        s.commit()
        assert db.codigos_recientes(s, "trabajador", "20700000003", "registro") == 1


# ---------------------------------------------------------------------------
# Catálogo de errores y fechas
# ---------------------------------------------------------------------------
def test_errores_de_registro_en_el_catalogo():
    esperados = {"E-REGISTRO-01": 400, "E-REGISTRO-02": 400, "E-REGISTRO-03": 429,
                 "E-REGISTRO-04": 403, "E-REGISTRO-05": 429, "E-REGISTRO-06": 503}
    for codigo, status in esperados.items():
        assert errores.MENSAJES[codigo][0] == status
        mensaje = errores.MENSAJES[codigo][1]
        assert mensaje and "foto" not in mensaje.lower()
    assert errores.ErrorApp("E-REGISTRO-02").status_code == 400


def test_fechas_a_texto():
    momento = datetime(2026, 10, 11, 9, 5, 59)
    assert fechas.a_texto(momento) == "2026-10-11 09:05"
    assert fechas.a_texto(momento + timedelta(minutes=15)) == "2026-10-11 09:20"


# ---------------------------------------------------------------------------
# subir_nivel: nivel igual, sin origen (Q-5)
# ---------------------------------------------------------------------------
def test_subir_nivel_al_mismo_nivel_sin_origen_registra_el_origen():
    with db.get_session() as s:
        c = CuentaTrabajador(cuil="20210000001")
        s.add(c)
        s.commit()
        assert (c.nivel_fiabilidad, c.nivel_origen) == (1, "")
        assert db.subir_nivel(s, c, "cuil_padron") is True
        assert (c.nivel_fiabilidad, c.nivel_origen) == (1, "cuil_padron")
        assert c.nivel_actualizado == fechas.ahora_texto()
        # ya con origen: la segunda vez no toca nada
        c.nivel_actualizado = "2026-01-01 00:00"
        assert db.subir_nivel(s, c, "cuil_padron") is False
        assert c.nivel_actualizado == "2026-01-01 00:00"
        # y un origen de nivel MENOR al actual nunca se registra
        c.nivel_fiabilidad, c.nivel_origen = 2, ""
        assert db.subir_nivel(s, c, "cuil_padron") is False


# ---------------------------------------------------------------------------
# El mail del padrón (Q-6): quién lo escribe y quién no
# ---------------------------------------------------------------------------
import cuit as _cuit  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_ADMIN = _cuit.corregir("20211111110")
with db.get_session() as _s:
    _sind = Sindicato(nombre="Mail Padron Rutas", slug="mail-padron-rutas", color_base="#101b2c",
                      modulos_habilitados=["empleadores"])
    _s.add(_sind)
    _s.commit()
    _s.refresh(_sind)
    SID_RUTAS = _sind.id
    _s.add(db.UsuarioSindicato(sindicato_id=SID_RUTAS, usuario=_ADMIN, cuil=_ADMIN, nombre="Admin Mail",
                               clave_hash=auth.hashear_clave("admin-mail"),
                               debe_cambiar_clave=False, es_super_admin=True))
    _s.commit()

DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}


def _admin():
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": _ADMIN, "clave": "admin-mail"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/inicio", r.headers
    return c


def _cuenta(cuil):
    with db.get_session() as s:
        return s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()


def _sesion_afiliado(cuil, sid):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(sid))
    return c


def test_el_alta_individual_carga_mail_y_mail_padron_y_el_perfil_solo_el_contacto():
    cuil = _cuit.corregir("27300000010")
    c = _admin()
    r = c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Ana Padron",
                                          "mail": "ana@gremio.com", **DOM}, follow_redirects=False)
    assert r.status_code == 303, r.text
    cta = _cuenta(cuil)
    assert (cta.mail, cta.mail_padron) == ("ana@gremio.com", "ana@gremio.com")
    # Registrada: la persona cambia SU contacto desde el perfil y el del padrón queda
    with db.get_session() as s:
        db.asegurar_cuenta(s, cuil).clave_hash = auth.hashear_clave("clave-larga-123")
        s.exec(select(Trabajador).where(Trabajador.cuil == cuil, Trabajador.sindicato_id == SID_RUTAS)
               ).first().registrado = True
        s.commit()
    p = _sesion_afiliado(cuil, SID_RUTAS).post(
        "/api/perfil", data={"nombre": "Ana Padron", "mail": "otra@casa.com", **DOM})
    assert p.status_code == 200, p.text
    cta = _cuenta(cuil)
    assert (cta.mail, cta.mail_padron) == ("otra@casa.com", "ana@gremio.com")
    with db.get_session() as s:
        assert db.mail_padron_de(s, cuil) == "ana@gremio.com"


def test_la_edicion_del_admin_no_convierte_el_contacto_de_la_persona_en_mail_del_padron():
    cuil = _cuit.corregir("27300000020")
    c = _admin()
    c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Beto", "mail": "beto@gremio.com", **DOM})
    with db.get_session() as s:
        tid = s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).first().id
        db.guardar_datos_personales(s, cuil, mail="beto@casa.com")      # lo cambió él, desde su perfil
        s.commit()
    # el admin guarda el formulario que le llegó precargado con el contacto, sin tocar el mail
    c.post("/admin/trabajador", data={"id": str(tid), "cuil": cuil, "nombre": "Beto Editado",
                                      "mail": "beto@casa.com", **DOM})
    cta = _cuenta(cuil)
    assert (cta.nombre, cta.mail, cta.mail_padron) == ("Beto Editado", "beto@casa.com", "beto@gremio.com")
    # si el admin SÍ cambia el mail, ese es el del padrón
    c.post("/admin/trabajador", data={"id": str(tid), "cuil": cuil, "nombre": "Beto Editado",
                                      "mail": "nuevo@gremio.com", **DOM})
    cta = _cuenta(cuil)
    assert (cta.mail, cta.mail_padron) == ("nuevo@gremio.com", "nuevo@gremio.com")


def test_alta_masiva_de_un_cuil_existente_actualiza_solo_mail_padron():
    cuil = _cuit.corregir("27300000030")
    c = _admin()
    c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Carla", **DOM})
    with db.get_session() as s:                                          # ya se registró y puso su contacto
        db.guardar_datos_personales(s, cuil, mail="carla@casa.com", telefono="341-555")
        db.asegurar_cuenta(s, cuil).clave_hash = auth.hashear_clave("clave-larga-123")
        s.commit()
    assert _cuenta(cuil).mail_padron == ""
    sin_alta = _cuit.corregir("27300000040")
    lista = "\n".join([
        f"{cuil}, Carla, , , , Rosario, Santa Fe, 000, carla@gremio.com",    # existente, con mail
        f"{sin_alta}, Dani, , , , Rosario, Santa Fe, 111, dani@gremio.com",  # alta nueva
        f"{cuil}, Carla, , , , Rosario, Santa Fe",                           # existente, sin mail: omitida
    ])
    r = c.post("/admin/trabajador/masivo", data={"lista": lista}, follow_redirects=False)
    destino = r.headers["location"]
    assert "altas=1" in destino and "mailsactualizados=1" in destino and "omitidas=1" in destino, destino
    cta = _cuenta(cuil)
    assert cta.mail_padron == "carla@gremio.com"
    assert (cta.mail, cta.telefono) == ("carla@casa.com", "341-555")       # el contacto y el resto, intactos
    dani = _cuenta(sin_alta)
    assert (dani.mail, dani.mail_padron) == ("dani@gremio.com", "dani@gremio.com")


def test_un_alta_en_blanco_no_borra_el_mail_del_padron_que_cargo_otro_gremio():
    cuil = _cuit.corregir("27300000050")
    with db.get_session() as s:
        db.guardar_datos_personales(s, cuil, nombre="Eva", mail="eva@otro.com", mail_padron="eva@otro.com")
        s.commit()
    c = _admin()
    c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Eva", **DOM})            # alta individual, sin mail
    assert _cuenta(cuil).mail_padron == "eva@otro.com"
    otra = _cuit.corregir("27300000060")
    with db.get_session() as s:
        db.guardar_datos_personales(s, otra, nombre="Fer", mail_padron="fer@otro.com")
        s.commit()
    c.post("/admin/trabajador/masivo", data={"lista": f"{otra}, Fer, , , , Rosario, Santa Fe"})
    assert _cuenta(otra).mail_padron == "fer@otro.com"


def test_el_perfil_de_la_empresa_no_toca_mail_padron_y_el_alta_del_admin_si_lo_carga():
    cuit_emp = _cuit.corregir("30300000010")
    c = _admin()
    r = c.post("/admin/empleador", data={"cuit": cuit_emp, "razon_social": "Mail SA",
                                         "mail": "rrhh@gremio.com"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    with db.get_session() as s:
        e = s.exec(select(Empleador).where(Empleador.cuit == cuit_emp)).first()
        eid = e.id
        assert (e.mail, e.mail_padron) == ("rrhh@gremio.com", "rrhh@gremio.com")
        assert db.mail_padron_de_empresa(s, cuit_emp) == "rrhh@gremio.com"
        s.add(CuentaEmpleador(cuit=cuit_emp, clave_hash=auth.hashear_clave("clave-larga-123")))
        s.commit()
    emp = TestClient(main.app)
    emp.cookies.set(main.COOKIE_EMPLEADOR, auth.crear_sesion("empleador", sindicato_id=0, ident=cuit_emp))
    p = emp.post("/api/empresa/perfil", data={"razon_social": "Mail SA", "mail": "otra@empresa.com"})
    assert p.status_code == 200, p.text
    with db.get_session() as s:
        e = s.get(Empleador, eid)
        assert (e.mail, e.mail_padron) == ("otra@empresa.com", "rrhh@gremio.com")
        assert db.mail_padron_de_empresa(s, cuit_emp) == "rrhh@gremio.com"
    # el admin edita sin tocar el mail precargado (el de contacto): el del padrón no se mueve
    c.post("/admin/empleador", data={"id": str(eid), "cuit": cuit_emp, "razon_social": "Mail SA 2",
                                     "mail": "otra@empresa.com"})
    with db.get_session() as s:
        assert s.get(Empleador, eid).mail_padron == "rrhh@gremio.com"
    # y si lo cambia, sí
    c.post("/admin/empleador", data={"id": str(eid), "cuit": cuit_emp, "razon_social": "Mail SA 2",
                                     "mail": "nuevo@gremio.com"})
    with db.get_session() as s:
        assert s.get(Empleador, eid).mail_padron == "nuevo@gremio.com"

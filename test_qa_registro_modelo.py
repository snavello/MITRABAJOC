"""QA del modelo del registro confirmado (PLAN_REGISTRO.md §3) y de
`auth.firmar_paso/leer_paso`: casos de ATAQUE y de OPERACIÓN que
`test_registro_modelo.py` y `test_auth_paso.py` no cubren.

No es una suite de regresión del desarrollador: es la evidencia de la revisión
de QA. Los tests marcados ROJO afirman lo que el plan o la lógica de seguridad
piden y HOY FALLAN; cada uno cita el hallazgo del reporte (Q-n). Los demás
documentan que el comportamiento revisado es correcto y evitan que se rompa.

Correr con: python -m pytest test_qa_registro_modelo.py -q
(un archivo por proceso, como todo el proyecto).
"""
import ast
import base64
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import auth
import db
import errores
import fechas
import main
import regularizar_cuit
from db import (CodigoVerificacion, CuentaEmpleador, CuentaTrabajador, Empleador,
                Sindicato, Trabajador)

db.crear_tablas()

RAIZ = Path(__file__).parent


def _sindicato(s, nombre, acepta=True, activo=True):
    sind = Sindicato(nombre=nombre, slug=nombre.lower().replace(" ", "-"),
                     color_base="#101b2c", acepta_mail_declarado=acepta, activo=activo)
    s.add(sind)
    s.commit()
    s.refresh(sind)
    return sind


def _crear(s, ident, proposito="registro", tipo="trabajador"):
    fila, codigo = db.crear_codigo(s, tipo, ident, proposito, "ana@ejemplo.com", "padron", "1.2.3.4")
    s.commit()
    return fila, codigo


def _malo(codigo):
    return "000000" if codigo != "000000" else "111111"


# ===========================================================================
# 1. CÓDIGOS DE VERIFICACIÓN
# ===========================================================================
def test_el_codigo_sale_de_secrets_y_siempre_tiene_seis_digitos(monkeypatch):
    """Formato: 6 dígitos con ceros a la izquierda, también en los extremos del
    rango, y la fuente de azar es `secrets` (no `random`)."""
    fuente = inspect.getsource(db.crear_codigo)
    assert "secrets.randbelow" in fuente and "random." not in fuente.replace("secrets.randbelow", "")
    with db.get_session() as s:
        for n, esperado in ((0, "000000"), (7, "000007"), (999999, "999999")):
            monkeypatch.setattr(db.secrets, "randbelow", lambda tope, n=n: n)
            fila, codigo = db.crear_codigo(s, "trabajador", f"2090000{n:04d}"[:11], "registro",
                                           "a@b.com", "padron", "ip")
            assert codigo == esperado
            assert re.fullmatch(r"\d{6}", codigo)
        s.rollback()
    monkeypatch.undo()
    with db.get_session() as s:
        codigos = {db.crear_codigo(s, "trabajador", f"2091{i:07d}", "registro", "a@b.com", "padron", "ip")[1]
                   for i in range(300)}
        s.rollback()
    assert all(re.fullmatch(r"\d{6}", c) for c in codigos)
    assert len(codigos) > 250        # no es una constante ni un rango minúsculo


def test_verificar_usa_comparacion_en_tiempo_constante():
    assert "hmac.compare_digest" in inspect.getsource(db.verificar_codigo)


def test_agotado_rechaza_aun_el_codigo_correcto_y_no_sigue_sumando():
    with db.get_session() as s:
        fila, codigo = _crear(s, "20910000001")
        for _ in range(db.CODIGO_MAX_INTENTOS):
            assert db.verificar_codigo(s, fila.id, _malo(codigo)) == "incorrecto"
        for _ in range(3):
            assert db.verificar_codigo(s, fila.id, codigo) == "agotado"
        assert fila.intentos == db.CODIGO_MAX_INTENTOS and fila.usado_en == ""


def test_usado_y_vencido_no_suman_intentos_y_no_dejan_tantear():
    """Lo acordado: un código usado/vencido no gasta intentos. Verifica que eso
    NO abre un camino: para tantear hay que pedir un código nuevo, que vence el
    anterior, y solo un código vivo admite probar (5 intentos)."""
    with db.get_session() as s:
        fila, codigo = _crear(s, "20910000002")
        assert db.verificar_codigo(s, fila.id, codigo) == "ok"
        for _ in range(20):
            assert db.verificar_codigo(s, fila.id, _malo(codigo)) == "usado"
        assert fila.intentos == 0
        v, cv = _crear(s, "20910000003")
        v.vence = "2000-01-01 00:00"
        s.add(v)
        s.commit()
        for _ in range(20):
            assert db.verificar_codigo(s, v.id, _malo(cv)) == "vencido"
        assert v.intentos == 0
        # ni siquiera el correcto sirve una vez vencido
        assert db.verificar_codigo(s, v.id, cv) == "vencido"


@pytest.mark.parametrize("entrada,esperado", [
    ("", "incorrecto"), (None, "incorrecto"), ("12345", "incorrecto"), ("1234567", "incorrecto"),
    ("123 456", "incorrecto"), ("١٢٣٤٥٦", "incorrecto"),          # dígitos árabes
    ("１２３４５６", "incorrecto"),                                  # dígitos de ancho completo
    ("123456\n", "ok"), ("\t123456 ", "ok"), ("123456", "ok"),
])
def test_entradas_raras_no_rompen_ni_se_cuelan(monkeypatch, entrada, esperado):
    monkeypatch.setattr(db.secrets, "randbelow", lambda tope: 123456)
    with db.get_session() as s:
        fila, _ = db.crear_codigo(s, "trabajador", "20910000010", "registro", "a@b.com", "padron", "ip")
        assert db.verificar_codigo(s, fila.id, entrada) == esperado
        s.rollback()


def test_pedir_otro_codigo_vence_de_verdad_al_anterior_aun_en_el_mismo_minuto():
    with db.get_session() as s:
        viejo, cviejo = _crear(s, "20910000020")
        nuevo, cnuevo = _crear(s, "20910000020")
        assert viejo.id != nuevo.id
        s.refresh(viejo)
        assert db.verificar_codigo(s, viejo.id, cviejo) == "vencido"
        assert db.verificar_codigo(s, nuevo.id, cnuevo) == "ok"
        # un código de OTRO propósito de la misma persona no se toca
        reg, creg = _crear(s, "20910000021", "registro")
        rec, crec = _crear(s, "20910000021", "recuperacion")
        s.refresh(reg)
        assert db.verificar_codigo(s, reg.id, creg) == "ok"


def test_el_codigo_vive_entre_14_y_15_minutos_nunca_0_ni_16(monkeypatch):
    """`vence` se guarda a minuto: un código creado a las 10:00:59 vence "10:15"
    y muere a las 10:14:59.99; uno de las 10:00:00, a las 10:14:59.99 también."""
    with db.get_session() as s:
        vidas = []
        for seg in (0, 1, 30, 59):
            t = datetime(2026, 10, 12, 10, 0, seg)
            monkeypatch.setattr(fechas, "ahora", lambda t=t: t)
            fila, _ = db.crear_codigo(s, "trabajador", f"20911{seg:06d}", "registro", "a@b.com", "padron", "ip")
            vence = datetime.strptime(fila.vence, "%Y-%m-%d %H:%M")
            vidas.append((vence - t).total_seconds())
        s.rollback()
    assert all(14 * 60 < v <= 15 * 60 for v in vidas), vidas


def test_codigos_recientes_en_el_borde_de_la_hora_y_del_cambio_de_dia_y_de_ano(monkeypatch):
    ahora = datetime(2027, 1, 1, 0, 10, 30)
    monkeypatch.setattr(fechas, "ahora", lambda: ahora)
    ident = "20912000001"
    with db.get_session() as s:
        for creado in ("2026-12-31 23:09", "2026-12-31 23:10", "2026-12-31 23:11", "2027-01-01 00:10"):
            s.add(CodigoVerificacion(tipo="trabajador", identificador=ident, proposito="registro",
                                     creado=creado, vence=creado))
        s.commit()
        # la ventana se trunca al minuto: cuenta lo creado desde las 23:10 (hasta 60 min 59 s,
        # lado conservador), no lo de las 23:09. Texto "AAAA-MM-DD HH:MM" ordena bien entre años.
        assert db.codigos_recientes(s, "trabajador", ident, "registro") == 3
        assert db.codigos_recientes(s, "trabajador", ident, "registro", horas=2) == 4


def test_crear_codigo_se_niega_a_pasar_del_cupo_por_hora():
    """ROJO (evidencia). Defensa en profundidad: hoy cualquier ruta que se olvide
    de consultar `codigos_recientes` permite bombardear un mail y ganar 5 intentos
    por cada código nuevo."""
    ident = "20913000001"
    with db.get_session() as s:
        for _ in range(db.CODIGOS_POR_HORA):
            _crear(s, ident)
        with pytest.raises(Exception):
            _crear(s, ident)


def test_el_intento_fallido_no_se_pierde_si_la_ruta_levanta_sin_commit():
    """ROJO. El idioma de todo main.py es `with db.get_session() as s:` + `raise
    ErrorApp(...)`: al salir del with la sesión hace rollback. Con eso el
    contador de intentos nunca llega a 5 y el código se puede tantear a
    voluntad durante los 15 minutos. El contrato 'el llamador confirma' es una
    trampa para un control de seguridad."""
    with db.get_session() as s:
        fila, codigo = _crear(s, "20914000001")
        fid = fila.id
    try:
        with db.get_session() as s:
            assert db.verificar_codigo(s, fid, _malo(codigo)) == "incorrecto"
            raise RuntimeError("la ruta responde E-REGISTRO-02 y sale")   # lo que hace un ErrorApp
    except RuntimeError:
        pass
    with db.get_session() as s:
        assert s.get(CodigoVerificacion, fid).intentos == 1


def _correr_en_paralelo(fn_a, fn_b):
    """Dos hilos que se encuentran en `fechas.ahora_texto` (que verificar_codigo
    llama DESPUÉS de leer la fila y ANTES de escribirla): ambos leyeron el mismo
    estado cuando siguen."""
    barrera = threading.Barrier(2, timeout=3)
    original = fechas.ahora_texto

    def sincronizada():
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass            # con bloqueo de fila el segundo no llega: está esperando al primero
        return original()

    resultados = {}

    def correr(nombre, fn):
        resultados[nombre] = fn()

    fechas.ahora_texto = sincronizada
    try:
        hilos = [threading.Thread(target=correr, args=("a", fn_a)), threading.Thread(target=correr, args=("b", fn_b))]
        [h.start() for h in hilos]
        [h.join(20) for h in hilos]
    finally:
        fechas.ahora_texto = original
    return resultados


def test_dos_intentos_en_paralelo_cuentan_dos():
    """ROJO. Dos requests simultáneos con un código errado leen intentos=0 y
    escriben 1: el tope de 5 intentos se burla con ráfagas en paralelo."""
    with db.get_session() as s:
        fila, codigo = _crear(s, "20915000001")
        fid = fila.id

    def intento():
        with db.get_session() as s:
            r = db.verificar_codigo(s, fid, _malo(codigo))
            s.commit()
            return r

    _correr_en_paralelo(intento, intento)
    with db.get_session() as s:
        assert s.get(CodigoVerificacion, fid).intentos == 2


def test_un_codigo_correcto_solo_se_consume_una_vez_en_paralelo():
    """ROJO. Dos requests con el código bueno a la vez: ambos reciben 'ok'. Un
    código de un solo uso podría crear dos cuentas / dos sesiones."""
    with db.get_session() as s:
        fila, codigo = _crear(s, "20915000002")
        fid = fila.id

    def intento():
        with db.get_session() as s:
            r = db.verificar_codigo(s, fid, codigo)
            s.commit()
            return r

    res = _correr_en_paralelo(intento, intento)
    assert sorted(res.values()).count("ok") == 1, res


def test_el_hash_del_codigo_no_se_recupera_por_fuerza_bruta_sin_el_secreto():
    """ROJO. El hash es sha256(codigo:identificador:creado) y los tres datos
    menos el código están en la MISMA fila: un millón de candidatos y listo. El
    docstring lo admite ('solo protege de quien lea la base sin poder probar'),
    pero con un HMAC con SESSION_SECRET el hash no sirve de nada fuera del
    servidor y no cuesta nada."""
    with db.get_session() as s:
        fila, codigo = _crear(s, "20916000001")
        hash_, ident, creado = fila.codigo_hash, fila.identificador, fila.creado
    recuperado = None
    for n in range(10 ** 6):
        c = f"{n:06d}"
        if hashlib.sha256(f"{c}:{ident}:{creado}".encode()).hexdigest() == hash_:
            recuperado = c
            break
    assert recuperado is None


# ===========================================================================
# 2. NIVELES
# ===========================================================================
def test_los_origenes_y_los_niveles_cierran_entre_si():
    assert set(db.ORIGENES_NIVEL.values()) == set(db.NIVELES_FIABILIDAD)     # no hay nivel inalcanzable
    assert sorted(db.NIVELES_FIABILIDAD) == [1, 2, 3, 4]
    assert all(isinstance(v, str) and v for v in db.NIVELES_FIABILIDAD.values())


def test_subir_nivel_nunca_baja_aun_con_nivel_nulo_o_cero_en_una_fila_vieja():
    with db.get_session() as s:
        for valor in (None, 0):
            c = CuentaTrabajador(cuil=f"2092000000{0 if valor is None else 1}")
            s.add(c)
            s.commit()
            c.nivel_fiabilidad = valor
            assert db.subir_nivel(s, c, "mail_padron") is True
            assert c.nivel_fiabilidad == 2
        for origen in db.ORIGENES_NIVEL:
            c.nivel_fiabilidad = 4
            c.nivel_origen = "presencial"
            assert db.subir_nivel(s, c, origen) is False
            assert (c.nivel_fiabilidad, c.nivel_origen) == (4, "presencial")
        for malo in ("", None, "PRESENCIAL", "nivel_4", "mail_padron "):
            with pytest.raises((ValueError, TypeError)):
                db.subir_nivel(s, c, malo)
        s.rollback()


def test_el_origen_cuil_padron_queda_registrado_en_una_cuenta_nueva():
    """ROJO. PLAN_REGISTRO §3: 'canal de mail apagado (D9) → nivel 1, origen
    cuil_padron'. Una cuenta nueva ya está en 1, así que subir_nivel devuelve
    False y deja `nivel_origen` vacío; la ruta tendría que escribirlo a mano,
    contradiciendo 'única escritura'."""
    with db.get_session() as s:
        c = CuentaTrabajador(cuil="20921000001")
        s.add(c)
        s.commit()
        db.subir_nivel(s, c, "cuil_padron")
        assert c.nivel_origen == "cuil_padron" and c.nivel_actualizado


def test_nadie_escribe_nivel_fiabilidad_fuera_de_subir_nivel():
    """Recorre con `ast` todo el código de la app (no migraciones ni tests ni
    scripts de carga): la única asignación a `.nivel_fiabilidad` es la de
    `db.subir_nivel`, y no hay SQL que lo actualice."""
    permitidos_scripts = {"cargar_demo.py", "cargar_lote_sindicato.py", "cargar_lote_uom.py",
                          "cargar_bancaria.py"}
    culpables = []
    for ruta in RAIZ.glob("*.py"):
        if ruta.name.startswith("test_") or ruta.name == "conftest.py":
            continue
        fuente = ruta.read_text(encoding="utf-8")
        if "nivel_fiabilidad" not in fuente:
            continue
        arbol = ast.parse(fuente)
        for padre in ast.walk(arbol):
            for hijo in ast.iter_child_nodes(padre):
                pass
        # asignaciones a un atributo `.nivel_fiabilidad`
        funcion_de = {}
        for fn in ast.walk(arbol):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for n in ast.walk(fn):
                    funcion_de.setdefault(id(n), fn.name)
        for nodo in ast.walk(arbol):
            objetivos = []
            if isinstance(nodo, ast.Assign):
                objetivos = nodo.targets
            elif isinstance(nodo, (ast.AugAssign, ast.AnnAssign)):
                objetivos = [nodo.target]
            for o in objetivos:
                if isinstance(o, ast.Attribute) and o.attr == "nivel_fiabilidad":
                    if not (ruta.name == "db.py" and funcion_de.get(id(nodo)) == "subir_nivel") \
                            and ruta.name not in permitidos_scripts:
                        culpables.append(f"{ruta.name}:{nodo.lineno}")
        for m in re.finditer(r"(?is)update\s+\w+\s+set[^;\"']*nivel_fiabilidad", fuente):
            culpables.append(f"{ruta.name}: SQL UPDATE de nivel_fiabilidad")
        # kwargs en un constructor: CuentaX(nivel_fiabilidad=3) también es escribir el nivel
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call):
                for kw in nodo.keywords:
                    if kw.arg in ("nivel_fiabilidad",) and ruta.name not in permitidos_scripts:
                        culpables.append(f"{ruta.name}:{nodo.lineno} (kwarg)")
    assert not culpables, culpables


# ===========================================================================
# 3. POLÍTICA POR SINDICATO
# ===========================================================================
def _ids_de_politica_trabajador(cuil):
    return {x["id"] for x in db.sindicatos_de_cuil(cuil)}


def test_acepta_mail_declarado_es_coherente_con_sindicatos_de_cuil():
    """Para toda combinación, `acepta_mail_declarado` mira exactamente los
    sindicatos que `sindicatos_de_cuil` devuelve (activos, con empadronamiento),
    incluida la fila `Trabajador.activo=False` (que ninguna de las dos filtra)."""
    with db.get_session() as s:
        flojo = _sindicato(s, "QA Flojo", acepta=True)
        estricto = _sindicato(s, "QA Estricto", acepta=False)
        estricto_off = _sindicato(s, "QA Estricto Inactivo", acepta=False, activo=False)
        flojo_off = _sindicato(s, "QA Flojo Inactivo", acepta=True, activo=False)
        casos = {
            "20930000001": [],
            "20930000002": [flojo],
            "20930000003": [estricto],
            "20930000004": [flojo, estricto],
            "20930000005": [flojo, estricto_off],
            "20930000006": [estricto_off],
            "20930000007": [flojo_off],
            "20930000008": [flojo, flojo_off, estricto_off],
        }
        for cuil, sinds in casos.items():
            for sd in sinds:
                s.add(Trabajador(sindicato_id=sd.id, cuil=cuil))
        # un afiliado dado de baja (activo=False) en un gremio estricto
        s.add(Trabajador(sindicato_id=flojo.id, cuil="20930000009"))
        s.add(Trabajador(sindicato_id=estricto.id, cuil="20930000009", activo=False))
        casos["20930000009"] = [flojo, estricto]
        s.commit()
        for cuil in casos:
            ids = _ids_de_politica_trabajador(cuil)
            flags = [x.acepta_mail_declarado for x in
                     s.exec(select(Sindicato).where(Sindicato.id.in_(ids))).all()] if ids else []
            esperado = bool(ids) and all(flags)
            assert db.acepta_mail_declarado(s, cuil) is esperado, cuil
        # el baja lógica de un gremio estricto SIGUE endureciendo la política (conservador)
        assert db.acepta_mail_declarado(s, "20930000009") is False


def test_acepta_mail_declarado_empresa_es_coherente_con_sindicatos_de_cuit_empleador():
    with db.get_session() as s:
        flojo = _sindicato(s, "QA Emp Flojo", acepta=True)
        estricto = _sindicato(s, "QA Emp Estricto", acepta=False)
        estricto_off = _sindicato(s, "QA Emp Estricto Inactivo", acepta=False, activo=False)
        s.add(Empleador(sindicato_id=flojo.id, cuit="30930000001"))
        s.add(Empleador(sindicato_id=flojo.id, cuit="30930000002"))
        s.add(Empleador(sindicato_id=estricto.id, cuit="30930000002"))
        s.add(Empleador(sindicato_id=estricto.id, cuit="30930000003", activo=False))
        s.add(Empleador(sindicato_id=flojo.id, cuit="30930000003"))
        s.add(Empleador(sindicato_id=estricto_off.id, cuit="30930000004"))
        s.add(Empleador(sindicato_id=flojo.id, cuit="30930000005"))
        s.add(Empleador(sindicato_id=estricto_off.id, cuit="30930000005"))
        s.commit()
        for cuit in ("30930000001", "30930000002", "30930000003", "30930000004", "30930000005", "30939999999"):
            ids = {x["id"] for x in db.sindicatos_de_cuit_empleador(cuit)}
            flags = [x.acepta_mail_declarado for x in
                     s.exec(select(Sindicato).where(Sindicato.id.in_(ids))).all()] if ids else []
            assert db.acepta_mail_declarado_empresa(s, cuit) is (bool(ids) and all(flags)), cuit


def test_la_persona_no_puede_cambiar_el_mail_del_padron_desde_su_perfil():
    """ROJO. D1/§3: `mail` es del padrón y 'nunca se pisa'. Pero /api/perfil
    (y el registro de hoy) llaman a guardar_datos_personales(mail=…) sobre la
    MISMA columna que `mail_padron_de` toma como confiable. Un impostor que
    llegó primero (o cualquier cuenta de hoy, nivel 1) pone su mail en el
    perfil y la recuperación de clave por 'mail del padrón' (D6) y el código
    de registro de los otros gremios pasan a ir a él."""
    with db.get_session() as s:
        sind = _sindicato(s, "QA Perfil")
        cuil = "20940000001"
        c = CuentaTrabajador(cuil=cuil, nombre="Ana Real", mail="real@sindicato.com",
                             clave_hash=auth.hashear_clave("clave-larga-123"))
        s.add(c)
        s.add(Trabajador(sindicato_id=sind.id, cuil=cuil, registrado=True))
        s.commit()
        sid = sind.id
    cli = TestClient(main.app)
    cli.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    cli.cookies.set("cuil_trab", cuil)
    cli.cookies.set("sind_elegido", str(sid))
    r = cli.post("/api/perfil", data={"nombre": "Ana Real", "provincia": "Santa Fe",
                                      "localidad": "Rosario", "mail": "impostor@malo.com"})
    assert r.status_code == 200, r.text
    with db.get_session() as s:
        assert db.mail_padron_de(s, cuil) == "real@sindicato.com"


# ===========================================================================
# 4. MIGRACIÓN f2d3d0bcf179
# ===========================================================================
MIGRACION = next((RAIZ / "migrations" / "versions").glob("f2d3d0bcf179_*.py"))
REV_ANTERIOR = "e28e33b0aec5"
COLUMNAS_NUEVAS = {
    "cuentatrabajador": ["nivel_fiabilidad", "nivel_origen", "nivel_actualizado", "mail_declarado",
                         "mail_declarado_confirmado", "clave_temporal"],
    "cuentaempleador": ["nivel_fiabilidad", "nivel_origen", "nivel_actualizado", "mail_declarado",
                        "mail_declarado_confirmado", "clave_temporal"],
    "sindicato": ["acepta_mail_declarado"],
}


def _url_con_base(url, base):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/" + base, p.query, p.fragment))


def _psy(url):
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _alembic(url, *args):
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=RAIZ,
                          env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, timeout=300)


def _instantanea(url):
    """Esquema completo comparable: columnas (con tipo, nulos y default),
    índices y constraints."""
    with psycopg.connect(_psy(url)) as c:
        cols = c.execute("SELECT table_name, column_name, data_type, is_nullable, column_default "
                         "FROM information_schema.columns WHERE table_schema='public' "
                         "AND table_name <> 'alembic_version' ORDER BY 1,2").fetchall()
        idx = c.execute("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2").fetchall()
        cons = c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                         "WHERE connamespace='public'::regnamespace ORDER BY 1,2").fetchall()
        return {"columnas": [tuple(map(str, f)) for f in cols], "indices": idx, "constraints": cons}


@pytest.fixture(scope="module")
def base_migracion():
    base = str(db.engine.url.render_as_string(hide_password=False))
    nombre = f"mitrabajo_qa_mig_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    admin = _psy(_url_con_base(base, "postgres"))
    url = _url_con_base(base, nombre)
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{nombre}"')
    try:
        r = _alembic(url, "upgrade", REV_ANTERIOR)
        assert r.returncode == 0, r.stderr[-1500:]
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


def test_migracion_backfill_downgrade_exacto_y_reupgrade(base_migracion):
    url = base_migracion
    previo = _instantanea(url)
    with psycopg.connect(_psy(url), autocommit=True) as c:
        try:
            c.execute("SET session_replication_role = replica")     # sin armar sindicatos para las FK
        except Exception:
            pytest.skip("hace falta superusuario para insertar sin armar el árbol de FK")
        c.execute("""INSERT INTO cuentatrabajador (cuil, clave_hash, nombre) VALUES
            ('20111111112','h','con recibo propio'),
            ('20111111113','h','sin recibo'),
            ('20111111114','','padron sin clave'),
            ('20111111116','h','recibo guardado con guiones'),
            ('20111111117','','padron sin clave pero con recibo')""")
        c.execute("""INSERT INTO reciboverificado (sindicato_id,cuil,periodo,fecha,estado) VALUES
            (1,'20111111112','2026-01','x','OK'),
            (1,'20-11111111-6','2026-01','x','OK'),
            (1,'20111111117','2026-01','x','OK'),
            (1,'20999999999','2026-01','x','OK')""")
        c.execute("INSERT INTO cuentaempleador (cuit, clave_hash) VALUES ('30111222335','h'),('30111222336','')")
        c.execute("INSERT INTO sindicato (nombre, slug, color_base, activo) VALUES ('X','x','#101b2c', true)") \
            if False else None
    r = _alembic(url, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-1500:]
    with psycopg.connect(_psy(url)) as c:
        filas = {cuil: (n, o, a) for cuil, n, o, a in c.execute(
            "SELECT cuil, nivel_fiabilidad, nivel_origen, nivel_actualizado FROM cuentatrabajador")}
        emp = {cuit: (n, o) for cuit, n, o in c.execute(
            "SELECT cuit, nivel_fiabilidad, nivel_origen FROM cuentaempleador")}
        # server_default en TODAS las columnas nuevas
        sin_default = [(t, col) for t, cols in COLUMNAS_NUEVAS.items() for col in cols
                       if c.execute("SELECT column_default FROM information_schema.columns "
                                    "WHERE table_name=%s AND column_name=%s", (t, col)).fetchone()[0] is None]
        tablas = {t for (t,) in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert not sin_default, sin_default
    assert "codigoverificacion" in tablas
    # backfill D10
    assert filas["20111111112"][:2] == (3, "recibo_propio")
    assert filas["20111111113"][:2] == (1, "cuil_padron")
    # sin clave: sin origen, sin nivel que justificar, aunque tenga un recibo
    assert filas["20111111114"] == (1, "", "")
    assert filas["20111111117"] == (1, "", "")
    assert emp["30111222335"] == (1, "cuil_padron") and emp["30111222336"] == (1, "")
    # El caso 20111111116: su recibo quedó guardado como '20-11111111-6'
    # (ReciboVerificado.cuil sale de `cuil_sesion or resultado["cuil"]`, este último crudo).
    # La migración compara sin normalizar: la cuenta NO sube. Es conservador (queda en 1);
    # se documenta como Q-7 (Bajo).
    assert filas["20111111116"][:2] == (1, "cuil_padron")
    posterior = _instantanea(url)
    # downgrade: el esquema vuelve EXACTAMENTE al de antes (columnas, defaults, índices, constraints)
    r = _alembic(url, "downgrade", "-1")
    assert r.returncode == 0, r.stderr[-1500:]
    assert _instantanea(url) == previo
    # y volver a subir da el mismo esquema
    r = _alembic(url, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-1500:]
    assert _instantanea(url) == posterior


def test_la_migracion_no_importa_la_app_y_no_usa_json_pelado():
    arbol = ast.parse(MIGRACION.read_text(encoding="utf-8"))
    importados = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            importados |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            importados.add((n.module or "").split(".")[0])
    app = {"db", "fechas", "main", "auth", "geo", "validador", "errores", "cuit"}
    assert not (importados & app), importados & app
    assert "sa.JSON" not in MIGRACION.read_text(encoding="utf-8")
    # ningún modelo de la base declara una columna json (todas JSONB, ver JSON_TIPO)
    with psycopg.connect(_psy(str(db.engine.url.render_as_string(hide_password=False)))) as c:
        pelados = c.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema='public' AND data_type='json'").fetchall()
    assert not pelados, pelados


# ===========================================================================
# 5. auth.firmar_paso / leer_paso
# ===========================================================================
def _reemplazar_cuerpo(token, **cambios):
    """Edita el payload de un token de paso conservando la firma vieja."""
    cuerpo, firma = token.rsplit(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4)))
    payload.update(cambios)
    nuevo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{nuevo}.{firma}"


def test_no_se_puede_alargar_la_vida_ni_cambiar_el_proposito_ni_los_datos_editando_el_token():
    tok = auth.firmar_paso({"cuil": "20111111112"}, minutos=1, proposito="registro")
    for cambio in ({"m": 10 ** 6}, {"t": int(time.time()) + 10 ** 6}, {"p": "recuperacion"},
                   {"d": {"cuil": "20222222223"}}):
        assert auth.leer_paso(_reemplazar_cuerpo(tok, **cambio), "registro") is None, cambio
        assert auth.leer_paso(_reemplazar_cuerpo(tok, **cambio), cambio.get("p", "registro")) is None, cambio
    # el mismo cuerpo firmado con el esquema de la SESIÓN (sin 'paso:') tampoco vale
    cuerpo, _ = tok.rsplit(".", 1)
    import hmac as _h
    firma_sesion = _h.new(auth.SECRETO.encode(), cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
    assert auth.leer_paso(f"{cuerpo}.{firma_sesion}", "registro") is None


def test_un_token_de_un_proposito_no_sirve_para_otro_ni_una_sesion_para_un_paso():
    props = ("registro", "recuperacion", "confirmar_mail", "")
    for emisor in props:
        tok = auth.firmar_paso({"x": 1}, proposito=emisor)
        for lector in props:
            assert (auth.leer_paso(tok, lector) is not None) == (emisor == lector)
    for rol in ("trabajador", "empleador", "sindicato", "plataforma"):
        ses = auth.crear_sesion(rol, 1, 1, "20111111112")
        for p in props:
            assert auth.leer_paso(ses, p) is None
        assert auth.leer_sesion(auth.firmar_paso({"rol": rol}, proposito="")) is None


@pytest.mark.parametrize("minutos", [0, -1, -15, 0.0])
def test_minutos_cero_o_negativos_producen_un_token_ya_vencido(monkeypatch, minutos):
    tok = auth.firmar_paso({"a": 1}, minutos=minutos, proposito="x")
    t = time.time()
    monkeypatch.setattr(time, "time", lambda: t + 0.5)
    assert auth.leer_paso(tok, "x") is None


def test_datos_que_no_son_dict_no_se_leen_y_el_token_no_explota():
    for raro in (["a"], "texto", 5, None):
        tok = auth.firmar_paso(raro, proposito="x")
        assert auth.leer_paso(tok, "x") is None


def test_el_paso_vive_lo_que_dice_y_un_segundo_menos(monkeypatch):
    tok = auth.firmar_paso({"a": 1}, minutos=2, proposito="x")
    t = time.time()
    monkeypatch.setattr(time, "time", lambda: t + 119)
    assert auth.leer_paso(tok, "x") == {"a": 1}
    monkeypatch.setattr(time, "time", lambda: t + 122)
    assert auth.leer_paso(tok, "x") is None


# ===========================================================================
# 6. errores.py
# ===========================================================================
def test_los_seis_codigos_de_registro_son_para_personas():
    esperados = {"E-REGISTRO-01": 400, "E-REGISTRO-02": 400, "E-REGISTRO-03": 429,
                 "E-REGISTRO-04": 403, "E-REGISTRO-05": 429, "E-REGISTRO-06": 503}
    for codigo, status in esperados.items():
        st, msg = errores.MENSAJES[codigo]
        assert st == status
        assert msg.strip().endswith(".") and len(msg) > 25
        bajo = msg.lower()
        assert not any(p in bajo for p in ("foto", "imagen", "otra foto", "traceback", "hash", "token", "sql",
                                           "turnstile", "resend", "excepción"))
    assert set(errores.MENSAJES) >= set(esperados)


# ===========================================================================
# 7. regularizar_cuit.INVENTARIO
# ===========================================================================
def test_el_inventario_incluye_el_identificador_de_los_codigos():
    cols = {(c.tabla, c.columna) for c in regularizar_cuit.INVENTARIO}
    assert ("codigoverificacion", "identificador") in cols
    # y ningún otro dato del registro nuevo guarda un CUIL/CUIT sin inventariar
    for t in ("cuentatrabajador", "cuentaempleador"):
        for col in COLUMNAS_NUEVAS[t]:
            assert (t, col) not in cols     # son texto libre/nivel: no contienen identificadores

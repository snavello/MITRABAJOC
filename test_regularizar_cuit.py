"""regularizar_cuit.py: la herramienta que convierte los CUIL/CUIT cargados sin
el dígito verificador (PLAN_CUIT_MOD11.md, etapas 1 y 2).

Lo que se prueba, en orden de importancia:

- que una conversión toca TODAS las tablas y todas las rutas de los JSON, y
  que la persona sigue siendo la misma (el JOIN, el hash de la clave, el token
  de la credencial, el login por HTTP);
- que el ensayo no escribe nada y que cualquier abortada tampoco -- ni siquiera
  una falla A MITAD de la conversión deja la base a medias;
- que las colisiones frenan y no se fusiona a nadie;
- que la historia (bitácoras, textos libres) queda igual;
- el test fail-closed: una columna nueva `cuil`/`cuit` (o un JSON nuevo) que
  nadie decidió hace fallar la suite.

Correr con: .venv/bin/python -m pytest test_regularizar_cuit.py -q
"""
import csv
import shutil
import types

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, select

import auth
import cuit
import db
import main
import regularizar_cuit as rc
from db import (CambioIdentificador, ConsultaConvenio, Concepto, CuentaEmpleador,
                CuentaTrabajador, Empleador, Encuesta, EncuestaParticipante, EnvioSindicato,
                LogPlataforma, Notificacion, NotificacionDestinatario, NotificacionEmpleador,
                NotificacionEmpleadorDestinatario, PreguntaEncuesta, ReciboSospechoso,
                ReciboVerificado, Reporte, RespuestaEncuesta, RespuestaNominal, Sindicato,
                SuscripcionPush, TipoTramite, TipoTramiteEmpleador, Trabajador, Tramite,
                TramiteEmpleador, TramiteLog, UsoIA, UsuarioPlataforma, UsuarioSindicato)

# Los números del escenario. Todos se verifican abajo (test_los_numeros_del_escenario).
PERSONA, PERSONA_NUEVO = "27999999999", "27999999994"        # cargada a mano, en muchas tablas
EMPRESA, EMPRESA_NUEVO = "30777777770", "30777777773"        # cargada a mano
COL_A, COL_B, COL_NUEVO = "20171717170", "20171717179", "20171717176"   # chocan: misma corrección
LOTE = "20600000017"                                         # cargar_lote_uom.CUILS[1]
DEMO_P, DEMO_P_NUEVO = "20111111119", "20111111112"          # Juan Molina, del mapa de la demo
DEMO_E, DEMO_E_NUEVO = "30999888776", "30999888778"          # Metalúrgica del Sur, del mapa de la demo
LECTURA, LECTURA_NUEVO = "30555555550", "30555555551"        # solo lo leyó la IA de un recibo
VALIDO_P, VALIDO_E = "20202790411", "30444640975"            # válidos: no se tocan
EN_UN_JSON = "20111111120"                                   # válido, y solo vive adentro de un JSON
ROTO_CORTO, ROTO_PREFIJO = "2012345", "99999999999"          # forma rota

CLAVE = "clave-de-prueba"
HASH = auth.hashear_clave(CLAVE)        # uno solo para todo: PBKDF2 es lento a propósito

TODAS_LAS_TABLAS = sorted(SQLModel.metadata.tables)


# ---------------------------------------------------------------------------
# Escenario
# ---------------------------------------------------------------------------
def _limpiar_todo():
    with db.engine.begin() as c:
        c.execute(sa.text("TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in TODAS_LAS_TABLAS) +
                          " RESTART IDENTITY CASCADE"))


def _detalle_recibo(cuil_con_guiones, cuil_pelado, cuit_con_guiones):
    """Lo que guarda /api/validar: lo leído por la IA + lo calculado."""
    return {
        "recibo": {
            "empleado": {"apellido_nombre": "Persona Manual", "cuil": cuil_con_guiones},
            "empleador": {"nombre": "Empresa", "cuit": cuit_con_guiones},
            "lineas": [{"codigo": "001", "descripcion": "Sueldo", "importe": 1000.0}],
            "observaciones": f"El CUIL {cuil_pelado} figura en este texto largo",
        },
        "resultado": {"cuil": cuil_pelado, "periodo": "2026-09",
                      "lista": ["27 99999999 9", int(cuil_pelado)]},
    }


def _sembrar() -> types.SimpleNamespace:
    _limpiar_todo()
    ns = types.SimpleNamespace()
    with db.get_session() as s:
        a = Sindicato(nombre="Sindicato A", slug="sind-a", cuit="30-77777777-0")
        b = Sindicato(nombre="Sindicato B", slug="sind-b", cuit="30444640975")
        s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
        ns.a, ns.b = a.id, b.id

        # ---- la persona cargada a mano: en muchas tablas -------------------
        db.guardar_datos_personales(s, PERSONA, nombre="Persona Manual")
        db.asegurar_cuenta(s, PERSONA).clave_hash = HASH
        s.add(Trabajador(sindicato_id=a.id, cuil=PERSONA, registrado=True, activo=True,
                         cuit_empleador="30-77777777-0",
                         semaforo_datos={"cuil": "27-99999999-9", "meses": [{"mes": "2026-08"}]}))
        s.add(Trabajador(sindicato_id=b.id, cuil=PERSONA, registrado=True, activo=True,
                         cuit_empleador=EMPRESA))
        s.add(UsuarioSindicato(sindicato_id=a.id, usuario=PERSONA, cuil=PERSONA, nombre="Operador Manual",
                               clave_hash=HASH, debe_cambiar_clave=False, es_super_admin=True))
        s.add(UsuarioPlataforma(usuario="pers-manual", nombre="Plataforma Manual", clave_hash=HASH,
                                cuil=PERSONA, dni=PERSONA[2:10]))
        s.add(ReciboVerificado(
            sindicato_id=a.id, cuil=PERSONA, periodo="2026-09", estado="OK", cuit_empleador=EMPRESA,
            detalle=_detalle_recibo("27-99999999-9", PERSONA, "30-77777777-0")))
        s.add(EnvioSindicato(sindicato_id=a.id, cuil=PERSONA, periodo="2026-09",
                             detalle=_detalle_recibo("27-99999999-9", PERSONA, "30-77777777-0")))
        s.add(Reporte(sindicato_id=a.id, fecha="01/09/2026 10:00", cuil=PERSONA, periodo="2026-09",
                      detalle=_detalle_recibo("27-99999999-9", PERSONA, "30-77777777-0")))
        s.add(ReciboSospechoso(sindicato_id=a.id, cuil=PERSONA, motivo="x", archivo_datos=b"x"))
        s.add(UsoIA(sindicato_id=a.id, cuil=PERSONA, tipo="recibo"))
        s.add(SuscripcionPush(cuil=PERSONA, endpoint="https://push.example/1"))
        s.add(ConsultaConvenio(sindicato_id=a.id, cuil=PERSONA, pregunta="¿cuánto?"))
        n = Notificacion(sindicato_id=a.id, criterio="cuil", criterio_valores=[PERSONA, VALIDO_P],
                         texto=f"Hola {PERSONA}", cantidad_destinatarios=1)
        n_secc = Notificacion(sindicato_id=a.id, criterio="seccional", criterio_valores=["12"])
        s.add(n); s.add(n_secc); s.commit(); s.refresh(n)
        s.add(NotificacionDestinatario(notificacion_id=n.id, cuil=PERSONA))
        tt = TipoTramite(sindicato_id=a.id, titulo="Reclamo", codigo="F01")
        s.add(tt); s.commit(); s.refresh(tt)
        tr = Tramite(sindicato_id=a.id, tipo_tramite_id=tt.id, numero_expediente="F01-2026-000001",
                     cuil=PERSONA)
        s.add(tr); s.commit(); s.refresh(tr)
        s.add(TramiteLog(tramite_id=tr.id, evento="creado", detalle=f"Lo inició {PERSONA}"))
        enc = Encuesta(sindicato_id=a.id, titulo="Clima", modo="nominal", criterio="cuil",
                       criterio_valores=[PERSONA], publicada=True)
        s.add(enc); s.commit(); s.refresh(enc)
        preg = PreguntaEncuesta(encuesta_id=enc.id, tipo_dato="escala", etiqueta="¿Cómo estás?")
        s.add(preg); s.commit(); s.refresh(preg)
        resp = RespuestaEncuesta(encuesta_id=enc.id, pregunta_id=preg.id, valor_numero=3,
                                 cuit_empleador=EMPRESA)
        s.add(resp); s.commit(); s.refresh(resp)
        s.add(EncuestaParticipante(encuesta_id=enc.id, cuil=PERSONA, respondio=True))
        s.add(RespuestaNominal(encuesta_id=enc.id, respuesta_id=resp.id, cuil=PERSONA))
        s.add(LogPlataforma(cuando="2026-09-01 10:00", accion="reseteo", usuario="snavello",
                            objetivo=PERSONA, detalle=f"Reseteo de clave de {PERSONA}"))

        # ---- la empresa cargada a mano ------------------------------------
        s.add(Empleador(sindicato_id=a.id, cuit=EMPRESA, razon_social="Empresa Manual SA"))
        s.add(Empleador(sindicato_id=b.id, cuit=EMPRESA, razon_social="Empresa Manual SA"))
        s.add(CuentaEmpleador(cuit=EMPRESA, clave_hash=HASH))
        s.add(Concepto(sindicato_id=a.id, codigo="X1", nombre="Adicional", tipo="ingreso",
                       cuit_empleador=EMPRESA))
        tte = TipoTramiteEmpleador(sindicato_id=a.id, titulo="Alta", codigo="E01")
        s.add(tte); s.commit(); s.refresh(tte)
        s.add(TramiteEmpleador(sindicato_id=a.id, tipo_tramite_id=tte.id,
                               numero_expediente="E01-2026-000001", cuit=EMPRESA))
        ne = NotificacionEmpleador(sindicato_id=a.id, criterio="cuit", criterio_valores=[EMPRESA])
        s.add(ne); s.commit(); s.refresh(ne)
        s.add(NotificacionEmpleadorDestinatario(notificacion_empleador_id=ne.id, cuit=EMPRESA))

        # ---- el resto del escenario ----------------------------------------
        for cuil, nombre in ((COL_A, "Colisión Uno"), (COL_B, "Colisión Dos"), (LOTE, "Del Lote"),
                             (DEMO_P, "Juan Molina"), (VALIDO_P, "Persona Válida")):
            db.guardar_datos_personales(s, cuil, nombre=nombre)
            db.asegurar_cuenta(s, cuil).clave_hash = HASH
            s.add(Trabajador(sindicato_id=a.id, cuil=cuil, registrado=True, activo=True))
        s.add(Empleador(sindicato_id=a.id, cuit=DEMO_E, razon_social="Metalúrgica del Sur SRL"))
        s.add(Empleador(sindicato_id=a.id, cuit=VALIDO_E, razon_social="Empresa Válida SA"))
        # El CUIT que solo leyó la IA de un recibo: no está en ningún alta.
        s.add(ReciboVerificado(
            sindicato_id=a.id, cuil=VALIDO_P, periodo="2026-08", estado="OK", cuit_empleador=LECTURA,
            detalle={"recibo": {"empleador": {"cuit": LECTURA}},
                     "resultado": {"cuil": VALIDO_P, "titular": EN_UN_JSON}}))
        # Forma rota: no son números.
        db.asegurar_cuenta(s, ROTO_CORTO)
        s.add(Trabajador(sindicato_id=a.id, cuil=ROTO_PREFIJO, activo=True))
        s.commit()
    return ns


@pytest.fixture(autouse=True)
def _entorno_de_los_tests(monkeypatch):
    """La suite corre con ENTORNO=pruebas en la CI y sin la variable en la PC. La
    herramienta lee `entorno.ENTORNO` al usarla (traza, nombre del backup, nombre
    de la planilla, chequeo contra el entorno de la planilla): cada test parte
    de "sin definir" (= 'local') y el que necesite otro lo fija él."""
    monkeypatch.setattr(rc.entorno, "ENTORNO", "")


@pytest.fixture
def base():
    return _sembrar()


def _volcado() -> dict:
    """Todas las filas de todas las tablas: para probar que algo NO escribió."""
    with db.engine.connect() as c:
        return {t: [tuple(r) for r in c.execute(sa.text(f'SELECT * FROM "{t}" ORDER BY 1'))]
                for t in TODAS_LAS_TABLAS}


def _filas(diag) -> dict:
    return {f.anterior: f for f in diag.filas}


def _diagnostico():
    with db.engine.connect() as c:
        return rc.diagnosticar(c)


def _planilla_basica(**mas):
    """La planilla que armaría la persona: lo que el diagnóstico propone para
    PERSONA y EMPRESA (los manuales sin colisión)."""
    filas = [{"anterior": PERSONA, "nuevo": PERSONA_NUEVO, "convertir": "si"},
             {"anterior": EMPRESA, "nuevo": EMPRESA_NUEVO, "convertir": "si"}]
    return filas + list(mas.get("extra", []))


def _aplicar(planilla, **kw):
    kw.setdefault("sin_backup", True)
    kw.setdefault("quien", "TEST")
    kw.setdefault("salida", lambda *_: None)
    kw.setdefault("entorno_declarado", rc._entorno_actual())     # las planillas armadas a mano no lo traen
    return rc.aplicar(planilla, **kw)


def _cuantos(clave_tabla, valor) -> int:
    tabla, col = clave_tabla.split(".")
    with db.engine.connect() as c:
        return c.execute(sa.text(f'SELECT COUNT(*) FROM "{tabla}" WHERE "{col}" = :v'), {"v": valor}).scalar()


def _apariciones() -> dict:
    with db.engine.connect() as c:
        return rc.escanear(c).plano()["apariciones"]


# ---------------------------------------------------------------------------
# El escenario es lo que dice ser
# ---------------------------------------------------------------------------
def test_los_numeros_del_escenario():
    invalidos = (PERSONA, EMPRESA, COL_A, COL_B, LOTE, DEMO_P, DEMO_E, LECTURA)
    assert not any(cuit.es_valido(n) for n in invalidos)
    assert all(cuit.es_valido(n) for n in (VALIDO_P, VALIDO_E, PERSONA_NUEVO, EMPRESA_NUEVO,
                                           COL_NUEVO, LECTURA_NUEVO, EN_UN_JSON))
    assert cuit.corregir(PERSONA) == PERSONA_NUEVO and cuit.corregir(EMPRESA) == EMPRESA_NUEVO
    assert cuit.corregir(COL_A) == cuit.corregir(COL_B) == COL_NUEVO       # el caso de la trampa
    assert cuit.corregir(LECTURA) == LECTURA_NUEVO
    assert rc.identificadores_demo.REEMPLAZOS_MOD11[DEMO_P] == DEMO_P_NUEVO
    assert rc.identificadores_demo.REEMPLAZOS_MOD11[DEMO_E] == DEMO_E_NUEVO


# ---------------------------------------------------------------------------
# Fail-closed: el inventario cubre el esquema
# ---------------------------------------------------------------------------
def test_el_inventario_cubre_el_esquema():
    """Una columna `cuil`/`cuit` (o `usuario`/`dni`, o cualquier JSON) que no está
    ni en INVENTARIO ni en EXCLUIDAS hace fallar este test: el olvido se nota,
    no se filtra."""
    sin_decidir = rc.columnas_sin_decidir()
    assert not sin_decidir, (
        "estas columnas pueden guardar un CUIL/CUIT y regularizar_cuit.py no sabe qué hacer con "
        f"ellas: agregalas a INVENTARIO (se reescriben) o a EXCLUIDAS (con el motivo): {sin_decidir}")


def test_el_fail_closed_detecta_una_columna_nueva():
    meta = sa.MetaData()
    sa.Table("tabla_nueva", meta, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("cuil_del_tutor", sa.String), sa.Column("extra", sa.JSON),
             sa.Column("usuario", sa.String), sa.Column("nombre", sa.String))
    assert rc.columnas_sin_decidir(meta) == [
        "tabla_nueva.cuil_del_tutor", "tabla_nueva.extra", "tabla_nueva.usuario"]


def test_todo_lo_del_inventario_y_de_las_excluidas_existe():
    """Un renombre de columna no puede dejar una entrada vieja que parece cubrir algo."""
    columnas = {f"{t}.{c.name}" for t, tabla in SQLModel.metadata.tables.items() for c in tabla.columns}
    claves = [c.clave for c in rc.INVENTARIO]
    assert len(claves) == len(set(claves)), "columna repetida en INVENTARIO"
    assert not {c.columna_db for c in rc.INVENTARIO} & set(rc.EXCLUIDAS), \
        "una columna no puede estar en las dos listas"
    for clave in [c.columna_db for c in rc.INVENTARIO] + list(rc.EXCLUIDAS):
        assert clave in columnas, f"{clave} no existe en el esquema"
    for c in rc.INVENTARIO:
        assert c.clase in (rc.PERSONA, rc.EMPRESA, rc.CUALQUIERA)
        assert c.valor in (rc.TEXTO, rc.JSON) and c.fuente in (rc.ALTA, rc.LECTURA, rc.COPIA)
        # Dos entradas de la misma columna se distinguen por etiqueta y filtro de filas.
        otras = [x for x in rc.INVENTARIO if x.columna_db == c.columna_db and x is not c]
        assert bool(c.etiqueta) == bool(otras) and (not c.etiqueta or c.donde), c.clave
    for motivo in rc.EXCLUIDAS.values():
        assert motivo.strip(), "toda exclusión tiene su motivo"


def test_el_inventario_tiene_todo_lo_pedido():
    pedido = """cuentatrabajador.cuil trabajador.cuil trabajador.cuit_empleador trabajador.semaforo_datos
        usuariosindicato.usuario usuariosindicato.cuil usuarioplataforma.cuil cuentaempleador.cuit
        empleador.cuit sindicato.cuit concepto.cuit_empleador reciboverificado.cuil
        reciboverificado.cuit_empleador reciboverificado.detalle enviosindicato.cuil enviosindicato.detalle
        reporte.cuil reporte.detalle recibosospechoso.cuil usoia.cuil tramite.cuil tramiteempleador.cuit
        notificaciondestinatario.cuil notificacionempleadordestinatario.cuit notificacion.criterio_valores
        notificacionempleador.criterio_valores encuesta.criterio_valores encuestaparticipante.cuil
        respuestanominal.cuil respuestaencuesta.cuit_empleador suscripcionpush.cuil
        consultaconvenio.cuil""".split()
    assert set(pedido) <= {c.columna_db for c in rc.INVENTARIO}
    for excluida in ("logplataforma.detalle", "tramitelog.detalle", "tramiteempleadorlog.detalle",
                     "eventoencuesta.detalle", "cambioplan.detalle", "registroenmascarado.cuil_encontrado",
                     "consultaasistente.filtros", "testcarga.parametros"):
        assert excluida in rc.EXCLUIDAS


# ---------------------------------------------------------------------------
# El recorrido de los JSON
# ---------------------------------------------------------------------------
def _caminar(doc):
    vistas = []
    nuevo, cambio = rc.caminar_json(doc, lambda ruta, hoja: vistas.append((ruta, hoja)))
    assert not cambio
    return vistas


def test_el_recorrido_de_json_solo_ve_valores_enteros_con_forma_de_numero():
    doc = {"a": "27999999999", "b": " 27-99999999-9 ", "c": 27999999999, "d": "27 99999999 9",
           "e": "27.99999999/9",
           "texto": "el CUIL 27999999999 está adentro de un texto largo",     # no
           "otro": "27999999999999",                                           # 14 dígitos: no
           "prefijo": "99999999999",                                           # prefijo desconocido: no
           "bool": True, "nulo": None, "float": 2.7e10, "corto": "2799999999"}
    assert sorted(_caminar(doc), key=str) == sorted([
        ("a", "27999999999"), ("b", " 27-99999999-9 "), ("c", 27999999999),
        ("d", "27 99999999 9"), ("e", "27.99999999/9")], key=str)


def test_las_rutas_usan_corchetes_para_las_listas():
    doc = {"recibo": {"empleado": {"cuil": "27999999999"}, "lineas": [{"cuit": "30777777770"},
                                                                       {"cuit": "30777777770"}]},
           "lista": ["27999999999"], "anidada": [["27999999999"]]}
    rutas = sorted(r for r, _ in _caminar(doc))
    assert rutas == ["anidada[][]", "lista[]", "recibo.empleado.cuil", "recibo.lineas[].cuit",
                     "recibo.lineas[].cuit"]
    assert _caminar("27999999999") == [("(raíz)", "27999999999")]
    assert _caminar(None) == [] and _caminar([]) == [] and _caminar({}) == []


def test_el_reemplazo_conserva_el_formato_y_el_tipo():
    doc = {"a": "27999999999", "b": "27-99999999-9", "c": 27999999999, "d": "27 99999999 9",
           "otro": "20202790411", "texto": "27999999999 es el CUIL", "n": 7}
    nuevo, cambio = rc.caminar_json(doc, lambda ruta, hoja: (
        cuit.con_formato_de(hoja, PERSONA_NUEVO) if not isinstance(hoja, int) else int(PERSONA_NUEVO))
        if cuit.normalizar(hoja) == PERSONA else None)
    assert cambio
    assert nuevo == {"a": "27999999994", "b": "27-99999999-4", "c": 27999999994, "d": "27-99999999-4",
                     "otro": "20202790411", "texto": "27999999999 es el CUIL", "n": 7}


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------
def test_diagnostico_clasifica_cada_numero(base):
    diag = _diagnostico()
    f = _filas(diag)

    assert (f[PERSONA].origen, f[PERSONA].convertir, f[PERSONA].nuevo, f[PERSONA].tipo,
            f[PERSONA].motivo) == ("manual", True, PERSONA_NUEVO, "persona", "")
    assert (f[EMPRESA].origen, f[EMPRESA].convertir, f[EMPRESA].nuevo, f[EMPRESA].tipo) == (
        "manual", True, EMPRESA_NUEVO, "empresa")
    # demo: el nuevo es EXACTAMENTE el del mapa, y se convierte
    assert (f[DEMO_P].origen, f[DEMO_P].convertir, f[DEMO_P].nuevo) == ("demo", True, DEMO_P_NUEVO)
    assert (f[DEMO_E].origen, f[DEMO_E].convertir, f[DEMO_E].nuevo) == ("demo", True, DEMO_E_NUEVO)
    # lote: no se convierte
    assert (f[LOTE].origen, f[LOTE].convertir, f[LOTE].motivo) == ("lote", False, "LOTE")
    # lectura: solo aparece en columnas que guardan lo que leyó la IA
    assert (f[LECTURA].origen, f[LECTURA].convertir, f[LECTURA].motivo) == ("lectura", False, "LECTURA")
    assert set(f[LECTURA].apariciones) == {"reciboverificado.cuit_empleador", "reciboverificado.detalle"}
    # colisión: los dos se corrigen al mismo número -> ninguno se elige solo
    for n in (COL_A, COL_B):
        assert (f[n].origen, f[n].convertir, f[n].motivo, f[n].nuevo) == ("manual", False, "COLISION", COL_NUEVO)
    assert f[COL_A].alternativa and f[COL_B].alternativa
    assert f[COL_A].alternativa != f[COL_B].alternativa
    # forma rota
    assert (f[ROTO_CORTO].motivo, f[ROTO_CORTO].convertir, f[ROTO_CORTO].nuevo) == ("FORMATO", False, "")
    assert (f[ROTO_PREFIJO].motivo, f[ROTO_PREFIJO].convertir) == ("FORMATO", False)
    # los válidos no salen
    assert VALIDO_P not in f and VALIDO_E not in f and PERSONA_NUEVO not in f


def test_un_prefijo_23_sin_verificador_posible_no_tiene_correccion(base):
    """23xxxxxxxx0 con r = 10 no se puede corregir ni cambiando el prefijo (ya es
    el 23): sale SIN_CORRECCION, sin convertir, y se ofrece renumerar."""
    sin_dv = "23121212030"
    assert cuit.corregir(sin_dv) == "" and cuit.digito_verificador(sin_dv[:10]) is None
    with db.get_session() as s:
        db.guardar_datos_personales(s, sin_dv, nombre="Sin Verificador")
        s.commit()
    f = _filas(_diagnostico())[sin_dv]
    assert (f.motivo, f.convertir, f.nuevo) == ("SIN_CORRECCION", False, "")
    assert f.alternativa == cuit.siguiente_libre(sin_dv, {sin_dv}) == "23121212048"
    # y si la persona acepta la alternativa, se convierte como cualquier otra
    _aplicar([_fila(sin_dv, f.alternativa)], si=True)
    assert f.alternativa in _apariciones() and sin_dv not in _apariciones()


def test_diagnostico_cuenta_las_apariciones_por_tabla_y_columna(base):
    f = _filas(_diagnostico())
    persona = f[PERSONA].apariciones
    esperadas = {
        "cuentatrabajador.cuil": 1, "trabajador.cuil": 2, "usuariosindicato.usuario": 1,
        "usuariosindicato.cuil": 1, "cuentapanel.cuil": 1, "usuarioplataforma.cuil": 1, "reciboverificado.cuil": 1,
        "reciboverificado.detalle": 1, "enviosindicato.cuil": 1, "enviosindicato.detalle": 1,
        "reporte.cuil": 1, "reporte.detalle": 1, "recibosospechoso.cuil": 1, "usoia.cuil": 1,
        "suscripcionpush.cuil": 1, "consultaconvenio.cuil": 1, "notificaciondestinatario.cuil": 1,
        "notificacion.criterio_valores": 1, "tramite.cuil": 1, "encuesta.criterio_valores": 1,
        "encuestaparticipante.cuil": 1, "respuestanominal.cuil": 1, "trabajador.semaforo_datos": 1}
    assert persona == esperadas
    empresa = f[EMPRESA].apariciones
    # sindicato.cuit y trabajador.cuit_empleador están con guiones: igual cuentan
    assert empresa == {
        "empleador.cuit": 2, "cuentaempleador.cuit": 1, "trabajador.cuit_empleador": 2,
        "concepto.cuit_empleador[confirmado]": 1, "reciboverificado.cuit_empleador": 1,
        "reciboverificado.detalle": 1, "enviosindicato.detalle": 1, "reporte.detalle": 1,
        "tramiteempleador.cuit": 1, "notificacionempleador.criterio_valores": 1,
        "notificacionempleadordestinatario.cuit": 1, "respuestaencuesta.cuit_empleador": 1,
        "sindicato.cuit": 1}


def test_diagnostico_reconoce_el_nombre(base):
    f = _filas(_diagnostico())
    assert f[PERSONA].nombre == "Operador Manual / Persona Manual / Plataforma Manual"
    assert f[EMPRESA].nombre == "Empresa Manual SA / Sindicato A"
    assert f[DEMO_P].nombre == "Juan Molina"


def test_el_diagnostico_acepta_una_sesion_tambien(base):
    with db.get_session() as s:
        diag = rc.diagnosticar(s)
    assert {f.anterior for f in diag.filas} == {f.anterior for f in _diagnostico().filas}


def test_el_diagnostico_no_escribe_nada(base):
    antes = _volcado()
    _diagnostico()
    assert _volcado() == antes


def test_un_texto_libre_con_el_numero_no_cuenta(base):
    """logplataforma / tramitelog / textos de notificación llevan el número VIEJO
    y no figuran: son la historia."""
    f = _filas(_diagnostico())
    assert not any(k.startswith(("logplataforma", "tramitelog", "notificacion.texto"))
                   for k in f[PERSONA].apariciones)


def test_un_valor_ajeno_a_la_columna_solo_se_avisa(base):
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=base.a, cuil=VALIDO_E, activo=True))   # un CUIT en una columna de CUIL
        s.commit()
    anomalias = _diagnostico().escaneo.anomalias
    assert ("trabajador.cuil", VALIDO_E, "empresa", "persona") in anomalias


def test_usuario_que_no_es_un_numero_se_ignora(base):
    with db.get_session() as s:
        s.add(UsuarioSindicato(sindicato_id=base.a, usuario="admin-central", cuil="", nombre="Admin",
                               clave_hash=HASH))
        s.commit()
    assert "admin-central" not in _filas(_diagnostico())


def test_la_segunda_corrida_no_tiene_manuales_convertibles(base):
    _aplicar(_planilla_basica(), si=True)
    diag = _diagnostico()
    f = _filas(diag)
    assert PERSONA not in f and EMPRESA not in f
    assert not [x for x in diag.filas if x.origen == "manual" and x.convertir]
    # lo que sigue sin convertirse es lo que no se tocó a propósito
    assert f[COL_A].motivo == "COLISION" and f[LOTE].motivo == "LOTE"


# ---------------------------------------------------------------------------
# La planilla
# ---------------------------------------------------------------------------
def test_la_planilla_sale_en_utf8_con_bom_y_se_lee_de_vuelta(base, tmp_path):
    diag = _diagnostico()
    ruta = rc.escribir_planilla(diag, tmp_path / "p.csv")
    crudo = ruta.read_bytes()
    assert crudo.startswith(b"\xef\xbb\xbf"), "Excel necesita el BOM para los acentos"
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    assert tuple(filas[0].keys()) == rc.COLUMNAS_PLANILLA
    assert len(filas) == len(diag.filas)
    por_numero = {x["anterior"]: x for x in filas}
    assert por_numero[PERSONA]["convertir"] == "si" and por_numero[PERSONA]["nuevo"] == PERSONA_NUEVO
    assert por_numero[PERSONA]["origen"] == "manual" and por_numero[PERSONA]["tipo"] == "persona"
    assert "cuentatrabajador.cuil:1" in por_numero[PERSONA]["apariciones"]
    assert por_numero[COL_A]["motivo"] == "COLISION" and por_numero[COL_A]["alternativa"]
    assert por_numero[LOTE]["convertir"] == "no"
    # y la lee la misma herramienta
    leidas = rc.leer_planilla(ruta)
    assert {x["anterior"] for x in leidas} == {x.anterior for x in diag.filas}


def test_la_planilla_se_lee_con_comas_y_en_cp1252(tmp_path):
    ruta = tmp_path / "excel.csv"
    contenido = "anterior,nuevo,alternativa,convertir,nombre\n27999999999,27999999994,,SI,Peña\n"
    ruta.write_bytes(contenido.encode("cp1252"))          # "CSV" común de Excel: sin UTF-8
    filas = rc.leer_planilla(ruta)
    assert filas[0]["anterior"] == "27999999999" and filas[0]["convertir"] == "SI"
    assert filas[0]["nombre"].startswith("Pe")
    ruta.write_text("Anterior;Nuevo;Convertir\n27999999999;27999999994;sí\n", encoding="utf-8-sig")
    assert rc.leer_planilla(ruta)[0]["nuevo"] == "27999999994"
    ruta.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(rc.ErrorRegularizacion, match="columnas"):
        rc.leer_planilla(ruta)


# ---------------------------------------------------------------------------
# Ensayo: no escribe nada
# ---------------------------------------------------------------------------
def test_el_ensayo_muestra_que_cambiaria_y_no_escribe_nada(base):
    antes = _volcado()
    res = _aplicar(_planilla_basica(), si=False)
    assert not res.aplicado and res.backup is None
    assert _volcado() == antes, "el ensayo escribió algo (ni siquiera la traza)"
    assert _cuantos("cuentatrabajador.cuil", PERSONA) == 1 and _cuantos("cuentatrabajador.cuil", PERSONA_NUEVO) == 0
    # pero sí cuenta lo que habría hecho, por tabla.columna y por ruta de JSON
    assert res.por_columna["cuentatrabajador.cuil"] == 1 and res.por_columna["trabajador.cuil"] == 2
    assert "reciboverificado.detalle:recibo.empleado.cuil" in res.rutas
    assert "reciboverificado.detalle:resultado.lista[]" in res.rutas
    assert {c.anterior for c in res.cambios} == {PERSONA, EMPRESA}


def test_el_ensayo_no_pide_quien_ni_hace_backup(base, tmp_path):
    res = _aplicar(_planilla_basica(), si=False, quien="", sin_backup=False, directorio_backup=tmp_path)
    assert not res.aplicado and list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Aplicar
# ---------------------------------------------------------------------------
def test_aplicar_convierte_todas_las_tablas(base):
    previo = _apariciones()
    res = _aplicar(_planilla_basica(), si=True)
    assert res.aplicado
    a = _apariciones()
    # LO CENTRAL: el nuevo tiene EXACTAMENTE las apariciones que tenía el viejo,
    # en cada tabla.columna, y del viejo no queda ninguna.
    assert a[PERSONA_NUEVO] == previo[PERSONA] and a[EMPRESA_NUEVO] == previo[EMPRESA]
    assert len(previo[PERSONA]) == 23 and len(previo[EMPRESA]) == 13
    assert PERSONA not in a and EMPRESA not in a, "quedó el número viejo en alguna parte"
    assert a[PERSONA_NUEVO]["cuentatrabajador.cuil"] == 1 and a[PERSONA_NUEVO]["trabajador.cuil"] == 2
    for clave in ("usuariosindicato.usuario", "usuariosindicato.cuil", "cuentapanel.cuil",
                  "usuarioplataforma.cuil",
                  "reciboverificado.cuil", "reciboverificado.detalle", "enviosindicato.cuil",
                  "enviosindicato.detalle", "reporte.cuil", "reporte.detalle", "recibosospechoso.cuil",
                  "usoia.cuil", "suscripcionpush.cuil", "consultaconvenio.cuil",
                  "notificaciondestinatario.cuil", "notificacion.criterio_valores", "tramite.cuil",
                  "encuesta.criterio_valores", "encuestaparticipante.cuil", "respuestanominal.cuil",
                  "trabajador.semaforo_datos"):
        assert a[PERSONA_NUEVO][clave] == 1, clave
    for clave, n in {"empleador.cuit": 2, "cuentaempleador.cuit": 1, "trabajador.cuit_empleador": 2,
                     "concepto.cuit_empleador[confirmado]": 1, "reciboverificado.cuit_empleador": 1,
                     "reciboverificado.detalle": 1, "tramiteempleador.cuit": 1,
                     "notificacionempleador.criterio_valores": 1,
                     "notificacionempleadordestinatario.cuit": 1, "respuestaencuesta.cuit_empleador": 1,
                     "sindicato.cuit": 1}.items():
        assert a[EMPRESA_NUEVO][clave] == n, clave
    # lo que no estaba en la planilla no se movió
    assert LOTE in a and COL_A in a and COL_B in a and DEMO_P in a and LECTURA in a
    assert a[VALIDO_P]["cuentatrabajador.cuil"] == 1


def test_los_json_se_reescriben_en_el_formato_que_tenian(base):
    _aplicar(_planilla_basica(), si=True)
    with db.get_session() as s:
        d = s.exec(select(ReciboVerificado).where(ReciboVerificado.periodo == "2026-09")).one().detalle
        assert d["recibo"]["empleado"]["cuil"] == "27-99999999-4"           # tenía guiones
        assert d["recibo"]["empleador"]["cuit"] == "30-77777777-3"          # tenía guiones
        assert d["resultado"]["cuil"] == "27999999994"                      # no tenía
        assert d["resultado"]["lista"] == ["27-99999999-4", 27999999994]    # con espacios -> guiones; el int sigue int
        assert d["recibo"]["observaciones"] == f"El CUIL {PERSONA} figura en este texto largo"   # un texto, intacto
        assert d["recibo"]["lineas"] == [{"codigo": "001", "descripcion": "Sueldo", "importe": 1000.0}]
        sem = s.exec(select(Trabajador).where(Trabajador.sindicato_id == base.a, Trabajador.cuil == PERSONA_NUEVO)).one()
        assert sem.semaforo_datos == {"cuil": "27-99999999-4", "meses": [{"mes": "2026-08"}]}
        assert sem.cuit_empleador == "30-77777777-3"                        # el alta no lo normaliza
        n = s.exec(select(Notificacion).where(Notificacion.criterio == "cuil")).one()
        assert n.criterio_valores == [PERSONA_NUEVO, VALIDO_P] and n.texto == f"Hola {PERSONA}"
        assert s.exec(select(Notificacion).where(Notificacion.criterio == "seccional")).one().criterio_valores == ["12"]
        assert s.exec(select(Encuesta)).one().criterio_valores == [PERSONA_NUEVO]
        assert s.get(Sindicato, base.a).cuit == "30-77777777-3"             # con guiones, igual que antes
        assert s.get(Sindicato, base.b).cuit == VALIDO_E                     # válido: ni se miró
        assert s.exec(select(NotificacionEmpleador)).one().criterio_valores == [EMPRESA_NUEVO]


def test_la_historia_no_se_reescribe(base):
    _aplicar(_planilla_basica(), si=True)
    with db.get_session() as s:
        log = s.exec(select(LogPlataforma)).one()
        assert log.objetivo == PERSONA and log.detalle == f"Reseteo de clave de {PERSONA}"
        assert s.exec(select(TramiteLog)).one().detalle == f"Lo inició {PERSONA}"
        assert s.exec(select(Notificacion).where(Notificacion.criterio == "cuil")).one().texto == f"Hola {PERSONA}"


def test_la_persona_sigue_siendo_la_misma(base):
    token_a = db.token_credencial(PERSONA, base.a)
    token_b = db.token_credencial(PERSONA, base.b)
    assert token_a and token_b and token_a != token_b
    with db.get_session() as s:
        antes = [(t.sindicato_id, p.nombre) for t, p in s.exec(
            select(Trabajador, CuentaTrabajador).join(CuentaTrabajador, CuentaTrabajador.cuil == Trabajador.cuil)
            .where(Trabajador.cuil == PERSONA).order_by(Trabajador.sindicato_id)).all()]
    assert antes == [(base.a, "Persona Manual"), (base.b, "Persona Manual")]

    _aplicar(_planilla_basica(), si=True)

    # el JOIN cuenta <-> empadronamiento por CUIL sigue dando a la misma persona, en los dos sindicatos
    with db.get_session() as s:
        despues = [(t.sindicato_id, p.nombre) for t, p in s.exec(
            select(Trabajador, CuentaTrabajador).join(CuentaTrabajador, CuentaTrabajador.cuil == Trabajador.cuil)
            .where(Trabajador.cuil == PERSONA_NUEVO).order_by(Trabajador.sindicato_id)).all()]
        assert despues == antes
        assert [p["nombre"] for p in db.padron_del_sindicato(s, base.a) if p["cuil"] == PERSONA_NUEVO] == ["Persona Manual"]
        cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == PERSONA_NUEVO)).one()
        assert auth.verificar_clave(CLAVE, cuenta.clave_hash), "el hash de la clave tiene que seguir verificando"
        assert cuenta.clave_hash == HASH
    # el token del QR de la credencial no depende del número
    assert db.token_credencial(PERSONA_NUEVO, base.a) == token_a
    assert db.token_credencial(PERSONA_NUEVO, base.b) == token_b
    assert db.credencial_por_token(token_a)["cuil"] == PERSONA_NUEVO


def test_el_login_por_http_entra_con_el_numero_nuevo_y_no_con_el_viejo(base):
    _aplicar(_planilla_basica(), si=True)
    c = TestClient(main.app)

    r = c.post("/trabajador/login", data={"cuil": PERSONA_NUEVO, "clave": CLAVE}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio"
    r = c.post("/trabajador/login", data={"cuil": PERSONA, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=login"

    r = c.post("/admin/login", data={"usuario": PERSONA_NUEVO, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/admin/inicio", "el operador entra con su número nuevo"
    r = c.post("/admin/login", data={"usuario": PERSONA, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/admin?error=1"

    r = c.post("/empresa/login", data={"cuit": EMPRESA_NUEVO, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/empresa/inicio"
    r = c.post("/empresa/login", data={"cuit": EMPRESA, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar-empresa?error=login"


def test_el_informe_compara_el_antes_y_el_despues(base, capsys):
    """Paso 4 de la etapa 2: se muestra cómo estaba la base y cómo quedó."""
    res = _aplicar(_planilla_basica(), si=True)
    assert res.antes == {
        "para_revisar": 10, "convertibles": 4, "colisiones": 2,
        "por_origen": {"manual": 6, "demo": 2, "lote": 1, "lectura": 1}}
    assert res.despues == {
        "para_revisar": 8, "convertibles": 2, "colisiones": 2,
        "por_origen": {"manual": 4, "demo": 2, "lote": 1, "lectura": 1}}
    # y es lo que dice la corrida siguiente
    siguiente = rc.resumen_de_filas(_diagnostico().filas)
    assert siguiente == res.despues


def test_el_informe_impreso_trae_antes_despues_y_la_lista_de_afectados(base):
    lineas = []
    rc.aplicar(_planilla_basica(), si=True, quien="SDN", sin_backup=True, salida=lineas.append,
               entorno_declarado="local")
    texto = "\n".join(lineas)
    assert "CONVERSIÓN APLICADA: 2 número(s)" in texto and "SIN backup" in texto
    assert "Antes  : 10" in texto and "Después: 8" in texto
    assert "Tienen que enterarse" in texto
    assert f"{PERSONA} -> {PERSONA_NUEVO}" in texto and f"{EMPRESA} -> {EMPRESA_NUEVO}" in texto
    assert "reciboverificado.detalle:recibo.empleado.cuil" in texto


def test_aplicar_deja_la_traza(base):
    res = _aplicar(_planilla_basica(), si=True, quien="SDN")
    with db.get_session() as s:
        filas = {f.anterior: f for f in s.exec(select(CambioIdentificador)).all()}
    assert set(filas) == {PERSONA, EMPRESA}
    p = filas[PERSONA]
    assert (p.nuevo, p.tipo, p.origen, p.quien) == (PERSONA_NUEVO, "persona", "manual", "SDN")
    assert p.entorno == rc._entorno_actual() and len(p.fecha) == 16 and p.fecha[4] == "-" and p.fecha[10] == " "
    assert p.detalle["cuentatrabajador.cuil"] == 1 and p.detalle["trabajador.cuil"] == 2
    assert p.filas == sum(p.detalle.values())
    assert sum(c.filas for c in res.cambios) == sum(res.por_columna.values())      # coherente con el informe
    e = filas[EMPRESA]
    assert (e.nuevo, e.tipo, e.origen) == (EMPRESA_NUEVO, "empresa", "manual")
    assert e.detalle["sindicato.cuit"] == 1


def test_una_fila_demo_se_convierte_con_el_numero_del_mapa(base):
    planilla = [{"anterior": DEMO_P, "nuevo": DEMO_P_NUEVO, "convertir": "si"},
                {"anterior": DEMO_E, "nuevo": DEMO_E_NUEVO, "convertir": "SI"}]
    _aplicar(planilla, si=True)
    a = _apariciones()
    assert DEMO_P not in a and DEMO_E not in a
    assert a[DEMO_P_NUEVO]["cuentatrabajador.cuil"] == 1 and a[DEMO_E_NUEVO]["empleador.cuit"] == 1
    with db.get_session() as s:
        assert {x.anterior: x.origen for x in s.exec(select(CambioIdentificador)).all()} == {
            DEMO_P: "demo", DEMO_E: "demo"}


def test_las_filas_sin_convertir_si_no_se_tocan(base):
    planilla = [{"anterior": PERSONA, "nuevo": PERSONA_NUEVO, "convertir": "no"},
                {"anterior": EMPRESA, "nuevo": EMPRESA_NUEVO, "convertir": ""},
                {"anterior": COL_A, "nuevo": "", "convertir": "no"}]
    antes = _volcado()
    res = _aplicar(planilla, si=True)
    assert res.cambios == [] and not res.aplicado and _volcado() == antes


def test_renumerar_una_colision_con_la_alternativa(base):
    f = _filas(_diagnostico())
    planilla = [{"anterior": n, "nuevo": f[n].alternativa, "convertir": "si"} for n in (COL_A, COL_B)]
    _aplicar(planilla, si=True)
    a = _apariciones()
    assert COL_A not in a and COL_B not in a and COL_NUEVO not in a
    assert cuit.es_valido(f[COL_A].alternativa) and cuit.es_valido(f[COL_B].alternativa)
    assert a[f[COL_A].alternativa]["cuentatrabajador.cuil"] == 1 and a[f[COL_B].alternativa]["cuentatrabajador.cuil"] == 1
    with db.get_session() as s:
        nombres = {c.cuil: c.nombre for c in s.exec(select(CuentaTrabajador)).all()}
    assert nombres[f[COL_A].alternativa] == "Colisión Uno" and nombres[f[COL_B].alternativa] == "Colisión Dos"


def test_las_alternativas_no_chocan_con_nada(base):
    diag = _diagnostico()
    alternativas = [x.alternativa for x in diag.filas if x.alternativa]
    assert alternativas and len(alternativas) == len(set(alternativas))
    propuestos = {x.nuevo for x in diag.filas if x.convertir}
    for alt in alternativas:
        assert cuit.es_valido(alt) and alt not in diag.escaneo.ocupados and alt not in propuestos


# ---------------------------------------------------------------------------
# Abortar: ni una fila escrita
# ---------------------------------------------------------------------------
def _fila(anterior, nuevo, convertir="si"):
    return {"anterior": anterior, "nuevo": nuevo, "convertir": convertir}


@pytest.mark.parametrize("planilla, mensaje", [
    # el nuevo ya existe en la base: fusionar dos personas no lo hace la herramienta
    ([_fila(PERSONA, VALIDO_P)], "no fusiona"),
    ([_fila(PERSONA, EN_UN_JSON)], "YA existe"),         # ocupado, pero solo adentro de un JSON
    ([_fila(EMPRESA, VALIDO_E)], "no fusiona"),          # el CUIT de otra empresa
    ([_fila(PERSONA, LECTURA_NUEVO), _fila(EMPRESA, PERSONA_NUEVO)], "misma clase"),   # cambia de tipo
    ([_fila(PERSONA, "27999999990")], "no es un CUIL/CUIT válido"),     # nuevo inválido
    ([_fila(PERSONA, "2799999994")], "'nuevo' no tiene 11 dígitos"),    # 10 dígitos
    ([_fila(PERSONA, "2,79999E+10")], "notación científica"),           # lo que hace Excel
    ([_fila(PERSONA, "")], "no tiene 'nuevo'"),
    ([_fila("27888888888", "27888888883")], "no está en la base"),      # el viejo no existe
    ([_fila(PERSONA, PERSONA_NUEVO), _fila(COL_A, PERSONA_NUEVO)], "repetido"),   # dos viejos, un nuevo
    ([_fila(PERSONA, PERSONA_NUEVO), _fila(PERSONA, PERSONA_NUEVO)], "2 veces"),
    ([_fila(PERSONA, COL_A), _fila(COL_A, "20171717184")], "a la vez el anterior"),   # nuevo = viejo de otra fila
    ([_fila(VALIDO_P, "20111111120")], "ya cumple el módulo 11"),       # no se renumeran válidos
    ([_fila("2012345", "20123456783")], "11 dígitos"),                  # forma rota
    ([_fila(PERSONA, PERSONA_NUEVO), _fila(EMPRESA, "30777777771")], "no es un CUIL/CUIT válido"),  # una buena y una mala
])
def test_aplicar_aborta_sin_escribir_nada(base, planilla, mensaje):
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar(planilla, si=True)
    texto = " ".join([str(e.value), *e.value.errores])
    assert mensaje in texto, texto
    assert _volcado() == antes, "una planilla que se aborta no puede dejar NADA escrito"


def test_aplicar_con_si_exige_quien(base):
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion, match="--quien"):
        rc.aplicar(_planilla_basica(), si=True, quien="  ", sin_backup=True, salida=lambda *_: None)
    assert _volcado() == antes


def test_aplicar_junta_todos_los_errores(base):
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar([_fila(PERSONA, "27999999990"), _fila(EMPRESA, PERSONA_NUEVO), _fila("2012345", "")],
                 si=True)
    assert len(e.value.errores) == 3


def test_una_falla_a_mitad_de_la_conversion_deshace_todo(base, monkeypatch):
    """La conversión es una sola transacción: si la columna JSON falla DESPUÉS de
    haber reescrito las de texto, no queda nada a medias."""
    antes = _volcado()

    def explota(*a, **k):
        raise RuntimeError("falla simulada en los JSON")

    monkeypatch.setattr(rc, "_reescribir_json", explota)
    with pytest.raises(RuntimeError):
        _aplicar(_planilla_basica(), si=True)
    assert _volcado() == antes


def test_la_verificacion_previa_al_commit_deshace_todo(base, monkeypatch):
    """Si la verificación encuentra algo que no cierra (aquí: una columna que se
    reescribió de menos), se deshace y se dice qué."""
    antes = _volcado()
    original = rc._reescribir_texto

    def a_medias(conn, col, mapa):
        return {} if col.clave == "trabajador.cuil" else original(conn, col, mapa)

    monkeypatch.setattr(rc, "_reescribir_texto", a_medias)
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar(_planilla_basica(), si=True)
    assert "verificación" in str(e.value) and any("trabajador.cuil" in x for x in e.value.errores)
    assert _volcado() == antes


def test_si_la_tabla_de_traza_falla_tampoco_queda_nada(base, monkeypatch):
    """La traza se escribe en la MISMA transacción: si falla, la conversión no se queda."""
    antes = _volcado()
    original = sa.insert

    def falla_en_la_traza(tabla, *a, **k):
        if getattr(tabla, "name", "") == "cambioidentificador":
            raise RuntimeError("no se pudo escribir la traza")
        return original(tabla, *a, **k)

    monkeypatch.setattr(rc.sa, "insert", falla_en_la_traza)
    with pytest.raises(RuntimeError):
        _aplicar(_planilla_basica(), si=True)
    assert _volcado() == antes


def test_con_la_base_ocupada_no_espera_para_siempre(base):
    """El candado de las tablas tiene lock_timeout: si un alta está a mitad de
    camino, la conversión se niega en vez de colgarse (tarda 5 s en rendirse)."""
    antes = _volcado()
    with db.engine.connect() as ocupada:
        ocupada.execute(sa.text("UPDATE usuariosindicato SET nombre = nombre"))     # ROW EXCLUSIVE sin commit
        with pytest.raises(rc.ErrorRegularizacion, match="ocupada"):
            rc.aplicar(_planilla_basica(), si=True, quien="T", sin_backup=True, salida=lambda *_: None,
                       entorno_declarado="local")
        ocupada.rollback()
    assert _volcado() == antes


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not shutil.which("pg_dump") or not shutil.which("psql"),
                    reason="hace falta pg_dump y psql para probar el backup")
def test_aplicar_con_si_hace_el_backup_antes(base, tmp_path):
    try:
        res = _aplicar(_planilla_basica(), si=True, sin_backup=False, directorio_backup=tmp_path)
    except rc.ErrorRegularizacion as e:
        if "No se pudo preparar el backup" in str(e):
            pytest.skip(f"este equipo no tiene un pg_dump compatible: {e}")
        raise
    assert res.aplicado and res.backup.parent == tmp_path
    assert res.backup.name.startswith(f"backup_regularizacion_{rc._entorno_actual()}_")
    assert res.backup.stat().st_size > 0
    assert PERSONA_NUEVO in _apariciones()


def test_si_el_backup_falla_no_se_convierte_nada(base, tmp_path, monkeypatch):
    def sin_cliente(*a, **k):
        raise rc.pg_cliente.ErrorPg("no hay pg_dump")

    monkeypatch.setattr(rc.pg_cliente, "version_de_servidor", sin_cliente)
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion, match="backup"):
        _aplicar(_planilla_basica(), si=True, sin_backup=False, directorio_backup=tmp_path)
    assert _volcado() == antes


def test_la_url_para_el_cliente_pierde_el_prefijo_de_sqlalchemy():
    assert rc.url_para_cliente("postgresql+psycopg://u:p@h/db") == "postgresql://u:p@h/db"
    assert rc.url_para_cliente("postgres://u:p@h/db") == "postgres://u:p@h/db"


# ---------------------------------------------------------------------------
# Los generadores sintéticos (origen "lote")
# ---------------------------------------------------------------------------
def test_los_generadores_exponen_la_regla_que_ellos_mismos_usan():
    import cargar_lote_sindicato as cls
    import cargar_lote_uom
    import demo_encuestas
    import medir_dashboard
    from carga import preparar_datos
    lote = rc.identificadores_de_lote()
    # cargar_lote_sindicato: lo que arma contexto_lote para cualquier sindicato está en el conjunto
    for sid in (1, 2, 17, 39, 40, 41, 79, 123):
        for nombre in ("Sindicato AEFIP", "La Bancaria", "Unión Obrera Metalúrgica"):
            ctx = cls.contexto_lote(sid, nombre)
            assert len(ctx["cuils"]) == 100
            assert set(ctx["cuils"]) <= lote and set(ctx["cuits"]) <= lote, (sid, nombre)
    assert cargar_lote_uom.identificadores_sinteticos() == (set(cargar_lote_uom.CUILS),
                                                            set(cargar_lote_uom.CUITS_EMPRESA))
    assert set(cargar_lote_uom.CUILS) <= lote
    cuils, cuits = demo_encuestas.identificadores_sinteticos()
    assert len(cuils) == demo_encuestas.CANTIDAD and not cuits
    assert demo_encuestas.cuil_del_padron(0) in lote
    cuils, cuits = preparar_datos.identificadores_sinteticos()
    assert len(cuils) == preparar_datos.CANTIDAD and not cuits and preparar_datos._cuil(5) in lote
    cuils, cuits = medir_dashboard.identificadores_sinteticos()
    assert medir_dashboard.USUARIO_ADMIN in cuils and len(cuits) == len(medir_dashboard.EMPRESAS)
    assert len(cuils) == medir_dashboard.TRABAJADORES + 1
    assert LOTE in lote and PERSONA not in lote and EMPRESA not in lote and LECTURA not in lote


def test_los_generadores_siguen_generando_los_mismos_numeros():
    """Extraer la regla a una función no cambió ni un número: estos son los
    primeros de cada generador, tomados de ANTES de la extracción."""
    import cargar_lote_sindicato as cls
    import cargar_lote_uom
    import demo_encuestas
    import medir_dashboard
    from carga import preparar_datos
    ctx = cls.contexto_lote(1, "La Bancaria")
    assert ctx["cuils"][:3] == ["27660000000", "20660000017", "20660000024"]
    assert ctx["cuits"][:2] == ["30669000000", "30669000013"]
    assert cargar_lote_uom.CUILS[:3] == ["27600000000", "20600000017", "20600000024"]
    assert demo_encuestas.cuil_del_padron(1) == "20480000017"
    assert preparar_datos._cuil(1) == "20900000011"
    assert medir_dashboard.cuil_sintetico(7) == "20900000007"


def test_lote_no_se_convierte_aunque_este_invalido(base):
    """Una colección de números de lote en la base: todos 'lote', ninguno convertible."""
    import cargar_lote_uom
    with db.get_session() as s:
        for cuil in cargar_lote_uom.CUILS[:10]:
            db.guardar_datos_personales(s, cuil, nombre=f"Lote {cuil}")
            s.add(Trabajador(sindicato_id=base.a, cuil=cuil, activo=True))
        s.commit()
    f = _filas(_diagnostico())
    de_lote = [x for x in f.values() if x.origen == "lote"]
    assert len(de_lote) >= 5
    assert not any(x.convertir for x in de_lote)


# ---------------------------------------------------------------------------
# La lectura de la IA no se corrige; la identidad cargada a mano sí, con todas sus copias
# ---------------------------------------------------------------------------
def test_un_cuit_que_solo_leyo_la_ia_queda_como_esta(base):
    antes = _apariciones()[LECTURA]
    _aplicar(_planilla_basica(), si=True)
    assert _apariciones()[LECTURA] == antes


def test_si_la_persona_lo_fuerza_la_lectura_tambien_se_puede_convertir(base):
    """convertir=si en una fila 'lectura' es una decisión humana y se respeta
    (con todas las validaciones); la traza dice que su origen era 'lectura'."""
    _aplicar([_fila(LECTURA, LECTURA_NUEVO)], si=True)
    a = _apariciones()
    assert LECTURA not in a and a[LECTURA_NUEVO]["reciboverificado.cuit_empleador"] == 1
    with db.get_session() as s:
        assert s.exec(select(CambioIdentificador)).one().origen == "lectura"


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------
def test_cli_diagnostico_escribe_la_planilla_y_el_resumen(base, tmp_path, capsys):
    ruta = tmp_path / "salida.csv"
    assert rc.main(["diagnostico", "--salida", str(ruta)]) == 0
    out = capsys.readouterr().out
    assert "Inválidos por origen" in out and "manual" in out and "COLISION" in out and str(ruta) in out
    assert "cuentatrabajador.cuil" in out
    filas = rc.leer_planilla(ruta)
    assert {x["anterior"] for x in filas} >= {PERSONA, EMPRESA, COL_A, LOTE}


def test_cli_diagnostico_con_comas(base, tmp_path):
    ruta = tmp_path / "coma.csv"
    assert rc.main(["diagnostico", "--salida", str(ruta), "--separador", ","]) == 0
    assert ruta.read_text(encoding="utf-8-sig").splitlines()[0].startswith("anterior,nuevo,alternativa")
    assert PERSONA in {x["anterior"] for x in rc.leer_planilla(ruta)}


def test_cli_aplicar_sin_si_es_un_ensayo(base, tmp_path, capsys):
    ruta = tmp_path / "p.csv"
    rc.main(["diagnostico", "--salida", str(ruta)])
    capsys.readouterr()
    antes = _volcado()
    assert rc.main(["aplicar", "--planilla", str(ruta)]) == 0
    out = capsys.readouterr().out
    assert "ENSAYO" in out and "no se escribió nada" in out and "--si --quien" in out
    assert _volcado() == antes


def test_cli_aplicar_con_si_sin_quien_no_hace_nada(base, tmp_path, capsys):
    ruta = tmp_path / "p.csv"
    rc.main(["diagnostico", "--salida", str(ruta)])
    antes = _volcado()
    assert rc.main(["aplicar", "--planilla", str(ruta), "--si", "--sin-backup"]) == 2
    assert "--quien" in capsys.readouterr().out
    assert _volcado() == antes


def test_cli_aplicar_de_punta_a_punta_con_la_planilla_del_diagnostico(base, tmp_path, capsys):
    """El flujo real: diagnóstico -> la planilla tal cual sale -> aplicar --si.
    Convierte los manuales y los demo sin colisión; no toca lote, lectura,
    colisiones ni formas rotas."""
    ruta = tmp_path / "p.csv"
    rc.main(["diagnostico", "--salida", str(ruta)])
    capsys.readouterr()
    assert rc.main(["aplicar", "--planilla", str(ruta), "--si", "--quien", "SDN", "--sin-backup"]) == 0
    out = capsys.readouterr().out
    assert "CONVERSIÓN APLICADA" in out and "Tienen que enterarse" in out
    assert f"{PERSONA} -> {PERSONA_NUEVO}" in out and "Persona Manual" in out
    a = _apariciones()
    for viejo in (PERSONA, EMPRESA, DEMO_P, DEMO_E):
        assert viejo not in a
    for intacto in (COL_A, COL_B, LOTE, LECTURA, VALIDO_P, VALIDO_E):
        assert intacto in a
    # y la corrida siguiente ya no tiene nada convertible
    assert not [x for x in _diagnostico().filas if x.convertir]
    rc.main(["diagnostico", "--salida", str(tmp_path / "2.csv")])
    assert "se convierte" not in capsys.readouterr().out


def test_cli_aborta_con_codigo_1_y_dice_por_que(base, tmp_path, capsys):
    ruta = tmp_path / "mala.csv"
    ruta.write_text(f"anterior;nuevo;convertir\n{PERSONA};{VALIDO_P};si\n", encoding="utf-8-sig")
    antes = _volcado()
    assert rc.main(["aplicar", "--planilla", str(ruta), "--si", "--quien", "SDN", "--sin-backup",
                    "--entorno", "local"]) == 1
    out = capsys.readouterr().out
    assert "ABORTADO" in out and "no fusiona" in out
    assert _volcado() == antes


def test_la_herramienta_no_importa_los_scripts_que_cargan_la_demo():
    """cargar_demo.py y cargar_bancaria.py ejecutan la carga AL IMPORTARSE: borran y
    recrean sindicatos. Nadie los importa para leer una constante."""
    import ast
    from pathlib import Path
    arbol = ast.parse(Path(rc.__file__).read_text(encoding="utf-8"))
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module.split(".")[0])
    assert not importados & {"cargar_demo", "cargar_bancaria"}


# ===========================================================================
# Arreglos de la QA-1 (2026-10-10)
# ===========================================================================

# ---- 1. La planilla con campos de más --------------------------------------
def test_la_planilla_con_separadores_de_mas_vacios_se_lee(tmp_path):
    """Excel deja ';' de más al final de las filas: se ignoran si están vacíos."""
    ruta = tmp_path / "p.csv"
    ruta.write_text("anterior;nuevo;convertir\n27999999999;27999999994;si;;\n\n"
                    "30777777770;30777777773;si;\n", encoding="utf-8-sig")
    filas = rc.leer_planilla(ruta)
    assert [f["anterior"] for f in filas] == ["27999999999", "30777777770"]
    assert [f["_linea"] for f in filas] == [2, 4], "la línea es la del archivo, con la fila en blanco incluida"
    assert len(rc._cambios_de_la_planilla(filas)) == 2


def test_la_planilla_con_datos_de_mas_aborta_diciendo_la_linea(tmp_path):
    ruta = tmp_path / "p.csv"
    ruta.write_text("anterior;nuevo;convertir\n27999999999;27999999994;si\n"
                    "30777777770;30777777773;si;sobra\n", encoding="utf-8-sig")
    with pytest.raises(rc.ErrorRegularizacion) as e:
        rc.leer_planilla(ruta)
    assert "línea 3" in str(e.value) and "sobra" in str(e.value) and "No se aplicó nada" in str(e.value)


def test_un_error_de_una_fila_dice_la_linea_del_archivo(tmp_path):
    ruta = tmp_path / "p.csv"
    ruta.write_text("anterior;nuevo;convertir\n\n\n27999999999;27999999990;si\n", encoding="utf-8-sig")
    with pytest.raises(rc.ErrorRegularizacion) as e:
        rc.aplicar(ruta, si=False, salida=lambda *_: None)
    assert "línea 4" in " ".join(e.value.errores)


# ---- 2. Un número en una columna de otro tipo -------------------------------
def test_un_cuit_cargado_como_cuil_es_una_anomalia_y_no_se_convierte(base):
    anomalo = "30444555667"                                    # prefijo de empresa en una columna de persona
    assert not cuit.es_valido(anomalo)
    with db.get_session() as s:
        db.guardar_datos_personales(s, anomalo, nombre="Cargado Mal")
        s.add(Trabajador(sindicato_id=base.a, cuil=anomalo, activo=True))
        # Una persona física con CUIT de empleador en una columna "cualquiera": eso NO es una anomalía.
        s.add(Empleador(sindicato_id=base.a, cuit="20555666770", razon_social="Monotributista"))
        s.commit()
    diag = _diagnostico()
    f = _filas(diag)
    assert (f[anomalo].motivo, f[anomalo].convertir, f[anomalo].nuevo, f[anomalo].origen) == (
        "ANOMALIA", False, "", "manual")
    assert not f[anomalo].alternativa
    assert (f["20555666770"].motivo, f["20555666770"].convertir, f["20555666770"].nuevo) == (
        "", True, "20555666773")
    # el aviso dice la verdad: los inválidos NO se convierten
    texto = rc.resumen_texto(diag)
    assert "ANOMALIA" in texto and "NO se convierten" in texto
    assert ("cuentatrabajador.cuil", anomalo, "empresa", "persona") in diag.escaneo.anomalias
    # y si la persona fuerza el convertir=si con un nuevo válido, es decisión suya y se respeta
    _aplicar([_fila(anomalo, "30444555668")], si=True)
    assert "30444555668" in _apariciones() and anomalo not in _apariciones()


def test_un_numero_valido_en_una_columna_de_otro_tipo_no_sale_en_la_planilla(base):
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=base.a, cuil=VALIDO_E, activo=True))
        s.commit()
    diag = _diagnostico()
    assert VALIDO_E not in _filas(diag)
    assert "aparición(es)" in rc.resumen_texto(diag)


# ---- 3. El backup va DESPUÉS de las validaciones ----------------------------
@pytest.mark.parametrize("planilla, mensaje", [
    ([_fila("27888888888", "27888888883")], "no está en la base"),
    ([_fila(PERSONA, VALIDO_P)], "no fusiona"),
    ([_fila(PERSONA, "27999999990")], "no es un CUIL/CUIT válido"),
])
def test_un_abort_de_validacion_no_deja_ningun_dump(base, tmp_path, planilla, mensaje):
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar(planilla, si=True, sin_backup=False, directorio_backup=tmp_path / "backups")
    assert mensaje in " ".join([str(e.value), *e.value.errores])
    assert not (tmp_path / "backups").exists() or list((tmp_path / "backups").iterdir()) == []


def test_una_planilla_ya_aplicada_aborta_sin_dump(base, tmp_path):
    _aplicar(_planilla_basica(), si=True)
    with pytest.raises(rc.ErrorRegularizacion, match="La planilla no se puede aplicar") as e:
        _aplicar(_planilla_basica(), si=True, sin_backup=False, directorio_backup=tmp_path)
    assert "no está en la base" in " ".join(e.value.errores)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not shutil.which("pg_dump") or not shutil.which("psql"),
                    reason="hace falta pg_dump y psql para probar el backup")
def test_si_algo_falla_despues_del_backup_se_avisa_donde_quedo(base, tmp_path, monkeypatch):
    def explota(*a, **k):
        raise rc.ErrorRegularizacion("falla simulada dentro de la transacción")

    monkeypatch.setattr(rc, "_aplicar_en_transaccion", explota)
    lineas = []
    try:
        with pytest.raises(rc.ErrorRegularizacion, match="falla simulada"):
            rc.aplicar(_planilla_basica(), si=True, quien="T", sin_backup=False,
                       directorio_backup=tmp_path, salida=lineas.append, entorno_declarado="local")
    except rc.ErrorRegularizacion as e:       # pragma: no cover
        pytest.skip(f"este equipo no tiene un pg_dump compatible: {e}")
    dumps = list(tmp_path.glob("backup_regularizacion_*.dump"))
    if not dumps:                              # pragma: no cover
        pytest.skip("este equipo no tiene un pg_dump compatible")
    assert len(dumps) == 1
    texto = "\n".join(lineas)
    assert "La base no cambió" in texto and str(dumps[0]) in texto


@pytest.mark.skipif(not shutil.which("pg_dump") or not shutil.which("psql"),
                    reason="hace falta pg_dump y psql para probar el backup")
def test_cli_directorio_backup(base, tmp_path, capsys):
    ruta = tmp_path / "p.csv"
    ruta.write_text(f"anterior;nuevo;convertir\n{PERSONA};{PERSONA_NUEVO};si\n", encoding="utf-8-sig")
    destino = tmp_path / "copias" / "hoy"
    codigo = rc.main(["aplicar", "--planilla", str(ruta), "--si", "--quien", "SDN",
                      "--directorio-backup", str(destino), "--entorno", "local"])
    salida = capsys.readouterr().out
    if codigo == 1 and "No se pudo preparar el backup" in salida:
        pytest.skip("este equipo no tiene un pg_dump compatible")
    assert codigo == 0, salida
    assert len(list(destino.glob("backup_regularizacion_*.dump"))) == 1
    assert PERSONA_NUEVO in _apariciones()


# ---- 4. Contra qué base se va a escribir ------------------------------------
def test_aplicar_dice_contra_que_base_y_entorno_va_a_escribir(base, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "")
    lineas = []
    rc.aplicar(_planilla_basica(), si=False, salida=lineas.append)
    texto = "\n".join(lineas)
    assert lineas[0].startswith("Base: ") and db.engine.url.database in lineas[0]
    assert "postgres:" not in texto, "la contraseña no se imprime"
    assert "ENTORNO sin definir" in lineas[0]
    assert any("ENTORNO no está definida" in x and "'local'" in x for x in lineas)


def test_con_entorno_definido_no_hay_aviso_y_la_traza_lo_dice(base, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    lineas = []
    rc.aplicar(_planilla_basica(), si=True, quien="SDN", sin_backup=True, salida=lineas.append,
               entorno_declarado="pruebas")
    assert "Entorno: pruebas" in lineas[0] and not any("no está definida" in x for x in lineas)
    with db.get_session() as s:
        assert {x.entorno for x in s.exec(select(CambioIdentificador)).all()} == {"pruebas"}


def test_cli_diagnostico_tambien_avisa_la_base_y_el_entorno(base, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "")
    rc.main(["diagnostico", "--salida", str(tmp_path / "d.csv")])
    out = capsys.readouterr().out
    assert out.startswith("Base: ") and "ENTORNO sin definir" in out and "van a decir 'local'" in out


# ---- 5. Un concepto pendiente es una lectura ---------------------------------
def test_un_cuit_mal_leido_con_un_concepto_pendiente_sigue_siendo_lectura(base):
    leido = "30666666660"                                      # lo leyó la IA de un recibo
    assert not cuit.es_valido(leido)
    with db.get_session() as s:
        s.add(ReciboVerificado(sindicato_id=base.a, cuil=VALIDO_P, periodo="2026-07", estado="OK",
                               cuit_empleador=leido,
                               detalle={"recibo": {"empleador": {"cuit": leido}}}))
        s.add(Concepto(sindicato_id=base.a, codigo="Y9", nombre="Concepto nuevo", tipo="ingreso",
                       cuit_empleador=leido, pendiente_revision=True))     # lo creó /api/validar
        s.commit()
    f = _filas(_diagnostico())[leido]
    assert (f.origen, f.motivo, f.convertir) == ("lectura", "LECTURA", False)
    assert set(f.apariciones) == {"reciboverificado.cuit_empleador", "reciboverificado.detalle",
                                  "concepto.cuit_empleador[pendiente]"}


def test_con_un_concepto_confirmado_el_mismo_cuit_pasa_a_manual_y_se_convierte_entero(base):
    leido = "30666666660"
    with db.get_session() as s:
        s.add(ReciboVerificado(sindicato_id=base.a, cuil=VALIDO_P, periodo="2026-07", estado="OK",
                               cuit_empleador=leido,
                               detalle={"recibo": {"empleador": {"cuit": leido}}}))
        s.add(Concepto(sindicato_id=base.a, codigo="Y9", nombre="Pendiente", tipo="ingreso",
                       cuit_empleador=leido, pendiente_revision=True))
        s.add(Concepto(sindicato_id=base.a, codigo="Y8", nombre="Confirmado", tipo="ingreso",
                       cuit_empleador=leido, pendiente_revision=False))     # lo cargó una persona
        s.commit()
    f = _filas(_diagnostico())[leido]
    assert (f.origen, f.motivo, f.convertir, f.nuevo) == ("manual", "", True, "30666666662")
    previo = _apariciones()[leido]
    _aplicar([_fila(leido, "30666666662")], si=True)
    a = _apariciones()
    assert leido not in a and a["30666666662"] == previo, "los dos conceptos se convierten, cada uno en su entrada"
    with db.get_session() as s:
        assert {c.cuit_empleador for c in s.exec(select(Concepto).where(Concepto.codigo.in_(["Y8", "Y9"]))).all()} == {
            "30666666662"}


# ---- 6. Completar una conversión ya hecha ------------------------------------
def _huerfanos_de_la_ventana(base):
    """Lo que escribe un pedido que pasó el chequeo de sesión ANTES del COMMIT de
    la conversión y grabó DESPUÉS, con el número viejo."""
    with db.get_session() as s:
        s.add(ReciboVerificado(sindicato_id=base.a, cuil=PERSONA, periodo="2026-10", estado="OK",
                               detalle=_detalle_recibo("27-99999999-9", PERSONA, "30-77777777-0")))
        # Un recibo que menciona al viejo Y al nuevo en la MISMA fila (el JSON cuenta filas).
        s.add(ReciboVerificado(sindicato_id=base.a, cuil=PERSONA, periodo="2026-11", estado="OK",
                               detalle={"recibo": {"empleado": {"cuil": PERSONA}},
                                        "resultado": {"cuil": PERSONA_NUEVO}}))
        s.add(SuscripcionPush(cuil=PERSONA, endpoint="https://push.example/huerfano"))
        s.commit()


def test_los_huerfanos_de_la_ventana_se_completan(base):
    _aplicar(_planilla_basica(), si=True)
    previo = _apariciones()[PERSONA_NUEVO]
    _huerfanos_de_la_ventana(base)
    assert PERSONA in _apariciones()

    diag = _diagnostico()
    f = _filas(diag)[PERSONA]
    assert (f.motivo, f.convertir, f.nuevo) == ("RESTO", True, PERSONA_NUEVO)
    assert not f.alternativa
    assert "Persona Manual" in f.nombre, "el viejo ya no está en el padrón: el nombre sale del nuevo"
    assert rc.resumen_de_filas(diag.filas)["convertibles"] >= 1

    # la planilla tal cual sale del diagnóstico se aplica
    res = _aplicar([_fila(f.anterior, f.nuevo)], si=True)
    assert res.cambios[0].resto
    a = _apariciones()
    assert PERSONA not in a
    assert a[PERSONA_NUEVO]["suscripcionpush.cuil"] == previo["suscripcionpush.cuil"] + 1
    assert a[PERSONA_NUEVO]["reciboverificado.cuil"] == previo["reciboverificado.cuil"] + 2
    assert a[PERSONA_NUEVO]["reciboverificado.detalle"] == previo["reciboverificado.detalle"] + 2
    # y queda OTRA fila en la traza: la primera conversión y la que la completó
    with db.get_session() as s:
        filas = s.exec(select(CambioIdentificador).where(CambioIdentificador.anterior == PERSONA)
                       .order_by(CambioIdentificador.id)).all()
    assert len(filas) == 2 and {x.nuevo for x in filas} == {PERSONA_NUEVO}
    assert filas[1].detalle == {"reciboverificado.cuil": 2, "reciboverificado.detalle": 2,
                                "suscripcionpush.cuil": 1} and filas[1].filas == 5
    # y la corrida siguiente ya no la ve
    assert PERSONA not in _filas(_diagnostico())


def test_el_informe_marca_el_resto(base):
    _aplicar(_planilla_basica(), si=True)
    _huerfanos_de_la_ventana(base)
    lineas = []
    rc.aplicar([_fila(PERSONA, PERSONA_NUEVO)], si=True, quien="SDN", sin_backup=True, salida=lineas.append,
               entorno_declarado="local")
    assert any("completa una conversión anterior" in x and PERSONA in x for x in lineas)


def test_un_par_que_no_esta_en_la_traza_sigue_siendo_colision(base):
    viejo, nuevo = "27555444330", "27555444333"
    assert cuit.corregir(viejo) == nuevo
    with db.get_session() as s:
        for numero, nombre in ((viejo, "Persona Vieja"), (nuevo, "Persona Nueva")):
            db.guardar_datos_personales(s, numero, nombre=nombre)
            s.add(Trabajador(sindicato_id=base.a, cuil=numero, activo=True))
        s.commit()
    f = _filas(_diagnostico())[viejo]
    assert (f.motivo, f.convertir) == ("COLISION", False) and f.alternativa
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion, match="no se puede aplicar") as e:
        _aplicar([_fila(viejo, nuevo)], si=True)
    assert "no fusiona" in " ".join(e.value.errores)
    assert _volcado() == antes


def test_el_resto_solo_vale_para_el_par_exacto_de_la_traza(base):
    """La traza dice PERSONA -> PERSONA_NUEVO: ese nuevo existe y se acepta. Pero
    otro nuevo que también existe, no."""
    _aplicar(_planilla_basica(), si=True)
    _huerfanos_de_la_ventana(base)
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar([_fila(PERSONA, VALIDO_P)], si=True)
    assert "no fusiona" in " ".join(e.value.errores)
    assert _volcado() == antes


def test_con_dos_destinos_en_la_traza_no_se_adivina(base):
    """Si la traza registra dos nuevos distintos para el mismo viejo, el diagnóstico
    no elige: sale como una fila común (acá, COLISION)."""
    _aplicar(_planilla_basica(), si=True)
    _huerfanos_de_la_ventana(base)
    with db.get_session() as s:
        s.add(CambioIdentificador(anterior=PERSONA, nuevo=VALIDO_P, tipo="persona", origen="manual",
                                  entorno="local", fecha="2026-10-10 10:00", quien="X", filas=0, detalle={}))
        s.commit()
    f = _filas(_diagnostico())[PERSONA]
    assert (f.motivo, f.convertir) == ("COLISION", False)


def test_un_conflicto_de_unicidad_aborta_sin_escribir_nada(base):
    """cuentatrabajador.cuil es única: si después de la conversión aparece OTRA cuenta
    con el número viejo, son dos filas de la misma persona y hay que juntarlas a mano."""
    _aplicar(_planilla_basica(), si=True)
    with db.get_session() as s:
        s.add(CuentaTrabajador(cuil=PERSONA, nombre="Cuenta huérfana", clave_hash=HASH))
        s.commit()
    antes = _volcado()
    f = _filas(_diagnostico())[PERSONA]
    assert f.motivo == "RESTO"            # el diagnóstico lo propone; es aplicar el que se niega
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar([_fila(PERSONA, PERSONA_NUEVO)], si=True)
    texto = " ".join(e.value.errores)
    assert "cuentatrabajador.cuil" in texto and "columna única" in texto and "a mano" in texto
    assert _volcado() == antes


def test_las_columnas_unicas_se_leen_de_la_base(base):
    with db.engine.connect() as c:
        unicas = rc.columnas_unicas(c)
    assert {"cuentatrabajador.cuil", "cuentaempleador.cuit"} <= unicas
    assert "trabajador.cuil" not in unicas and "reciboverificado.cuil" not in unicas


def test_el_resto_de_una_empresa_tambien_se_completa(base):
    _aplicar(_planilla_basica(), si=True)
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=base.b, codigo="Z1", nombre="Huérfano", tipo="ingreso",
                       cuit_empleador=EMPRESA))
        s.add(TramiteEmpleador(sindicato_id=base.a, tipo_tramite_id=s.exec(select(TipoTramiteEmpleador)).first().id,
                               numero_expediente="E01-2026-000002", cuit=EMPRESA))
        s.commit()
    f = _filas(_diagnostico())[EMPRESA]
    assert (f.motivo, f.convertir, f.nuevo) == ("RESTO", True, EMPRESA_NUEVO)
    _aplicar([_fila(EMPRESA, EMPRESA_NUEVO)], si=True)
    a = _apariciones()
    assert EMPRESA not in a
    assert a[EMPRESA_NUEVO]["concepto.cuit_empleador[confirmado]"] == 2
    assert a[EMPRESA_NUEVO]["tramiteempleador.cuit"] == 2


# ---- 7. Lo que vale como "sí" -------------------------------------------------
@pytest.mark.parametrize("valor", ["si", "SI", "Sí", "sí", "s", "S", "x", "X", "1", "true", "TRUE",
                                   "Verdadero", "verdadero", " si "])
def test_convertir_acepta_estas_formas_de_decir_que_si(valor):
    cambios = rc._cambios_de_la_planilla([{"anterior": PERSONA, "nuevo": PERSONA_NUEVO, "convertir": valor}])
    assert len(cambios) == 1


@pytest.mark.parametrize("valor", ["no", "n", "0", "", "false", "talvez", "sii"])
def test_convertir_con_cualquier_otra_cosa_no_convierte(valor):
    assert rc._cambios_de_la_planilla([{"anterior": PERSONA, "nuevo": PERSONA_NUEVO, "convertir": valor}]) == []


def test_el_ensayo_dice_cuantas_filas_tomo(base):
    lineas = []
    planilla = [{"anterior": PERSONA, "nuevo": PERSONA_NUEVO, "convertir": "x"},
                {"anterior": EMPRESA, "nuevo": EMPRESA_NUEVO, "convertir": "1"},
                {"anterior": COL_A, "nuevo": "", "convertir": "no"}]
    rc.aplicar(planilla, si=False, salida=lineas.append)
    assert any("Planilla: 3 fila(s), 2 con convertir=si." in x for x in lineas)


def test_notacion_cientifica_en_nuevo_da_el_mismo_consejo_que_en_anterior():
    for campo, fila in (("anterior", {"anterior": "2,79999E+10", "nuevo": PERSONA_NUEVO}),
                        ("nuevo", {"anterior": PERSONA, "nuevo": "2,79999E+10"})):
        with pytest.raises(rc.ErrorRegularizacion) as e:
            rc._cambios_de_la_planilla([{**fila, "convertir": "si"}])
        texto = " ".join(e.value.errores)
        assert f"'{campo}' no tiene 11 dígitos" in texto and "notación científica" in texto


# ===========================================================================
# Revisión general (2026-10-10)
# ===========================================================================

# ---- 2. Renumerar un número válido pero equivocado (--permitir-validos) --------
def _libre_para(numero) -> str:
    """Un número válido, del mismo prefijo, que no está en ninguna parte de la base."""
    return cuit.siguiente_libre(numero, set(_apariciones()))


def test_sin_permitir_validos_el_error_dice_que_la_opcion_existe(base):
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar([_fila(VALIDO_P, _libre_para(VALIDO_P))], si=True)
    texto = " ".join(e.value.errores)
    assert "ya cumple el módulo 11" in texto and "--permitir-validos" in texto and "OTRA persona" in texto
    assert _volcado() == antes


def test_renumerar_una_persona_valida_con_permitir_validos(base):
    nuevo = _libre_para(VALIDO_P)
    assert cuit.es_valido(nuevo) and nuevo != VALIDO_P
    previo = _apariciones()[VALIDO_P]
    lineas = []
    res = _aplicar([_fila(VALIDO_P, nuevo)], si=True, permitir_validos=True, salida=lineas.append)
    assert res.aplicado and res.cambios[0].renumeracion
    a = _apariciones()
    assert VALIDO_P not in a and a[nuevo] == previo, "el nuevo queda exactamente donde estaba el viejo"
    with db.get_session() as s:
        fila = s.exec(select(CambioIdentificador)).one()
        assert (fila.anterior, fila.nuevo, fila.origen, fila.tipo) == (VALIDO_P, nuevo, "renumeracion", "persona")
        assert s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == nuevo)).one().nombre == "Persona Válida"
    texto = "\n".join(lineas)
    assert "renumeran un número que YA cumplía" in texto and "renumeración de un número válido" in texto
    # y entra con el número nuevo, con la misma clave
    c = TestClient(main.app)
    r = c.post("/trabajador/login", data={"cuil": nuevo, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/app/inicio"
    r = c.post("/trabajador/login", data={"cuil": VALIDO_P, "clave": CLAVE}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar?error=login"


def test_renumerar_una_empresa_valida_en_todas_sus_tablas(base):
    nuevo = _libre_para(VALIDO_E)
    previo = _apariciones()[VALIDO_E]
    assert "sindicato.cuit" in previo and "empleador.cuit" in previo
    _aplicar([_fila(VALIDO_E, nuevo)], si=True, permitir_validos=True)
    a = _apariciones()
    assert VALIDO_E not in a and a[nuevo] == previo
    with db.get_session() as s:
        assert s.get(Sindicato, base.b).cuit == nuevo
        assert s.exec(select(CambioIdentificador)).one().origen == "renumeracion"


def test_en_una_misma_planilla_el_invalido_conserva_su_origen_y_el_valido_es_renumeracion(base):
    nuevo = _libre_para(VALIDO_P)
    _aplicar(_planilla_basica(extra=[_fila(VALIDO_P, nuevo)]), si=True, permitir_validos=True)
    with db.get_session() as s:
        origenes = {x.anterior: x.origen for x in s.exec(select(CambioIdentificador)).all()}
    assert origenes == {PERSONA: "manual", EMPRESA: "manual", VALIDO_P: "renumeracion"}


@pytest.mark.parametrize("planilla, mensaje", [
    ([_fila(VALIDO_P, "20202790420")], "no es un CUIL/CUIT válido"),            # el verificador no cierra
    ([_fila(VALIDO_P, VALIDO_E)], "cambia de tipo"),                             # persona -> empresa
    ([_fila(VALIDO_E, VALIDO_P)], "cambia de tipo"),                             # empresa -> persona
    ([_fila(VALIDO_P, EN_UN_JSON)], "no fusiona"),                               # ya existe, solo adentro de un JSON
    ([_fila(VALIDO_P, VALIDO_P)], "no fusiona"),                                 # a sí mismo
    ([_fila(COL_NUEVO, cuit.siguiente_libre(COL_NUEVO))], "no está en la base"),  # el anterior no existe
    ([_fila(VALIDO_P, "")], "no tiene 'nuevo'"),
])
def test_renumerar_un_valido_tiene_las_mismas_garantias(base, planilla, mensaje):
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar(planilla, si=True, permitir_validos=True)
    assert mensaje in " ".join([str(e.value), *e.value.errores])
    assert _volcado() == antes


def test_renumerar_un_valido_no_pisa_a_otra_persona_que_ya_tiene_ese_numero(base):
    with db.get_session() as s:
        db.guardar_datos_personales(s, PERSONA_NUEVO, nombre="Otra Persona")      # la cuenta del número destino
        s.commit()
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        _aplicar([_fila(VALIDO_P, PERSONA_NUEVO)], si=True, permitir_validos=True)
    assert "no fusiona" in " ".join(e.value.errores)
    assert _volcado() == antes


def test_cli_permitir_validos(base, tmp_path, capsys):
    nuevo = _libre_para(VALIDO_P)
    ruta = tmp_path / "p.csv"
    ruta.write_text(f"anterior;nuevo;convertir;entorno\n{VALIDO_P};{nuevo};si;local\n", encoding="utf-8-sig")
    antes = _volcado()
    base_args = ["aplicar", "--planilla", str(ruta), "--si", "--quien", "SDN", "--sin-backup"]
    assert rc.main(base_args) == 1
    assert "--permitir-validos" in capsys.readouterr().out
    assert _volcado() == antes
    assert rc.main([*base_args, "--permitir-validos"]) == 0
    assert nuevo in _apariciones() and VALIDO_P not in _apariciones()


def test_el_ensayo_con_permitir_validos_no_escribe(base):
    antes = _volcado()
    lineas = []
    res = _aplicar([_fila(VALIDO_P, _libre_para(VALIDO_P))], si=False, permitir_validos=True,
                   salida=lineas.append)
    assert not res.aplicado and _volcado() == antes
    assert any("renumeran un número que YA cumplía" in x for x in lineas)


# ---- 3. El texto de las sesiones abiertas -------------------------------------
def test_el_informe_no_promete_que_las_sesiones_caducan_en_15_minutos(base):
    lineas = []
    _aplicar(_planilla_basica(), si=True, salida=lineas.append)
    texto = "\n".join(lineas)
    assert "como mucho" not in texto and "queda sin acceso" not in texto
    assert "se renueva con cada pedido" in texto and "SIN actividad" in texto
    assert "15 minutos" in texto and "RESTO" in texto and "`diagnostico`" in texto


# ---- 4. El entorno de la planilla ----------------------------------------------
def _escribir(tmp_path, entornos, cabecera="anterior;nuevo;convertir;entorno"):
    ruta = tmp_path / "p.csv"
    filas = [f"{PERSONA};{PERSONA_NUEVO};si;{entornos[0]}"]
    if len(entornos) > 1:
        filas.append(f"{EMPRESA};{EMPRESA_NUEVO};si;{entornos[1]}")
    ruta.write_text(cabecera + "\n" + "\n".join(filas) + "\n", encoding="utf-8-sig")
    return ruta


def test_el_diagnostico_escribe_el_entorno_en_cada_fila(base, tmp_path, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    ruta = tmp_path / "d.csv"
    assert rc.main(["diagnostico", "--salida", str(ruta)]) == 0
    filas = rc.leer_planilla(ruta)
    assert filas and {f["entorno"] for f in filas} == {"pruebas"}
    assert rc.COLUMNAS_PLANILLA[-1] == "entorno"


def test_una_planilla_del_mismo_entorno_se_aplica(base, tmp_path, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    res = rc.aplicar(_escribir(tmp_path, ["pruebas", "Pruebas"]), si=True, quien="SDN", sin_backup=True,
                     salida=lambda *_: None)
    assert res.aplicado and PERSONA_NUEVO in _apariciones()


@pytest.mark.parametrize("entornos", [["demo"], ["pruebas", "demo"], ["demo", "pruebas"], ["prod", "prod"]])
def test_con_si_una_planilla_de_otro_entorno_aborta_sin_escribir(base, tmp_path, monkeypatch, entornos):
    """Aunque UNA sola fila sea de otro entorno."""
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        rc.aplicar(_escribir(tmp_path, entornos), si=True, quien="SDN", sin_backup=False,
                   directorio_backup=tmp_path / "bk", salida=lambda *_: None)
    texto = " ".join([str(e.value), *e.value.errores])
    assert "no coincide" in str(e.value) and "'pruebas'" in texto and "no es de la que salió la planilla" in texto
    assert _volcado() == antes
    assert not (tmp_path / "bk").exists(), "ni siquiera hizo el backup"


def test_una_planilla_vieja_sin_la_columna_exige_entorno_explicito(base, tmp_path, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    ruta = tmp_path / "vieja.csv"
    ruta.write_text(f"anterior;nuevo;convertir\n{PERSONA};{PERSONA_NUEVO};si\n", encoding="utf-8-sig")
    antes = _volcado()
    with pytest.raises(rc.ErrorRegularizacion) as e:
        rc.aplicar(ruta, si=True, quien="SDN", sin_backup=True, salida=lambda *_: None)
    assert "no dice de qué entorno es" in " ".join(e.value.errores) and "--entorno pruebas" in " ".join(e.value.errores)
    assert _volcado() == antes
    # con el entorno explícito de OTRO entorno, tampoco
    with pytest.raises(rc.ErrorRegularizacion, match="no coincide") as e:
        rc.aplicar(ruta, si=True, quien="SDN", sin_backup=True, salida=lambda *_: None, entorno_declarado="demo")
    assert "Pasaste --entorno demo" in " ".join(e.value.errores)
    assert _volcado() == antes
    # con el actual, sí
    rc.aplicar(ruta, si=True, quien="SDN", sin_backup=True, salida=lambda *_: None, entorno_declarado="Pruebas")
    assert PERSONA_NUEVO in _apariciones()


def test_una_celda_de_entorno_vacia_cuenta_como_que_no_lo_dice(base, tmp_path, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    with pytest.raises(rc.ErrorRegularizacion) as e:
        rc.aplicar(_escribir(tmp_path, ["pruebas", ""]), si=True, quien="SDN", sin_backup=True,
                   salida=lambda *_: None)
    assert "no dice de qué entorno es" in " ".join(e.value.errores)


def test_el_ensayo_solo_avisa_si_el_entorno_no_coincide(base, tmp_path, monkeypatch):
    monkeypatch.setattr(rc.entorno, "ENTORNO", "pruebas")
    antes = _volcado()
    lineas = []
    res = rc.aplicar(_escribir(tmp_path, ["demo"]), si=False, salida=lineas.append)
    assert not res.aplicado and _volcado() == antes
    assert any(x.startswith("ATENCIÓN (con --si esto abortaría)") and "'demo'" in x for x in lineas)


def test_cli_entorno_explicito(base, tmp_path, capsys):
    ruta = tmp_path / "vieja.csv"
    ruta.write_text(f"anterior;nuevo;convertir\n{PERSONA};{PERSONA_NUEVO};si\n", encoding="utf-8-sig")
    comun = ["aplicar", "--planilla", str(ruta), "--si", "--quien", "SDN", "--sin-backup"]
    assert rc.main(comun) == 1 and "--entorno local" in capsys.readouterr().out
    assert rc.main([*comun, "--entorno", "demo"]) == 1
    capsys.readouterr()
    assert rc.main([*comun, "--entorno", "local"]) == 0


# ---- 5. Inyección de fórmulas en el CSV ----------------------------------------
@pytest.mark.parametrize("valor", ["=HYPERLINK(\"http://x\")", "+54 11 4444", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_una_celda_que_empieza_como_una_formula_se_escapa(valor):
    assert rc._celda_segura(valor) == "'" + valor


@pytest.mark.parametrize("valor", ["Juan Pérez", "20111111112", "", None, "a=b", "x-y", "'ya"])
def test_el_resto_de_las_celdas_queda_igual(valor):
    assert rc._celda_segura(valor) == ("" if valor is None else valor)


def test_la_planilla_escapa_los_nombres_y_los_valores_raros_y_se_lee_de_vuelta(base, tmp_path):
    maligno = "=cmd|' /C calc'!A0"
    with db.get_session() as s:
        db.guardar_datos_personales(s, "20161616160", nombre=maligno)                 # el nombre lo escribe el afiliado
        s.add(Trabajador(sindicato_id=base.a, cuil="20161616160", activo=True))
        s.add(Trabajador(sindicato_id=base.a, cuil="=1+1", activo=True))                # un valor roto sale tal cual de la base
        s.commit()
    diag = _diagnostico()
    ruta = rc.escribir_planilla(diag, tmp_path / "p.csv")
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        crudo = list(csv.DictReader(f, delimiter=";"))
    por_anterior = {x["anterior"]: x for x in crudo}
    assert por_anterior["20161616160"]["nombre"] == "'" + maligno
    assert "'=1+1" in por_anterior, "el valor roto que empieza con = también se escapa"
    for fila in crudo:
        for celda in fila.values():
            assert not celda.startswith(("=", "+", "-", "@", "\t", "\r")), (fila, celda)
    # al leer, el apóstrofo sale de anterior y nuevo
    leidas = {x["anterior"]: x for x in rc.leer_planilla(ruta)}
    assert "=1+1" in leidas and "'=1+1" not in leidas
    assert leidas["20161616160"]["nuevo"] == "20161616169"


def test_el_apostrofo_no_se_confunde_en_los_numeros_de_una_planilla_editada(tmp_path):
    ruta = tmp_path / "e.csv"
    ruta.write_text("anterior;nuevo;convertir\n'27999999999;'27999999994;si\n", encoding="utf-8-sig")
    (fila,) = rc.leer_planilla(ruta)
    assert (fila["anterior"], fila["nuevo"]) == ("27999999999", "27999999994")


# ---- 6. El backup ----------------------------------------------------------------
def test_el_backup_va_por_defecto_a_backups_que_el_gitignore_cubre():
    assert rc.BACKUPS == rc.RAIZ / "backups"
    assert "backups/" in [l.strip() for l in (rc.RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()]
    import inspect
    assert inspect.signature(rc.aplicar).parameters["directorio_backup"].default == rc.BACKUPS
    assert inspect.signature(rc.hacer_backup).parameters["directorio"].default == rc.BACKUPS


@pytest.mark.skipif(not shutil.which("pg_dump") or not shutil.which("psql"),
                    reason="hace falta pg_dump y psql para probar el backup")
def test_el_backup_tiene_permisos_0600_y_el_informe_dice_la_ruta_completa(base, tmp_path):
    import os
    import stat
    lineas = []
    try:
        res = _aplicar(_planilla_basica(), si=True, sin_backup=False, directorio_backup=tmp_path / "bk",
                       salida=lineas.append)
    except rc.ErrorRegularizacion as e:
        if "No se pudo preparar el backup" in str(e):
            pytest.skip(f"este equipo no tiene un pg_dump compatible: {e}")
        raise
    assert res.backup.is_absolute() and res.backup.parent == (tmp_path / "bk").resolve()
    if os.name != "nt":
        assert stat.S_IMODE(res.backup.stat().st_mode) == 0o600
    assert any(str(res.backup) in x for x in lineas), "el informe imprime la ruta completa"


@pytest.mark.skipif(not shutil.which("pg_dump") or not shutil.which("psql"),
                    reason="hace falta pg_dump y psql para probar el backup")
def test_la_cli_sin_directorio_backup_usa_el_default(base, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rc, "BACKUPS", tmp_path / "por_defecto")
    ruta = tmp_path / "p.csv"
    ruta.write_text(f"anterior;nuevo;convertir;entorno\n{PERSONA};{PERSONA_NUEVO};si;local\n", encoding="utf-8-sig")
    codigo = rc.main(["aplicar", "--planilla", str(ruta), "--si", "--quien", "SDN"])
    salida = capsys.readouterr().out
    if codigo == 1 and "No se pudo preparar el backup" in salida:
        pytest.skip("este equipo no tiene un pg_dump compatible")
    assert codigo == 0, salida
    assert len(list((tmp_path / "por_defecto").glob("backup_regularizacion_*.dump"))) == 1


# ---- 7. La nota de enviosindicato / reporte ---------------------------------------
def test_la_nota_de_envios_y_reportes_no_dice_que_el_cuil_esta_verificado():
    notas = {c.columna_db: c.nota for c in rc.INVENTARIO if c.columna_db in ("enviosindicato.cuil", "reporte.cuil")}
    assert set(notas) == {"enviosindicato.cuil", "reporte.cuil"}
    for nota in notas.values():
        assert "ya verificado" not in nota
        assert "H-0021" in nota and "payload" in nota
    assert all(c.fuente == rc.COPIA for c in rc.INVENTARIO if c.columna_db in notas)

"""XSII, catálogo y controles de Colm3na (xsii/proyectos/colm3na): el catálogo
valida y coincide con el código de la app, cada control calcula sobre la base
y el tablero de un sindicato es coherente y está aislado de los demás.

Correr con: python -m pytest test_xsii_colm3na.py -q
"""
import re
import inspect
import itertools

import pytest

import cuit
import db
import fechas
import main
import modulos
from db import (Area, Beneficio, Concepto, CuentaPanel, Formula, Noticia, PermisoArea,
                Seccional, Sindicato, TipoTramite, CampoTramite, Trabajador,
                UsuarioSindicato, ReciboVerificado, DocumentoConvenio, Convenio)
from xsii import informe
from xsii.motor import catalogo as motor_catalogo, consulta
from xsii.proyectos.colm3na import catalogo, controles, tablero

db.crear_tablas()

_contador = itertools.count(1)

# `donde` que apuntan a una zona de la app y no a una ruta registrada: ninguna
# hoy. Una excepción nueva se declara acá, con su motivo.
DONDE_EXCEPCIONES: dict = {}


def nuevo_sindicato(modulos_habilitados=None, **campos):
    """Un sindicato como lo deja el alta de plataforma: con sus aportes de ley."""
    n = next(_contador)
    campos.setdefault("cuit", cuit.corregir("30700000000"))
    with db.get_session() as s:
        sind = Sindicato(
            nombre=f"Sindicato XSII {n}", slug=f"xsii-{n}",
            modulos_habilitados=list(modulos.MODULOS_INICIALES if modulos_habilitados is None
                                     else modulos_habilitados), **campos)
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id
    db.crear_conceptos_universales(sid)
    return sid


def cuil_nuevo():
    """Un CUIL válido y distinto en cada llamada: las cuentas de personas son
    globales y compartirlas entre tests los acopla."""
    return cuit.corregir(f"2760{next(_contador):06d}0")


def el_tablero(sid, **kw):
    with db.get_session() as s:
        return tablero.armar(s, sid, **kw)


def estados_de(sid, **kw):
    _, tb = el_tablero(sid, **kw)
    return {c: e.estado for c, e in tb.items()}


def control(sid, codigo):
    _, tb = el_tablero(sid)
    return tb[codigo].control


# ---------------------------------------------------------------- catálogo

def test_el_catalogo_valida():
    assert motor_catalogo.validar(catalogo.TAREAS, catalogo.GRUPOS) == []
    assert len(catalogo.TAREAS) == 34


def test_todo_insumo_de_una_tarea_esta_en_el_catalogo_de_insumos():
    usados = {i for t in catalogo.TAREAS for i in t.insumos}
    assert usados == set(catalogo.INSUMOS)
    for clave, datos in catalogo.INSUMOS.items():
        assert datos["nombre"] and datos["descripcion"], clave


def test_todo_aplica_si_es_un_modulo_de_la_app():
    for t in catalogo.TAREAS:
        if t.aplica_si is not None:
            assert t.aplica_si in modulos.MODULOS, f"{t.codigo}: {t.aplica_si} no es un módulo"


def test_todo_donde_es_una_ruta_de_la_app():
    rutas = {getattr(r, "path", None) for r in main.app.routes}
    for t in catalogo.TAREAS:
        if t.donde is None:
            continue
        ruta = t.donde.split("#")[0].split("?")[0]
        assert ruta in rutas or ruta in DONDE_EXCEPCIONES, f"{t.codigo}: {t.donde} no es una ruta de la app"


def test_toda_tarea_tiene_su_control():
    for t in catalogo.TAREAS:
        fn = getattr(controles, t.control, None)
        assert callable(fn), f"{t.codigo}: no existe controles.{t.control}"
        assert list(inspect.signature(fn).parameters) == ["s", "sid"], t.codigo
    usados = {t.control for t in catalogo.TAREAS}
    assert len(usados) == len(catalogo.TAREAS)      # una función por tarea


def test_las_dependencias_con_modulo_no_aplican_con_el_modulo_apagado():
    sid = nuevo_sindicato()
    est = estados_de(sid)
    for codigo in ("TRA-01", "TRA-02", "PAD-04", "PAD-05", "COM-04", "COM-05", "COM-06", "REC-08"):
        assert est[codigo] == "no_aplica", codigo


# --------------------------------------------------------- sindicato nuevo

def test_un_sindicato_recien_creado_da_un_tablero_coherente():
    sid = nuevo_sindicato()
    tareas, tb = el_tablero(sid)
    est = {c: e.estado for c, e in tb.items()}
    hechas = {c for c, e in est.items() if e == "hecha"}
    assert {"BAS-01", "REC-02"} <= hechas
    # Lo demás que aplica no está hecho: no hay nada cargado.
    assert est["BAS-02"] == "lista"        # sin logo
    assert est["EST-01"] == "lista" or est["EST-01"] == "esperando"
    assert est["EST-02"] == "bloqueada" and tb["EST-02"].frenada_por == ["EST-01"]
    assert est["PAD-02"] == "bloqueada"
    assert est["REC-01"] == "esperando"    # espera los recibos de muestra
    assert est["REC-04"] == "bloqueada" and tb["REC-04"].frenada_por == ["REC-01"]
    for codigo in ("COM-02", "COM-03"):    # noticias y beneficios son iniciales: aplican y faltan
        assert est[codigo] == "lista"
    assert est["CIE-03"] == "bloqueada"
    # Cada tarea tiene un estado y un control calculado.
    assert set(est) == {t.codigo for t in tareas}
    assert all(e.control is not None for e in tb.values())
    # Y hay un siguiente paso para recomendar.
    assert consulta.recomendada(tareas, tb) is not None


def test_las_confirmaciones_puras_quedan_listas_hasta_que_alguien_confirma():
    sid = nuevo_sindicato()
    confirmaciones = {"BAS-03", "BAS-05", "COM-01", "REC-01", "PAD-01"}
    _, tb = el_tablero(sid, insumos={"recibos_muestra": True, "planilla_padron": True})
    for codigo in confirmaciones:
        e = tb[codigo]
        assert e.control.estado in ("completa", "observaciones"), codigo
        assert e.falta_confirmar and e.confirmacion, codigo
        # COM-01 espera además a BAS-02 (logo): ahí manda el bloqueo.
        assert e.estado == ("bloqueada" if codigo == "COM-01" else "lista"), codigo
    # Con la decisión `confirmada`, hechas.
    dec = {c: {"tipo": "confirmada", "quien": "ana", "cuando": "2026-11-26", "motivo": ""}
           for c in confirmaciones}
    _, tb = el_tablero(sid, decisiones=dec, insumos={"recibos_muestra": True, "planilla_padron": True})
    assert all(tb[c].estado == "hecha" for c in confirmaciones)


def test_lo_que_todavia_no_existe_sigue_incompleto_y_lo_dice():
    sid = nuevo_sindicato()
    for codigo in ("REC-07", "CIE-02"):
        c = control(sid, codigo)
        assert c.estado == "incompleta" and "todavía no existe" in c.faltan[0], codigo


def test_los_mixtos_llevan_confirmacion_y_sin_aviso_de_falta_confirmar():
    por_codigo = {t.codigo: t for t in catalogo.TAREAS}
    assert por_codigo["EST-01"].confirmacion and not por_codigo["EST-01"].solo_confirmacion
    assert por_codigo["PAD-02"].confirmacion and not por_codigo["PAD-02"].solo_confirmacion
    sid = nuevo_sindicato()
    with db.get_session() as s:
        s.add(Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True))
        s.commit()
    c = control(sid, "EST-01")
    assert c.estado == "completa" and not c.faltan
    _, tb = el_tablero(sid, insumos={"lista_seccionales": True})
    assert tb["EST-01"].estado == "en_curso" and tb["EST-01"].falta_confirmar
    assert tb["EST-02"].estado == "bloqueada"          # sin confirmar no destraba
    dec = {"EST-01": {"tipo": "confirmada", "quien": "ana", "cuando": "x", "motivo": ""}}
    _, tb = el_tablero(sid, decisiones=dec, insumos={"lista_seccionales": True})
    assert tb["EST-01"].estado == "hecha" and tb["EST-02"].estado == "lista"


def test_la_ficha_se_lee_una_vez_en_el_tablero_y_no_queda_en_la_sesion():
    sid = nuevo_sindicato()
    with db.get_session() as s:
        tablero.armar(s, sid)
        assert "xsii_sindicato" not in s.info


def test_bas_01_exige_cuit_valido():
    bueno = cuit.corregir("30123456780")
    malo = bueno[:-1] + str((int(bueno[-1]) + 1) % 10)       # verificador mal
    sid = nuevo_sindicato(cuit=malo)
    assert control(sid, "BAS-01").estado == "incompleta"
    sid = nuevo_sindicato(cuit="")
    assert "Falta el CUIT del sindicato" in control(sid, "BAS-01").faltan


# ------------------------------------------------------------------- Base

def test_bas_02_logo_y_prueba_de_lectura():
    # Los colores por defecto de un alta (acento #b23a2e) ya traen un aviso de
    # lectura sobre la base oscura: se parte de un acento que pasa la prueba.
    sid = nuevo_sindicato(color_acento="#c0392b")
    assert control(sid, "BAS-02").estado == "incompleta"
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        sind.logo_datos, sind.logo_mime, sind.logo = b"\x89PNG logo", "image/png", "logo.png"
        s.add(sind); s.commit()
    assert control(sid, "BAS-02").estado == "completa"
    with db.get_session() as s:       # una base clarísima: el texto blanco no se lee
        sind = s.get(Sindicato, sid)
        sind.color_base = "#ffffff"
        s.add(sind); s.commit()
    c = control(sid, "BAS-02")
    assert c.estado == "observaciones" and c.cifras["avisos_de_lectura"] >= 1


def test_bas_04_clave_propia():
    sid = nuevo_sindicato()
    cuil_ana = cuil_nuevo()
    assert control(sid, "BAS-04").estado == "incompleta"
    with db.get_session() as s:
        s.add(UsuarioSindicato(sindicato_id=sid, usuario=cuil_ana, nombre="Ana",
                               clave_hash="x" * 10, es_super_admin=True))
        s.commit()
    c = control(sid, "BAS-04")
    assert c.estado == "incompleta" and c.en_curso       # la clave inicial es transitoria
    with db.get_session() as s:
        cuenta = s.exec(db.select(CuentaPanel).where(CuentaPanel.cuil == cuil_ana)).first()
        cuenta.debe_cambiar_clave = False
        s.add(cuenta); s.commit()
    assert control(sid, "BAS-04").estado == "completa"


def test_bas_06_contrato_y_clausula():
    sid = nuevo_sindicato()
    assert control(sid, "BAS-06").estado == "incompleta"
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        sind.contrato_datos, sind.contrato_mime, sind.contrato_nombre = b"%PDF contrato", "application/pdf", "c.pdf"
        s.add(sind); s.commit()
    c = control(sid, "BAS-06")
    assert c.estado == "incompleta" and c.en_curso
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        sind.clausula_confidencialidad = True
        s.add(sind); s.commit()
    assert control(sid, "BAS-06").estado == "completa"


# ------------------------------------------------------------ Estructura

def test_seccionales_y_ubicacion():
    sid = nuevo_sindicato()
    assert control(sid, "EST-01").estado == "incompleta"
    with db.get_session() as s:
        s.add(Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True,
                        latitud=-34.6, longitud=-58.4, precision_geo="exacta"))
        s.add(Seccional(sindicato_id=sid, nombre="Rosario"))
        s.commit()
    c = control(sid, "EST-01")
    assert c.estado == "completa" and c.cifras["seccionales"] == 2
    c = control(sid, "EST-02")
    assert c.estado == "incompleta" and c.cifras["sin_ubicar"] == 1 and c.en_curso
    with db.get_session() as s:
        r = s.exec(db.select(Seccional).where(Seccional.sindicato_id == sid,
                                              Seccional.nombre == "Rosario")).one()
        r.latitud, r.longitud, r.precision_geo = -32.9, -60.7, "manual"
        s.add(r); s.commit()
    assert control(sid, "EST-02").estado == "completa"
    est = estados_de(sid, decisiones={"EST-01": {"tipo": "confirmada", "quien": "ana",
                                                 "cuando": "x", "motivo": ""}})
    assert est["EST-01"] == "hecha" and est["EST-02"] == "hecha"


def test_areas_con_permisos_y_usuarios():
    sid = nuevo_sindicato()
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True)
        s.add(sec); s.commit(); s.refresh(sec)
        a1 = Area(sindicato_id=sid, seccional_id=sec.id, nombre="Legales")
        a2 = Area(sindicato_id=sid, seccional_id=sec.id, nombre="Prensa")
        s.add(a1); s.add(a2); s.commit(); s.refresh(a1); s.refresh(a2)
        a1id, a2id, secid = a1.id, a2.id, sec.id
        s.add(PermisoArea(area_id=a1id, seccion="tramites")); s.commit()
    c = control(sid, "EST-03")
    assert c.estado == "incompleta" and c.cifras["sin_permisos"] == 1
    with db.get_session() as s:
        s.add(PermisoArea(area_id=a2id, seccion="noticias")); s.commit()
    assert control(sid, "EST-03").estado == "completa"
    # Usuarios: sin ningún formulario, se exige uno por cada área activa.
    c = control(sid, "EST-04")
    assert c.estado == "incompleta" and c.cifras["areas_sin_usuario"] == 2
    with db.get_session() as s:
        for cuil_, area in ((cuil_nuevo(), a1id), (cuil_nuevo(), a2id)):
            s.add(UsuarioSindicato(sindicato_id=sid, usuario=cuil_, nombre="U", seccional_id=secid,
                                   area_id=area, clave_hash="x" * 10))
        s.commit()
    c = control(sid, "EST-04")
    assert c.estado == "observaciones" and c.cifras["usuarios_con_clave_transitoria"] == 2


# ---------------------------------------------------------------- Recibos

def test_rec_02_aportes_de_ley_y_su_faltante():
    sid = nuevo_sindicato()
    assert control(sid, "REC-02").estado == "completa"
    with db.get_session() as s:
        f = s.exec(db.select(Formula).where(Formula.sindicato_id == sid, Formula.target == "PAMI")).one()
        s.delete(f); s.commit()
    c = control(sid, "REC-02")
    assert c.estado == "incompleta" and any("PAMI" in x for x in c.faltan)


def test_rec_03_a_rec_05_conceptos_y_reglas():
    sid = nuevo_sindicato()
    assert control(sid, "REC-03").estado == "incompleta"
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=sid, codigo="CUOTA", nombre="Cuota sindical", tipo="descuento",
                       categoria_sindical="afiliacion"))
        s.commit()
    c = control(sid, "REC-03")
    assert c.estado == "incompleta" and c.en_curso
    with db.get_session() as s:
        s.add(Formula(sindicato_id=sid, target="CUOTA", descripcion="2%", expr="0.02 * base_remunerativa"))
        s.commit()
    assert control(sid, "REC-03").estado == "completa"
    assert control(sid, "REC-05").estado == "completa"
    # Una regla que no evalúa, y dos con vigencias superpuestas.
    with db.get_session() as s:
        s.add(Formula(sindicato_id=sid, target="CUOTA", descripcion="rota", expr="0,02 * ???"))
        s.commit()
    c = control(sid, "REC-05")
    assert c.estado == "incompleta" and any("no evalúa" in x for x in c.faltan)
    assert any("Vigencias superpuestas" in x for x in c.faltan)
    with db.get_session() as s:
        for f in s.exec(db.select(Formula).where(Formula.sindicato_id == sid, Formula.target == "CUOTA")).all():
            if f.descripcion == "rota":
                s.delete(f)
        s.commit()
        # Solo vigencias superpuestas que se resuelven con una fecha de baja:
    with db.get_session() as s:
        s.add(Formula(sindicato_id=sid, target="CUOTA", descripcion="otra", expr="0.03 * base_remunerativa",
                      tolerancia=500))
        s.commit()
    assert control(sid, "REC-05").estado == "incompleta"       # dos sin fechas = se pisan
    with db.get_session() as s:
        f = s.exec(db.select(Formula).where(Formula.sindicato_id == sid, Formula.descripcion == "otra")).one()
        f.fecha_desde = "2030-01"
        s.add(f)
        g = s.exec(db.select(Formula).where(Formula.sindicato_id == sid, Formula.descripcion == "2%")).one()
        g.fecha_hasta = "2029-12"
        s.add(g); s.commit()
    c = control(sid, "REC-05")
    assert c.estado == "observaciones" and c.cifras["tolerancia_alta"] == 1


def test_rec_04_conceptos_pendientes():
    sid = nuevo_sindicato()
    assert control(sid, "REC-04").estado == "incompleta"
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=sid, codigo="A1", nombre="Básico", tipo="ingreso"))
        s.add(Concepto(sindicato_id=sid, codigo="A2", nombre="Raro", tipo="ingreso", pendiente_revision=True))
        s.commit()
    c = control(sid, "REC-04")
    assert c.estado == "incompleta" and c.en_curso and c.cifras["pendientes_de_revision"] == 1
    with db.get_session() as s:
        c2 = s.exec(db.select(Concepto).where(Concepto.sindicato_id == sid, Concepto.codigo == "A2")).one()
        c2.pendiente_revision = False
        s.add(c2); s.commit()
    assert control(sid, "REC-04").estado == "completa"


def test_rec_06_topes():
    sid = nuevo_sindicato()
    with db.get_session() as s:
        for t in s.exec(db.select(db.TopeBaseImponible)).all():
            s.delete(t)
        s.commit()
    assert control(sid, "REC-06").estado == "incompleta"
    with db.get_session() as s:
        s.add(db.TopeBaseImponible(vigencia_desde="2025-01", tope_maximo=1.0, base_minima=1.0,
                                   estado="por_verificar"))
        s.commit()
    assert control(sid, "REC-06").estado == "observaciones"
    with db.get_session() as s:
        t = s.exec(db.select(db.TopeBaseImponible)).first()
        t.estado = "verificado"
        s.add(t); s.commit()
    assert control(sid, "REC-06").estado == "completa"
    with db.get_session() as s:       # un recibo de un período anterior al primer tope
        s.add(ReciboVerificado(sindicato_id=sid, cuil="20111111120", periodo="2015-02"))
        s.commit()
    assert control(sid, "REC-06").estado == "incompleta"


def test_rec_08_requiere_convenio_y_grilla():
    sid = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["grilla_convenio"])
    assert control(sid, "REC-08").estado == "incompleta"
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        sind.convenio_grilla = "cct-18-75"
        s.add(sind); s.commit()
        publicadas = s.exec(db.select(db.GrillaSalarial).where(
            db.GrillaSalarial.convenio == "cct-18-75", db.GrillaSalarial.estado == "publicada")).all()
        if not publicadas:
            s.add(db.GrillaSalarial(convenio="cct-18-75", periodo="2026-08", estado="publicada"))
            s.commit()
    assert control(sid, "REC-08").estado == "completa"


# ----------------------------------------------------------------- Padrón

def test_padron_y_domicilios():
    sid = nuevo_sindicato()
    assert control(sid, "PAD-02").estado == "incompleta"
    c1, c2 = cuil_nuevo(), cuil_nuevo()
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True)
        s.add(sec); s.commit(); s.refresh(sec)
        for cuil_ in (c1, c2):
            db.guardar_datos_personales(s, cuil_, nombre="Afiliado " + cuil_, domicilio={
                "calle": "Mitre", "numero": "1", "localidad": "Rosario", "provincia": "Santa Fe"})
            s.add(Trabajador(sindicato_id=sid, cuil=cuil_,
                             seccional_id=sec.id if cuil_ == c1 else None))
        s.commit()
    c = control(sid, "PAD-02")
    assert c.estado == "observaciones" and c.cifras["afiliados_activos"] == 2 and c.cifras["sin_seccional"] == 1
    c = control(sid, "PAD-03")
    assert c.estado == "observaciones" and c.cifras["pendientes_de_ubicar"] == 2
    with db.get_session() as s:
        for cuil_ in (c1, c2):
            db.guardar_datos_personales(s, cuil_, domicilio={
                "calle": "Mitre", "numero": "1", "localidad": "Rosario", "provincia": "Santa Fe",
                "latitud": -32.9, "longitud": -60.7, "precision_geo": "exacta"})
        s.commit()
    assert control(sid, "PAD-03").estado == "completa"


def test_empleadores_y_cuit_de_conceptos():
    sid = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["empleadores"])
    assert control(sid, "PAD-04").estado == "incompleta"
    cuit_emp = cuit.corregir("30711111110")
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=sid, codigo="X", nombre="X", tipo="ingreso", cuit_empleador=cuit_emp))
        s.add(db.Empleador(sindicato_id=sid, cuit=cuit.corregir("30722222220"), razon_social="Otra SA"))
        s.commit()
    c = control(sid, "PAD-04")
    assert c.estado == "observaciones" and c.cifras["cuit_de_conceptos_sin_importar"] == 1


def test_listas_que_nombran_los_formularios():
    sid = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["tramites"])
    assert control(sid, "PAD-05").estado == "incompleta"
    with db.get_session() as s:
        tipo = TipoTramite(sindicato_id=sid, titulo="Kit", codigo="KIT", activo=True, borrador=False)
        s.add(tipo); s.commit(); s.refresh(tipo)
        s.add(CampoTramite(tipo_tramite_id=tipo.id, orden=1, etiqueta="Hijo", tipo_dato="texto",
                           validaciones=[{"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar"}]))
        s.commit()
    c = control(sid, "PAD-05")
    assert c.estado == "incompleta" and c.cifras["plantillas_sin_cargar"] == 1
    with db.get_session() as s:
        s.add(db.ListaSindicato(sindicato_id=sid, plantilla="grupo_familiar", nombre="Familia"))
        s.commit()
    assert control(sid, "PAD-05").estado == "completa"


# ------------------------------------------------------ Trámites y cierre

def test_formularios_y_tramite_de_prueba():
    sid = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["tramites"])
    assert control(sid, "TRA-01").estado == "incompleta"
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="Sede Central", ve_todas=True)
        s.add(sec); s.commit(); s.refresh(sec)
        area = Area(sindicato_id=sid, seccional_id=sec.id, nombre="Legales")
        s.add(area); s.commit(); s.refresh(area)
        borrador = TipoTramite(sindicato_id=sid, titulo="B", codigo="B1", activo=False, borrador=True)
        tipo = TipoTramite(sindicato_id=sid, titulo="Kit", codigo="KIT", activo=True,
                           area_destino_default_id=area.id)
        s.add(borrador); s.add(tipo); s.commit(); s.refresh(tipo)
        s.add(CampoTramite(tipo_tramite_id=tipo.id, orden=1, etiqueta="Hijo", tipo_dato="texto"))
        s.commit()
        tipo_id = tipo.id
    c = control(sid, "TRA-01")
    assert c.estado == "observaciones" and c.cifras["borradores"] == 1
    assert control(sid, "TRA-02").estado == "incompleta"
    with db.get_session() as s:
        s.add(db.Tramite(sindicato_id=sid, tipo_tramite_id=tipo_id, numero_expediente=f"KIT-{sid}-1",
                         cuil="20111111120", estado="iniciado"))
        s.commit()
    assert control(sid, "TRA-02").en_curso
    with db.get_session() as s:
        t = s.exec(db.select(db.Tramite).where(db.Tramite.sindicato_id == sid)).one()
        t.estado = "terminado"
        s.add(t); s.commit()
    assert control(sid, "TRA-02").estado == "completa"


def test_comunicacion_noticias_beneficios_notificaciones_convenio_encuestas():
    sid = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES)
                          + ["notificaciones", "convenio", "encuestas"])
    for codigo in ("COM-02", "COM-03", "COM-04", "COM-05", "COM-06"):
        assert control(sid, codigo).estado == "incompleta", codigo
    hoy = fechas.hoy_texto()
    with db.get_session() as s:
        s.add(Noticia(sindicato_id=sid, titulo="Hola", fecha_desde="2000-01-01", fecha_hasta="2000-01-02"))
        s.add(Beneficio(sindicato_id=sid, rubro="Salud", fecha_desde="2000-01-01", fecha_hasta="2000-01-02"))
        s.commit()
    assert control(sid, "COM-02").estado == "incompleta"      # vencida
    with db.get_session() as s:
        s.add(Noticia(sindicato_id=sid, titulo="Vigente", fecha_desde="2000-01-01", fecha_hasta="2999-12-31"))
        s.add(Beneficio(sindicato_id=sid, rubro="Salud", fecha_desde=hoy, fecha_hasta="2999-12-31"))
        s.add(db.Notificacion(sindicato_id=sid, texto="Bienvenidos", enviado_en="2026-11-01 10:00"))
        conv = Convenio(sindicato_id=sid, nombre="CCT")
        s.add(conv); s.commit(); s.refresh(conv)
        s.add(DocumentoConvenio(convenio_id=conv.id, sindicato_id=sid, estado="procesando"))
        s.commit()
    assert control(sid, "COM-02").estado == "completa" and control(sid, "COM-03").estado == "completa"
    assert control(sid, "COM-04").estado == "completa"
    assert control(sid, "COM-05").en_curso
    with db.get_session() as s:
        d = s.exec(db.select(DocumentoConvenio).where(DocumentoConvenio.sindicato_id == sid)).one()
        d.estado = "listo"
        s.add(d); s.commit()
    assert control(sid, "COM-05").estado == "completa"


def test_cie_01_cuenta_registrada_con_recibo_y_cie_03_aprobacion():
    sid = nuevo_sindicato()
    assert control(sid, "CIE-01").estado == "incompleta"
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=sid, cuil="20111111120", registrado=True))
        s.add(ReciboVerificado(sindicato_id=sid, cuil="20111111120", periodo="2026-10"))
        s.commit()
    assert control(sid, "CIE-01").estado == "completa"
    assert control(sid, "CIE-03").estado == "incompleta"
    with db.get_session() as s:
        p = db.ImplProyecto(nombre="Proyecto", sindicato_id=sid)
        s.add(p); s.commit(); s.refresh(p)
        s.add(db.ImplTarjeta(proyecto_id=p.id, numero=1, codigo="AP0001", tipo="aprobacion",
                             estado="aprobada", resuelta_en="2026-11-20 10:00",
                             resuelta_por_lado="sindicato"))
        s.commit()
    assert control(sid, "CIE-03").estado == "completa"


# ------------------------------------------------------ decisiones y aislamiento

def test_las_decisiones_llegan_al_tablero():
    sid = nuevo_sindicato()
    est = estados_de(sid, decisiones={"BAS-03": {"tipo": "completada_a_mano", "quien": "ana",
                                                 "cuando": "2026-11-26", "motivo": "ya hablado"}})
    assert est["BAS-03"] == "hecha"
    assert est["EST-03"] != "bloqueada" or est["EST-01"] != "hecha"      # BAS-03 ya no la frena
    _, tb = el_tablero(sid, decisiones={"BAS-03": {"tipo": "completada_a_mano", "motivo": "m"}})
    assert tb["BAS-03"].a_mano and tb["BAS-03"].control.estado == "completa"
    # El motivo del control sigue a la vista: la decisión reemplaza a la confirmación.
    assert tb["BAS-03"].confirmacion
    est = estados_de(sid, insumos={"lista_seccionales": True})
    assert est["EST-01"] == "lista"


def test_los_datos_de_otro_sindicato_no_cambian_el_tablero():
    a = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["tramites", "empleadores"])
    antes = estados_de(a)
    otro = nuevo_sindicato(modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["tramites", "empleadores"])
    with db.get_session() as s:
        sec = Seccional(sindicato_id=otro, nombre="Sede Central", ve_todas=True,
                        latitud=-34.6, longitud=-58.4, precision_geo="exacta")
        s.add(sec); s.commit(); s.refresh(sec)
        area = Area(sindicato_id=otro, seccional_id=sec.id, nombre="Legales")
        s.add(area); s.commit(); s.refresh(area)
        s.add(PermisoArea(area_id=area.id, seccion="tramites"))
        s.add(Concepto(sindicato_id=otro, codigo="Z", nombre="Z", tipo="ingreso", pendiente_revision=True,
                       cuit_empleador=cuit.corregir("30733333330")))
        s.add(Concepto(sindicato_id=otro, codigo="CUOTA", nombre="Cuota", tipo="descuento",
                       categoria_sindical="afiliacion"))
        s.add(Formula(sindicato_id=otro, target="CUOTA", descripcion="c", expr="0.02 * base_remunerativa"))
        s.add(Noticia(sindicato_id=otro, titulo="N", fecha_desde="2000-01-01", fecha_hasta="2999-12-31"))
        s.add(Trabajador(sindicato_id=otro, cuil="20111111120", registrado=True))
        s.add(db.Empleador(sindicato_id=otro, cuit=cuit.corregir("30733333330")))
        s.add(UsuarioSindicato(sindicato_id=otro, usuario="20555555556", nombre="U", es_super_admin=True,
                               clave_hash="x" * 10))
        s.commit()
    assert estados_de(a) == antes
    # El del otro, en cambio, sí se movió.
    assert estados_de(otro)["EST-01"] != antes["EST-01"] or estados_de(otro)["REC-03"] == "hecha"


# ---------------------------------------------------------------- informe

def test_el_informe_imprime_el_tablero(capsys):
    sid = nuevo_sindicato()
    with db.get_session() as s:
        nombre = s.get(Sindicato, sid).nombre
    assert informe.main([nombre]) == 0
    salida = capsys.readouterr().out
    assert "Avance:" in salida and "Siguiente paso recomendado" in salida
    assert "BAS-01" in salida and "CIE-03" in salida and "ESTRUCTURA" in salida.upper()
    assert informe.main([]) == 0
    assert nombre in capsys.readouterr().out
    assert informe.main(["no existe este sindicato"]) == 1


# ------------------------------------------------- mejoras de controles (C)

def test_pad_02_avisa_cuantos_afiliados_no_tienen_seccional():
    sid = nuevo_sindicato()
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="Central", ve_todas=True)
        s.add(sec); s.commit(); s.refresh(sec)
        for i in range(3):
            s.add(Trabajador(sindicato_id=sid, cuil=cuil_nuevo(), seccional_id=sec.id if i == 0 else None))
        s.commit()
    c = control(sid, "PAD-02")
    assert c.estado == "observaciones" and c.cifras["sin_seccional"] == 2
    assert any("2 afiliados sin seccional" in x for x in c.faltan)


def test_rec_05_avisa_los_descuentos_revisados_sin_regla_vigente():
    sid = nuevo_sindicato()
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=sid, codigo="CUOTA", nombre="Cuota", tipo="descuento",
                       categoria_sindical="afiliacion"))
        s.add(Concepto(sindicato_id=sid, codigo="SEGURO", nombre="Seguro", tipo="descuento"))
        s.add(Concepto(sindicato_id=sid, codigo="NUEVO", nombre="Nuevo", tipo="descuento",
                       pendiente_revision=True))          # pendiente: no cuenta acá
        s.add(Formula(sindicato_id=sid, target="CUOTA", descripcion="c", expr="0.02 * base_remunerativa"))
        s.commit()
    c = control(sid, "REC-05")
    assert c.estado == "observaciones" and c.cifras["descuentos_sin_regla"] == 1
    assert any("SEGURO" in x for x in c.faltan) and not any("NUEVO" in x for x in c.faltan)
    with db.get_session() as s:      # una regla ya vencida tampoco controla
        s.add(Formula(sindicato_id=sid, target="SEGURO", descripcion="v", expr="0.01 * base_remunerativa",
                      fecha_hasta="2020-01"))
        s.commit()
    assert control(sid, "REC-05").cifras["descuentos_sin_regla"] == 1
    with db.get_session() as s:
        s.add(Formula(sindicato_id=sid, target="SEGURO", descripcion="n", expr="0.01 * base_remunerativa",
                      fecha_desde="2020-02"))
        s.commit()
    assert control(sid, "REC-05").estado == "completa"


def test_bas_04_un_super_admin_sin_cuenta_cuenta_como_pendiente():
    sid = nuevo_sindicato()
    with db.get_session() as s:
        # Un login que no es un CUIL no tiene CuentaPanel.
        s.add(UsuarioSindicato(sindicato_id=sid, usuario="admin-raro", nombre="R", es_super_admin=True))
        s.commit()
    c = control(sid, "BAS-04")
    assert c.estado == "incompleta" and c.cifras["super_admins_activos"] == 1
    assert c.cifras["con_clave_propia"] == 0 and c.cifras["pendientes_de_clave"] == 1


def test_el_tablero_ignora_modulos_habilitados_raros():
    sid = nuevo_sindicato(modulos_habilitados=[{"a": 1}, 3, "tramites", "no_existe"])
    est = estados_de(sid)
    assert est["TRA-01"] != "no_aplica" and est["COM-05"] == "no_aplica"


def test_informe_distingue_modulo_apagado_de_declarada_no_aplica_y_muestra_pospuesta():
    sid = nuevo_sindicato()
    tareas, tb = el_tablero(sid, decisiones={
        "COM-02": {"tipo": "no_aplica", "quien": "ana", "cuando": "x", "motivo": "no usan noticias"},
        "BAS-02": {"tipo": "pospuesta", "quien": "ana", "cuando": "x", "motivo": ""}})
    texto = informe.texto("X", tareas, tb)
    linea = {t.codigo: informe._linea(t, tb[t.codigo]) for t in tareas}
    assert "declarada no aplica por ana: no usan noticias" in linea["COM-02"]
    assert "módulo tramites apagado" in linea["TRA-01"]
    assert "(pospuesta)" in linea["BAS-02"] and "BAS-02" in texto


# ------------------------------------------------------------ guía clara

def _textos_de_guia():
    for t in catalogo.TAREAS:
        yield t.codigo, t.para_que
        for x in t.pasos:
            yield t.codigo, x
    for k, d in catalogo.INSUMOS.items():
        yield k, d["formato"]


def test_toda_tarea_dice_para_que_sirve_y_sus_pasos():
    for t in catalogo.TAREAS:
        assert t.para_que and len(t.para_que) <= 160, t.codigo
        assert 2 <= len(t.pasos) <= 5, t.codigo
        for x in t.pasos:
            assert isinstance(x, str) and x and len(x) <= 150, (t.codigo, x)


def test_toda_tarea_con_insumo_empieza_por_conseguirlo():
    for t in catalogo.TAREAS:
        if t.insumos:
            assert "Pedile" in t.pasos[0], t.codigo


def test_todo_insumo_dice_si_es_archivo_o_dato_y_que_formato():
    for clave, d in catalogo.INSUMOS.items():
        assert d["tipo"] in ("archivo", "dato"), clave
        assert d["formato"] and len(d["formato"]) <= 120, clave


def test_los_textos_de_la_guia_no_tienen_jerga_tecnica():
    import db
    tablas = [c.__name__ for c in vars(db).values()
              if isinstance(c, type) and getattr(c, "__table__", None) is not None and re.search(r'[a-z][A-Z]', c.__name__)]
    for codigo, texto in _textos_de_guia():
        assert "/admin" not in texto and "/plataforma" not in texto and "/entornos" not in texto, (codigo, texto)
        assert "—" not in texto and "–" not in texto, (codigo, texto)
        for nombre in tablas:
            assert not re.search(r"\b" + nombre + r"\b", texto), (codigo, nombre)

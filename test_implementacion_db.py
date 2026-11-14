"""Mesa de implementación: acceso a datos y resguardos de I3.

Correr con: python -m pytest test_implementacion_db.py -q
"""
import ast
import fnmatch
import pathlib
import threading

import pytest
from sqlmodel import SQLModel, select

import db
import implementacion as im
from implementacion import Actor, ErrorImpl

db.crear_tablas()

EQ = Actor("equipo", 1, "Ana (Colm3na)")
EQ2 = Actor("equipo", 2, "Beto (Colm3na)")
SI = Actor("sindicato", 10, "Carla (Sindicato)")
SI2 = Actor("sindicato", 11, "Dante (Sindicato)")
RAIZ = pathlib.Path(__file__).resolve().parent


@pytest.fixture
def proy():
    with db.get_session() as s:
        p = db.impl_crear_proyecto(s, "Proyecto de prueba", EQ)
        yield p.id


def _tarjeta(proyecto_id, actor=EQ, tipo="pedido", titulo="Padrón", texto="Mandanos el padrón", **kw):
    with db.get_session() as s:
        return db.impl_crear_tarjeta(s, proyecto_id, actor, tipo, titulo, texto, **kw).id


def _eventos(proyecto_id, tarjeta_id=None, lado="equipo"):
    with db.get_session() as s:
        return db.impl_eventos(s, proyecto_id, lado, tarjeta_id)


# ---------- Proyecto ----------
def test_proyecto_nace_con_sus_seis_etapas():
    with db.get_session() as s:
        p = db.impl_crear_proyecto(s, "La Bancaria", EQ, sindicato_id=None)
        et = db.impl_etapas(s, p.id)
        assert p.sindicato_id is None
        assert [e.nombre for e in et] == [n for n, _ in im.FASES_POR_DEFECTO]
        assert [e.orden for e in et] == [1, 2, 3, 4, 5, 6]
        assert db.impl_eventos(s, p.id, "equipo")[0].accion == "crear_proyecto"
        with pytest.raises(ErrorImpl):
            db.impl_crear_proyecto(s, "  ", EQ)


# ---------- Tarjetas ----------
def test_numero_correlativo_por_proyecto():
    with db.get_session() as s:
        a = db.impl_crear_proyecto(s, "A", EQ).id
        b = db.impl_crear_proyecto(s, "B", EQ).id
    n_a = [_tarjeta(a) for _ in range(3)]
    n_b = _tarjeta(b)
    with db.get_session() as s:
        assert [db.impl_tarjeta(s, a, i).numero for i in n_a] == [1, 2, 3]
        assert db.impl_tarjeta(s, b, n_b).numero == 1


def test_numero_correlativo_con_hilos_en_paralelo(proy):
    errores = []

    def crear():
        try:
            for _ in range(3):
                _tarjeta(proy)
        except Exception as e:   # pragma: no cover
            errores.append(e)
    hilos = [threading.Thread(target=crear) for _ in range(4)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert not errores
    with db.get_session() as s:
        numeros = sorted(t.numero for t in db.impl_listar_tarjetas(s, proy, "equipo"))
    assert numeros == list(range(1, 13))


def test_tarjeta_nueva_espera_al_otro_lado_y_deja_evento(proy):
    tid = _tarjeta(proy, actor=EQ)
    with db.get_session() as s:
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.lado_que_espera, t.autor_lado) == ("abierta", "sindicato", "equipo")
        h = db.impl_hilo(s, proy, tid, "sindicato")
        assert [m.texto for m in h["mensajes"]] == ["Mandanos el padrón"]
        assert [e.accion for e in h["eventos"]] == ["crear"]
    sid = _tarjeta(proy, actor=SI, tipo="error", titulo="Falla", texto="No anda")
    with db.get_session() as s:
        assert db.impl_tarjeta(s, proy, sid).lado_que_espera == "equipo"


def test_aviso_nace_cerrado_sin_dueno_y_registra_lectura(proy):
    tid = _tarjeta(proy, tipo="aviso", titulo="Feriado", texto="No hay reunión")
    with db.get_session() as s:
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.lado_que_espera) == ("cerrada", "")
        with pytest.raises(ErrorImpl):
            db.impl_responder(s, proy, tid, SI, "hola")
        l1 = db.impl_marcar_leido_aviso(s, proy, tid, SI)
        l2 = db.impl_marcar_leido_aviso(s, proy, tid, SI)
        assert l1.id == l2.id                                  # una vez por persona
        db.impl_marcar_leido_aviso(s, proy, tid, SI2)
        assert [l.nombre for l in db.impl_lecturas_aviso(s, proy, tid)] == [SI.nombre, SI2.nombre]
    pid = _tarjeta(proy)
    with db.get_session() as s, pytest.raises(ErrorImpl):
        db.impl_marcar_leido_aviso(s, proy, pid, SI)


def test_tarjeta_invalida_no_se_crea(proy):
    with db.get_session() as s:
        with pytest.raises(ErrorImpl):
            db.impl_crear_tarjeta(s, proy, EQ, "pedido", "", "texto")
        with pytest.raises(ErrorImpl):
            db.impl_crear_tarjeta(s, proy, EQ, "nada", "t", "texto")
        assert db.impl_crear_tarjeta(s, 99999999, EQ, "pedido", "t", "texto") is None


def test_responder_y_cambiar_estado_es_un_solo_acto(proy):
    tid = _tarjeta(proy, actor=EQ)
    with db.get_session() as s:
        m = db.impl_responder(s, proy, tid, SI, "Ya lo mandamos", estado_nuevo="respondida")
        t = db.impl_tarjeta(s, proy, tid)
        assert m.id and t.estado == "respondida" and t.lado_que_espera == "equipo"
    acciones = [e.accion for e in _eventos(proy, tid)]
    assert acciones.count("responder") == 1                    # un acto, un evento
    ev = [e for e in _eventos(proy, tid) if e.accion == "responder"][0]
    assert ev.detalle["estado_anterior"] == "abierta" and ev.detalle["estado_nuevo"] == "respondida"
    with db.get_session() as s:
        db.impl_responder(s, proy, tid, EQ, "Recibido", estado_nuevo="cerrada")
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.lado_que_espera) == ("cerrada", "")
        with pytest.raises(ErrorImpl) as e:
            db.impl_responder(s, proy, tid, SI, "una más")
        assert e.value.codigo == "cerrada"
        db.impl_responder(s, proy, tid, SI, "Faltó una hoja", estado_nuevo="abierta")   # reabrir
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.lado_que_espera) == ("abierta", "equipo")


def test_transicion_invalida_y_acto_vacio(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        with pytest.raises(ErrorImpl):
            db.impl_responder(s, proy, tid, SI, "x", estado_nuevo="aprobada")
        with pytest.raises(ErrorImpl):
            db.impl_responder(s, proy, tid, SI, "", None)
        # solo cambia el estado, sin texto: vale
        m = db.impl_responder(s, proy, tid, EQ, "", "en_curso")
        assert m.id is None
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.lado_que_espera) == ("en_curso", "equipo")


# ---------- Aislamiento entre proyectos ----------
def test_un_id_de_otro_proyecto_devuelve_none():
    with db.get_session() as s:
        a = db.impl_crear_proyecto(s, "Aislado A", EQ).id
        b = db.impl_crear_proyecto(s, "Aislado B", EQ).id
    tid = _tarjeta(a)
    with db.get_session() as s:
        arch = db.impl_subir_archivo(s, a, tid, EQ, "x.pdf", "application/pdf", b"%PDF")
        hito = db.impl_agregar_hito(s, a, db.impl_etapas(s, a)[0].id, "Hito", EQ)
        assert db.impl_tarjeta(s, b, tid) is None
        assert db.impl_hilo(s, b, tid, "equipo") is None
        assert db.impl_responder(s, b, tid, EQ, "intruso") is None
        assert db.impl_reasignar(s, b, tid, EQ, "x", "equipo") is None
        assert db.impl_resolver_aprobacion(s, b, tid, SI, True) is None
        assert db.impl_subir_archivo(s, b, tid, EQ, "y.pdf", "application/pdf", b"1") is None
        assert db.impl_archivo(s, b, arch.id) is None
        assert db.impl_bajar_archivo(s, b, arch.id, EQ) is None
        assert db.impl_borrar_archivo(s, b, arch.id, EQ) is None
        assert db.impl_tildar_hito(s, b, hito.id, EQ) is None
        assert db.impl_agregar_hito(s, b, db.impl_etapas(s, a)[0].id, "ajeno", EQ) is None
        assert db.impl_listar_tarjetas(s, b, "equipo") == []
        assert db.impl_carpetas(s, b, EQ, "salida") == []
        assert db.impl_aprobaciones(s, b) == []
        # y la tarjeta ajena no se puede colgar de la etapa de otro proyecto
        with pytest.raises(ErrorImpl):
            db.impl_crear_tarjeta(s, b, EQ, "pedido", "t", "x", etapa_id=db.impl_etapas(s, a)[0].id)
        assert db.impl_tarjeta(s, a, tid).estado == "abierta"          # nadie la tocó


# ---------- Notas internas ----------
def test_la_nota_interna_no_sale_para_el_sindicato(proy):
    tid = _tarjeta(proy, actor=SI, tipo="consulta", titulo="Duda", texto="¿Cómo va?")
    with db.get_session() as s:
        nota = db.impl_responder(s, proy, tid, EQ, "El sindicato está apurado, ojo", solo_equipo=True)
        pub = db.impl_responder(s, proy, tid, EQ, "Lo vemos esta semana", estado_nuevo="respondida")
        arch = db.impl_subir_archivo(s, proy, tid, EQ, "interno.pdf", "application/pdf", b"%PDF",
                                     mensaje_id=nota.id)
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.lado_que_espera) == ("respondida", "sindicato")   # la nota no movió nada

        h_si = db.impl_hilo(s, proy, tid, "sindicato")
        textos = [m.texto for m in h_si["mensajes"]]
        assert "El sindicato está apurado, ojo" not in textos and "Lo vemos esta semana" in textos
        assert all(not m.solo_equipo for m in h_si["mensajes"])
        assert arch.id not in [a.id for a in h_si["archivos"]]
        assert all(not e.solo_equipo for e in h_si["eventos"])
        h_eq = db.impl_hilo(s, proy, tid, "equipo")
        assert "El sindicato está apurado, ojo" in [m.texto for m in h_eq["mensajes"]]
        assert arch.id in [a.id for a in h_eq["archivos"]]
        # ni el archivo de la nota ni su descarga existen para el sindicato
        assert db.impl_bajar_archivo(s, proy, arch.id, SI) is None
        assert db.impl_borrar_archivo(s, proy, arch.id, SI) is None
        assert arch.id not in [f["archivo_id"] for f in db.impl_carpetas(s, proy, SI, "salida")]
        assert arch.id in [f["archivo_id"] for f in db.impl_carpetas(s, proy, EQ, "salida")]
        assert all(not e.solo_equipo for e in db.impl_eventos(s, proy, "sindicato", tid))


def test_reglas_de_la_nota_interna(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        with pytest.raises(ErrorImpl) as e:
            db.impl_responder(s, proy, tid, SI, "nota", solo_equipo=True)
        assert e.value.codigo == "sin_permiso"
        with pytest.raises(ErrorImpl):
            db.impl_responder(s, proy, tid, EQ, "nota", estado_nuevo="cerrada", solo_equipo=True)


# ---------- Aprobaciones ----------
def test_aprobacion_inmutable(proy):
    tid = _tarjeta(proy, actor=EQ, tipo="aprobacion", titulo="Plan", texto="¿Aprueban el plan?")
    with db.get_session() as s:
        with pytest.raises(ErrorImpl) as e:
            db.impl_resolver_aprobacion(s, proy, tid, EQ, True)         # quien la pidió no se la aprueba
        assert e.value.codigo == "sin_permiso"
        t = db.impl_resolver_aprobacion(s, proy, tid, SI, True, "De acuerdo")
        assert t.estado == "aprobada" and t.resuelta_por_nombre == SI.nombre and t.resuelta_en
        assert t.lado_que_espera == ""
        for accion in (lambda: db.impl_resolver_aprobacion(s, proy, tid, SI, False),
                       lambda: db.impl_responder(s, proy, tid, EQ, "cambio de idea", estado_nuevo="abierta"),
                       lambda: db.impl_responder(s, proy, tid, EQ, "comentario"),
                       lambda: db.impl_reasignar(s, proy, tid, EQ, "x", "equipo"),
                       lambda: db.impl_subir_archivo(s, proy, tid, EQ, "a.pdf", "application/pdf", b"1")):
            with pytest.raises(ErrorImpl) as e:
                accion()
            assert e.value.codigo == "inmutable"
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.estado, t.resuelta_por_nombre) == ("aprobada", SI.nombre)
        reg = db.impl_aprobaciones(s, proy)
        assert [(r["numero"], r["estado"], r["resuelta_por"]) for r in reg] == [(1, "aprobada", SI.nombre)]
    assert [e.accion for e in _eventos(proy, tid)].count("resolver") == 1


def test_rechazo_y_registro_con_pendientes(proy):
    t1 = _tarjeta(proy, actor=SI, tipo="aprobacion", titulo="A", texto="a")
    _tarjeta(proy, actor=SI, tipo="aprobacion", titulo="B", texto="b")
    _tarjeta(proy)                                                       # no es aprobación
    with db.get_session() as s:
        db.impl_resolver_aprobacion(s, proy, t1, EQ, False, "Falta el anexo")
        reg = db.impl_aprobaciones(s, proy)
        assert [(r["titulo"], r["estado"]) for r in reg] == [("A", "rechazada"), ("B", "abierta")]
        with pytest.raises(ErrorImpl):
            db.impl_resolver_aprobacion(s, proy, _tarjeta(proy), SI, True)   # no es aprobación


# ---------- Archivos ----------
def test_archivo_con_datos_personales(proy):
    tid = _tarjeta(proy, actor=EQ, tipo="entrega", titulo="Padrón", texto="Subí el padrón")
    with db.get_session() as s:
        a = db.impl_subir_archivo(s, proy, tid, SI, "../padron.xlsx", "application/vnd.ms-excel",
                                  b"CUIL;NOMBRE", datos_personales=True)
        assert a.nombre == "padron.xlsx" and a.tamano == 11 and a.datos_personales
        # sin bytes al traer metadatos
        meta = db.impl_archivo(s, proy, a.id)
        assert "datos" in meta.__dict__.get("_sa_instance_state").unloaded
        # quien lo subió y el equipo lo bajan; otro del sindicato, no
        meta, datos = db.impl_bajar_archivo(s, proy, a.id, SI)
        assert datos == b"CUIL;NOMBRE"
        assert db.impl_bajar_archivo(s, proy, a.id, EQ2)[1] == b"CUIL;NOMBRE"
        with pytest.raises(ErrorImpl) as e:
            db.impl_bajar_archivo(s, proy, a.id, SI2)
        assert e.value.codigo == "sin_permiso"
        assert [(d.lado, d.usuario_id) for d in db.impl_descargas(s, proy, a.id)] == [("sindicato", 10), ("equipo", 2)]
        # la carpeta lo lista a todos pero marca quién puede bajarlo
        fila = db.impl_carpetas(s, proy, SI2, "entrada")[0]
        assert fila["archivo_id"] == a.id and fila["puede_bajar"] is False
        assert db.impl_carpetas(s, proy, SI, "entrada")[0]["puede_bajar"] is True
        assert db.impl_carpetas(s, proy, EQ, "salida") == []
    acciones = [e.accion for e in _eventos(proy, tid)]
    assert acciones.count("subir") == 1 and acciones.count("bajar") == 2    # el rechazado no cuenta


def test_archivo_sin_datos_personales_lo_baja_cualquiera(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        a = db.impl_subir_archivo(s, proy, tid, EQ, "guia.pdf", "application/pdf", b"%PDF-1")
        assert db.impl_bajar_archivo(s, proy, a.id, SI2)[1] == b"%PDF-1"


def test_tope_y_validacion_de_archivo(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        for datos in (b"", b"x" * (im.TOPE_ARCHIVO + 1)):
            with pytest.raises(ErrorImpl) as e:
                db.impl_subir_archivo(s, proy, tid, EQ, "a.bin", "x/y", datos)
            assert e.value.codigo == "archivo"
        ok = db.impl_subir_archivo(s, proy, tid, EQ, "a.bin", "x/y", b"x" * im.TOPE_ARCHIVO)
        assert ok.tamano == im.TOPE_ARCHIVO
        with pytest.raises(ErrorImpl):
            db.impl_subir_archivo(s, proy, tid, EQ, "a.bin", "x/y", b"1", mensaje_id=987654)


def test_borrar_archivo_deja_constancia(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        a = db.impl_subir_archivo(s, proy, tid, SI, "contrato.pdf", "application/pdf", b"%PDF-contrato")
        with pytest.raises(ErrorImpl) as e:
            db.impl_borrar_archivo(s, proy, a.id, SI2)               # ni el que subió ni el equipo
        assert e.value.codigo == "sin_permiso"
        b = db.impl_borrar_archivo(s, proy, a.id, EQ)
        assert b.borrado_en and b.borrado_por_nombre == EQ.nombre
        assert (b.nombre, b.tamano, b.subido_por_nombre) == ("contrato.pdf", 13, SI.nombre)
        assert s.exec(select(db.ImplArchivo.datos).where(db.ImplArchivo.id == a.id)).first() is None
        with pytest.raises(ErrorImpl) as e:
            db.impl_bajar_archivo(s, proy, a.id, EQ)
        assert e.value.codigo == "borrado"
        with pytest.raises(ErrorImpl):
            db.impl_borrar_archivo(s, proy, a.id, EQ)
        fila = db.impl_carpetas(s, proy, SI, "entrada")[0]
        assert fila["borrado"] and fila["puede_bajar"] is False       # la constancia sigue en la carpeta
    assert [e.accion for e in _eventos(proy, tid)].count("borrar_archivo") == 1


def test_quien_subio_puede_borrar_el_propio(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        a = db.impl_subir_archivo(s, proy, tid, SI, "mio.pdf", "application/pdf", b"%PDF")
        assert db.impl_borrar_archivo(s, proy, a.id, SI).borrado_por_lado == "sindicato"


def test_carpetas_entrada_y_salida_por_etapa(proy):
    with db.get_session() as s:
        et = db.impl_etapas(s, proy)
    t_relevar = _tarjeta(proy, etapa_id=et[2].id)
    t_acordar = _tarjeta(proy, etapa_id=et[1].id)
    t_sin = _tarjeta(proy)
    with db.get_session() as s:
        db.impl_subir_archivo(s, proy, t_relevar, SI, "r.pdf", "application/pdf", b"1")
        db.impl_subir_archivo(s, proy, t_acordar, SI, "a.pdf", "application/pdf", b"1")
        db.impl_subir_archivo(s, proy, t_sin, SI, "s.pdf", "application/pdf", b"1")
        db.impl_subir_archivo(s, proy, t_acordar, EQ, "plan.pdf", "application/pdf", b"1")
        entrada = db.impl_carpetas(s, proy, EQ, "entrada")
        assert [f["nombre"] for f in entrada] == ["a.pdf", "r.pdf", "s.pdf"]       # por etapa; sin etapa al final
        assert [f["etapa"] for f in entrada] == ["Acordar", "Relevar", ""]
        assert [f["nombre"] for f in db.impl_carpetas(s, proy, SI, "salida")] == ["plan.pdf"]
        with pytest.raises(ErrorImpl):
            db.impl_carpetas(s, proy, SI, "otra")


# ---------- Hitos y avance ----------
def test_tildar_hito_y_avance(proy):
    with db.get_session() as s:
        et = db.impl_etapas(s, proy)
        h1 = db.impl_agregar_hito(s, proy, et[0].id, "Primero", EQ)
        h2 = db.impl_agregar_hito(s, proy, et[0].id, "Segundo", EQ)
        db.impl_agregar_hito(s, proy, et[1].id, "Otro", EQ)
        assert (h1.orden, h2.orden) == (1, 2)
        with pytest.raises(ErrorImpl):
            db.impl_agregar_hito(s, proy, et[0].id, "del sindicato", SI)         # el plan lo edita el equipo
        h = db.impl_tildar_hito(s, proy, h1.id, SI)
        assert h.hecho and h.hecho_por == SI.nombre and h.hecho_en
        db.impl_tildar_hito(s, proy, h1.id, SI)                                  # idempotente
        av = {a["nombre"]: a for a in db.impl_avance(s, proy)}
        assert (av["Preparar"]["total"], av["Preparar"]["hechos"], av["Preparar"]["porcentaje"]) == (2, 1, 50)
        assert av["Acordar"]["porcentaje"] == 0 and av["Piloto"]["total"] == 0
        h = db.impl_tildar_hito(s, proy, h1.id, EQ, hecho=False)
        assert not h.hecho and h.hecho_por == "" and h.hecho_en == ""
    acciones = [e.accion for e in _eventos(proy)]
    assert acciones.count("hito") == 2                                           # tildar, destildar (la repetida no)


def test_tarjeta_con_hito_hereda_la_etapa(proy):
    with db.get_session() as s:
        et = db.impl_etapas(s, proy)
        etapa = et[3].id
        hito = db.impl_agregar_hito(s, proy, etapa, "Cargar conceptos", EQ).id
    tid = _tarjeta(proy, hito_id=hito)
    with db.get_session() as s:
        t = db.impl_tarjeta(s, proy, tid)
        assert (t.hito_id, t.etapa_id) == (hito, etapa)
        assert db.impl_avance(s, proy)[3]["tarjetas_abiertas"] == 1


# ---------- Vistas ----------
def test_me_toca_y_filtros(proy):
    a = _tarjeta(proy, actor=EQ)                               # espera al sindicato
    b = _tarjeta(proy, actor=SI, tipo="error", titulo="E", texto="x")   # espera al equipo
    c = _tarjeta(proy, actor=EQ, tipo="aviso", titulo="Av", texto="x")
    with db.get_session() as s:
        assert [t.id for t in db.impl_listar_tarjetas(s, proy, "sindicato", me_toca=True)] == [a]
        assert [t.id for t in db.impl_listar_tarjetas(s, proy, "equipo", me_toca=True)] == [b]
        assert db.impl_contar_me_toca(s, proy, "sindicato") == 1
        assert [t.id for t in db.impl_listar_tarjetas(s, proy, "equipo", tipo="aviso")] == [c]
        assert {t.id for t in db.impl_listar_tarjetas(s, proy, "equipo", estado="abierta")} == {a, b}
        db.impl_reasignar(s, proy, a, EQ, "Beto", "equipo")
        t = db.impl_tarjeta(s, proy, a)
        assert (t.responsable, t.responsable_lado) == ("Beto", "equipo")
        with pytest.raises(ErrorImpl):
            db.impl_reasignar(s, proy, a, EQ, "x", "marte")


# ---------- Traza ----------
def test_todo_acto_deja_su_evento_y_la_traza_es_inmutable(proy):
    tid = _tarjeta(proy)
    with db.get_session() as s:
        db.impl_responder(s, proy, tid, SI, "hola", estado_nuevo="respondida")
        db.impl_reasignar(s, proy, tid, EQ, "Ana", "equipo")
        a = db.impl_subir_archivo(s, proy, tid, SI, "a.pdf", "application/pdf", b"1")
        db.impl_bajar_archivo(s, proy, a.id, EQ)
        db.impl_borrar_archivo(s, proy, a.id, EQ)
    evs = _eventos(proy, tid)
    assert sorted(e.accion for e in evs) == sorted(
        ["crear", "responder", "reasignar", "subir", "bajar", "borrar_archivo"])
    assert all(e.actor_nombre and e.cuando for e in evs)
    assert set(e.accion for e in evs) <= set(im.ACCIONES)
    with db.get_session() as s:
        e = s.get(db.ImplEvento, evs[0].id)
        e.accion = "falsificada"
        s.add(e)
        with pytest.raises(Exception):
            s.commit()
        s.rollback()
        e = s.get(db.ImplEvento, evs[0].id)
        with pytest.raises(Exception):
            s.delete(e)
            s.commit()
        s.rollback()
        d = db.impl_descargas(s, proy, a.id)[0]
        with pytest.raises(Exception):
            s.delete(d)
            s.commit()


# ---------- I3: resguardos ----------
def _tablas_impl_del_esquema():
    return sorted(t for t in SQLModel.metadata.tables if t.startswith(im.PREFIJO_TABLAS))


def test_toda_tabla_impl_esta_declarada():
    """Una tabla `impl*` nueva que no esté en db.IMPL_TABLAS rompe este test:
    obliga a decidir (y a que clonar/recargar la excluyan)."""
    assert tuple(_tablas_impl_del_esquema()) == db.IMPL_TABLAS
    assert len(db.IMPL_TABLAS) == 10


def test_clonar_demo_a_pruebas_excluye_las_tablas_impl():
    import clonar_demo_a_pruebas as c
    patrones = c.tablas_excluidas()
    assert "recurso" in patrones
    for tabla in _tablas_impl_del_esquema():
        assert any(fnmatch.fnmatchcase(tabla, p) for p in patrones), f"{tabla} entra al dump de la demo"
        assert any(fnmatch.fnmatchcase(f"{tabla}_id_seq", p) for p in patrones)
    # y el patrón no se come tablas que no son de la Mesa
    otras = [t for t in SQLModel.metadata.tables if not t.startswith(im.PREFIJO_TABLAS)]
    comidas = [t for t in otras if any(fnmatch.fnmatchcase(t, p) for p in patrones if p != "recurso")]
    assert comidas == []
    fuente = (RAIZ / "clonar_demo_a_pruebas.py").read_text(encoding="utf-8")
    assert "tablas_excluidas()" in fuente and "--exclude-table" in fuente


def test_las_tablas_impl_no_cuelgan_de_nada_por_clave_foranea():
    """Sin claves foráneas ni desde ni hacia afuera: así el borrado por
    dependencia de un sindicato (cargar_demo) no puede arrastrarlas."""
    for nombre in db.IMPL_TABLAS:
        assert list(SQLModel.metadata.tables[nombre].foreign_keys) == [], nombre
    for t in SQLModel.metadata.tables.values():
        if t.name.startswith(im.PREFIJO_TABLAS):
            continue
        for fk in t.foreign_keys:
            assert not fk.column.table.name.startswith(im.PREFIJO_TABLAS)


def test_recargar_la_demo_no_borra_la_mesa():
    """Se ejecuta `borrar_sindicato_completo` de cargar_demo.py (que no se
    puede importar: carga la demo al importarse) sobre un sindicato asociado
    a un proyecto, y la Mesa tiene que quedar intacta."""
    fuente = (RAIZ / "cargar_demo.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    funciones = [n for n in arbol.body if isinstance(n, ast.FunctionDef)
                 and n.name in ("borrar_sindicato_completo", "_tandas")]
    assert {f.name for f in funciones} == {"borrar_sindicato_completo", "_tandas"}
    from sqlalchemy import delete as sa_delete, select as sa_select
    espacio = {"SQLModel": SQLModel, "sa_delete": sa_delete, "sa_select": sa_select, "implementacion": im}
    exec(compile(ast.Module(body=funciones, type_ignores=[]), "cargar_demo.py", "exec"), espacio)
    with db.get_session() as s:
        sind = db.Sindicato(nombre="Sindicato a recargar", slug="sindicato-a-recargar")
        s.add(sind); s.commit(); s.refresh(sind)
        p = db.impl_crear_proyecto(s, "Con sindicato", EQ, sindicato_id=sind.id)
        pid, sid = p.id, sind.id
    tid = _tarjeta(pid)
    with db.get_session() as s:
        db.impl_subir_archivo(s, pid, tid, SI, "a.pdf", "application/pdf", b"1")
        espacio["borrar_sindicato_completo"](s, sid)
        assert s.get(db.Sindicato, sid) is None
    with db.get_session() as s:
        assert db.impl_proyecto(s, pid).sindicato_id == sid
        assert db.impl_tarjeta(s, pid, tid) is not None
        assert len(db.impl_carpetas(s, pid, EQ, "entrada")) == 1
        assert len(db.impl_etapas(s, pid)) == 6

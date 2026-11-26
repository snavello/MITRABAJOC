"""XSII bloque 1, las tablas del registro (decisiones, insumos, movimientos):
unicidad de lo activo, deshacer sin borrar, traza inmutable, insumos con su
tarjeta de la Mesa y los resguardos de datos reales de Pruebas.

Correr con: python -m pytest test_xsii_db.py -q
"""
import fnmatch
import threading
import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, select

import db
import implementacion as im

db.crear_tablas()

EQ = im.Actor(im.EQUIPO, 1, "Ana (Colm3na)")
OTRO = im.Actor(im.EQUIPO, 2, "Beto (Colm3na)")


def _proyecto():
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, "XSII " + uuid.uuid4().hex[:8], EQ).id


def _tarjeta(pid):
    with db.get_session() as s:
        return db.impl_crear_tarjeta(s, pid, EQ, "pedido", "Padrón", "Mandanos el padrón").id


# ---------------------------------------------------------------- decisiones

def test_decidir_deja_la_decision_activa_y_su_movimiento():
    pid = _proyecto()
    with db.get_session() as s:
        d = db.xsii_decidir(s, pid, EQ, "PAD-02", "Padrón cargado", "completada_a_mano", "se carga en la segunda etapa")
        assert d.activa and d.quien_nombre == EQ.nombre and d.cuando
        activas = db.xsii_decisiones_activas(s, pid)
        assert activas == {"PAD-02": [{"tipo": "completada_a_mano", "motivo": "se carga en la segunda etapa",
                                       "quien": EQ.nombre, "cuando": d.cuando}]}
        movs = db.xsii_movimientos(s, pid)
        assert len(movs) == 1 and movs[0].tipo == "decision" and movs[0].codigo == "PAD-02"
        assert movs[0].texto == "Completó a mano Padrón cargado: se carga en la segunda etapa"
        assert movs[0].cantidades == {}


def test_varias_decisiones_de_distinto_tipo_conviven_y_la_misma_no_se_repite():
    pid = _proyecto()
    with db.get_session() as s:
        db.xsii_decidir(s, pid, EQ, "BAS-03", "Módulos", "pospuesta")
        db.xsii_decidir(s, pid, EQ, "BAS-03", "Módulos", "confirmada")
        assert [d["tipo"] for d in db.xsii_decisiones_activas(s, pid)["BAS-03"]] == ["pospuesta", "confirmada"]
        with pytest.raises(db.XsiiError) as e:
            db.xsii_decidir(s, pid, EQ, "BAS-03", "Módulos", "pospuesta")
        assert e.value.estado == 409
        assert len(db.xsii_movimientos(s, pid)) == 2        # el rechazo no deja traza


def test_motivo_obligatorio_solo_donde_corresponde():
    pid = _proyecto()
    with db.get_session() as s:
        for tipo in ("completada_a_mano", "no_aplica"):
            for malo in ("", "   ", "abc", None):
                with pytest.raises(db.XsiiError) as e:
                    db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", tipo, malo)
                assert e.value.estado == 400 and "obligatorio" in e.value.mensaje
        with pytest.raises(db.XsiiError) as e:
            db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "pospuesta", "x" * 501)
        assert e.value.estado == 400
        with pytest.raises(db.XsiiError) as e:
            db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "inventada", "motivo largo")
        assert e.value.estado == 400
        db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "pospuesta")           # sin motivo: vale
        db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "confirmada")
        assert db.xsii_movimientos(s, pid)[0].texto == "Confirmó Noticias"


def test_el_texto_del_motivo_se_sanea():
    pid = _proyecto()
    with db.get_session() as s:
        d = db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "no_aplica", "  sin\x00 noticias por ahora  ")
        assert d.motivo == "sin noticias por ahora"


def test_deshacer_no_borra_y_permite_decidir_de_nuevo():
    pid = _proyecto()
    with db.get_session() as s:
        db.xsii_decidir(s, pid, EQ, "COM-03", "Beneficios", "no_aplica", "no los usan todavía")
        d = db.xsii_deshacer(s, pid, OTRO, "COM-03", "Beneficios", "no_aplica", "se arrepintieron")
        assert not d.activa and d.deshecha_por_nombre == OTRO.nombre and d.deshecha_motivo == "se arrepintieron"
        assert d.deshecha_cuando
        assert db.xsii_decisiones_activas(s, pid) == {}
        filas = s.exec(select(db.XsiiDecision).where(db.XsiiDecision.proyecto_id == pid)).all()
        assert len(filas) == 1                                  # no se borró
        db.xsii_decidir(s, pid, EQ, "COM-03", "Beneficios", "no_aplica", "ahora sí no aplica")
        assert len(s.exec(select(db.XsiiDecision).where(db.XsiiDecision.proyecto_id == pid)).all()) == 2
        tipos = [m.tipo for m in db.xsii_movimientos(s, pid)]
        assert tipos == ["decision", "decision_deshecha", "decision"]


def test_deshacer_sin_activa_es_409_y_con_tipo_invalido_400():
    pid = _proyecto()
    with db.get_session() as s:
        with pytest.raises(db.XsiiError) as e:
            db.xsii_deshacer(s, pid, EQ, "COM-03", "Beneficios", "pospuesta")
        assert e.value.estado == 409
        with pytest.raises(db.XsiiError) as e:
            db.xsii_deshacer(s, pid, EQ, "COM-03", "Beneficios", "rara")
        assert e.value.estado == 400


def test_lo_de_un_proyecto_no_aparece_en_otro():
    a, b = _proyecto(), _proyecto()
    with db.get_session() as s:
        db.xsii_decidir(s, a, EQ, "COM-03", "Beneficios", "pospuesta")
        db.xsii_registrar_insumo(s, a, EQ, "planilla_padron", "Planilla", "pedido")
        assert db.xsii_decisiones_activas(s, b) == {} and db.xsii_insumos_activos(s, b) == {}
        assert db.xsii_movimientos(s, b) == []
        # mismo código y tipo en el otro proyecto: el único es POR proyecto
        db.xsii_decidir(s, b, EQ, "COM-03", "Beneficios", "pospuesta")


def test_dos_pedidos_a_la_vez_uno_solo_gana_y_el_otro_es_409():
    pid = _proyecto()
    resultados, barrera = [], threading.Barrier(2)

    def intento():
        with db.get_session() as s:
            barrera.wait()
            try:
                db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "pospuesta")
                resultados.append("ok")
            except db.XsiiError as e:
                resultados.append(e.estado)

    hilos = [threading.Thread(target=intento) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sorted(map(str, resultados)) == ["409", "ok"]
    with db.get_session() as s:
        assert len(db.xsii_decisiones_activas(s, pid)["COM-02"]) == 1


def test_el_indice_unico_parcial_lo_impone_la_base():
    pid = _proyecto()
    with db.get_session() as s:
        s.add(db.XsiiDecision(proyecto_id=pid, codigo="X", tipo="pospuesta"))
        s.commit()
        s.add(db.XsiiDecision(proyecto_id=pid, codigo="X", tipo="pospuesta"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.add(db.XsiiDecision(proyecto_id=pid, codigo="X", tipo="pospuesta", activa=False))   # inactivas: sin tope
        s.add(db.XsiiDecision(proyecto_id=pid, codigo="X", tipo="pospuesta", activa=False))
        s.commit()
        s.add(db.XsiiInsumo(proyecto_id=pid, clave="k"))
        s.commit()
        s.add(db.XsiiInsumo(proyecto_id=pid, clave="k"))
        with pytest.raises(IntegrityError):
            s.commit()


# ---------------------------------------------------------------- traza

def test_el_movimiento_no_se_edita_ni_se_borra():
    pid = _proyecto()
    with db.get_session() as s:
        db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "pospuesta")
        m = db.xsii_movimientos(s, pid)[0]
        m.texto = "otra cosa"
        s.add(m)
        with pytest.raises(ValueError):
            s.commit()
        s.rollback()
        m = db.xsii_movimientos(s, pid)[0]
        s.delete(m)
        with pytest.raises(ValueError):
            s.commit()
        s.rollback()
        assert len(db.xsii_movimientos(s, pid)) == 1


def test_movimientos_filtra_por_tarea_y_por_sus_insumos_y_acota_el_limite():
    pid = _proyecto()
    with db.get_session() as s:
        db.xsii_decidir(s, pid, EQ, "PAD-02", "Padrón cargado", "pospuesta")
        db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "pospuesta")
        db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla del padrón", "pedido")
        db.xsii_registrar_insumo(s, pid, EQ, "recibos_muestra", "Recibos de muestra", "pedido")
        assert len(db.xsii_movimientos(s, pid)) == 4
        movs = db.xsii_movimientos(s, pid, codigo="PAD-02", claves_insumo=("planilla_padron",))
        assert sorted(m.tipo for m in movs) == ["decision", "insumo_pedido"]
        assert len(db.xsii_movimientos(s, pid, codigo="PAD-02")) == 1
        assert len(db.xsii_movimientos(s, pid, limite=2)) == 2
        assert len(db.xsii_movimientos(s, pid, limite=-5)) == 1 and len(db.xsii_movimientos(s, pid, limite=9999)) == 4
        ids = [m.id for m in db.xsii_movimientos(s, pid)]
        assert ids == sorted(ids, reverse=True)


# ---------------------------------------------------------------- insumos

def test_registrar_reemplaza_y_pasar_a_recibido_conserva_la_tarjeta():
    pid = _proyecto()
    tid = _tarjeta(pid)
    with db.get_session() as s:
        a = db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla del padrón", "pedido", tid, "lo pedimos")
        assert a.activa and a.estado == "pedido" and a.tarjeta_id == tid and a.nota == "lo pedimos"
        b = db.xsii_registrar_insumo(s, pid, OTRO, "planilla_padron", "Planilla del padrón", "recibido")
        assert b.estado == "recibido" and b.tarjeta_id == tid and b.id != a.id
        activos = db.xsii_insumos_activos(s, pid)
        assert list(activos) == ["planilla_padron"] and activos["planilla_padron"].id == b.id
        viejo = s.get(db.XsiiInsumo, a.id)
        assert not viejo.activa and viejo.retirado_por_nombre == OTRO.nombre and viejo.retirado_cuando
        assert [m.tipo for m in db.xsii_movimientos(s, pid)] == ["insumo_recibido", "insumo_pedido"]


def test_la_tarjeta_de_otro_proyecto_se_rechaza():
    pid, ajeno = _proyecto(), _proyecto()
    tid_ajena = _tarjeta(ajeno)
    with db.get_session() as s:
        with pytest.raises(db.XsiiError) as e:
            db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla", "pedido", tid_ajena)
        assert e.value.estado == 400 and "tarjeta" in e.value.mensaje
        assert db.xsii_insumos_activos(s, pid) == {}
        with pytest.raises(db.XsiiError):
            db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla", "pedido", 99999999)


def test_estado_y_nota_invalidos_son_400_y_no_dejan_nada():
    pid = _proyecto()
    with db.get_session() as s:
        for kw in ({"estado": "listo"}, {"estado": "pedido", "nota": "n" * 501}):
            with pytest.raises(db.XsiiError) as e:
                db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla", **kw)
            assert e.value.estado == 400
        assert db.xsii_insumos_activos(s, pid) == {} and db.xsii_movimientos(s, pid) == []


def test_retirar_deja_la_traza_y_sin_activo_es_409():
    pid = _proyecto()
    with db.get_session() as s:
        with pytest.raises(db.XsiiError) as e:
            db.xsii_retirar_insumo(s, pid, EQ, "planilla_padron", "Planilla")
        assert e.value.estado == 409
        db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla", "pedido")
        i = db.xsii_retirar_insumo(s, pid, OTRO, "planilla_padron", "Planilla")
        assert not i.activa and i.retirado_por_nombre == OTRO.nombre
        assert db.xsii_insumos_activos(s, pid) == {}
        assert [m.tipo for m in db.xsii_movimientos(s, pid)] == ["insumo_retirado", "insumo_pedido"]
        assert len(s.exec(select(db.XsiiInsumo).where(db.XsiiInsumo.proyecto_id == pid)).all()) == 1


# ---------------------------------------------------------------- resguardos (datos reales de Pruebas)

def _tablas_xsii_del_esquema():
    return sorted(t for t in SQLModel.metadata.tables if t.startswith("xsii"))


def test_toda_tabla_xsii_esta_declarada():
    assert tuple(_tablas_xsii_del_esquema()) == db.XSII_TABLAS
    assert db.XSII_TABLAS == ("xsiidecision", "xsiiinsumo", "xsiimovimiento")


def test_el_clonado_de_la_demo_excluye_las_tablas_xsii():
    import clonar_demo_a_pruebas as c
    patrones = c.tablas_excluidas()
    for tabla in db.XSII_TABLAS:
        assert any(fnmatch.fnmatchcase(tabla, p) for p in patrones), f"{tabla} entra al dump de la demo"
        assert any(fnmatch.fnmatchcase(f"{tabla}_id_seq", p) for p in patrones)


def test_las_tablas_xsii_no_cuelgan_de_nada_por_clave_foranea():
    for nombre in db.XSII_TABLAS:
        assert list(SQLModel.metadata.tables[nombre].foreign_keys) == [], nombre
    for t in SQLModel.metadata.tables.values():
        if t.name.startswith("xsii"):
            continue
        for fk in t.foreign_keys:
            assert not fk.column.table.name.startswith("xsii")


def test_borrar_un_sindicato_no_toca_el_registro_de_xsii():
    import ast
    from pathlib import Path
    from sqlalchemy import delete as sa_delete, select as sa_select
    fuente = (Path(__file__).parent / "cargar_demo.py").read_text(encoding="utf-8")
    funciones = [n for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)
                 and n.name in ("borrar_sindicato_completo", "_tandas")]
    espacio = {"SQLModel": SQLModel, "sa_delete": sa_delete, "sa_select": sa_select, "implementacion": im}
    exec(compile(ast.Module(body=funciones, type_ignores=[]), "cargar_demo.py", "exec"), espacio)
    with db.get_session() as s:
        sind = db.Sindicato(nombre="Sindicato XSII a borrar", slug="xsii-a-borrar-" + uuid.uuid4().hex[:6])
        s.add(sind); s.commit(); s.refresh(sind)
        p = db.impl_crear_proyecto(s, "Con sindicato", EQ, sindicato_id=sind.id)
        pid, sid = p.id, sind.id
        db.xsii_decidir(s, pid, EQ, "COM-02", "Noticias", "pospuesta")
        db.xsii_registrar_insumo(s, pid, EQ, "planilla_padron", "Planilla", "pedido")
        espacio["borrar_sindicato_completo"](s, sid)
        assert s.get(db.Sindicato, sid) is None
    with db.get_session() as s:
        assert len(db.xsii_decisiones_activas(s, pid)["COM-02"]) == 1
        assert "planilla_padron" in db.xsii_insumos_activos(s, pid)
        assert len(db.xsii_movimientos(s, pid)) == 2

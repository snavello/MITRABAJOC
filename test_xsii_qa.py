"""QA independiente del bloque 0 de XSII. Los tests que HOY fallan documentan un
defecto (el nombre empieza con `test_defecto_`); el resto son de borde y pasan.

Correr con: python -m pytest test_xsii_qa.py -q
"""
import itertools
import json

import pytest
from sqlmodel import select

import cuit
import db
import fechas
import modulos
from db import (Area, Beneficio, Concepto, CuentaPanel, Empleador, Formula, ImplProyecto,
                ImplTarjeta, Noticia, PermisoArea, Seccional, Sindicato, TipoTramite,
                CampoTramite, Trabajador, UsuarioSindicato)
from xsii import informe
from xsii.motor import consulta, estados
from xsii.motor.catalogo import Tarea, validar
from xsii.motor.estados import Control
from xsii.proyectos.colm3na import catalogo, controles, tablero

db.crear_tablas()
_n = itertools.count(1)
TODOS = list(modulos.MODULOS)


def sind(mods=None):
    n = next(_n)
    with db.get_session() as s:
        x = Sindicato(nombre=f"QA XSII {n}", slug=f"qa-xsii-{n}", cuit=cuit.corregir("30710000000"),
                      modulos_habilitados=list(TODOS if mods is None else mods))
        s.add(x); s.commit(); s.refresh(x)
        sid = x.id
    db.crear_conceptos_universales(sid)
    return sid


def cuil():
    return cuit.corregir(f"2761{next(_n):06d}0")


def tb(sid, **kw):
    with db.get_session() as s:
        return tablero.armar(s, sid, **kw)


def ctl(sid, codigo):
    return tb(sid)[1][codigo].control


def T(codigo, necesita=(), **kw):
    return Tarea(codigo, codigo, "G", "manual", necesita=tuple(necesita), control="c", **kw)


def hechos_con(controles_=None, **kw):
    return {"controles": controles_ or {}, **kw}


OK = Control("completa")
NO = Control("incompleta")


# ============================================================ motor (puro)

def test_defecto_recomendada_ofrece_una_tarea_pospuesta_en_curso():
    # `_candidatas` filtra las pospuestas entre las `lista` pero no entre las `en_curso`.
    tareas = [T("A"), T("B")]
    h = hechos_con({"A": NO, "B": NO}, ensayos_abiertos={"A"},
                   decisiones={"A": {"tipo": "pospuesta", "quien": "x", "cuando": "", "motivo": "m"}})
    t = estados.resolver(tareas, h)
    assert t["A"].estado == "en_curso" and t["A"].pospuesta
    assert consulta.recomendada(tareas, t) == "B"


def test_defecto_porcentaje_100_con_una_tarea_sin_hacer():
    tareas = [T(f"T{i}") for i in range(200)]
    cs = {t.codigo: OK for t in tareas}
    cs["T0"] = NO
    r = consulta.resumen(estados.resolver(tareas, hechos_con(cs)))
    assert r["resueltas"] == 199 and r["porcentaje"] < 100     # hoy: round(99.5) = 100


def test_defecto_que_destraba_y_que_frena_no_coinciden_ante_un_codigo_desconocido():
    tareas = [T("A")]
    t = estados.resolver(tareas, hechos_con({"A": NO}))
    # Ajustado en la segunda vuelta: el diseño decidió ValueError (mensaje claro)
    # en las tres consultas, no KeyError; lo que el defecto pide es que coincidan.
    for f in (consulta.que_frena, consulta.que_destraba, consulta.camino_hasta):
        with pytest.raises(ValueError, match="ZZZ"):
            f(tareas, t, "ZZZ")


def test_precedencia_hecha_gana_a_bloqueada_y_no_aplica_a_hecha():
    tareas = [T("A"), T("B", ["A"]), T("C", aplica_si="m")]
    t = estados.resolver(tareas, hechos_con({"A": NO, "B": OK, "C": OK}, aplica={"m": False}))
    assert t["B"].estado == "hecha" and t["C"].estado == "no_aplica"


def test_a_mano_destraba_y_conserva_el_control():
    tareas = [T("A"), T("B", ["A"])]
    d = {"A": {"tipo": "completada_a_mano", "quien": "q", "cuando": "c", "motivo": "m"}}
    t = estados.resolver(tareas, hechos_con({"A": NO, "B": NO}, decisiones=d))
    assert t["A"].estado == "hecha" and t["A"].a_mano and t["A"].control.estado == "incompleta"
    assert t["B"].estado == "lista"


def test_codigos_desconocidos_en_decisiones_y_controles_se_ignoran_y_ciclo_levanta():
    tareas = [T("A")]
    t = estados.resolver(tareas, hechos_con({"A": OK, "X": NO}, decisiones={"Y": {"tipo": "pospuesta"}}))
    assert list(t) == ["A"]
    with pytest.raises(ValueError):
        estados.resolver(tareas, hechos_con({"A": NO}, decisiones={"A": {"tipo": "rara"}}))
    ciclo = [T("A", ["B"]), T("B", ["C"]), T("C", ["A"])]
    assert any("Ciclo" in e for e in validar(ciclo, ["G"]))
    tt = estados.resolver(ciclo, hechos_con({}))
    with pytest.raises(ValueError):
        consulta.camino_hasta(ciclo, tt, "A")


def test_catalogo_vacio_y_diamante_deterministas():
    assert validar([], ["G"]) == []
    assert consulta.resumen({})["porcentaje"] == 0
    assert consulta.recomendada([], {}) is None
    tareas = [T("A"), T("B", ["A"]), T("C", ["A"]), T("D", ["B", "C"]), T("E", ["D"])]
    t = estados.resolver(tareas, hechos_con({}))
    assert consulta.camino_hasta(tareas, t, "E") == ["A", "B", "C", "D"]
    assert consulta.que_destraba(tareas, t, "A")["transitivo"] == ["B", "C", "D", "E"]
    assert consulta.recomendada(tareas, t) == "A"
    assert json.dumps(consulta.a_json(tareas, t))


def test_cadena_larga_no_rompe_la_pila():
    n = 1500
    tareas = [T("T0")] + [T(f"T{i}", [f"T{i-1}"]) for i in range(1, n)]
    assert validar(tareas, ["G"]) == []
    t = estados.resolver(tareas, hechos_con({}))
    assert len(consulta.camino_hasta(tareas, t, f"T{n-1}")) == n - 1


def test_a_json_del_tablero_real_serializa():
    sid = sind()
    tareas, t = tb(sid)
    json.dumps(consulta.a_json(tareas, t))


# ======================================================= controles (base)

def test_defecto_cie_03_cuenta_una_aprobacion_rechazada_como_aceptacion():
    sid = sind()
    with db.get_session() as s:
        p = ImplProyecto(nombre="p", sindicato_id=sid); s.add(p); s.commit(); s.refresh(p)
        s.add(ImplTarjeta(proyecto_id=p.id, numero=1, codigo="AP0001", tipo="aprobacion",
                          estado="rechazada", resuelta_por_lado="sindicato", resuelta_en="2026-11-26 10:00:00"))
        s.commit()
    assert ctl(sid, "CIE-03").estado == "incompleta"


def test_defecto_est_04_con_formularios_hacia_un_area_inactiva_da_completa_sin_exigir_nada():
    sid = sind()
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="Central", ve_todas=True); s.add(sec); s.commit(); s.refresh(sec)
        activa = Area(sindicato_id=sid, seccional_id=sec.id, nombre="Legales");
        inactiva = Area(sindicato_id=sid, seccional_id=sec.id, nombre="Vieja", activo=False)
        s.add(activa); s.add(inactiva); s.commit(); s.refresh(inactiva)
        s.add(TipoTramite(sindicato_id=sid, titulo="F", codigo=f"F{sid}", area_destino_default_id=inactiva.id))
        s.commit()
    # «Legales» está activa y sin usuarios; hoy el control dice «completa» con 0 áreas exigidas.
    assert ctl(sid, "EST-04").estado == "incompleta"


def test_defecto_pad_04_un_empleador_dado_de_baja_figura_como_cuit_sin_importar():
    # db.importar_cuits_de_conceptos compara contra TODOS los Empleador (activos o no):
    # el botón no lo vuelve a crear, pero el control lo pide para siempre.
    sid = sind()
    c1, c2 = cuit.corregir("30111222330"), cuit.corregir("30222333440")
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=sid, cuit=c1))
        s.add(Empleador(sindicato_id=sid, cuit=c2, activo=False))
        s.add(Concepto(sindicato_id=sid, codigo="X1", nombre="x", tipo="ingreso", cuit_empleador=c2))
        s.commit()
    assert ctl(sid, "PAD-04").estado == "completa"


def test_defecto_pad_04_no_normaliza_el_cuit_de_los_conceptos():
    sid = sind()
    c = cuit.corregir("30111222330")
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=sid, cuit=c))
        s.add(Concepto(sindicato_id=sid, codigo="X1", nombre="x", tipo="ingreso",
                       cuit_empleador=f"{c[:2]}-{c[2:10]}-{c[10]}"))      # como lo deja el aprendizaje (main.py:1236)
        s.commit()
    assert ctl(sid, "PAD-04").estado == "completa"


def test_defecto_tablero_se_cae_con_modulos_habilitados_raros():
    sid = sind([{"a": 1}])        # JSONB admite cualquier cosa; `set([{...}])` revienta fuera del try
    tb(sid)


def test_sindicato_inexistente_no_revienta_y_nada_aplica_de_mas():
    tareas, t = tb(987654321)
    assert t["BAS-01"].estado != "hecha"
    assert all(e.control is not None for e in t.values())


def test_un_control_que_falla_no_tumba_el_tablero_ni_la_sesion(monkeypatch):
    def roto(s, sid):
        s.execute(__import__("sqlalchemy").text("select 1/0"))
    monkeypatch.setattr(controles, "bas_02", roto)
    sid = sind()
    tareas, t = tb(sid)
    assert "Error al calcular" in t["BAS-02"].control.faltan[0]
    assert t["BAS-01"].estado == "hecha" and t["REC-02"].estado == "hecha"


def test_noticia_vigente_incluye_el_dia_de_hoy_y_excluye_vencidas():
    sid = sind()
    hoy = fechas.hoy()
    from datetime import timedelta
    ayer, man = (hoy - timedelta(days=1)).isoformat(), (hoy + timedelta(days=1)).isoformat()
    with db.get_session() as s:
        s.add(Noticia(sindicato_id=sid, titulo="v", fecha_desde=ayer, fecha_hasta=ayer))
        s.add(Noticia(sindicato_id=sid, titulo="f", fecha_desde=man, fecha_hasta=man))
        s.commit()
    assert ctl(sid, "COM-02").estado == "incompleta"
    with db.get_session() as s:
        s.add(Noticia(sindicato_id=sid, titulo="h", fecha_desde=hoy.isoformat(), fecha_hasta=hoy.isoformat()))
        s.commit()
    assert ctl(sid, "COM-02").estado == "completa"


def test_tra_01_un_formulario_solo_con_separadores_o_borrador_no_cuenta():
    sid = sind()
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="C", ve_todas=True); s.add(sec); s.commit(); s.refresh(sec)
        a = Area(sindicato_id=sid, seccional_id=sec.id, nombre="L"); s.add(a); s.commit(); s.refresh(a)
        t1 = TipoTramite(sindicato_id=sid, titulo="A", codigo=f"A{sid}", area_destino_default_id=a.id)
        t2 = TipoTramite(sindicato_id=sid, titulo="B", codigo=f"B{sid}", area_destino_default_id=a.id, borrador=True)
        s.add(t1); s.add(t2); s.commit(); s.refresh(t1); s.refresh(t2)
        s.add(CampoTramite(tipo_tramite_id=t1.id, tipo_dato="separador"))
        s.add(CampoTramite(tipo_tramite_id=t2.id, tipo_dato="texto", etiqueta="x"))
        s.commit()
    assert ctl(sid, "TRA-01").estado == "incompleta"


def test_rec_05_vigencias_superpuestas_y_est_03_area_inactiva():
    sid = sind()
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=sid, codigo="C1", nombre="c", tipo="ingreso"))
        s.add(Formula(sindicato_id=sid, target="C1", descripcion="a", expr="0.1 * base_remunerativa",
                      fecha_desde="2026-01-01", fecha_hasta="2026-06-30"))
        s.add(Formula(sindicato_id=sid, target="C1", descripcion="b", expr="0.1 * base_remunerativa",
                      fecha_desde="2026-06-01", fecha_hasta=None))
        s.commit()
    c = ctl(sid, "REC-05")
    assert c.estado == "incompleta" and c.cifras["con_vigencias_superpuestas"] == 1


# ---------------------------------------------------------- aislamiento

def _poblar(sid):
    h = cuil()
    hoy = fechas.hoy_texto()
    with db.get_session() as s:
        sec = Seccional(sindicato_id=sid, nombre="Central", ve_todas=True, latitud=-34.6, longitud=-58.4,
                        precision_geo="exacta"); s.add(sec); s.commit(); s.refresh(sec)
        a = Area(sindicato_id=sid, seccional_id=sec.id, nombre="L"); s.add(a); s.commit(); s.refresh(a)
        s.add(PermisoArea(area_id=a.id, seccion="tramites"))
        s.add(UsuarioSindicato(sindicato_id=sid, usuario=h, cuil=h, nombre="u", activo=True,
                               es_super_admin=True, area_id=a.id, seccional_id=sec.id))
        s.add(CuentaPanel(cuil=h, clave_hash="x", debe_cambiar_clave=False))
        s.add(Concepto(sindicato_id=sid, codigo="CUOTA", nombre="c", tipo="descuento",
                       categoria_sindical="afiliacion"))
        s.add(Concepto(sindicato_id=sid, codigo="K2", nombre="k", tipo="ingreso", cuit_empleador="30111222330"))
        s.add(Formula(sindicato_id=sid, target="CUOTA", descripcion="c", expr="0.02 * base_remunerativa"))
        s.add(Noticia(sindicato_id=sid, titulo="n", fecha_desde=hoy, fecha_hasta=hoy))
        s.add(Beneficio(sindicato_id=sid, titulo="b", rubro="r", fecha_desde=hoy, fecha_hasta=hoy))
        s.add(Empleador(sindicato_id=sid, cuit=cuit.corregir("30555666770")))
        s.add(Trabajador(sindicato_id=sid, cuil=cuil(), registrado=True, seccional_id=sec.id))
        ti = TipoTramite(sindicato_id=sid, titulo="F", codigo=f"Q{sid}", area_destino_default_id=a.id)
        s.add(ti); s.commit(); s.refresh(ti)
        s.add(CampoTramite(tipo_tramite_id=ti.id, tipo_dato="texto", etiqueta="x"))
        p = ImplProyecto(nombre="p", sindicato_id=sid); s.add(p); s.commit(); s.refresh(p)
        s.add(ImplTarjeta(proyecto_id=p.id, numero=1, codigo="AP1", tipo="aprobacion", estado="aprobada",
                          resuelta_por_lado="sindicato", resuelta_en="2026-11-26 10:00:00"))
        s.commit()


def _foto(sid):
    _, t = tb(sid)
    return {c: (e.estado, e.control.estado, json.dumps(e.control.cifras, sort_keys=True),
                tuple(e.control.faltan)) for c, e in t.items()}


def test_un_sindicato_lleno_no_cambia_el_resultado_de_otro_vacio():
    a = sind()
    antes = _foto(a)
    b = sind()
    _poblar(b)
    assert _foto(a) == antes
    assert _foto(b) != antes          # y el lleno sí cambió: la prueba tiene dientes


def test_defecto_informe_dice_modulo_apagado_para_una_tarea_declarada_no_aplica_con_modulo_prendido():
    tareas = list(catalogo.TAREAS)
    t = next(x for x in tareas if x.codigo == "COM-02")
    e = estados.EstadoTarea("COM-02", "no_aplica", decision={"tipo": "no_aplica", "motivo": "m"})
    assert "apagado" not in informe._linea(t, e)

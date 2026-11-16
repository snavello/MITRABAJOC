# -*- coding: utf-8 -*-
"""QA independiente del Bloque 1 de PLAN_CONVENIO_ESCALAS.md."""
import copy
import itertools
import json
import subprocess
import sys
import threading

import pytest
from sqlmodel import Session, text

import db
import grilla_bancaria as gb

CONV = db.CONVENIO_BANCARIO


@pytest.fixture(autouse=True)
def base_limpia():
    db.crear_tablas()
    with Session(db.engine) as s:
        s.exec(text("DELETE FROM grillasalarial"))
        s.commit()
    yield
    gb.registrar(gb.grillas_semilla())


def _ida_y_vuelta(g):
    """Lo que hace la base: JSONB ordena las claves por largo y alfabeto."""
    gid = db.guardar_grilla(g["periodo"], g, estado="publicada", origen="manual")
    return db.grillas_publicadas(CONV)[g["periodo"]], gid


def _entradas(g):
    for rama, r in g["ramas"].items():
        for i in range(len(r["categorias"])):
            for caj, gu, dia, af in itertools.product((False, True), repeat=4):
                for tr in range(len(g["roe"]["tramos"])):
                    yield {"rama": rama, "categoria": i, "cajero": caj, "guarderia": gu,
                           "dia_bancario": dia, "afiliado": af, "tramo_roe": tr}
    base = {"rama": "administrativa", "categoria": 3, "tramo_roe": 1}
    for t in g["adicionales"]["titulos"]:
        yield {**base, "titulo": t, "falla_me": True, "cajero": True}
    for z in g["adicionales"]["zona_patagonica"]:
        yield {**base, "zona": z}
    yield {**base, "conectividad": "mensual"}
    yield {**base, "conectividad": "diario", "dias_conectividad": 3}


def test_equivalencia_archivo_contra_base():
    semilla = gb.grillas_semilla()
    gb.registrar(semilla)
    antes_op = json.dumps(gb.opciones(), ensure_ascii=False)       # orden de claves incluido
    entradas = list(_entradas(semilla["2026-08"]))
    antes = [json.dumps(gb.calcular_recibo(e), ensure_ascii=False) for e in entradas]
    consts = (gb.GRILLA, gb.ESCALA_ADMINISTRATIVA, gb.JERARQUIAS, gb.TITULOS, gb.ZONA_PATAGONICA,
              gb.ROE_TABLA, gb.TRAMOS_ROE, gb.FUNCION_CAJERO, gb.GUARDERIA, gb.DIA_BANCARIO_MINIMO)
    db.sembrar_grillas()
    gb.registrar(db.grillas_publicadas(CONV))
    assert json.dumps(gb.opciones(), ensure_ascii=False) == antes_op
    despues = [json.dumps(gb.calcular_recibo(e), ensure_ascii=False) for e in entradas]
    assert despues == antes
    assert (gb.GRILLA, gb.ESCALA_ADMINISTRATIVA, gb.JERARQUIAS, gb.TITULOS, gb.ZONA_PATAGONICA,
            gb.ROE_TABLA, gb.TRAMOS_ROE, gb.FUNCION_CAJERO, gb.GUARDERIA, gb.DIA_BANCARIO_MINIMO) == consts
    assert list(gb.TITULOS) == list(consts[3]) and list(gb.ZONA_PATAGONICA) == list(consts[4])


def test_ida_y_vuelta_jsonb_conserva_valores():
    for p, g in gb.grillas_semilla().items():
        vuelta, _ = _ida_y_vuelta(g)
        assert vuelta == g          # igualdad de dict no mira el orden: los valores son idénticos


def test_grilla_bancaria_sigue_pura():
    codigo = ("import sys, grilla_bancaria; "
              "print(sorted(m for m in ('db','main','urllib.request','http.client','requests','socket') "
              "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True,
                         cwd=".", env={"PYTHONPATH": "."}).stdout.strip()
    assert "'db'" not in out and "'main'" not in out, out
    import ast
    imports = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(open("grilla_bancaria.py").read()))
               if isinstance(n, ast.Import)} | {n.module.split(".")[0] for n in ast.walk(
                   ast.parse(open("grilla_bancaria.py").read())) if isinstance(n, ast.ImportFrom)}
    assert not imports & {"db", "main", "requests", "urllib", "httpx", "socket", "sqlmodel"}, imports


def test_siembra_concurrente_no_duplica():
    resultados = []
    def sembrar():
        resultados.append(db.sembrar_grillas())
    hilos = [threading.Thread(target=sembrar) for _ in range(8)]
    [h.start() for h in hilos]; [h.join() for h in hilos]
    n = len(gb.grillas_semilla())
    assert sum(resultados) == n
    assert len(db.listar_grillas(CONV)) == n


def test_publicaciones_simultaneas_dejan_una():
    g = gb.grillas_semilla()["2026-08"]
    errores = []
    def pub():
        try:
            db.guardar_grilla("2026-10", {**g, "periodo": "2026-10"}, estado="publicada", quien="a")
        except Exception as e:           # un perdedor puede fallar por el índice único, pero no duplicar
            errores.append(e)
    hilos = [threading.Thread(target=pub) for _ in range(6)]
    [h.start() for h in hilos]; [h.join() for h in hilos]
    filas = [f for f in db.listar_grillas(CONV) if f["periodo"] == "2026-10"]
    assert sum(1 for f in filas if f["estado"] == "publicada") == 1
    assert errores == [] or all("uq_grillasalarial" in str(e) or "unique" in str(e).lower() for e in errores)


def test_publicar_retenidas_simultaneas():
    g = gb.grillas_semilla()["2026-08"]
    ids = [db.guardar_grilla("2026-11", {**g, "periodo": "2026-11"}) for _ in range(4)]
    res, errs = [], []
    def go(i):
        try:
            res.append(db.publicar_grilla(i, "q"))
        except Exception as e:
            errs.append(e)
    hilos = [threading.Thread(target=go, args=(i,)) for i in ids]
    [h.start() for h in hilos]; [h.join() for h in hilos]
    filas = [f for f in db.listar_grillas(CONV) if f["periodo"] == "2026-11"]
    # Invariante: UNA publicada. Observación del QA: el perdedor de la carrera levanta
    # IntegrityError (el índice único lo ampara) en vez de reemplazar; ver informe.
    assert sum(1 for f in filas if f["estado"] == "publicada") == 1
    assert all("uq_grillasalarial_publicada" in str(e) for e in errs)


def test_retenida_no_cambia_vigente_ni_sello():
    db.sembrar_grillas()
    sello = db.sello_grillas()
    g = gb.grillas_semilla()["2026-08"]
    db.guardar_grilla("2026-09", {**g, "periodo": "2026-09"}, estado="retenida")
    db.guardar_grilla("2026-08", g, estado="retenida")
    assert db.sello_grillas() == sello
    assert set(db.grillas_publicadas(CONV)) == set(gb.grillas_semilla())


def test_sello_cambia_al_reemplazar_mismo_periodo():
    db.sembrar_grillas()
    s0 = db.sello_grillas()
    g = gb.grillas_semilla()["2026-08"]
    db.guardar_grilla("2026-08", g, estado="publicada", quien="x")
    assert db.sello_grillas() != s0


def test_descartar_y_publicar_estados():
    g = gb.grillas_semilla()["2026-08"]
    i = db.guardar_grilla("2026-12", {**g, "periodo": "2026-12"})
    assert db.descartar_grilla(i, "q") and not db.publicar_grilla(i, "q")
    assert not db.descartar_grilla(999999, "q")


def test_registrar_invalido_no_deja_a_medias():
    gb.registrar(gb.grillas_semilla())
    snap = (gb.PERIODO_VIGENTE, gb.GRILLA, list(gb.ESCALA_ADMINISTRATIVA), dict(gb.TITULOS), gb.GRILLAS)
    base = gb.grillas_semilla()
    rota = copy.deepcopy(base["2026-08"]); rota["periodo"] = "2026-09"
    del rota["roe"]
    for mala in (None, {}, {"2026-09": rota}, {"2026-09": {"periodo": "2026-09"}},
                 {"2026-09": {**base["2026-08"], "periodo": "2026-09", "ramas": {}}}):
        try:
            gb.registrar(mala)
        except Exception:
            pass
        else:
            pytest.fail(f"aceptó {mala!r}"[:80])
        assert (gb.PERIODO_VIGENTE, gb.GRILLA, list(gb.ESCALA_ADMINISTRATIVA), dict(gb.TITULOS), gb.GRILLAS) == snap


def test_registrar_mes_nuevo_y_volver_atras():
    base = gb.grillas_semilla()
    gb.registrar(base)
    ref = json.dumps(gb.calcular_recibo({"categoria": 2, "cajero": True}), ensure_ascii=False)
    nueva = copy.deepcopy(base["2026-08"]); nueva["periodo"] = "2026-09"; nueva["nombre"] = "Septiembre 2026"
    gb.registrar({**base, "2026-09": nueva})
    assert gb.PERIODO_VIGENTE == "2026-09" and gb.GRILLA.startswith("septiembre")
    gb.registrar(base)
    assert gb.PERIODO_VIGENTE == "2026-08"
    assert json.dumps(gb.calcular_recibo({"categoria": 2, "cajero": True}), ensure_ascii=False) == ref
    with pytest.raises(ValueError):
        gb.grilla("2026-09")


def test_arranque_sin_tabla(monkeypatch):
    import main
    def boom(*a, **k): raise RuntimeError("tabla inexistente")
    monkeypatch.setattr(db, "sembrar_grillas", boom)
    antes = gb.PERIODO_VIGENTE
    with pytest.raises(RuntimeError):
        main._refrescar_grillas(forzar=True)
    main._grillas_al_dia.__call__()          # el camino de pedidos no propaga
    monkeypatch.setattr(main, "_refrescar_grillas", boom)
    main._grillas_al_dia()
    assert gb.PERIODO_VIGENTE == antes
    assert gb.calcular_recibo({"categoria": 0})["totales"]


def test_arranque_real_con_tabla_borrada():
    with Session(db.engine) as s:
        s.exec(text("DROP TABLE grillasalarial")); s.commit()
    try:
        from fastapi.testclient import TestClient
        import main
        with TestClient(main.app):          # dispara el startup
            assert gb.calcular_recibo({"categoria": 0})["totales"]
    finally:
        db.crear_tablas()


def test_refresco_toma_publicada_nueva_de_otro_proceso(monkeypatch):
    import main
    db.sembrar_grillas()
    main._refrescar_grillas(forzar=True)
    g = copy.deepcopy(gb.grillas_semilla()["2026-08"])
    g["periodo"] = "2026-09"; g["nombre"] = "Septiembre 2026"
    db.guardar_grilla("2026-09", g, estado="publicada")
    main._GRILLAS_SELLO["revisado"] = 0
    main._refrescar_grillas()
    assert gb.PERIODO_VIGENTE == "2026-09"

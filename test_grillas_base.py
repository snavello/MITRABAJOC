# -*- coding: utf-8 -*-
"""Bloque 1 de PLAN_CONVENIO_ESCALAS.md: las grillas salariales en la base.

La tabla `GrillaSalarial`, la siembra desde data/, el índice único de
publicadas y la puerta `grilla_bancaria.registrar`. Con solo la semilla, la
calculadora tiene que dar lo mismo que con los archivos."""
import copy
import json

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, text

import db
import grilla_bancaria as gb

CONV = db.CONVENIO_BANCARIO
ENTRADA = {"rama": "administrativa", "categoria": 4, "cajero": True, "titulo": "universitario",
           "guarderia": True, "conectividad": "mensual", "dia_bancario": True,
           "afiliado": True, "tramo_roe": 2}


@pytest.fixture(autouse=True)
def base_limpia():
    db.crear_tablas()
    with Session(db.engine) as s:
        s.exec(text("DELETE FROM grillasalarial"))
        s.commit()
    yield
    gb.registrar(gb.grillas_semilla())          # el registro es global del proceso


def _siguiente(g, periodo="2026-09", factor=1.019):
    n = copy.deepcopy(g)
    n["periodo"] = periodo
    n["nombre"] = "Septiembre 2026"
    for r in n["ramas"].values():
        for c in r["categorias"]:
            c["basico"] = round(c["basico"] * factor, 2)
    return n


def test_sembrar_es_idempotente():
    semilla = gb.grillas_semilla()
    assert db.sembrar_grillas() == len(semilla)
    assert db.sembrar_grillas() == 0
    pub = db.grillas_publicadas(CONV)
    assert set(pub) == set(semilla)
    assert pub["2026-08"] == semilla["2026-08"]
    fila = db.listar_grillas(CONV)[0]
    assert (fila["estado"], fila["origen"]) == ("publicada", "semilla")


def test_sembrar_respeta_una_publicada_existente():
    g = gb.grillas_semilla()["2026-08"]
    db.guardar_grilla("2026-08", g, estado="publicada", origen="manual", quien="x")
    assert db.sembrar_grillas() == 0
    assert [f["origen"] for f in db.listar_grillas(CONV)] == ["manual"]


def test_registrar_cambia_la_vigente_y_las_constantes():
    base = gb.grillas_semilla()
    agosto = base["2026-08"]
    nueva = _siguiente(agosto)
    nueva["adicionales"]["funcion_cajero"] = agosto["adicionales"]["funcion_cajero"] + 1000
    gb.registrar({**base, "2026-09": nueva})
    assert gb.PERIODO_VIGENTE == "2026-09"
    assert gb.grilla()["periodo"] == "2026-09"
    assert gb.FUNCION_CAJERO == nueva["adicionales"]["funcion_cajero"]
    assert gb.GRILLA.startswith("septiembre 2026")
    assert gb.fila_de_escala(0)[2] == nueva["ramas"]["administrativa"]["categorias"][0]["basico"]
    assert gb.opciones()["periodo"] == "2026-09"
    # Las anteriores siguen disponibles por período.
    assert gb.grilla("2026-08") == agosto


def test_registrar_rechaza_vacio_o_roto_sin_cambiar_nada():
    antes = gb.PERIODO_VIGENTE
    with pytest.raises(ValueError):
        gb.registrar({})
    roto = {"2099-01": {"periodo": "2099-01"}}
    with pytest.raises(KeyError):
        gb.registrar(roto)
    with pytest.raises(ValueError):
        gb.registrar({"2099-01": {"periodo": "2098-12"}})
    assert gb.PERIODO_VIGENTE == antes and "2099-01" not in gb.GRILLAS


def test_publicar_una_nueva_reemplaza_a_la_anterior_del_mismo_periodo():
    g = gb.grillas_semilla()["2026-08"]
    db.sembrar_grillas()
    corregida = copy.deepcopy(g)
    corregida["adicionales"]["guarderia"] += 1
    rid = db.guardar_grilla("2026-08", corregida, estado="retenida",
                            controles={"C2": {"ok": False}}, fuente_pdf="https://x/y.pdf")
    # Mientras está retenida, manda la publicada.
    assert db.grillas_publicadas(CONV)["2026-08"] == g
    assert db.publicar_grilla(rid, "snavello", "corregida a mano") is True
    assert db.grillas_publicadas(CONV)["2026-08"] == corregida
    estados = {f["id"]: f["estado"] for f in db.listar_grillas(CONV)}
    assert estados[rid] == "publicada"
    assert sorted(estados.values()) == ["publicada", "reemplazada"]
    fila = next(f for f in db.listar_grillas(CONV) if f["id"] == rid)
    assert fila["resuelta_por"] == "snavello" and fila["resuelta_en"] and fila["nota"] == "corregida a mano"
    anterior = next(f for f in db.listar_grillas(CONV) if f["estado"] == "reemplazada")
    assert anterior["resuelta_por"] == "snavello"
    # Ya publicada: no se vuelve a publicar ni a descartar.
    assert db.publicar_grilla(rid, "x") is False
    assert db.descartar_grilla(rid, "x") is False


def test_guardar_publicada_directa_reemplaza():
    g = gb.grillas_semilla()["2026-08"]
    db.sembrar_grillas()
    nueva = copy.deepcopy(g)
    nueva["adicionales"]["guarderia"] += 5
    db.guardar_grilla("2026-08", nueva, estado="publicada", origen="automatica", quien="auto")
    assert db.grillas_publicadas(CONV)["2026-08"] == nueva
    assert sorted(f["estado"] for f in db.listar_grillas(CONV)) == ["publicada", "reemplazada"]


def test_descartar_una_retenida():
    g = gb.grillas_semilla()["2026-08"]
    rid = db.guardar_grilla("2026-09", _siguiente(g), estado="retenida")
    assert db.descartar_grilla(rid, "snavello", "no era") is True
    assert db.listar_grillas(CONV)[0]["estado"] == "descartada"
    assert db.publicar_grilla(rid, "x") is False
    assert "2026-09" not in db.grillas_publicadas(CONV)


def test_indice_unico_de_publicadas_por_periodo():
    g = gb.grillas_semilla()["2026-08"]
    db.sembrar_grillas()
    with pytest.raises(IntegrityError):
        with Session(db.engine) as s:
            s.add(db.GrillaSalarial(convenio=CONV, periodo="2026-08", estado="publicada", contenido=g))
            s.commit()
    # Varias retenidas / descartadas del mismo período sí pueden convivir.
    with Session(db.engine) as s:
        for estado in ("retenida", "retenida", "descartada", "reemplazada"):
            s.add(db.GrillaSalarial(convenio=CONV, periodo="2026-08", estado=estado, contenido=g))
        # y otro convenio puede tener su publicada del mismo período
        s.add(db.GrillaSalarial(convenio="otro", periodo="2026-08", estado="publicada", contenido=g))
        s.commit()


def test_sello_cambia_cuando_cambian_las_publicadas():
    g = gb.grillas_semilla()["2026-08"]
    db.sembrar_grillas()
    s0 = db.sello_grillas(CONV)
    assert db.sello_grillas(CONV) == s0
    rid = db.guardar_grilla("2026-08", copy.deepcopy(g), estado="retenida")
    assert db.sello_grillas(CONV) == s0                     # una retenida no cambia nada
    db.publicar_grilla(rid, "x")
    assert db.sello_grillas(CONV) != s0
    s1 = db.sello_grillas(CONV)
    db.guardar_grilla("2026-09", _siguiente(g), estado="publicada", quien="auto")
    assert db.sello_grillas(CONV) != s1


def test_el_refresco_de_main_toma_lo_publicado():
    import main
    g = gb.grillas_semilla()["2026-08"]
    main._refrescar_grillas(forzar=True)
    assert gb.PERIODO_VIGENTE == "2026-08"
    db.guardar_grilla("2026-09", _siguiente(g), estado="publicada", quien="auto")
    main._refrescar_grillas()                               # dentro de los 60 s: no mira
    assert gb.PERIODO_VIGENTE == "2026-08"
    main._GRILLAS_SELLO["revisado"] = 0.0
    main._refrescar_grillas()
    assert gb.PERIODO_VIGENTE == "2026-09"


def test_el_orden_de_las_listas_sobrevive_al_jsonb():
    # La base devuelve las claves de un objeto en otro orden (JSONB): el
    # registro tiene que dejar ramas, títulos y zonas como en el archivo.
    db.sembrar_grillas()
    de_base = db.grillas_publicadas(CONV)
    gb.registrar(de_base)
    o = gb.opciones()
    assert list(o["ramas"]) == ["administrativa", "maestranza", "ordenanza"]
    assert o["titulos"] == ["secundario", "terciario", "universitario"]
    assert o["zonas"] == list(gb.grillas_semilla()["2026-08"]["adicionales"]["zona_patagonica"])


def test_con_solo_la_semilla_la_calculadora_da_lo_mismo():
    antes = json.dumps(gb.calcular_recibo(ENTRADA), sort_keys=True)
    opciones_antes = json.dumps(gb.opciones(), sort_keys=True)
    constantes_antes = (gb.GRILLA, gb.ESCALA_ADMINISTRATIVA, dict(gb.JERARQUIAS), gb.TITULOS,
                        gb.ZONA_PATAGONICA, gb.ROE_TABLA, gb.TRAMOS_ROE, gb.DIA_BANCARIO_MINIMO)
    db.sembrar_grillas()
    gb.registrar(db.grillas_publicadas(CONV))
    assert json.dumps(gb.calcular_recibo(ENTRADA), sort_keys=True) == antes
    assert json.dumps(gb.opciones(), sort_keys=True) == opciones_antes
    assert (gb.GRILLA, gb.ESCALA_ADMINISTRATIVA, dict(gb.JERARQUIAS), gb.TITULOS,
            gb.ZONA_PATAGONICA, gb.ROE_TABLA, gb.TRAMOS_ROE, gb.DIA_BANCARIO_MINIMO) == constantes_antes

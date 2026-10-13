# -*- coding: utf-8 -*-
"""La grilla bancaria (agosto 2026) y los recibos sintéticos de La Bancaria.

Los números se comparan contra lo que publicó la Asociación Bancaria (el
comunicado y la grilla firmada, `docs/cct-1875-bancarios.md`): si alguien
toca un monto por error, o el lote vuelve a calcular adicionales como % del
inicial, esto falla."""
import random

import grilla_bancaria as g


def test_el_inicial_del_comunicado():
    # "Salario Inicial + ROE: $ 2.505.061,24 + $ 72.413,50 = $ 2.577.474,74"
    _, coef, basico, conformado = g.fila_de_escala(0)
    assert (coef, basico, conformado) == (1.00, 1_642_764.63, 2_505_061.24)
    assert g.roe_mensual(conformado, 1) == 72_413.50
    assert round(conformado + g.roe_mensual(conformado, 1), 2) == 2_577_474.74


def test_basico_y_conformado_no_son_lo_mismo():
    for desde, _, basico, conformado in g.ESCALA_ADMINISTRATIVA:
        assert basico >= 1_642_764.63
        if desde <= 15:
            assert conformado is not None and conformado > basico
        else:
            # Desde los 20 años el básico ya supera al conformado de 15.
            assert conformado is None and basico > 2_540_849.85


def test_desde_los_4_anos_el_basico_sigue_al_coeficiente():
    # Básico ≈ coeficiente × $ 1.474.068 (la grilla redondea por categoría).
    for desde, coef, basico, _ in g.ESCALA_ADMINISTRATIVA:
        if desde >= 4:
            assert abs(basico / coef - 1_474_068) < 15


def test_la_escala_toma_el_tramo_cumplido():
    assert g.fila_de_escala(17)[0] == 15
    assert g.fila_de_escala(38)[0] == 35
    assert g.categoria_de(22) == "Jefe de Sección"


def test_roe_por_tramo_de_bruto_y_de_banco():
    assert g.roe_mensual(3_275_626, 5) == round(1_642_844.40 / 12, 2)
    assert g.roe_mensual(3_275_627, 5) == round(3_080_333.26 / 12, 2)
    assert g.roe_mensual(9_000_000, 3) == round(4_412_680.07 / 12, 2)
    assert all(g.roe_mensual(b, 0) == 0 for b in (1, 4_000_000, 9_000_000))


def test_dia_del_bancario():
    assert g.dia_del_bancario(1.00) == 2_233_175.44
    # Tabla de la grilla, rama administrativa: 20 años (1,74) $ 2.425.205,15.
    assert abs(g.dia_del_bancario(1.74) - 2_425_205.15) < 0.02


def test_el_lote_usa_montos_de_la_grilla():
    import cargar_bancaria as cb
    importes_validos = {
        "CAJFUN": {g.FUNCION_CAJERO}, "CAJFAL": {g.FALLA_DE_CAJA},
        "TITULO": set(g.TITULOS.values()), "ZONA": set(g.ZONA_PATAGONICA.values()),
        "BAS": {f[2] for f in g.ESCALA_ADMINISTRATIVA},
    }
    rnd = random.Random(1)
    vistos = set()
    for i in range(300):
        cuil = f"2066{i:07d}"
        trab = {"cuil": cuil, "semilla": int(cuil[-7:]),
                "empresa": {"cuit": f"30{i % 7:09d}", "razon": "Banco"}}
        lineas = cb.componer_recibo_bancario(rnd, trab, [], None)
        por_codigo = {l["codigo"]: l["importe"] for l in lineas}
        vistos |= set(por_codigo)
        for codigo, validos in importes_validos.items():
            if codigo in por_codigo:
                assert por_codigo[codigo] in validos, (codigo, por_codigo[codigo])
        _, _, basico, conformado = g.fila_de_escala(cb.antiguedad_de(cuil))
        assert por_codigo["BAS"] == basico
        if conformado and conformado > basico:
            assert round(por_codigo["BAS"] + por_codigo["CONFOR"], 2) == conformado
        else:
            assert "CONFOR" not in por_codigo
        # El ROE del mes sale del bruto SIN el ROE y del tramo de su banco.
        bruto = sum(v for c, v in por_codigo.items() if c not in ("ROE", "CUOTA"))
        roe = g.roe_mensual(bruto, cb.tramo_roe_del_banco(trab["empresa"]["cuit"]))
        assert por_codigo.get("ROE", 0) == roe
    # Ninguno de los adicionales sin monto vigente en la grilla.
    assert not vistos & {"COMPU", "TECNICO", "MAQCON", "PORTAV", "NOCTUR"}
    assert {"BAS", "CONFOR", "ROE", "CAJFUN", "TITULO", "ZONA"} <= vistos


def _validar_como_la_app(sid, recibo):
    """Lo que hacen /api/leer + /api/validar con un recibo ya leído: los
    códigos que el catálogo no conoce se dan de alta como pendientes (los
    aportes de ley, vinculados a su genérico) y después se valida."""
    import db
    import validador
    from db import Concepto
    from main import CATEGORIAS_UNIVERSALES
    from sqlmodel import select
    cuit_emp = recibo["empleador"]["cuit"]
    nuevos = validador.detectar_nuevos(db.conceptos_como_dicts(sid), recibo["lineas"], cuit_emp)
    with db.get_session() as s:
        catalogo = s.exec(select(Concepto).where(Concepto.sindicato_id == sid)).all()
        existentes = {(c.codigo, c.cuit_empleador or "") for c in catalogo}
        genericos = {c.codigo for c in catalogo if not c.cuit_empleador}
        for n in nuevos:
            if (n["codigo"], cuit_emp) in existentes:
                continue
            universal = CATEGORIAS_UNIVERSALES.get(n.get("categoria_universal"))
            s.add(Concepto(sindicato_id=sid, codigo=n["codigo"], nombre=n["descripcion"],
                           tipo=n["tipo"], remunerativo=n.get("remunerativo", n["tipo"] == "ingreso"),
                           alias=[n["descripcion"]], pendiente_revision=True, cuit_empleador=cuit_emp,
                           codigo_generico=universal if universal in genericos else None))
            existentes.add((n["codigo"], cuit_emp))
        s.commit()
    return validador.validar(db.conceptos_como_dicts(sid), db.formulas_como_dicts(sid), recibo,
                             tope_sindical_pct=db.obtener_tope_sindical(), cuil_sesion=recibo["empleado"]["cuil"],
                             topes=db.topes_como_dicts())


def test_los_diez_pdf_de_prueba_dan_lo_que_anuncian():
    """Los recibos de docs/recibos-bancaria-prueba/: siete OK y tres con el
    error que dice su nombre. Se arman igual que el PDF (sin reportlab)."""
    import importlib.util
    import os
    import cargar_bancaria
    import db
    ruta = os.path.join(os.path.dirname(__file__), "docs", "recibos-bancaria-prueba", "generar.py")
    spec = importlib.util.spec_from_file_location("generar_recibos_bancaria", ruta)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    db.sembrar_topes_si_vacio()
    sid = cargar_bancaria.crear_sindicato()
    aportes = {"0501": "jubilacion", "0502": "pami", "0503": "obra_social", "0510": "cuota_sindical"}
    esperado = {"08-ERROR-jubilacion-10": {"formula:JUBILACION"},
                "09-ERROR-sin-obra-social": {"concepto_faltante:OBRASOCIAL"},
                "10-ERROR-neto-mal-sumado": {"total_inconsistente:neto"}}
    assert len(gen.CASOS) == 10
    for caso in gen.CASOS:
        gen._completar(caso)
        haberes, descuentos, bruto, total_desc, neto = gen.armar(caso)
        lineas = [{"codigo": c, "descripcion": d, "importe": i, "tipo": "remuneracion",
                   "seccion": "haberes", "categoria_universal": None} for c, d, i in haberes]
        lineas += [{"codigo": c, "descripcion": d, "importe": -i,
                    "tipo": "aporte_trabajador" if c in aportes else "otro",
                    "seccion": "descuentos", "categoria_universal": aportes.get(c)}
                   for c, d, i in descuentos]
        recibo = {"formato": "clasico", "periodo": gen.PERIODO, "lineas": lineas,
                  "empleado": {"cuil": gen.CUIL, "apellido_nombre": gen.NOMBRE},
                  "empleador": {"nombre": gen.BANCOS[caso["banco"]][0],
                                "cuit": gen.BANCOS[caso["banco"]][1]},
                  "totales_impresos": {"remuneraciones": bruto, "descuentos": -total_desc,
                                       "neto": neto}}
        r = _validar_como_la_app(sid, recibo)
        hallado = {f"{d['tipo']}:{d.get('codigo')}" for d in r["discrepancias"]}
        assert hallado == esperado.get(caso["archivo"], set()), (caso["archivo"], hallado)
    # El tope de la seguridad social: el caso 6 aporta sobre el tope, no sobre el bruto.
    caso6 = next(c for c in gen.CASOS if c["archivo"].startswith("06-"))
    _, descuentos, bruto, _, _ = gen.armar(caso6)
    assert bruto > gen.TOPE and descuentos[0][2] == round(gen.TOPE * 0.11, 2)

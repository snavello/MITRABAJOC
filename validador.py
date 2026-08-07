"""Motor de validación de recibos. Matchea conceptos y evalúa fórmulas.

Sin dependencias externas: solo biblioteca estándar.
Verificado contra recibos reales AEFIP (ago/sep 2024): diferencia 0.00.
"""
import unicodedata

TOLERANCIA_TOTALES = 1.0  # pesos


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.upper().split())


def indexar_conceptos(conceptos: list) -> dict:
    """{codigo o alias normalizado: concepto} para matchear líneas del recibo."""
    idx = {}
    for c in conceptos:
        idx[c["codigo"]] = c
        idx[normalizar(c["nombre"])] = c
        for a in c.get("alias", []):
            idx[normalizar(a)] = c
    return idx


def matchear_lineas(lineas: list, idx: dict):
    matcheadas, desconocidas = [], []
    for ln in lineas:
        concepto = idx.get(ln.get("codigo")) or idx.get(normalizar(ln.get("descripcion", "")))
        if concepto:
            matcheadas.append({**ln, "concepto": concepto})
        else:
            desconocidas.append(ln)
    return matcheadas, desconocidas


def _evaluar(expr: str, variables: dict) -> float:
    # Entorno restringido: sin builtins. Las expresiones vienen de la tabla de fórmulas.
    return float(eval(expr, {"__builtins__": {}}, variables))


def validar(conceptos: list, formulas: list, recibo: dict, tope_sindical_pct: float = 2.0) -> dict:
    idx = indexar_conceptos(conceptos)
    matcheadas, desconocidas = matchear_lineas(recibo["lineas"], idx)

    ingresos = [m for m in matcheadas if m["concepto"]["tipo"] == "ingreso"]
    descuentos = [m for m in matcheadas if m["concepto"]["tipo"] == "descuento"]
    importe_por_codigo = {m["concepto"]["codigo"]: m["importe"] for m in matcheadas}

    variables = {
        "total_ingresos": sum(m["importe"] for m in ingresos),
        "base_remunerativa": sum(
            m["importe"] for m in ingresos
            if m["concepto"].get("remunerativo", True)
        ),
        "c": lambda codigo: importe_por_codigo.get(codigo, 0.0),
    }

    resultados, discrepancias = [], []

    for f in formulas:
        codigo = f["target"]
        if codigo not in importe_por_codigo:
            discrepancias.append({
                "tipo": "concepto_faltante", "codigo": codigo,
                "detalle": f"El recibo no incluye '{f['descripcion']}'.",
            })
            continue
        esperado = _evaluar(f["expr"], variables)
        real = abs(importe_por_codigo[codigo])  # los descuentos figuran en negativo
        dif = round(real - esperado, 2)
        ok = abs(dif) <= f.get("tolerancia", 1.0)
        resultados.append({
            "codigo": codigo, "descripcion": f["descripcion"],
            "esperado": round(esperado, 2), "en_recibo": round(real, 2),
            "diferencia": dif, "ok": ok,
        })
        if not ok:
            discrepancias.append({
                "tipo": "formula", "codigo": codigo,
                "detalle": f"{f['descripcion']}: esperado ${esperado:,.2f}, "
                           f"figura ${real:,.2f} (diferencia ${dif:,.2f}).",
            })

    # Consistencia interna: la suma de líneas debe coincidir con los totales impresos.
    impresos = recibo.get("totales_impresos") or {}
    checks = [
        ("remuneraciones", variables["total_ingresos"], impresos.get("remuneraciones")),
        ("descuentos", sum(m["importe"] for m in descuentos), impresos.get("descuentos")),
        ("neto", sum(m["importe"] for m in matcheadas), impresos.get("neto")),
    ]
    for nombre, calculado, impreso in checks:
        if impreso is None:
            continue
        if abs(round(calculado - impreso, 2)) > TOLERANCIA_TOTALES:
            discrepancias.append({
                "tipo": "total_inconsistente", "codigo": nombre,
                "detalle": f"Suma de {nombre} (${calculado:,.2f}) no coincide con el "
                           f"impreso (${impreso:,.2f}). Puede ser un error de lectura; "
                           "conviene revisar la foto antes de reportar.",
            })

    avisos = [{
        "codigo": ln.get("codigo"), "descripcion": ln.get("descripcion"),
        "importe": ln.get("importe"),
    } for ln in desconocidas]

    # Ley 27.802 art. 133 / Dto 407/2026: tope global a las cargas sindicales de
    # convenio (cuota solidaria, fondos convencionales). NO es un error de cálculo:
    # es una advertencia de posible retención en exceso, separada de discrepancias.
    alertas = []
    cargas_convenio = sum(
        abs(m.get("importe", 0) or 0) for m in matcheadas
        if m.get("tipo") == "aporte_trabajador" and m["concepto"].get("categoria_sindical") == "convenio"
    )
    cargas_afiliacion = sum(
        abs(m.get("importe", 0) or 0) for m in matcheadas
        if m.get("tipo") == "aporte_trabajador" and m["concepto"].get("categoria_sindical") == "afiliacion"
    )
    # Retención de cuota sindical (convenio + afiliación): la base para que el
    # trabajador, si quiere, se la envíe al sindicato como prueba de afiliado
    # cotizante (art. 21 bis, Dto 407/2026). Solo "convenio" cuenta para el tope.
    retencion_sindical = {
        "convenio": round(cargas_convenio, 2),
        "afiliacion": round(cargas_afiliacion, 2),
        "total": round(cargas_convenio + cargas_afiliacion, 2),
    }
    base_remunerativa = variables["base_remunerativa"]
    if base_remunerativa > 0:
        tope_pesos = tope_sindical_pct / 100 * base_remunerativa
        if cargas_convenio > tope_pesos:
            pct_real = round(cargas_convenio / base_remunerativa * 100, 2)
            alertas.append({
                "tipo": "tope_sindical",
                "detalle": f"Las cargas sindicales de convenio (${cargas_convenio:,.2f}, "
                           f"{pct_real}% de la remuneración) superan el tope legal del "
                           f"{tope_sindical_pct}% (art. 133 Ley 27.802). Puede ser una "
                           "retención en exceso: conviene revisarlo con el sindicato.",
            })

    return {
        "periodo": recibo.get("periodo"),
        "cuil": (recibo.get("empleado") or {}).get("cuil"),
        "estado": "OK" if not discrepancias else "CON_DISCREPANCIAS",
        "formulas_validadas": resultados,
        "discrepancias": discrepancias,
        "avisos": avisos,
        "alertas": alertas,
        "retencion_sindical": retencion_sindical,
        "totales": {
            "remunerativo": round(variables["base_remunerativa"], 2),
            "ingresos": round(variables["total_ingresos"], 2),
            "descuentos": round(abs(sum(m["importe"] for m in descuentos)), 2),
        },
    }


def detectar_nuevos(conceptos: list, lineas: list) -> list:
    """Devuelve las líneas del recibo cuyo concepto no está en el catálogo.

    Cada una viene con el tipo inferido del signo del importe. Estos conceptos
    se dan de alta como pendientes de revisión; hasta que el sindicato los
    clasifique, no participan de la base de cálculo.
    """
    idx = indexar_conceptos(conceptos)
    nuevos, vistos = [], set()
    for ln in lineas:
        concepto = idx.get(ln.get("codigo")) or idx.get(normalizar(ln.get("descripcion", "")))
        if concepto:
            continue
        # Clave para no duplicar si el mismo concepto nuevo aparece dos veces.
        clave = ln.get("codigo") or normalizar(ln.get("descripcion", ""))
        if clave in vistos:
            continue
        vistos.add(clave)
        importe = ln.get("importe", 0) or 0
        nuevos.append({
            "codigo": ln.get("codigo") or f"NUEVO-{clave[:12]}",
            "descripcion": ln.get("descripcion", "(sin descripción)"),
            "importe": importe,
            "tipo": "descuento" if importe < 0 else "ingreso",
        })
    return nuevos

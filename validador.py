"""Motor de validación de recibos. Matchea conceptos y evalúa fórmulas.

Sin dependencias externas: solo biblioteca estándar.
Verificado contra recibos reales AEFIP (ago/sep 2024): diferencia 0.00.
"""
import re
import difflib
import unicodedata

TOLERANCIA_TOTALES = 1.0  # pesos

# Código que se le pone a un concepto detectado en un recibo cuando la IA no
# pudo leer su código. Ver detectar_nuevos() y detectar_provisorios().
PREFIJO_PROVISORIO = "NUEVO-"
UMBRAL_SIMILITUD = 0.75


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.upper().split())


def _norm_cuil(cuil: str) -> str:
    return re.sub(r"[^0-9]", "", cuil or "")


def indexar_conceptos(conceptos: list, cuit_empleador: str = None) -> dict:
    """{codigo o alias normalizado: concepto} para matchear líneas del recibo.

    Con muchos empleadores por sindicato, un concepto puede ser específico de
    uno (`cuit_empleador` cargado) o genérico (`cuit_empleador` NULL, visible
    para cualquier recibo). Se indexan primero los genéricos y después los
    específicos del CUIT del recibo, así estos últimos pisan a los genéricos
    en caso de colisión de clave: el específico es siempre más preciso. Si no
    se pasa `cuit_empleador` (o no hay conceptos de ese CUIT), el resultado es
    el catálogo genérico de siempre.
    """
    idx = {}
    genericos = [c for c in conceptos if not c.get("cuit_empleador")]
    especificos = [c for c in conceptos if cuit_empleador and c.get("cuit_empleador") == cuit_empleador]
    for c in genericos + especificos:
        idx[c["codigo"]] = c
        idx[normalizar(c["nombre"])] = c
        for a in c.get("alias", []):
            idx[normalizar(a)] = c
    return idx


def codigo_efectivo(concepto: dict) -> str:
    """El código que realmente controla una Formula: el propio `codigo` para
    un concepto genérico, o `codigo_generico` para uno específico de un
    empleador (así todas las variantes de distintos empleadores para "lo
    mismo" se validan con una única fórmula por sindicato, sin duplicarlas)."""
    return concepto.get("codigo_generico") or concepto["codigo"]


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


def validar(conceptos: list, formulas: list, recibo: dict, tope_sindical_pct: float = 2.0,
            cuil_sesion: str = None) -> dict:
    cuit_empleador = _norm_cuil((recibo.get("empleador") or {}).get("cuit"))
    idx = indexar_conceptos(conceptos, cuit_empleador)
    matcheadas, desconocidas = matchear_lineas(recibo["lineas"], idx)

    ingresos = [m for m in matcheadas if m["concepto"]["tipo"] == "ingreso"]
    descuentos = [m for m in matcheadas if m["concepto"]["tipo"] == "descuento"]
    # Las fórmulas siempre apuntan a un código genérico (ver codigo_efectivo):
    # un concepto específico de un empleador aporta su importe bajo ESE código,
    # no bajo el propio, para que una sola fórmula controle a todos los
    # empleadores sin tener que duplicarla por cada variante.
    importe_por_codigo = {codigo_efectivo(m["concepto"]): m["importe"] for m in matcheadas}

    variables = {
        "total_ingresos": sum(m["importe"] for m in ingresos),
        "base_remunerativa": sum(
            m["importe"] for m in ingresos
            if m["concepto"].get("remunerativo", True)
        ),
        "c": lambda codigo: importe_por_codigo.get(codigo, 0.0),
    }

    resultados, discrepancias = [], []

    # El CUIL que leyó la IA del recibo tiene que ser el mismo que el de la
    # sesión (no el que diga el trabajador): evita validar/enviar el recibo
    # de otra persona, a propósito o por error.
    cuil_recibo = _norm_cuil((recibo.get("empleado") or {}).get("cuil"))
    cuil_sesion_norm = _norm_cuil(cuil_sesion)
    if cuil_recibo and cuil_sesion_norm and cuil_recibo != cuil_sesion_norm:
        discrepancias.append({
            "tipo": "cuil_no_coincide",
            "detalle": f"Este recibo pertenece al CUIL {cuil_recibo}, pero iniciaste sesión "
                       f"con el CUIL {cuil_sesion_norm}. Verificá que sea tu propio recibo "
                       "antes de continuar.",
        })

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
            "neto": round(variables["total_ingresos"] - abs(sum(m["importe"] for m in descuentos)), 2),
        },
    }


def detectar_nuevos(conceptos: list, lineas: list, cuit_empleador: str = None) -> list:
    """Devuelve las líneas del recibo cuyo concepto no está en el catálogo
    (genérico o específico del `cuit_empleador` del recibo, si se pasa).

    Cada una viene con el tipo inferido del signo del importe. Estos conceptos
    se dan de alta como pendientes de revisión; hasta que el sindicato los
    clasifique, no participan de la base de cálculo.
    """
    idx = indexar_conceptos(conceptos, cuit_empleador)
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
            "codigo": ln.get("codigo") or f"{PREFIJO_PROVISORIO}{clave[:12]}",
            "descripcion": ln.get("descripcion", "(sin descripción)"),
            "importe": importe,
            "tipo": "descuento" if importe < 0 else "ingreso",
        })
    return nuevos


def es_codigo_provisorio(codigo) -> bool:
    return str(codigo or "").startswith(PREFIJO_PROVISORIO)


def _clave_similitud(texto: str) -> str:
    """Normalización agresiva SOLO para comparar parecidos entre sí.
    NO se usa para matchear líneas del recibo: ahí la comparación sigue siendo
    por código exacto o por nombre/alias normalizado (ver indexar_conceptos)."""
    return re.sub(r"[^A-Z0-9]", "", normalizar(texto))


def similitud(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _clave_similitud(a), _clave_similitud(b)).ratio()


def buscar_similar(nombre: str, conceptos: list, excluir_codigo=None) -> dict | None:
    """El concepto de código real más parecido a `nombre`, o None.

    Solo mira conceptos con código real: uno provisorio no sirve de referencia.
    """
    mejor, mejor_ratio = None, 0.0
    for c in conceptos:
        if es_codigo_provisorio(c.get("codigo")):
            continue
        if excluir_codigo is not None and c.get("codigo") == excluir_codigo:
            continue
        for candidato in [c.get("nombre", "")] + list(c.get("alias") or []):
            r = similitud(nombre, candidato)
            if r > mejor_ratio:
                mejor, mejor_ratio = c, r
    if mejor is not None and mejor_ratio >= UMBRAL_SIMILITUD:
        return {"concepto": mejor, "ratio": round(mejor_ratio, 3)}
    return None


def detectar_provisorios(conceptos: list) -> list:
    """Conceptos con código provisorio, con el existente más parecido si lo hay.

    Un código provisorio nunca va a matchear por código contra un recibo real
    (ningún recibo trae 'NUEVO-...'), así que solo puede matchear por nombre:
    son frágiles y hay que revisarlos, sean duplicados o no.

    Por qué se filtra por código provisorio y no solo por similitud de nombre:
    medido sobre un catálogo real de 33 conceptos, comparar por nombre a secas
    da 6 falsos positivos por cada duplicado real — las variantes por grado del
    escalafón ('PERMANENCIA EN EL GRUPO' vs '...GRUPO 26', 0.95) se parecen MÁS
    entre sí que el duplicado verdadero (0.82). El umbral solo no los separa.
    """
    resultado = []
    for c in conceptos:
        if not es_codigo_provisorio(c.get("codigo")):
            continue
        resultado.append({
            "concepto": c,
            "similar": buscar_similar(c.get("nombre", ""), conceptos, excluir_codigo=c.get("codigo")),
        })
    return resultado

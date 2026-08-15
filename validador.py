"""Motor de validación de recibos. Matchea conceptos y evalúa fórmulas.

Sin dependencias externas: solo biblioteca estándar.
Verificado contra recibos reales AEFIP (ago/sep 2024): diferencia 0.00.
"""
import re
import difflib
import unicodedata
from collections import defaultdict

TOLERANCIA_TOTALES = 1.0  # pesos

# Código que se le pone a un concepto detectado en un recibo cuando la IA no
# pudo leer su código. Ver detectar_nuevos() y detectar_provisorios().
PREFIJO_PROVISORIO = "NUEVO-"
UMBRAL_SIMILITUD = 0.75

# Aportes de ley, casi idénticos en cualquier recibo argentino en blanco
# (cambia el nombre/código que le puso cada empleador, no el %). El
# extractor (ver extractor.py) etiqueta cada línea de aporte del trabajador
# con una de estas 4 categorías cuando la reconoce con confianza; acá se
# mapean al código genérico FIJO con el que se busca/sugiere el concepto en
# el catálogo del sindicato. "jubilacion"/"pami"/"obra_social" se autocargan
# (concepto + fórmula) al dar de alta un sindicato — ver db.crear_conceptos_universales().
# "cuota_sindical" NO se autocarga (el % varía por sindicato) pero si el
# admin crea a mano un concepto genérico con este código, se beneficia del
# mismo mecanismo de sugerencia/respaldo.
CATEGORIAS_UNIVERSALES = {
    "jubilacion": "JUBILACION",
    "pami": "PAMI",
    "obra_social": "OBRASOCIAL",
    "cuota_sindical": "CUOTA_SINDICAL",
}

# Aclaraciones en lenguaje llano para discrepancias de aportes sujetos a
# tope de base imponible (ver TopeSS_contexto.md, puntos 2.3 y 2.5) -- se
# agregan al `detalle` de la discrepancia, no son un campo aparte: así el
# frontend (que ya renderiza discrepancia.detalle tal cual) no necesita
# ningún cambio para mostrarlas.
NOTA_LIQUIDACIONES_MULTIPLES = (
    "Este aporte tiene un tope máximo mensual. Si tuviste más de un recibo "
    "este mes (por ejemplo, un adelanto y una liquidación complementaria, "
    "o más de un empleador), es posible que el tope ya se haya alcanzado "
    "con el otro recibo y que este esté bien igual. No podemos confirmarlo "
    "mirando un solo recibo."
)
NOTA_PISO_PROPORCIONAL = (
    "Además, el monto mínimo sobre el que se calculan estos aportes se "
    "reduce si trabajaste jornada parcial o no trabajaste el mes completo "
    "(por ejemplo, si empezaste o dejaste el trabajo a mitad de mes). Si es "
    "tu caso, el cálculo del recibo puede ser correcto igual."
)

# Los 3 que se autocargan al crear un sindicato (ver db.crear_conceptos_universales).
CONCEPTOS_UNIVERSALES = [
    {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)", "pct": 0.11,
     "descripcion_formula": "Jubilación (SIPA) = 11% del remunerativo"},
    {"codigo": "PAMI", "nombre": "Ley 19.032 (PAMI)", "pct": 0.03,
     "descripcion_formula": "Ley 19.032 (PAMI) = 3% del remunerativo"},
    {"codigo": "OBRASOCIAL", "nombre": "Obra Social", "pct": 0.03,
     "descripcion_formula": "Obra Social = 3% del remunerativo"},
]


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.upper().split())


def _norm_cuil(cuil: str) -> str:
    return re.sub(r"[^0-9]", "", cuil or "")


def _mes(fecha: str) -> str:
    """'AAAA-MM' o 'AAAA-MM-DD' -> 'AAAA-MM' (para comparar por mes; el
    período del recibo solo tiene resolución mensual)."""
    return (fecha or "")[:7]


def formula_vigente_en(formula: dict, periodo: str) -> bool:
    """¿Esta fórmula regía en el período (AAAA-MM) del recibo?

    fecha_desde/fecha_hasta en None = sin límite de ese lado (una fórmula sin
    fechas cargadas sigue vigente siempre, igual que antes de esta feature).
    Si la fórmula SÍ tiene un límite de un lado pero no se puede determinar el
    período del recibo, no se la considera vigente para ese lado: mejor no
    chequear el concepto que aplicar una fórmula que podría no corresponder.
    """
    mp = _mes(periodo)
    desde, hasta = formula.get("fecha_desde"), formula.get("fecha_hasta")
    if desde and (not mp or mp < _mes(desde)):
        return False
    if hasta and (not mp or mp > _mes(hasta)):
        return False
    return True


def tope_vigente_en(topes: list, periodo: str) -> dict | None:
    """El tope de base imponible de la seguridad social vigente en el
    período (AAAA-MM) del recibo, o None si no hay ninguno cargado para esa
    fecha o antes -- a propósito NO se usa el más cercano (ni anterior ni
    posterior): si no hay dato, no se inventa uno.

    A diferencia de formula_vigente_en (que compara contra un rango
    desde/hasta), acá cada tope no tiene "hasta": rige desde su
    vigencia_desde hasta que empieza el siguiente. Es una búsqueda "as of":
    entre los que ya regían en el período (vigencia_desde <= período), el
    vigente es el de vigencia_desde más reciente."""
    mp = _mes(periodo)
    if not mp:
        return None
    candidatos = [t for t in topes if t.get("vigencia_desde") and t["vigencia_desde"] <= mp]
    if not candidatos:
        return None
    return max(candidatos, key=lambda t: t["vigencia_desde"])


def rangos_se_superponen(desde1, hasta1, desde2, hasta2) -> bool:
    """¿Los rangos [desde1,hasta1] y [desde2,hasta2] (AAAA-MM-DD o None = sin
    límite de ese lado) se pisan en algún período? Los límites son inclusivos:
    un rango que termina en 2020-12 y otro que empieza en 2020-12 SÍ se pisan
    (ambos vigentes ese mes)."""
    d1, h1, d2, h2 = _mes(desde1) or None, _mes(hasta1) or None, _mes(desde2) or None, _mes(hasta2) or None
    cond1 = h2 is None or d1 is None or d1 <= h2
    cond2 = h1 is None or d2 is None or d2 <= h1
    return cond1 and cond2


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
    """Matchea cada línea del recibo contra el catálogo (por código o por
    nombre/alias normalizado). Si una línea no matchea así pero la IA la
    etiquetó con una categoría universal (ver CATEGORIAS_UNIVERSALES) y el
    sindicato tiene el concepto genérico correspondiente, se la matchea IGUAL
    contra ese concepto — red de seguridad para un empleador recién agregado
    que todavía no tiene ningún concepto propio cargado. Esas líneas quedan
    marcadas con "chequeo_automatico": True para que quede claro que no pasó
    por el catálogo curado del sindicato."""
    matcheadas, desconocidas = [], []
    for ln in lineas:
        concepto = idx.get(ln.get("codigo")) or idx.get(normalizar(ln.get("descripcion", "")))
        automatico = False
        if not concepto:
            codigo_universal = CATEGORIAS_UNIVERSALES.get(ln.get("categoria_universal"))
            if codigo_universal:
                concepto = idx.get(codigo_universal)
                automatico = concepto is not None
        if concepto:
            entrada = {**ln, "concepto": concepto}
            if automatico:
                entrada["chequeo_automatico"] = True
            matcheadas.append(entrada)
        else:
            desconocidas.append(ln)
    return matcheadas, desconocidas


def _evaluar(expr: str, variables: dict) -> float:
    # Entorno restringido: sin builtins. Las expresiones vienen de la tabla de fórmulas.
    return float(eval(expr, {"__builtins__": {}}, variables))


def cuil_no_coincide(recibo: dict, cuil_sesion: str) -> bool:
    """¿El CUIL que leyó la IA del recibo es distinto del de la sesión?
    (Si alguno falta, no se puede afirmar que no coincide -> False: no bloquea
    con datos incompletos, solo ante una discrepancia real y verificable.)"""
    cuil_recibo = _norm_cuil((recibo.get("empleado") or {}).get("cuil"))
    cuil_sesion_norm = _norm_cuil(cuil_sesion)
    return bool(cuil_recibo and cuil_sesion_norm and cuil_recibo != cuil_sesion_norm)


def _resultado_bloqueado_por_cuil(recibo: dict, cuil_sesion: str) -> dict:
    cuil_recibo = _norm_cuil((recibo.get("empleado") or {}).get("cuil"))
    cuil_sesion_norm = _norm_cuil(cuil_sesion)
    return {
        "periodo": recibo.get("periodo"),
        "cuil": cuil_recibo,
        "estado": "CUIL_NO_COINCIDE",
        "bloqueado": True,
        "formulas_validadas": [],
        "discrepancias": [{
            "tipo": "cuil_no_coincide",
            "detalle": f"Este recibo pertenece al CUIL {cuil_recibo}, pero iniciaste sesión "
                       f"con el CUIL {cuil_sesion_norm}. No se hizo ningún chequeo: subí tu "
                       "propio recibo para verificarlo.",
        }],
        "avisos": [], "alertas": [],
        "retencion_sindical": {"convenio": 0.0, "afiliacion": 0.0, "total": 0.0},
        "totales": {"remunerativo": 0.0, "ingresos": 0.0, "descuentos": 0.0, "neto": 0.0},
    }


def validar(conceptos: list, formulas: list, recibo: dict, tope_sindical_pct: float = 2.0,
            cuil_sesion: str = None, topes: list = None) -> dict:
    # El CUIL que leyó la IA del recibo tiene que ser el mismo que el de la
    # sesión (no el que diga el trabajador). Si no coincide, se corta ACÁ: no
    # se matchea, no se evalúa ninguna fórmula, no se detecta ninguna
    # discrepancia de monto — evita validar/enviar el recibo de otra persona,
    # a propósito o por error.
    if cuil_no_coincide(recibo, cuil_sesion):
        return _resultado_bloqueado_por_cuil(recibo, cuil_sesion)

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
    # Códigos que solo matchearon por la red de seguridad de categoría
    # universal (ver matchear_lineas) — para avisar en el resultado que ESE
    # chequeo puntual no pasó por el catálogo curado del sindicato.
    codigos_automaticos = {codigo_efectivo(m["concepto"]) for m in matcheadas if m.get("chequeo_automatico")}

    total_ingresos = sum(m["importe"] for m in ingresos)
    base_remunerativa = sum(
        m["importe"] for m in ingresos
        if m["concepto"].get("remunerativo", True)
    )
    # Si no matcheó NINGÚN ingreso (típico junto con la red de seguridad de
    # categoría universal: un sindicato que solo cargó los 3 conceptos
    # genéricos de descuento, sin ningún concepto de haberes para este
    # empleador), la base remunerativa da 0 y las fórmulas de % terminan
    # comparando contra $0 — una discrepancia falsa, no real. Se usa el total
    # de remuneraciones IMPRESO en el recibo como aproximación: mejor una
    # base aproximada que compararlo todo contra cero.
    base_aproximada = False
    if not ingresos:
        impreso_remuneraciones = (recibo.get("totales_impresos") or {}).get("remuneraciones")
        if impreso_remuneraciones is not None:
            total_ingresos = impreso_remuneraciones
            base_remunerativa = impreso_remuneraciones
            base_aproximada = True

    variables = {
        "total_ingresos": total_ingresos,
        "base_remunerativa": base_remunerativa,
        "c": lambda codigo: importe_por_codigo.get(codigo, 0.0),
    }

    resultados, discrepancias = [], []

    # Un mismo target puede tener varias fórmulas históricas (vigencias que no
    # se superponen, se garantiza al cargar/editar — ver rangos_se_superponen).
    # Para este recibo se usa la que regía en SU período, no la fórmula
    # actual. Si ninguna estaba vigente en ese período, el concepto
    # simplemente no se chequea (no se inventa una discrepancia de monto).
    formulas_por_target = defaultdict(list)
    for f in formulas:
        formulas_por_target[f["target"]].append(f)
    periodo_recibo = recibo.get("periodo")

    # Base imponible con tope: el mismo tope (vigente en el período de ESTE
    # recibo) se usa para todas las fórmulas sujetas a tope, así que se
    # busca una sola vez, no por fórmula. Sin tope cargado para el período
    # no se usa el más cercano (ver tope_vigente_en): se evalúa igual con
    # la base sin topear, y se avisa después del loop (alertas).
    topes = topes or []
    tope_periodo = tope_vigente_en(topes, periodo_recibo)
    conceptos_con_tope = []  # descripciones de las fórmulas sujetas a tope evaluadas, para las alertas

    for target, fs in formulas_por_target.items():
        f = next((x for x in fs if formula_vigente_en(x, periodo_recibo)), None)
        if f is None:
            continue
        codigo = f["target"]
        sujeto_a_tope = bool(f.get("sujeto_a_tope"))
        if sujeto_a_tope:
            conceptos_con_tope.append(f["descripcion"])
        if codigo not in importe_por_codigo:
            detalle = f"El recibo no incluye '{f['descripcion']}'."
            if sujeto_a_tope:
                detalle += " " + NOTA_LIQUIDACIONES_MULTIPLES
            discrepancias.append({
                "tipo": "concepto_faltante", "codigo": codigo, "detalle": detalle,
            })
            continue

        variables_f = variables
        aplico_piso = False
        if sujeto_a_tope and tope_periodo:
            base_topeada = min(max(base_remunerativa, tope_periodo["base_minima"]), tope_periodo["tope_maximo"])
            aplico_piso = base_remunerativa < tope_periodo["base_minima"]
            variables_f = dict(variables, base_remunerativa=base_topeada)

        esperado = _evaluar(f["expr"], variables_f)
        real = abs(importe_por_codigo[codigo])  # los descuentos figuran en negativo
        dif = round(real - esperado, 2)
        ok = abs(dif) <= f.get("tolerancia", 1.0)
        resultados.append({
            "codigo": codigo, "descripcion": f["descripcion"],
            "esperado": round(esperado, 2), "en_recibo": round(real, 2),
            "diferencia": dif, "ok": ok,
            "chequeo_automatico": codigo in codigos_automaticos,
        })
        if not ok:
            detalle = (f"{f['descripcion']}: esperado ${esperado:,.2f}, "
                       f"figura ${real:,.2f} (diferencia ${dif:,.2f}).")
            if sujeto_a_tope:
                detalle += " " + NOTA_LIQUIDACIONES_MULTIPLES
                if aplico_piso:
                    detalle += " " + NOTA_PISO_PROPORCIONAL
            discrepancias.append({
                "tipo": "formula", "codigo": codigo, "detalle": detalle,
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

    alertas = []

    # Tope de base imponible de la seguridad social: si hubo al menos una
    # fórmula sujeta a tope evaluada este recibo, se avisa cuando el dato de
    # referencia no es confiable -- sin tope cargado para el período (no se
    # topeó nada, se comparó contra el sueldo completo) o con el tope
    # marcado SOSPECHOSO (se topeó, pero el valor todavía no está
    # verificado contra la resolución oficial de ANSES).
    if conceptos_con_tope:
        lista_conceptos = ", ".join(conceptos_con_tope)
        if tope_periodo is None:
            alertas.append({
                "tipo": "tope_no_verificable",
                "detalle": f"No tenemos cargado el tope de aportes de la seguridad social "
                           f"para {periodo_recibo}, así que {lista_conceptos} se compararon "
                           "contra el sueldo completo, sin aplicar el tope. Si tu remuneración "
                           "de ese mes superó el tope vigente, el resultado de estos conceptos "
                           "puede no ser correcto.",
            })
        elif tope_periodo.get("estado") == "SOSPECHOSO":
            alertas.append({
                "tipo": "tope_sospechoso",
                "detalle": f"El valor de referencia que usamos para el tope de aportes de "
                           f"{periodo_recibo} todavía está pendiente de verificación contra la "
                           "resolución oficial de ANSES. Si más adelante se corrige, el "
                           f"resultado de {lista_conceptos} para este recibo podría cambiar.",
            })

    # Ley 27.802 art. 133 / Dto 407/2026: tope global a las cargas sindicales de
    # convenio (cuota solidaria, fondos convencionales). NO es un error de cálculo:
    # es una advertencia de posible retención en exceso, separada de discrepancias.
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
        "base_remunerativa_aproximada": base_aproximada,
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
            "categoria_universal": ln.get("categoria_universal"),
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

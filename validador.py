"""Motor de validación de recibos. Matchea conceptos y evalúa fórmulas.

Sin dependencias externas: solo biblioteca estándar.
Verificado contra recibos reales AEFIP (ago/sep 2024): diferencia 0.00.
"""
import re
import math
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

# Aclaración en lenguaje llano para discrepancias de aportes sujetos a tope
# de base imponible (ver TopeSS_contexto.md, puntos 2.3 y 2.5). A diferencia
# de las demás notas de discrepancia, ésta NO se agrega al `detalle` de cada
# concepto (se repetiría una vez por cada aporte con tope afectado, jubilación
# + PAMI + obra social) -- se junta una sola vez por recibo en una `alerta`
# (ver más abajo, tope_posible_explicacion).
#
# SOLO vale hacia abajo, y por eso el signo se mira antes de agregarla: que el
# tope se haya alcanzado entre dos recibos puede hacer que un empleador retenga
# de MENOS, nunca de más. Ofrecerla cuando el recibo retuvo de más es peor que
# no decir nada -- tranquiliza justo en el caso en que al trabajador le
# descontaron de más y conviene que consulte. Ese caso tiene su propia alerta
# (tope_no_aplicado, más abajo).
NOTA_TOPE_DISCREPANCIA = (
    "puede deberse a que tuviste más de un recibo este mes (otro empleador, "
    "un adelanto) y el tope se alcanzó entre los dos -- no se puede confirmar "
    "mirando un solo recibo."
)
NOTA_PISO_PROPORCIONAL = " También puede deberse a jornada parcial o mes incompleto."

# Los 3 que se autocargan al crear un sindicato (ver db.crear_conceptos_universales).
CONCEPTOS_UNIVERSALES = [
    {"codigo": "JUBILACION", "nombre": "Aporte jubilatorio (SIPA)", "pct": 0.11,
     "descripcion_formula": "Jubilación (SIPA) = 11% del remunerativo"},
    {"codigo": "PAMI", "nombre": "Ley 19.032 (PAMI)", "pct": 0.03,
     "descripcion_formula": "Ley 19.032 (PAMI) = 3% del remunerativo"},
    {"codigo": "OBRASOCIAL", "nombre": "Obra Social", "pct": 0.03,
     "descripcion_formula": "Obra Social = 3% del remunerativo"},
]


def normalizar(texto) -> str:
    # str() y no solo `texto or ""`: un código numérico (288 en vez de "288")
    # o cualquier valor que no sea texto hacía explotar unicodedata.normalize
    # con un TypeError. Tanto el recibo (lo devuelve un modelo) como el
    # catálogo (lo carga una persona) pueden traer una forma inesperada.
    if texto is None:
        texto = ""
    elif not isinstance(texto, str):
        texto = str(texto)
    t = unicodedata.normalize("NFD", texto)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.upper().split())


def _norm_cuil(cuil: str) -> str:
    return re.sub(r"[^0-9]", "", cuil or "")


def a_numero(valor):
    """Un importe tal como vino de la IA -> float, o None si no se puede leer.

    El extractor tiene instruccion de devolver numeros y de poner null cuando
    algo es ilegible, pero la salida de un modelo NO es un contrato: un null,
    un "1.234,56" o cualquier texto llegaban crudos hasta las sumas de mas
    abajo y reventaban con un TypeError. Como esa excepcion no la manejaba
    nadie, el trabajador terminaba viendo el 500 generico de la app ("proba
    con una foto mas nitida"), que no tenia nada que ver con la causa real.
    Todo importe que entra al motor pasa primero por aca.

    Los separadores se interpretan con el criterio argentino cuando no hay
    ambiguedad posible: coma decimal si separa 1 o 2 digitos finales, y punto
    de miles cuando hay mas de uno. Ante cualquier duda devuelve None (linea
    ilegible, se avisa) en vez de arriesgar un numero equivocado: un importe
    mal leido en silencio es peor que uno declarado ilegible.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if math.isfinite(valor) else None
    if not isinstance(valor, str):
        return None
    t = valor.strip().replace("\u00a0", "").replace(" ", "").replace("$", "")
    if t.startswith("(") and t.endswith(")"):   # (1.234) = negativo
        t = "-" + t[1:-1]
    if not t:
        return None
    if "," in t and "." in t:                   # el ultimo separador es el decimal
        decimal = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif "," in t:
        entero, _, resto = t.rpartition(",")
        t = f"{entero}.{resto}" if len(resto) in (1, 2) else t.replace(",", "")
    elif t.count(".") > 1:                      # 1.234.567 -> puntos de miles
        t = t.replace(".", "")
    try:
        n = float(t)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def lineas_legibles(recibo: dict) -> tuple[list, list]:
    """Separa las lineas del recibo en (utilizables, ilegibles).

    Una linea sin importe numerico no se puede sumar ni comparar: queda
    afuera de los calculos y se informa aparte, en vez de contarla como $0
    (inventaria discrepancias que el recibo no tiene) o de hacer explotar la
    validacion entera por una sola linea que la IA no pudo leer.
    """
    utilizables, ilegibles = [], []
    for ln in recibo.get("lineas") or []:
        if not isinstance(ln, dict):
            continue
        importe = a_numero(ln.get("importe"))
        if importe is None:
            ilegibles.append(ln)
        else:
            utilizables.append({**ln, "importe": importe})
    return utilizables, ilegibles


# Valores de juguete para probar una expresion SIN un recibo real (ver
# error_de_expresion). Los nombres son los mismos que ve una formula al
# validar de verdad; si se agrega una variable al motor, va tambien aca.
VARIABLES_DE_PRUEBA = {
    "total_ingresos": 1000.0,
    "base_remunerativa": 1000.0,
    "c": lambda codigo: 0.0,
}


def error_de_expresion(expr: str) -> str | None:
    """None si la expresion es evaluable; si no, el motivo en castellano.

    Se usa al GUARDAR la formula (ver POST /admin/formula). Antes no se
    probaba nada al guardar, y una formula mal escrita no fallaba ahi: se
    guardaba lo mas tranquila y explotaba semanas despues en la pantalla del
    TRABAJADOR, la primera vez que llegaba un recibo que trajera ese concepto
    (una formula solo se evalua si su concepto esta en el recibo). El que veia
    el error no era el que la habia cargado.
    """
    if not (expr or "").strip():
        return "La expresión está vacía."
    ayuda_coma = (" Ojo con las comas: el decimal se escribe con punto (0.015), "
                  "no con coma.") if "," in expr else ""
    try:
        _evaluar(expr, dict(VARIABLES_DE_PRUEBA))
    except SyntaxError:
        return ("No es una expresión válida: usá punto decimal (0.015), * para "
                "multiplicar, y no escribas el signo %." + ayuda_coma)
    except NameError as e:
        nombre = str(e).split("'")[1] if "'" in str(e) else "?"
        return (f"No existe ninguna variable llamada '{nombre}'. Las que podés "
                'usar son base_remunerativa, total_ingresos y c("CODIGO").')
    except ZeroDivisionError:
        return "La expresión divide por cero."
    except Exception as e:
        return f"No se pudo evaluar ({type(e).__name__})." + ayuda_coma
    return None


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


def _clave(valor) -> str:
    """El código tal cual, pasado a texto y sin espacios de más. Un código
    puede venir como número (del recibo) o con un espacio al final (del
    formulario del admin): sin esto, '288-001 ' y '288-001' son dos claves
    distintas y el concepto cargado no matchea nunca."""
    if valor is None:
        return ""
    return (valor if isinstance(valor, str) else str(valor)).strip()


def _alias_de(concepto: dict) -> list:
    """Los alias de un concepto, sea lo que sea que haya en la columna.

    Es JSON en la base: si por lo que sea quedó un texto suelto en vez de una
    lista, iterarlo devolvía LETRA POR LETRA y ensuciaba el índice de matcheo
    con entradas de un caracter -- sin fallar, que es lo peor: una línea del
    recibo podía matchear contra un concepto equivocado."""
    alias = concepto.get("alias")
    if isinstance(alias, str):
        return [alias]
    if not isinstance(alias, (list, tuple)):
        return []
    return list(alias)


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
    conceptos = [c for c in conceptos if isinstance(c, dict) and _clave(c.get("codigo"))]
    genericos = [c for c in conceptos if not c.get("cuit_empleador")]
    especificos = [c for c in conceptos if cuit_empleador and c.get("cuit_empleador") == cuit_empleador]
    for c in genericos + especificos:
        idx[_clave(c["codigo"])] = c
        nombre = normalizar(c.get("nombre"))
        if nombre:
            idx[nombre] = c
        for a in _alias_de(c):
            clave_alias = normalizar(a)
            if clave_alias:
                idx[clave_alias] = c
    return idx


def codigo_efectivo(concepto: dict) -> str:
    """El código que realmente controla una Formula: el propio `codigo` para
    un concepto genérico, o `codigo_generico` para uno específico de un
    empleador (así todas las variantes de distintos empleadores para "lo
    mismo" se validan con una única fórmula por sindicato, sin duplicarlas)."""
    return _clave(concepto.get("codigo_generico")) or _clave(concepto.get("codigo"))


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
        concepto = idx.get(_clave(ln.get("codigo"))) or idx.get(normalizar(ln.get("descripcion")))
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


import ast as _ast
import operator as _op

_BINOPS = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul,
           _ast.Div: _op.truediv, _ast.Mod: _op.mod, _ast.Pow: _op.pow}
_UNARIOS = {_ast.UAdd: _op.pos, _ast.USub: _op.neg}


def _ev_nodo(nodo, variables):
    """Evalúa UN nodo del árbol de la fórmula. Solo permite lo que una
    fórmula del catálogo necesita; cualquier otra cosa levanta SyntaxError."""
    if isinstance(nodo, _ast.Constant):
        # Solo números. Un string suelto (o bool) no es una fórmula válida;
        # los strings solo valen como el código dentro de c("...").
        if isinstance(nodo.value, bool) or not isinstance(nodo.value, (int, float)):
            raise SyntaxError("solo se permiten números")
        return nodo.value
    if isinstance(nodo, _ast.Name):
        if nodo.id not in variables:
            raise NameError(f"name '{nodo.id}' is not defined")
        return variables[nodo.id]
    if isinstance(nodo, _ast.BinOp) and type(nodo.op) in _BINOPS:
        return _BINOPS[type(nodo.op)](_ev_nodo(nodo.left, variables),
                                      _ev_nodo(nodo.right, variables))
    if isinstance(nodo, _ast.UnaryOp) and type(nodo.op) in _UNARIOS:
        return _UNARIOS[type(nodo.op)](_ev_nodo(nodo.operand, variables))
    if isinstance(nodo, _ast.Call):
        # Única llamada permitida: c("CODIGO") con un string literal.
        if (isinstance(nodo.func, _ast.Name) and nodo.func.id == "c"
                and "c" in variables and len(nodo.args) == 1 and not nodo.keywords
                and isinstance(nodo.args[0], _ast.Constant)
                and isinstance(nodo.args[0].value, str)):
            return variables["c"](nodo.args[0].value)
        raise SyntaxError("llamada no permitida")
    raise SyntaxError("expresión no permitida")


def _evaluar(expr: str, variables: dict) -> float:
    """Evalúa una fórmula del catálogo sin usar la función incorporada de
    Python (XSK H-0005).

    Antes se evaluaba con __builtins__ vacío, que NO es un sandbox: desde un
    literal se llega a las clases del intérprete por dunders y se ejecuta
    código arbitrario. Como la fórmula la escribe un admin de sindicato
    (`/admin/formula`), eso era ejecución de código en el servidor
    multi-tenant. Ahora se parsea a un árbol y se recorre a mano, permitiendo
    solo números, las variables provistas (total_ingresos, base_remunerativa),
    aritmética y la función c("CODIGO"). Se conservan los tipos de excepción
    (SyntaxError/NameError/ZeroDivisionError) que espera error_de_expresion()."""
    # .strip(): en modo "eval" ast.parse NO tolera espacios/saltos al inicio
    # (da IndentationError), cosa que la función incorporada sí aceptaba. Una
    # fórmula guardada como "  0.03*total_ingresos " tiene que evaluar igual.
    arbol = _ast.parse((expr or "").strip(), mode="eval")
    return float(_ev_nodo(arbol.body, variables))


def cuiles_distintos(cuil_leido, cuil_sesion) -> bool:
    """¿Dos CUIL son distintos, normalizados? (Si alguno falta, no se puede
    afirmar que no coinciden -> False: no se bloquea con datos incompletos,
    solo ante una discrepancia real y verificable.)

    Está separado de cuil_no_coincide() porque el comprobante de aportes de
    ARCA trae el CUIL suelto y no adentro de un recibo: el criterio de
    comparación tiene que ser UNO solo para los dos documentos que sube el
    trabajador.
    """
    a, b = _norm_cuil(cuil_leido), _norm_cuil(cuil_sesion)
    return bool(a and b and a != b)


def cuil_no_coincide(recibo: dict, cuil_sesion: str) -> bool:
    """¿El CUIL que leyó la IA del recibo es distinto del de la sesión?"""
    return cuiles_distintos((recibo.get("empleado") or {}).get("cuil"), cuil_sesion)


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
    # Nada de lo que devolvio la IA se usa crudo: los importes se pasan a
    # numero y lo que no se pueda leer queda afuera (ver lineas_legibles).
    lineas, lineas_ilegibles = lineas_legibles(recibo)
    impresos = {k: a_numero(v) for k, v in (recibo.get("totales_impresos") or {}).items()}
    matcheadas, desconocidas = matchear_lineas(lineas, idx)

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
        impreso_remuneraciones = impresos.get("remuneraciones")
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
    formulas_rotas = []      # (descripción, motivo) de las que no se pudieron evaluar
    # Los dos subsets de los de arriba que dieron discrepancia, SEPARADOS por
    # signo: cada uno tiene su explicación y son opuestas (ver
    # NOTA_TOPE_DISCREPANCIA). Un recibo puede caer en las dos listas a la vez
    # (un aporte de menos y otro de más), y entonces se emiten las dos alertas.
    conceptos_tope_retuvo_de_menos = []
    conceptos_tope_retuvo_de_mas = []
    exceso_retenido_con_tope = 0.0   # cuánto suman las diferencias de la 2da lista
    aplico_piso_en_discrepancia = False
    aplico_techo_en_discrepancia = False

    for target, fs in formulas_por_target.items():
        f = next((x for x in fs if formula_vigente_en(x, periodo_recibo)), None)
        if f is None:
            continue
        codigo = f["target"]
        sujeto_a_tope = bool(f.get("sujeto_a_tope"))
        if sujeto_a_tope:
            conceptos_con_tope.append(f["descripcion"])
        if codigo not in importe_por_codigo:
            # No figura la línea: se retuvo 0, que es menos de lo esperado.
            if sujeto_a_tope:
                conceptos_tope_retuvo_de_menos.append(f["descripcion"])
            discrepancias.append({
                "tipo": "concepto_faltante", "codigo": codigo,
                "detalle": f"El recibo no incluye '{f['descripcion']}'.",
            })
            continue

        variables_f = variables
        aplico_piso = aplico_techo = False
        piso = a_numero((tope_periodo or {}).get("base_minima"))
        techo = a_numero((tope_periodo or {}).get("tope_maximo"))
        if sujeto_a_tope and piso is not None and techo is not None:
            base_topeada = min(max(base_remunerativa, piso), techo)
            aplico_piso = base_remunerativa < piso
            aplico_techo = base_remunerativa > techo
            variables_f = dict(variables, base_remunerativa=base_topeada)

        # Una fórmula mal escrita (la carga un humano en /admin) NO puede
        # tumbar la verificación entera del recibo: se saltea ese chequeo y se
        # avisa cuál falló. Ver error_de_expresion(), que además ahora impide
        # guardarla así.
        try:
            esperado = _evaluar(f["expr"], variables_f)
        except Exception as e:
            formulas_rotas.append((f.get("descripcion") or codigo, type(e).__name__))
            continue
        real = abs(importe_por_codigo[codigo])  # los descuentos figuran en negativo
        dif = round(real - esperado, 2)
        tolerancia = a_numero(f.get("tolerancia"))
        ok = abs(dif) <= (1.0 if tolerancia is None else tolerancia)
        resultados.append({
            "codigo": codigo, "descripcion": f["descripcion"],
            "esperado": round(esperado, 2), "en_recibo": round(real, 2),
            "diferencia": dif, "ok": ok,
            "chequeo_automatico": codigo in codigos_automaticos,
        })
        if not ok:
            if sujeto_a_tope and dif < 0:
                conceptos_tope_retuvo_de_menos.append(f["descripcion"])
                aplico_piso_en_discrepancia = aplico_piso_en_discrepancia or aplico_piso
            elif sujeto_a_tope:
                conceptos_tope_retuvo_de_mas.append(f["descripcion"])
                exceso_retenido_con_tope += dif
                aplico_techo_en_discrepancia = aplico_techo_en_discrepancia or aplico_techo
            discrepancias.append({
                "tipo": "formula", "codigo": codigo,
                "detalle": (f"{f['descripcion']}: esperado ${esperado:,.2f}, "
                            f"figura ${real:,.2f} (diferencia ${dif:,.2f})."),
            })

    # Consistencia interna: la suma de líneas debe coincidir con los totales
    # impresos (los que no se hayan podido leer como número valen None y ese
    # chequeo se saltea, igual que cuando el recibo no los trae).
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

    # Líneas que la IA no pudo leer: quedaron afuera de todos los cálculos,
    # así que hay que decirlo -- si no, el trabajador ve un "todo en orden"
    # sacado con un recibo incompleto.
    if lineas_ilegibles:
        cuales = ", ".join(
            (ln.get("descripcion") or ln.get("codigo") or "(sin descripción)")
            for ln in lineas_ilegibles)
        alertas.append({
            "tipo": "importe_ilegible",
            "detalle": f"No pudimos leer el importe de {len(lineas_ilegibles)} línea(s) "
                       f"del recibo ({cuales}), así que quedaron afuera de los cálculos. "
                       "Si el resultado no te cierra, probá con una foto más nítida o "
                       "con el PDF original.",
        })

    # Fórmulas del sindicato que no se pudieron evaluar (mal escritas). Se
    # avisa sin tecnicismos: el trabajador no puede hacer nada, pero tiene que
    # saber que ESE aporte no se chequeó.
    if formulas_rotas:
        cuales = ", ".join(d for d, _ in formulas_rotas)
        alertas.append({
            "tipo": "formula_invalida",
            "detalle": f"No pudimos chequear {cuales}: la fórmula que cargó tu "
                       "sindicato tiene un error de escritura. El resto del recibo se "
                       "verificó igual. Conviene avisarle al sindicato.",
        })

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

    # Aclaración de las discrepancias en conceptos con tope (una sola vez por
    # recibo, no repetida por cada concepto -- ver NOTA_TOPE_DISCREPANCIA).
    # Solo para los que retuvieron de MENOS: es lo único que un tope alcanzado
    # entre dos recibos puede producir. El texto arranca igual sirva la línea
    # con un importe bajo o directamente no figure.
    if conceptos_tope_retuvo_de_menos:
        lista_disc = ", ".join(conceptos_tope_retuvo_de_menos)
        detalle = f"Que figure menos de lo esperado en {lista_disc} {NOTA_TOPE_DISCREPANCIA}"
        if aplico_piso_en_discrepancia:
            detalle += NOTA_PISO_PROPORCIONAL
        alertas.append({"tipo": "tope_posible_explicacion", "detalle": detalle})

    # El caso opuesto: el recibo retuvo MÁS de lo esperado en un aporte con
    # tope, y la app sí topeó la base (o sea, el sueldo del mes superaba el
    # tope y el recibo no lo aplicó). Acá no hay nada que conjeturar: el dato
    # es público y el exceso es una cuenta, así que se dice el hecho -- es
    # accionable frente al sindicato, a diferencia del "no se puede confirmar"
    # del caso de arriba. Si la app NO topeó (sueldo por debajo del tope, o
    # período sin tope cargado), el tope no explica nada y no se dice nada:
    # de ese caso ya avisa tope_no_verificable.
    if conceptos_tope_retuvo_de_mas and aplico_techo_en_discrepancia:
        techo_periodo = a_numero((tope_periodo or {}).get("tope_maximo"))
        lista_exc = ", ".join(conceptos_tope_retuvo_de_mas)
        verbo = "se calculó" if len(conceptos_tope_retuvo_de_mas) == 1 else "se calcularon"
        alertas.append({
            "tipo": "tope_no_aplicado",
            "detalle": (
                f"En {periodo_recibo} la base máxima para aportes de la seguridad "
                f"social era ${techo_periodo:,.2f}, y tu sueldo la superó. En tu recibo "
                f"{lista_exc} {verbo} igual sobre el sueldo completo: te retuvieron "
                f"${round(exceso_retenido_con_tope, 2):,.2f} de más. Un tope no puede hacer "
                "que te retengan de más, así que conviene consultarlo con tu sindicato."
            ),
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
    tope_sindical_pct = a_numero(tope_sindical_pct)
    tope_sindical_pct = 2.0 if tope_sindical_pct is None else tope_sindical_pct
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
        if not isinstance(ln, dict):
            continue
        codigo = _clave(ln.get("codigo"))
        concepto = idx.get(codigo) or idx.get(normalizar(ln.get("descripcion")))
        if concepto:
            continue
        # Clave para no duplicar si el mismo concepto nuevo aparece dos veces.
        clave = codigo or normalizar(ln.get("descripcion"))
        if clave in vistos:
            continue
        vistos.add(clave)
        importe = a_numero(ln.get("importe")) or 0
        nuevos.append({
            "codigo": codigo or f"{PREFIJO_PROVISORIO}{clave[:12]}",
            # a texto sí o sí: esta descripción termina como Concepto.nombre
            # en la base, y una columna de texto no acepta un número.
            "descripcion": str(ln.get("descripcion") or "(sin descripción)"),
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
        for candidato in [c.get("nombre") or ""] + _alias_de(c):
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

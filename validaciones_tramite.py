"""Validaciones de los formularios de Trámites (capa acordada 2026-09-01).

Cada campo de un TipoTramite puede llevar 0..N validaciones, y el tipo puede
llevar reglas de consistencia entre dos campos. Fase 1: fuente "fija" (el
valor del campo contra un límite prefijado por el admin) y consistencia
campo-contra-campo. La forma del dato ya contempla las fuentes futuras
(lista / sistema / externa): cada validación declara su "fuente", y una
fuente no implementada se ignora al evaluar en vez de romper el envío.

Reglas de oro heredadas del proyecto:
- Una validación mal formada NO se guarda (se sanea en el alta, como
  _campos_tramite_validos / error_de_expresion): si se guardara rota,
  fallaría meses después en la pantalla del trabajador y no en la del admin
  que la escribió.
- La MISMA función `evaluar_envio` corre en el envío real, en el banco de
  pruebas del admin y (como espejo JS) en la validación en vivo del
  trabajador. El servidor es siempre la verdad.
- `bloquea=False` ("avisa") no frena el envío: deja el mensaje como
  advertencia visible para el operador del sindicato.

Sin acceso a base de datos a propósito: funciones puras, testeables solas
(test_validaciones_tramite.py).
"""

import ast
import re
import unicodedata
from datetime import date, timedelta

import fechas
import listas as listas_mod

# Operadores admitidos. Se guardan en ASCII; _OP_LEGIBLE es solo para armar
# mensajes por defecto.
OPERADORES = ("<=", ">=", "<", ">", "==", "!=")
_OP_LEGIBLE = {"<=": "menor o igual a", ">=": "mayor o igual a",
               "<": "menor a", ">": "mayor a",
               "==": "igual a", "!=": "distinto de"}
_OP_LEGIBLE_CORTO = {"<=": "≤", ">=": "≥", "<": "<", ">": ">", "==": "=", "!=": "≠"}

# La validación fija y la consistencia solo aplican sobre tipos comparables.
# Texto libre/opciones/archivos quedan afuera en la Fase 1.
TIPOS_VALIDABLES = ("numero", "fecha")

FUENTES = ("fija", "funcion")   # externa: BACKLOG, fase 4

# ---------------------------------------------------------------------------
# Fuente `funcion` (PLAN_LISTAS_VALIDACIONES.md, D2/D6, bloque 3)
# ---------------------------------------------------------------------------
# Una validación de fuente `funcion` busca algo fuera del formulario -- una
# fila de una LISTA del sindicato (listas.PLANTILLAS) o un dato del SISTEMA
# (el padrón) -- y lo compara, o evalúa una fórmula escrita como las Reglas
# de control (parseo con `ast`, sin eval, nombres cerrados). Lo que se
# nombra en una fórmula: `campo.<etiqueta_normalizada>` (lo que la persona
# escribió en el formulario, ya tipado), `lista.<columna>` (la fila
# encontrada) y `sistema.<dato>` (DATOS_SISTEMA). Un campo de tipo
# `calculado` es una de estas sin operador: lo que se muestra es el
# resultado.
ORIGENES = ("lista", "sistema")
TIPOS_CON_FUNCION = ("texto", "numero", "fecha", "seleccion", "opcion_unica", "calculado")
TIPO_CALCULADO = "calculado"

# dato -> (tipo, rótulo). Lo que `sistema.<dato>` puede nombrar. Lo llena
# db.contexto_validaciones; acá solo se declara para que el constructor lo
# ofrezca y el saneo lo verifique.
DATOS_SISTEMA = {
    "en_padron": ("booleano", "Está en el padrón de este sindicato"),
    "activo": ("booleano", "Empadronamiento activo (no dado de baja)"),
    "registrado": ("booleano", "Ya se registró en la app"),
    "seccional": ("texto", "Nombre de su seccional"),
    "provincia": ("texto", "Provincia de su domicilio"),
    "localidad": ("texto", "Localidad de su domicilio"),
    "nivel_fiabilidad": ("numero", "Nivel de fiabilidad de la cuenta (1 a 4)"),
    "recibos_verificados": ("numero", "Cantidad de recibos verificados"),
    "semaforo": ("texto", "Color del último semáforo de aportes (verde, amarillo, rojo o gris)"),
    "fecha_afiliacion": ("fecha", "Fecha de afiliación a este sindicato"),
    "fecha_nacimiento": ("fecha", "Fecha de nacimiento"),
    "tramites_de_este_tipo": ("numero", "Cuántas veces ya pidió este mismo trámite (en cualquier estado)"),
    "tramites_abiertos_de_este_tipo": ("numero", "Cuántos pedidos de este mismo trámite tiene sin terminar"),
}

# Las funciones que una fórmula puede llamar, con su ayuda. Las de fechas
# reciben AAAA-MM-DD (lo que emite <input type=date> y lo que guardan las
# listas y el padrón) y cuentan unidades ENTERAS cumplidas.
FUNCIONES_FORMULA = {
    "hoy": "hoy() → la fecha del día (Buenos Aires)",
    "dias_entre": "dias_entre(desde, hasta) → días entre dos fechas",
    "meses_entre": "meses_entre(desde, hasta) → meses cumplidos entre dos fechas",
    "anios_entre": "anios_entre(desde, hasta) → años cumplidos entre dos fechas",
    "min": "min(a, b, …)",
    "max": "max(a, b, …)",
    "redondear": "redondear(x, decimales=0)",
    "largo": "largo(texto) → cantidad de caracteres",
    "existe": "existe(x) → verdadero si el dato tiene valor",
}
PALABRAS_FORMULA = {"y": "and", "o": "or", "no": "not", "verdadero": "True", "falso": "False"}

_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # lo que emite <input type=date>

# Límite dinámico para validaciones de fecha: "hoy", "hoy+10", "hoy-3". Se
# resuelve AL EVALUAR (la fecha del día en que la persona envía el trámite),
# no al guardar: un límite fijo resuelto al guardar se pudre solo.
_RE_HOY = re.compile(r"^hoy([+-]\d{1,4})?$")


def _a_comparable(valor, tipo_dato):
    """Convierte el texto de un campo a algo comparable, o None.

    numero -> float (coma o punto decimal); fecha -> el string ISO tal cual
    (AAAA-MM-DD compara bien lexicográficamente). None nunca entra a una
    comparación: un valor ilegible no vale 0 ni 'menor que todo'."""
    t = str(valor or "").strip()
    if not t:
        return None
    if tipo_dato == "numero":
        try:
            return float(t.replace(",", "."))
        except ValueError:
            return None
    if tipo_dato == "fecha":
        return t if _RE_FECHA.match(t) else None
    return None


def _compara(a, operador, b) -> bool:
    if operador == "<=":
        return a <= b
    if operador == ">=":
        return a >= b
    if operador == "<":
        return a < b
    if operador == ">":
        return a > b
    if operador == "==":
        return a == b
    if operador == "!=":
        return a != b
    return True  # operador desconocido: no bloquear (ya se saneó al guardar)


def _limite_comparable(valor, tipo_dato):
    """El LÍMITE de una validación, comparable. Igual que _a_comparable,
    más el límite dinámico 'hoy±N' para fechas (resuelto recién acá, al
    momento de evaluar)."""
    if tipo_dato == "fecha":
        m = _RE_HOY.match(str(valor or "").strip().lower())
        if m:
            dias = int(m.group(1) or 0)
            return (fechas.hoy() + timedelta(days=dias)).isoformat()
    return _a_comparable(valor, tipo_dato)


def _valor_legible(valor, tipo_dato):
    """El límite como lo lee una persona en un mensaje ('180', '31/12/2026',
    'el día del envío', '10 días después del envío')."""
    if tipo_dato == "fecha":
        m = _RE_HOY.match(str(valor or "").strip().lower())
        if m:
            dias = int(m.group(1) or 0)
            if dias == 0:
                return "el día del envío"
            rumbo = "después" if dias > 0 else "antes"
            unidad = "día" if abs(dias) == 1 else "días"
            return f"{abs(dias)} {unidad} {rumbo} del envío"
    if tipo_dato == "fecha" and _RE_FECHA.match(str(valor or "")):
        a, m, d = str(valor).split("-")
        return f"{d}/{m}/{a}"
    return str(valor)


def validaciones_saneadas(crudas, tipo_dato, campos=None, indice=None) -> list:
    """Filtra/normaliza las validaciones de UN campo al guardar el tipo.

    Descarta en silencio lo mal formado (fuente desconocida, operador fuera
    de la lista, valor no comparable con el tipo_dato del campo) -- mismo
    criterio defensivo que _campos_tramite_validos en main.py. Si el admin
    no escribió mensaje, se genera uno por defecto ACÁ (queda guardado y el
    admin lo ve al reabrir, en vez de descubrirlo en la pantalla del
    trabajador).

    `campos` e `indice` (la lista entera del formulario y la posición de
    este campo) hacen falta para la fuente `funcion`: la segunda clave se
    referencia por orden y la fórmula se compila contra los nombres del
    formulario. Sin ellos, las de fuente `funcion` se descartan."""
    validas = []
    for v in crudas or []:
        if not isinstance(v, dict):
            continue
        if v.get("fuente") == "funcion":
            if campos is not None and tipo_dato in TIPOS_CON_FUNCION:
                limpia = funcion_saneada(v, campos, indice, calculado=(tipo_dato == TIPO_CALCULADO))
                if limpia:
                    validas.append(limpia)
            continue
        if tipo_dato not in TIPOS_VALIDABLES:
            continue
        if v.get("fuente") not in FUENTES:
            continue
        operador = v.get("operador")
        if operador not in OPERADORES:
            continue
        valor = str(v.get("valor") or "").strip()
        if _limite_comparable(valor, tipo_dato) is None:
            continue
        mensaje = str(v.get("mensaje") or "").strip()[:300]
        if not mensaje:
            mensaje = (f"Tiene que ser {_OP_LEGIBLE[operador]} "
                       f"{_valor_legible(valor, tipo_dato)}.")
        validas.append({
            "fuente": "fija",
            "operador": operador,
            "valor": valor,
            "mensaje": mensaje,
            "bloquea": bool(v.get("bloquea", True)),
        })
    return validas


def reglas_saneadas(crudas, campos) -> list:
    """Filtra/normaliza las reglas de consistencia del tipo al guardarlo.

    Las reglas referencian campos POR ORDEN (índice en la lista), no por id:
    editar un tipo REEMPLAZA sus campos (ids nuevos en cada edición, ver
    db.editar_tipo_tramite) y una referencia por id quedaría colgada tras la
    primera edición. El payload del constructor manda campos y reglas juntos,
    así que el orden es consistente por construcción.

    Solo se admite comparar dos campos del MISMO tipo_dato comparable
    (numero-numero o fecha-fecha): comparar una fecha con un número no
    significa nada y se descarta al guardar, no al evaluar."""
    validas = []
    n = len(campos or [])
    for r in crudas or []:
        if not isinstance(r, dict):
            continue
        operador = r.get("operador")
        if operador not in OPERADORES:
            continue
        try:
            a, b = int(r.get("campo_a")), int(r.get("campo_b"))
        except (TypeError, ValueError):
            continue
        if not (0 <= a < n and 0 <= b < n) or a == b:
            continue
        tipo_a, tipo_b = campos[a].get("tipo_dato"), campos[b].get("tipo_dato")
        if tipo_a not in TIPOS_VALIDABLES or tipo_a != tipo_b:
            continue
        mensaje = str(r.get("mensaje") or "").strip()[:300]
        if not mensaje:
            mensaje = (f'"{campos[a].get("etiqueta")}" tiene que ser '
                       f'{_OP_LEGIBLE[operador]} "{campos[b].get("etiqueta")}".')
        validas.append({
            "campo_a": a, "operador": operador, "campo_b": b,
            "mensaje": mensaje,
            "bloquea": bool(r.get("bloquea", True)),
        })
    return validas


def evaluar_envio(campos, reglas, valores, contexto=None, requisitos=None) -> dict:
    """Evalúa TODAS las validaciones de un envío ya tipado-válido.

    `contexto` (bloque 3) es lo que las validaciones de fuente `funcion`
    miran fuera del formulario: `{"sistema": {dato: valor}, "buscar":
    callable(plantilla, clave2) -> fila | None}`, armado por
    db.contexto_validaciones con el CUIL de la SESIÓN. Sin contexto, las de
    fuente `funcion` y los `requisitos` no se evalúan y se cuentan en
    `sin_contexto` (el banco de pruebas sin CUIL elegido lo dice; el envío
    real siempre lo trae). `calculados` trae el texto de cada campo
    `calculado` por id.

    - `campos`: lista de dicts del tipo (id/orden/etiqueta/tipo_dato/
      validaciones), como la devuelve db.tipo_tramite_por_id. El orden de la
      lista es el `orden` persistido (las reglas referencian ese índice).
    - `reglas`: reglas_consistencia del tipo.
    - `valores`: {campo_id: valor_texto} de lo que mandó la persona (solo
      campos con valor de texto; archivos/booleanos no participan).

    Devuelve {"errores": [msj], "errores_campos": {campo_id: msj},
    "advertencias": [msj]}. Un campo vacío no dispara validaciones: de eso
    se encarga el chequeo de obligatorio del llamador. Un valor presente
    pero no comparable tampoco (el llamador ya rechazó números ilegibles);
    ante la duda esta capa NO inventa un bloqueo."""
    errores, errores_campos, advertencias = [], {}, []
    calculados, sin_contexto = {}, 0

    # ---- fuente `funcion`: requisitos del tipo, validaciones y calculados
    ns_campo = _namespace_campos(campos, valores)
    cache_filas = {}

    def _resolver(v):
        return _evaluar_funcion(v, ns_campo, contexto, campos, valores, cache_filas)

    for r in requisitos or []:
        if contexto is None:
            sin_contexto += 1
            continue
        pasa, _resultado, motivo = _resolver(r)
        if not pasa:
            errores.append(r.get("mensaje") or motivo)

    for campo in campos or []:
        cid = campo.get("id")
        funcion = [v for v in (campo.get("validaciones") or []) if v.get("fuente") == "funcion"]
        if campo.get("tipo_dato") == TIPO_CALCULADO:
            if not funcion:
                continue
            if contexto is None:
                sin_contexto += 1
                continue
            pasa, resultado, motivo = _resolver(funcion[0])
            calculados[cid] = _texto_resultado(resultado) if pasa else ""
            if not pasa:
                advertencias.append(f'"{campo.get("etiqueta")}": no se pudo calcular ({motivo}).')
            continue
        if funcion and str(valores.get(cid) or "").strip():
            for v in funcion:
                if contexto is None:
                    sin_contexto += 1
                    continue
                pasa, _resultado, motivo = _resolver(v)
                if pasa:
                    continue
                mensaje = f'"{campo.get("etiqueta")}": {v.get("mensaje")}'
                if v.get("bloquea", True):
                    errores.append(mensaje)
                    errores_campos.setdefault(cid, v.get("mensaje"))
                else:
                    advertencias.append(mensaje)

    for campo in campos or []:
        cid = campo.get("id")
        comparable = _a_comparable(valores.get(cid), campo.get("tipo_dato"))
        if comparable is None:
            continue
        for v in campo.get("validaciones") or []:
            if v.get("fuente") != "fija":
                continue  # las de fuente `funcion` ya se evaluaron arriba
            limite = _limite_comparable(v.get("valor"), campo.get("tipo_dato"))
            if limite is None:
                continue
            if _compara(comparable, v.get("operador"), limite):
                continue
            mensaje = f'"{campo.get("etiqueta")}": {v.get("mensaje")}'
            if v.get("bloquea", True):
                errores.append(mensaje)
                # el primer bloqueo del campo es el que se pinta inline
                errores_campos.setdefault(cid, v.get("mensaje"))
            else:
                advertencias.append(mensaje)

    por_orden = list(campos or [])
    for r in reglas or []:
        try:
            campo_a, campo_b = por_orden[int(r["campo_a"])], por_orden[int(r["campo_b"])]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if campo_a.get("tipo_dato") != campo_b.get("tipo_dato"):
            continue
        a = _a_comparable(valores.get(campo_a.get("id")), campo_a.get("tipo_dato"))
        b = _a_comparable(valores.get(campo_b.get("id")), campo_b.get("tipo_dato"))
        if a is None or b is None:
            continue
        if _compara(a, r.get("operador"), b):
            continue
        mensaje = r.get("mensaje") or "Los valores no son consistentes entre sí."
        if r.get("bloquea", True):
            errores.append(mensaje)
            errores_campos.setdefault(campo_a.get("id"), mensaje)
        else:
            advertencias.append(mensaje)

    return {"errores": errores, "errores_campos": errores_campos,
            "advertencias": advertencias, "calculados": calculados,
            "sin_contexto": sin_contexto}


# ===========================================================================
# Fuente `funcion`: nombres, saneo, fórmulas y evaluación
# ===========================================================================

def _plano(texto: str) -> str:
    plano = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    plano = re.sub(r"[^a-z0-9]+", "_", plano).strip("_")
    if plano and plano[0].isdigit():
        plano = "c_" + plano
    return plano or "campo"


def nombres_de_campos(campos) -> list:
    """El nombre con el que una fórmula nombra a cada campo del formulario,
    POR ORDEN: `campo.<etiqueta_normalizada>` (minúsculas, sin tildes, los
    espacios y signos como guion bajo; repetidos con `_2`, `_3`…). El
    constructor los muestra al lado de cada campo. Un separador no tiene
    nombre (devuelve '')."""
    nombres, vistos = [], {}
    for c in campos or []:
        if c.get("tipo_dato") == "separador":
            nombres.append("")
            continue
        base = _plano(c.get("etiqueta"))
        n = vistos.get(base, 0) + 1
        vistos[base] = n
        nombres.append(base if n == 1 else f"{base}_{n}")
    return nombres


def _tipado(valor, tipo):
    """Un valor de texto convertido al tipo con el que lo ve una fórmula.
    None = no hay dato (vacío o ilegible): nunca entra a una cuenta como 0."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    if tipo == "numero":
        if isinstance(valor, (int, float)):
            return float(valor)
        return _a_comparable(valor, "numero")
    if tipo == "fecha":
        return _a_comparable(valor, "fecha")
    if tipo == "booleano":
        t = str(valor).strip().lower()
        return t in ("si", "sí", "true", "1", "verdadero", "x")
    if tipo in ("cuil", "dni", "texto") or tipo is None:
        t = str(valor).strip()
        return t if t else None
    if isinstance(valor, (int, float)):
        return float(valor)
    t = str(valor).strip()
    return t if t else None


def _namespace_campos(campos, valores) -> dict:
    ns = {}
    for nombre, c in zip(nombres_de_campos(campos), campos or []):
        if not nombre:
            continue
        tipo = c.get("tipo_dato")
        tipo = tipo if tipo in ("numero", "fecha", "booleano") else "texto"
        ns[nombre] = _tipado(valores.get(c.get("id")), tipo)
    return ns


def _namespace_lista(plantilla, fila) -> dict:
    if not fila:
        return {}
    return {col["clave"]: _tipado(fila.get(col["clave"]), col["tipo"])
            for col in listas_mod.columnas(plantilla)}


# ---- la fórmula --------------------------------------------------------

_RE_PALABRA = re.compile(r'("[^"]*"|\'[^\']*\')|\b(y|o|no|verdadero|falso)\b')


def _a_python(expr: str) -> str:
    """`y` / `o` / `no` / `verdadero` / `falso` → los operadores de Python,
    sin tocar lo que va entre comillas."""
    def _r(m):
        return m.group(1) if m.group(1) else PALABRAS_FORMULA[m.group(2)]
    return _RE_PALABRA.sub(_r, expr or "")


def _fecha(valor):
    if isinstance(valor, date):
        return valor
    f = _a_comparable(valor, "fecha")
    if f is None:
        raise ValueError("fecha inválida")
    return date.fromisoformat(f)


def _meses_entre(desde, hasta) -> int:
    a, b = _fecha(desde), _fecha(hasta)
    meses = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        meses -= 1
    return meses


_FUNCIONES = {
    "hoy": lambda: fechas.hoy().isoformat(),
    "dias_entre": lambda a, b: (_fecha(b) - _fecha(a)).days,
    "meses_entre": _meses_entre,
    "anios_entre": lambda a, b: int(_meses_entre(a, b) // 12),
    "min": min,
    "max": max,
    "redondear": lambda x, n=0: round(float(x), int(n)),
    "largo": lambda t: len(str(t)) if t is not None else 0,
    "existe": lambda x: x is not None and str(x).strip() != "",
}
_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
           ast.Mod: lambda a, b: a % b}
_COMPARA = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
            ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
            ast.Eq: lambda a, b: _igual(a, b), ast.NotEq: lambda a, b: not _igual(a, b)}


def _igual(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return _plano(a) == _plano(b)
    return a == b


def _ev(nodo, ns):
    """Recorre el árbol de la fórmula a mano (como validador._ev_nodo, XSK
    H-0005): solo números, textos entre comillas, los tres espacios de
    nombres, aritmética, comparaciones, y/o/no y las funciones de la lista.
    Cualquier otra cosa es SyntaxError. Un dato que falta (None) en una
    cuenta o una comparación levanta TypeError: la validación no pasa."""
    if isinstance(nodo, ast.Constant):
        if isinstance(nodo.value, (bool, int, float, str)):
            return float(nodo.value) if isinstance(nodo.value, (int, float)) and not isinstance(nodo.value, bool) else nodo.value
        raise SyntaxError("constante no permitida")
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        espacio = nodo.value.id
        if espacio not in ns:
            raise NameError(f"name '{espacio}' is not defined")
        if nodo.attr not in ns[espacio]:
            raise NameError(f"name '{espacio}.{nodo.attr}' is not defined")
        return ns[espacio][nodo.attr]
    if isinstance(nodo, ast.Name):
        raise NameError(f"name '{nodo.id}' is not defined")
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _BINOPS:
        a, b = _ev(nodo.left, ns), _ev(nodo.right, ns)
        if a is None or b is None:
            raise TypeError("falta un dato")
        return _BINOPS[type(nodo.op)](a, b)
    if isinstance(nodo, ast.UnaryOp):
        v = _ev(nodo.operand, ns)
        if isinstance(nodo.op, ast.Not):
            return not v
        if v is None:
            raise TypeError("falta un dato")
        if isinstance(nodo.op, ast.USub):
            return -v
        if isinstance(nodo.op, ast.UAdd):
            return +v
        raise SyntaxError("operador no permitido")
    if isinstance(nodo, ast.BoolOp):
        valores = [_ev(v, ns) for v in nodo.values]
        return all(valores) if isinstance(nodo.op, ast.And) else any(valores)
    if isinstance(nodo, ast.Compare):
        izq = _ev(nodo.left, ns)
        for op, der in zip(nodo.ops, nodo.comparators):
            if type(op) not in _COMPARA:
                raise SyntaxError("comparación no permitida")
            d = _ev(der, ns)
            if izq is None or d is None:
                raise TypeError("falta un dato")
            if not _COMPARA[type(op)](izq, d):
                return False
            izq = d
        return True
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and not nodo.keywords:
        if nodo.func.id not in _FUNCIONES:
            raise NameError(f"name '{nodo.func.id}' is not defined")
        args = [_ev(a, ns) for a in nodo.args]
        return _FUNCIONES[nodo.func.id](*args)
    raise SyntaxError("expresión no permitida")


def evaluar_formula(expr: str, ns: dict):
    """El valor de la fórmula contra el namespace {campo, lista, sistema}.
    Levanta SyntaxError / NameError / TypeError / ValueError / ZeroDivisionError."""
    arbol = ast.parse(_a_python((expr or "").strip()), mode="eval")
    return _ev(arbol.body, ns)


def namespace_de_prueba(campos, plantilla=None) -> dict:
    """Valores de juguete para COMPILAR una fórmula al guardar: los nombres
    reales del formulario, de la lista y del sistema, con un valor del tipo
    que corresponde. Si se nombra algo que no existe, falla acá y no en la
    pantalla del afiliado (mismo criterio que validador.error_de_expresion)."""
    muestra = {"numero": 1.0, "fecha": "2020-01-15", "booleano": True, "texto": "x",
               "cuil": "20111111112", "dni": "12345678"}
    ns_campo = {}
    for nombre, c in zip(nombres_de_campos(campos), campos or []):
        if nombre:
            tipo = c.get("tipo_dato")
            ns_campo[nombre] = muestra.get(tipo if tipo in ("numero", "fecha", "booleano") else "texto")
    ns_lista = ({col["clave"]: muestra.get(col["tipo"], "x") for col in listas_mod.columnas(plantilla)}
                if plantilla in listas_mod.PLANTILLAS else {})
    ns_sistema = {k: muestra[t] for k, (t, _) in DATOS_SISTEMA.items()}
    return {"campo": ns_campo, "lista": ns_lista, "sistema": ns_sistema}


def error_de_formula(expr: str, campos, plantilla=None):
    """None si la fórmula compila y evalúa contra los nombres del formulario;
    si no, el motivo en castellano (lo ve el admin al guardar o al probar)."""
    if not (expr or "").strip():
        return "La fórmula está vacía."
    try:
        evaluar_formula(expr, namespace_de_prueba(campos, plantilla))
    except SyntaxError:
        return ("No es una fórmula válida: usá punto decimal, * para multiplicar, "
                "y / o / no para combinar, y las funciones de la lista.")
    except NameError as e:
        nombre = str(e).split("'")[1] if "'" in str(e) else "?"
        return f"No existe ningún dato llamado «{nombre}». Los nombres válidos son los que muestra el constructor."
    except ZeroDivisionError:
        return "La fórmula divide por cero."
    except Exception as e:
        return f"No se pudo evaluar la fórmula ({type(e).__name__})."
    return None


def funcion_saneada(v: dict, campos, indice=None, calculado=False, requisito=False):
    """Una validación de fuente `funcion` normalizada, o None si está mal
    formada. Contrato en PLAN_LISTAS_VALIDACIONES.md ("El contrato")."""
    origen = v.get("origen")
    if origen not in ORIGENES:
        return None
    plantilla = v.get("lista") if origen == "lista" else None
    if origen == "lista" and plantilla not in listas_mod.PLANTILLAS:
        return None
    clave2 = None
    if origen == "lista" and not requisito and v.get("clave2") not in (None, ""):
        try:
            clave2 = int(v.get("clave2"))
        except (TypeError, ValueError):
            return None
        # La segunda clave puede ser el MISMO campo que se valida (el caso
        # típico: el DNI del familiar se busca con el DNI que se tipeó).
        if not (0 <= clave2 < len(campos or [])):
            return None
        if (campos[clave2].get("tipo_dato") or "") in ("separador", "archivo", "booleano", "multiple", TIPO_CALCULADO):
            return None
    trae = str(v.get("trae") or "").strip()
    if trae == "__formula":        # marca del constructor: "lo que se mira es una fórmula"
        trae = ""
    formula = str(v.get("formula") or "").strip() or None
    if origen == "lista":
        columnas = {c["clave"] for c in listas_mod.columnas(plantilla)}
        if trae and trae != "existe" and trae not in columnas:
            return None
        if not trae and not formula:
            trae = "existe"
    else:
        if trae and trae not in DATOS_SISTEMA:
            return None
        if not trae and not formula:
            return None
    if formula and error_de_formula(formula, campos, plantilla):
        return None
    operador = v.get("operador") or None
    if operador is not None and operador not in OPERADORES:
        return None
    valor = str(v.get("valor") or "").strip()
    if calculado:
        if not formula and not trae:
            return None
        operador, valor = None, ""
    elif operador is None and not formula and trae != "existe":
        # Un dato traído sin fórmula ni operador no afirma nada.
        return None
    if trae == "existe" and operador is None:
        operador, valor = "==", "si"
    mensaje = str(v.get("mensaje") or "").strip()[:300]
    if not mensaje:
        mensaje = _mensaje_funcion(origen, plantilla, trae, formula, operador, valor)
    return {
        "fuente": "funcion", "origen": origen, "lista": plantilla, "clave2": clave2,
        "trae": trae or "", "formula": formula, "operador": operador, "valor": valor,
        "mensaje": mensaje, "bloquea": True if requisito else bool(v.get("bloquea", True)),
        "en_vivo": bool(v.get("en_vivo", False)) and not requisito,
    }


def _mensaje_funcion(origen, plantilla, trae, formula, operador, valor) -> str:
    if trae == "existe":
        nombre = listas_mod.PLANTILLAS[plantilla]["nombre"].lower()
        return (f"Tiene que figurar en la lista «{nombre}» del sindicato." if valor != "no" and operador == "=="
                else f"No puede figurar en la lista «{nombre}» del sindicato.")
    que = formula or (f"{origen}.{trae}")
    if operador:
        return f"{que} tiene que ser {_OP_LEGIBLE[operador]} {valor}."
    return f"No se cumple: {que}."


def requisitos_saneados(crudos, campos) -> list:
    """Los requisitos para INICIAR el trámite (TipoTramite.requisitos): una
    lista de validaciones de fuente `funcion`, todas bloqueantes y sin
    segunda clave (se evalúan antes de que haya formulario)."""
    salida = []
    for r in crudos or []:
        if isinstance(r, dict):
            limpio = funcion_saneada(r, campos, requisito=True)
            if limpio:
                salida.append(limpio)
    return salida


def evaluar_campo_en_vivo(campos, indice, valores, contexto) -> dict:
    """La validación EN VIVO de un campo (D3, bloque 4): solo sus funciones
    marcadas `en_vivo`, y solo pasa / no pasa con el mensaje del admin --
    nunca la fila ni el dato que se miró. Recalcula además los campos
    `calculado` que usan a este campo como segunda clave, porque es el
    momento en que se puede. Devuelve {"pasa", "mensaje", "calculados"}."""
    campos = list(campos or [])
    try:
        campo = campos[int(indice)]
    except (IndexError, TypeError, ValueError):
        return {"pasa": True, "mensaje": "", "calculados": {}}
    ns_campo = _namespace_campos(campos, valores)
    cache = {}
    pasa, mensaje = True, ""
    if str(valores.get(campo.get("id")) or "").strip():
        for v in campo.get("validaciones") or []:
            if v.get("fuente") != "funcion" or not v.get("en_vivo"):
                continue
            ok, _r, _m = _evaluar_funcion(v, ns_campo, contexto, campos, valores, cache)
            if not ok and v.get("bloquea", True):
                pasa, mensaje = False, v.get("mensaje") or ""
                break
    calculados = {}
    for c in campos:
        if c.get("tipo_dato") != TIPO_CALCULADO:
            continue
        f = next((v for v in (c.get("validaciones") or []) if v.get("fuente") == "funcion"), None)
        if not f or f.get("clave2") is None or int(f["clave2"]) != int(indice):
            continue
        ok, resultado, _m = _evaluar_funcion(f, ns_campo, contexto, campos, valores, cache)
        calculados[c.get("id")] = _texto_resultado(resultado) if ok else ""
    return {"pasa": pasa, "mensaje": mensaje, "calculados": calculados}


def requisitos_al_abrir(campos, requisitos, contexto) -> dict:
    """Al abrir el formulario (bloque 4): si los requisitos no se cumplen,
    los mensajes en vez de los campos; y los calculados que ya se pueden
    completar (los que no dependen de una segunda clave del formulario)."""
    v = evaluar_envio(campos, [], {}, contexto, requisitos)
    calculados = {}
    for c in campos or []:
        if c.get("tipo_dato") != TIPO_CALCULADO:
            continue
        f = next((x for x in (c.get("validaciones") or []) if x.get("fuente") == "funcion"), None)
        if f and f.get("clave2") is None and v["calculados"].get(c.get("id")):
            calculados[c.get("id")] = v["calculados"][c.get("id")]
    mensajes = [r.get("mensaje") for r in (requisitos or [])
                if r.get("mensaje") in v["errores"]]
    return {"cumple": not mensajes, "mensajes": mensajes, "calculados": calculados}


def _texto_resultado(resultado) -> str:
    if resultado is None:
        return ""
    if isinstance(resultado, bool):
        return "Sí" if resultado else "No"
    if isinstance(resultado, float):
        return str(int(resultado)) if resultado == int(resultado) else f"{resultado:.2f}".rstrip("0").rstrip(".")
    return str(resultado)


def _comparable_para(resultado, valor):
    """El `valor` de la validación convertido al tipo del resultado."""
    if isinstance(resultado, bool):
        return _tipado(valor, "booleano")
    if isinstance(resultado, (int, float)):
        return _a_comparable(valor, "numero")
    if isinstance(resultado, str) and _RE_FECHA.match(resultado):
        return _limite_comparable(valor, "fecha")
    return str(valor or "").strip()


def clave2_de(v, campos, valores):
    """(clave2, motivo): la segunda clave con la que esta validación busca
    en la lista -- el valor del campo del formulario que `clave2` señala,
    normalizado como lo normaliza la lista (un DNI, a sus dígitos). Sin
    segunda clave, ''. `motivo` explica por qué no se puede buscar."""
    if v.get("clave2") is None:
        return "", ""
    try:
        campo2 = campos[int(v["clave2"])]
    except (IndexError, TypeError, ValueError):
        return None, "la segunda clave no existe en el formulario"
    clave2 = str(valores.get(campo2.get("id")) or "").strip()
    if not clave2:
        return None, "falta el dato de la segunda clave"
    return listas_mod.normalizar_dni(clave2) or clave2, ""


def busquedas_necesarias(campos, requisitos, valores) -> set:
    """Las (plantilla, clave2) que un envío va a buscar en las listas, para
    que db.contexto_validaciones las traiga ANTES de evaluar y la
    evaluación siga siendo pura (y una sola conexión por request)."""
    pendientes = [v for c in (campos or []) for v in (c.get("validaciones") or [])
                  if v.get("fuente") == "funcion" and v.get("origen") == "lista"]
    pendientes += [r for r in (requisitos or []) if r.get("origen") == "lista"]
    salida = set()
    for v in pendientes:
        clave2, motivo = clave2_de(v, campos, valores)
        if not motivo:
            salida.add((v.get("lista"), clave2))
    return salida


def catalogo_funcion() -> dict:
    """Lo que el constructor ofrece para armar una validación por función:
    los datos del sistema, las funciones de fórmula y las listas con sus
    columnas. Es el catálogo del código, no una lista a mano."""
    return {
        "sistema": [{"clave": k, "tipo": t, "rotulo": r} for k, (t, r) in DATOS_SISTEMA.items()],
        "funciones": [{"nombre": k, "ayuda": v} for k, v in FUNCIONES_FORMULA.items()],
        "listas": [{"clave": k, "nombre": p["nombre"],
                    "columnas": [{"clave": c["clave"], "tipo": c["tipo"], "rotulo": c["rotulo"],
                                  "busqueda": c.get("busqueda", 0)} for c in p["columnas"]]}
                   for k, p in listas_mod.PLANTILLAS.items()],
        "operadores": list(OPERADORES),
    }


def _evaluar_funcion(v, ns_campo, contexto, campos, valores, cache):
    """(pasa, resultado, motivo). `motivo` explica por qué no pasó, para el
    banco de pruebas y los calculados; lo que ve el afiliado es `mensaje`."""
    sistema = (contexto or {}).get("sistema") or {}
    buscar = (contexto or {}).get("buscar")
    fila = None
    if v.get("origen") == "lista":
        clave2, motivo = clave2_de(v, campos, valores)
        if motivo:
            return False, None, motivo
        llave = (v.get("lista"), clave2)
        if llave not in cache:
            cache[llave] = buscar(v.get("lista"), clave2) if buscar else None
        fila = cache[llave]
    ns = {"campo": ns_campo, "lista": _namespace_lista(v.get("lista"), fila), "sistema": sistema}
    try:
        if v.get("formula"):
            if v.get("origen") == "lista" and fila is None:
                return False, None, "no está en la lista"
            resultado = evaluar_formula(v["formula"], ns)
        elif v.get("trae") == "existe":
            resultado = fila is not None
        elif v.get("origen") == "lista":
            if fila is None:
                return False, None, "no está en la lista"
            resultado = ns["lista"].get(v.get("trae"))
        else:
            resultado = sistema.get(v.get("trae"))
        if v.get("operador"):
            limite = _comparable_para(resultado, v.get("valor"))
            if resultado is None or limite is None:
                return False, resultado, "falta el dato para comparar"
            return bool(_compara(resultado, v["operador"], limite)
                        if not isinstance(resultado, str) or _RE_FECHA.match(resultado)
                        else _compara(_plano(resultado), v["operador"], _plano(str(limite)))), resultado, "no cumple la condición"
        if v.get("formula") and not isinstance(resultado, bool) and resultado is not None:
            # un calculado: lo que se muestra es el resultado
            return True, resultado, ""
        return bool(resultado), resultado, "no cumple la condición"
    except ZeroDivisionError:
        return False, None, "la fórmula divide por cero"
    except (TypeError, ValueError):
        return False, None, "falta un dato que la fórmula necesita"
    except (SyntaxError, NameError):
        return False, None, "la fórmula no se pudo evaluar"

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

import re
from datetime import date, timedelta

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

FUENTES = ("fija",)  # se amplía en fases siguientes: lista, sistema, externa

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
            return (date.today() + timedelta(days=dias)).isoformat()
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


def validaciones_saneadas(crudas, tipo_dato) -> list:
    """Filtra/normaliza las validaciones de UN campo al guardar el tipo.

    Descarta en silencio lo mal formado (fuente desconocida, operador fuera
    de la lista, valor no comparable con el tipo_dato del campo) -- mismo
    criterio defensivo que _campos_tramite_validos en main.py. Si el admin
    no escribió mensaje, se genera uno por defecto ACÁ (queda guardado y el
    admin lo ve al reabrir, en vez de descubrirlo en la pantalla del
    trabajador)."""
    if tipo_dato not in TIPOS_VALIDABLES:
        return []
    validas = []
    for v in crudas or []:
        if not isinstance(v, dict):
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


def evaluar_envio(campos, reglas, valores) -> dict:
    """Evalúa TODAS las validaciones de un envío ya tipado-válido.

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

    for campo in campos or []:
        cid = campo.get("id")
        comparable = _a_comparable(valores.get(cid), campo.get("tipo_dato"))
        if comparable is None:
            continue
        for v in campo.get("validaciones") or []:
            if v.get("fuente") != "fija":
                continue  # fuentes de fases siguientes: todavía no evalúan
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
            "advertencias": advertencias}

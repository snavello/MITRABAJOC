# -*- coding: utf-8 -*-
"""Los seis controles de una grilla salarial leída de un PDF escaneado
(PLAN_CONVENIO_ESCALAS.md, D9.3 y D19). Módulo PURO: sin `db`, sin red, sin IA.

Una grilla nueva se publica sola SOLO si pasan los seis; si falla uno queda
retenida con el detalle de cada celda que no pasó. Cada control devuelve

    {"control": "C1", "nombre": "...", "pasa": True | False | None,
     "resumen": "una frase", "detalle": [ {...celdas concretas...} ], "mas": 0}

`pasa` es None cuando el control NO APLICA (no hay grilla anterior, como en el
ensayo de la primera grilla): nunca cuenta como aprobado, `todos_pasan` pide
True en los seis.

Qué cuenta como «celda» y cómo escala de un mes al siguiente (esto se midió
sobre la grilla de agosto de 2026 y los comunicados de julio a octubre):

- escalan con UN mismo factor (el del comunicado): los básicos, los
  conformados, los adicionales (cajero, falla, títulos, zona, guardería), los
  montos anuales del ROE y los tres valores del Día del Bancario (el mínimo
  del comunicado de septiembre es el de agosto por el mismo 1,9 %).
- NO escalan y se controlan aparte: los coeficientes y los años (son
  estructura: si cambian, C1 retiene), la conectividad (se actualiza por
  trimestre, trae sus `meses`) y los topes `hasta` de los tramos de ROE
  (se aceptan iguales a los de antes o escalados por el mismo factor, con hasta
  1 peso de diferencia: D26; el detalle dice cuál pasó). La conectividad de un
  trimestre YA VENCIDO puede faltar en el PDF y se conserva de la grilla
  anterior (D27).

D28: UNA celda que escala con el factor y no se pudo leer en ninguna de las dos lecturas
(la tapa una firma) se completa por cálculo (`completar_celdas`): hasta
`MAX_CELDAS_CALCULADAS` celdas por grilla y solo si todo lo demás pasa. Ver el docstring de esa
función y PLAN_CONVENIO_ESCALAS.md.

Tolerancias (parámetros, con default ESTRICTO; se calibran con grillas
reales en el bloque 6 y SDN ve el número antes de fijarlo):
  c3_centavos   0,00  anclas del comunicado (inicial y mínimo del Día del Bancario), al centavo exacto
  c3_roe_centavos 0,01 el ROE sale de dividir un monto anual por 12: un centavo de redondeo
  c4_extra      0,00  pesos por encima de lo que explica el redondeo (D19: se calibra con
                       septiembre real en el bloque 6; subirlo aflojaría el control)
  c4_hasta      1,0   pesos, en los topes `hasta` escalados (D26: el sindicato a veces trunca y a
                       veces redondea, así que un tope entero a 1 peso del valor escalado pasa; a 2 o más, no)
  c5_pesos      2,00  básico contra coeficiente × unidad (la grilla firmada de
                       agosto trae hasta ~1,7 en ordenanza: es la fuente)
"""
import copy
import re
import statistics

TOLERANCIAS = {"c3_centavos": 0.0, "c3_roe_centavos": 0.01, "c4_extra": 0.0, "c4_hasta": 1.0, "c5_pesos": 2.0}

CLAVES_DATOS = ("ramas", "adicionales", "conectividad", "roe", "dia_bancario")
TOPE_DETALLE = 200
TOPE_HASTA_FACTOR_MIN_CELDAS = 10


def _tol(tolerancias: dict | None) -> dict:
    return {**TOLERANCIAS, **(tolerancias or {})}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _res(clave: str, nombre: str, pasa, resumen: str, detalle: list | None = None) -> dict:
    detalle = detalle or []
    return {"control": clave, "nombre": nombre, "pasa": pasa, "resumen": resumen,
            "detalle": detalle[:TOPE_DETALLE], "mas": max(0, len(detalle) - TOPE_DETALLE)}


# ---------------------------------------------------------------- celdas
def plano(obj, prefijo: str = "") -> dict:
    """El JSON aplanado a {ruta: valor}, con las listas por índice
    ('ramas.administrativa.categorias.3.basico'). Sirve para comparar dos
    lecturas celda por celda y para ubicar una celda al corregirla."""
    salida = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            salida.update(plano(v, f"{prefijo}.{k}" if prefijo else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            salida.update(plano(v, f"{prefijo}.{i}" if prefijo else str(i)))
    else:
        salida[prefijo] = obj
    return salida


def asignar(contenido: dict, ruta: str, valor) -> dict:
    """Una copia de `contenido` con `ruta` (la de `plano`) puesta en `valor`.
    Levanta KeyError/IndexError/ValueError si la ruta no existe: corregir una
    celda no puede crear estructura nueva."""
    nuevo = copy.deepcopy(contenido)
    partes = ruta.split(".")
    nodo = nuevo
    for p in partes[:-1]:
        nodo = nodo[int(p)] if isinstance(nodo, list) else nodo[p]
    ultimo = partes[-1]
    if isinstance(nodo, list):
        i = int(ultimo)
        if not 0 <= i < len(nodo):
            raise IndexError(ruta)
        nodo[i] = valor
    else:
        if ultimo not in nodo:
            raise KeyError(ruta)
        nodo[ultimo] = valor
    return nuevo


def celdas(g: dict) -> list:
    """Cada valor numérico (o nulo) de una grilla con su ruta, una etiqueta para
    una persona, su tipo y, si es de una categoría, su coeficiente. Es la
    única definición de qué es una celda y de qué grupo es."""
    out = []

    def agregar(ruta, etiqueta, valor, tipo, coef=None):
        out.append({"ruta": ruta, "etiqueta": etiqueta, "valor": valor, "tipo": tipo, "coef": coef})

    # Defensivo: una grilla retenida dañada (un nodo que dejó de ser objeto) tiene que
    # poder mostrarse; lo que no tiene la forma esperada simplemente no aporta celdas.
    ramas = g.get("ramas")
    for rk, r in (ramas.items() if isinstance(ramas, dict) else []):
        if not isinstance(r, dict):
            continue
        nombre_rama = r.get("nombre", rk)
        cats = r.get("categorias")
        for i, c in enumerate(cats if isinstance(cats, list) else []):
            if not isinstance(c, dict):
                continue
            base = f"ramas.{rk}.categorias.{i}"
            et = f"{nombre_rama} · {c.get('nombre')}"
            agregar(f"{base}.anios", f"{et} · años", c.get("anios"), "anios")
            agregar(f"{base}.coef", f"{et} · coeficiente", c.get("coef"), "coef")
            agregar(f"{base}.basico", f"{et} · básico", c.get("basico"), "basico", c.get("coef"))
            agregar(f"{base}.conformado", f"{et} · conformado", c.get("conformado"), "conformado", c.get("coef"))
    adic = g.get("adicionales")
    for k, v in (adic.items() if isinstance(adic, dict) else []):
        if isinstance(v, dict):
            for k2, v2 in v.items():
                agregar(f"adicionales.{k}.{k2}", f"Adicional · {k.replace('_', ' ')} · {k2}", v2, "adicional")
        else:
            agregar(f"adicionales.{k}", f"Adicional · {k.replace('_', ' ')}", v, "adicional")
    conect = g.get("conectividad")
    for i, c in enumerate(conect if isinstance(conect, list) else []):
        if not isinstance(c, dict):
            continue
        meses = "+".join(str(m) for m in (c.get("meses") or []))
        for k in ("diario", "mas_de_4_dias", "mensual"):
            agregar(f"conectividad.{i}.{k}", f"Conectividad {meses} · {k.replace('_', ' ')}", c.get(k), "conectividad")
    roe = g.get("roe") if isinstance(g.get("roe"), dict) else {}
    tramos = roe.get("tramos") if isinstance(roe.get("tramos"), list) else []
    filas = roe.get("filas")
    for i, f in enumerate(filas if isinstance(filas, list) else []):
        if not isinstance(f, dict):
            continue
        agregar(f"roe.filas.{i}.hasta", f"ROE fila {i + 1} · tope del tramo de sueldo", f.get("hasta"), "hasta")
        anual = f.get("anual")
        for j, v in enumerate(anual if isinstance(anual, list) else []):
            tr = tramos[j] if j < len(tramos) else str(j)
            agregar(f"roe.filas.{i}.anual.{j}", f"ROE fila {i + 1} · {tr} · anual", v, "roe")
    db = g.get("dia_bancario")
    for k, v in (db.items() if isinstance(db, dict) else []):
        agregar(f"dia_bancario.{k}", f"Día del Bancario · {k.replace('_', ' ')}", v, "dia_bancario")
    return out


ESCALAN = ("basico", "conformado", "adicional", "roe", "dia_bancario")


def forma_valida(g: dict) -> list:
    try:
        return _forma_valida(g)
    except Exception as e:           # una grilla dañada (un nodo que no es del tipo esperado) es forma inválida, no un 500
        return [f"la grilla tiene una estructura dañada ({type(e).__name__})"]


def _forma_valida(g: dict) -> list:
    """Los problemas que impedirían que `grilla_bancaria.registrar` use esta
    grilla (vacío = se puede usar). Se exige también a una grilla corregida a
    mano: una grilla con forma rota rompería la calculadora."""
    p = []
    if not isinstance(g, dict):
        return ["la grilla no es un objeto"]
    for k in ("periodo", "nombre", "firmada"):
        if not isinstance(g.get(k), str) or not g.get(k):
            p.append(f"falta «{k}»")
    for k in CLAVES_DATOS:
        if k not in g:
            p.append(f"falta «{k}»")
    if p:
        return p
    ramas = g["ramas"]
    if not isinstance(ramas, dict) or not ramas:
        return ["no hay ramas"]
    if "administrativa" not in ramas:
        p.append("falta la rama administrativa (la calculadora y el lote parten de ella)")
    for rk, r in ramas.items():
        cats = r.get("categorias") if isinstance(r, dict) else None
        if not cats:
            p.append(f"la rama {rk} no tiene categorías")
            continue
        for i, c in enumerate(cats):
            if not isinstance(c.get("nombre"), str) or not _num(c.get("coef")) or not _num(c.get("basico")):
                p.append(f"{rk}[{i}]: nombre, coeficiente y básico son obligatorios")
            if c.get("conformado") is not None and not _num(c.get("conformado")):
                p.append(f"{rk}[{i}]: conformado inválido")
    adic = g["adicionales"]
    for k in ("funcion_cajero", "falla_caja", "falla_caja_moneda_extranjera", "guarderia"):
        if not _num(adic.get(k)):
            p.append(f"adicional {k} sin importe")
    for k in ("titulos", "zona_patagonica"):
        d = adic.get(k)
        if not isinstance(d, dict) or not d or not all(_num(v) for v in d.values()):
            p.append(f"adicionales.{k} incompleto")
    roe = g["roe"]
    tramos, filas = roe.get("tramos"), roe.get("filas")
    if not tramos or not filas:
        p.append("ROE sin tramos o sin filas")
    else:
        for i, f in enumerate(filas):
            if not isinstance(f.get("anual"), list) or len(f["anual"]) != len(tramos) \
                    or not all(_num(v) for v in f["anual"]):
                p.append(f"ROE fila {i + 1}: montos incompletos")
            if i < len(filas) - 1 and not _num(f.get("hasta")):
                p.append(f"ROE fila {i + 1}: falta el tope")
        if filas[-1].get("hasta") is not None:
            p.append("la última fila de ROE no tiene tope")
    db = g["dia_bancario"]
    for k in ("suma_fija", "por_coeficiente", "minimo"):
        if not _num(db.get(k)):
            p.append(f"día del bancario sin {k}")
    for i, c in enumerate(g["conectividad"] or []):
        if not c.get("meses") or not all(_num(c.get(k)) for k in ("diario", "mas_de_4_dias", "mensual")):
            p.append(f"conectividad[{i}] incompleta")
    return p


# ---------------------------------------------------------------- C1
# Un trimestre NUEVO de conectividad no tiene contra qué compararse (no escala con el factor
# del mes y no está en la grilla anterior): mientras no haya un control propio, la grilla que
# lo trae queda RETENIDA siempre y una persona lo revisa contra el PDF. Pasa a lo sumo cuatro
# veces por año. Para aflojarlo más adelante (aceptar el trimestre si el cociente contra el
# anterior es razonable, por ejemplo) se pone en False y se agrega el control en su lugar.
RETENER_TRIMESTRE_NUEVO_DE_CONECTIVIDAD = True
_VALORES_CONECTIVIDAD = ("diario", "mas_de_4_dias", "mensual")


def _trimestre_siguiente(meses: tuple) -> tuple:
    """Los tres meses que siguen a `meses` (AAAA-MM, el último manda)."""
    m1 = _mes_siguiente(max(meses))
    m2 = _mes_siguiente(m1)
    return (m1, m2, _mes_siguiente(m2))


def conectividad_vencida(meses, periodo: str | None) -> bool:
    """D27: un trimestre terminó antes del mes de la grilla si todos sus meses son anteriores al período."""
    return bool(periodo) and bool(meses) and all(isinstance(m, str) and len(m) == 7 for m in meses) \
        and all(m < periodo for m in meses)


def conectividad_conservada(previa: dict | None, g: dict, periodo: str | None) -> list:
    """D27: las entradas de conectividad de la grilla anterior que ya vencieron antes de `periodo` y
    que el PDF ya no trae. No son un dato leído ni inventado: se copian tal cual estaban publicadas."""
    if not previa or not periodo:
        return []
    leidas = {tuple(c.get("meses") or []) for c in (g.get("conectividad") or []) if isinstance(c, dict)}
    return [copy.deepcopy(c) for c in (previa.get("conectividad") or [])
            if isinstance(c, dict) and tuple(c.get("meses") or []) not in leidas
            and conectividad_vencida(c.get("meses"), periodo)]


def con_conectividad_conservada(g: dict, conservadas: list) -> dict:
    """La grilla `g` con las entradas conservadas sumadas a las leídas, en orden cronológico."""
    if not conservadas:
        return g
    todas = list(g.get("conectividad") or []) + copy.deepcopy(conservadas)
    return {**g, "conectividad": sorted(todas, key=lambda c: tuple(c.get("meses") or []))}


def texto_conservada(conservadas: list) -> str:
    partes = []
    for c in conservadas:
        m = sorted(c.get("meses") or [])
        partes.append(f"{m[0]} a {m[-1]}" if m else "?")
    return ("Conectividad " + ", ".join(partes) + ": conservada de la grilla anterior, el PDF ya no la trae") if partes else ""


def _problemas_conectividad(previa: dict, g: dict, periodo: str | None = None) -> list:
    """Las entradas de conectividad de la grilla leída tienen que ser EXACTAMENTE las ya
    publicadas (idénticas, celda por celda) más, como mucho, UNA entrada nueva que sea el
    trimestre consecutivo siguiente al último publicado; y esa entrada nueva retiene la
    grilla siempre (RETENER_TRIMESTRE_NUEVO_DE_CONECTIVIDAD). Excepción (D27): un trimestre ya
    vencido (todos sus meses anteriores al `periodo`) puede faltar; si viene, tiene que ser idéntico."""
    problemas = []
    leidas = g.get("conectividad") if isinstance(g.get("conectividad"), list) else []
    if any(not isinstance(c, dict) for c in leidas):
        return [{"problema": "conectividad con una entrada que no es un objeto"}]
    previas = [c for c in (previa.get("conectividad") or []) if isinstance(c, dict)]
    pm = {tuple(c.get("meses") or []): c for c in previas}
    claves_leidas = [tuple(c.get("meses") or []) for c in leidas]
    for meses, c in pm.items():
        if claves_leidas.count(meses) == 0:
            if conectividad_vencida(meses, periodo):
                continue                  # D27: ya venció, el PDF no lo trae y se conserva
            problemas.append({"problema": "falta la conectividad de un trimestre ya publicado", "etiqueta": "+".join(meses)})
            continue
        if claves_leidas.count(meses) > 1:
            problemas.append({"problema": "conectividad repetida de un trimestre ya publicado", "etiqueta": "+".join(meses)})
        propia = next(c2 for c2 in leidas if tuple(c2.get("meses") or []) == meses)
        for k in _VALORES_CONECTIVIDAD:
            if propia.get(k) != c.get(k):
                problemas.append({"problema": "cambió la conectividad de un trimestre ya publicado",
                                  "etiqueta": f"{'+'.join(meses)} · {k}", "antes": c.get(k), "ahora": propia.get(k)})
    nuevas = [c for c in leidas if tuple(c.get("meses") or []) not in pm]
    if not nuevas:
        return problemas
    if len(nuevas) > 1:
        problemas.append({"problema": "hay más de una entrada nueva de conectividad",
                          "detalle": ["+".join(str(m) for m in (c.get("meses") or [])) for c in nuevas]})
        return problemas
    nueva = nuevas[0]
    meses = tuple(nueva.get("meses") or [])
    validos = [m for m in pm if m and all(isinstance(x, str) and len(x) == 7 for x in m)]
    if not validos or not meses or not all(isinstance(x, str) and len(x) == 7 for x in meses):
        problemas.append({"problema": "entrada nueva de conectividad con meses ilegibles o sin trimestre publicado del cual seguir",
                          "leido": list(meses)})
        return problemas
    ultimo = max(validos, key=max)
    esperado = _trimestre_siguiente(ultimo)
    if meses != esperado:
        problemas.append({"problema": "la conectividad nueva no es el trimestre siguiente al último publicado",
                          "leido": list(meses), "esperado": list(esperado)})
        return problemas
    if RETENER_TRIMESTRE_NUEVO_DE_CONECTIVIDAD:
        anterior = pm[ultimo]
        cocientes = {}
        for k in _VALORES_CONECTIVIDAD:
            a, b = nueva.get(k), anterior.get(k)
            cocientes[k] = round(a / b, 4) if _num(a) and _num(b) and b else None
        problemas.append({
            "problema": f"Trimestre nuevo de conectividad {meses[0]} a {meses[-1]}: hay que revisarlo a mano contra el PDF",
            "leido": {k: nueva.get(k) for k in _VALORES_CONECTIVIDAD},
            "trimestre_anterior": {"meses": list(ultimo), **{k: anterior.get(k) for k in _VALORES_CONECTIVIDAD}},
            "cociente_contra_el_anterior": cocientes})
    return problemas


def c1_estructura(lectura: dict, previa: dict | None, periodo: str | None = None) -> dict:
    """C1: las mismas ramas, categorías (nombre, años y coeficiente), jerarquías,
    adicionales, tramos de ROE y valores nulos que la grilla anterior; nada falta
    ni sobra, ninguna celda sin leer, y la IA no anotó diferencias. En la
    conectividad se exige que exista una entrada que cubra el período y que las
    entradas de trimestres ya publicados no hayan cambiado."""
    g = lectura["contenido"]
    problemas = []
    # D29: los comentarios de la IA (`notas`) NUNCA retienen por sí solos; se guardan y se muestran. Lo que sí
    # frena son los defectos de la respuesta (un valor que no era número, una fila ilegible o repetida).
    for n in lectura.get("defectos") or []:
        problemas.append({"problema": "defecto en la respuesta de la lectura", "detalle": str(n)})
    for k in CLAVES_DATOS:
        if k not in g:
            problemas.append({"problema": "falta una sección", "detalle": k})
    if problemas and any(p["problema"] == "falta una sección" for p in problemas):
        return _res("C1", "Estructura", False, "Faltan secciones de la grilla.", problemas)
    for c in celdas(g):
        # Pueden ser nulos a propósito: el conformado desde los 16 años, los años de
        # una jerarquía y el tope de la última fila de ROE. Si faltan donde no
        # deben, lo atrapan la forma y la comparación con la grilla anterior.
        if c["valor"] is None and c["tipo"] not in ("conformado", "hasta", "anios"):
            problemas.append({"problema": "celda sin leer", "ruta": c["ruta"], "etiqueta": c["etiqueta"]})
    for p in forma_valida({**g, "periodo": periodo or "x", "nombre": "x", "firmada": "x"}):
        problemas.append({"problema": "forma inválida", "detalle": p})
    if previa is not None:
        rp, rg = previa["ramas"], g["ramas"]
        # Se comparan como conjunto: la base guarda JSONB, que no conserva el orden de las claves.
        if set(rp) != set(rg):
            problemas.append({"problema": "ramas distintas", "detalle": f"antes {sorted(rp)}, ahora {sorted(rg)}"})
        for rk in rp:
            if rk not in rg:
                continue
            a, b = rp[rk]["categorias"], rg[rk]["categorias"]
            na, nb = [c["nombre"] for c in a], [c["nombre"] for c in b]
            for n in na:
                if n not in nb:
                    problemas.append({"problema": "categoría que falta", "etiqueta": f"{rk} · {n}"})
            for n in nb:
                if n not in na:
                    problemas.append({"problema": "categoría que sobra", "etiqueta": f"{rk} · {n}"})
            if na == nb:
                for i, (ca, cb) in enumerate(zip(a, b)):
                    for campo in ("anios", "coef"):
                        if ca.get(campo) != cb.get(campo):
                            problemas.append({"problema": f"cambió el {campo}", "ruta": f"ramas.{rk}.categorias.{i}.{campo}",
                                              "etiqueta": f"{rg[rk]['nombre']} · {cb['nombre']}",
                                              "antes": ca.get(campo), "ahora": cb.get(campo)})
                    if (ca.get("conformado") is None) != (cb.get("conformado") is None):
                        problemas.append({"problema": "cambió dónde hay conformado",
                                          "ruta": f"ramas.{rk}.categorias.{i}.conformado",
                                          "etiqueta": f"{rg[rk]['nombre']} · {cb['nombre']}"})
            elif sorted(na) == sorted(nb):
                problemas.append({"problema": "cambió el orden de las categorías", "detalle": rk})
        ap, ag = previa["adicionales"], g["adicionales"]
        for k in sorted(set(ap) | set(ag)):
            if k not in ag:
                problemas.append({"problema": "adicional que falta", "detalle": k})
            elif k not in ap:
                problemas.append({"problema": "adicional nuevo", "detalle": k})
            elif isinstance(ap[k], dict):
                if not isinstance(ag[k], dict):
                    problemas.append({"problema": "adicional con otra forma", "detalle": k})
                    continue
                for k2 in sorted(set(ap[k]) | set(ag[k])):
                    if k2 not in ag[k]:
                        problemas.append({"problema": "adicional que falta", "detalle": f"{k} · {k2}"})
                    elif k2 not in ap[k]:
                        problemas.append({"problema": "adicional nuevo", "detalle": f"{k} · {k2}"})
        if previa["roe"]["tramos"] != g["roe"]["tramos"]:
            problemas.append({"problema": "cambiaron los tramos de ROE",
                              "antes": previa["roe"]["tramos"], "ahora": g["roe"]["tramos"]})
        if len(previa["roe"]["filas"]) != len(g["roe"]["filas"]):
            problemas.append({"problema": "cambió la cantidad de filas de ROE"})
        if sorted(previa["dia_bancario"]) != sorted(g["dia_bancario"]):
            problemas.append({"problema": "cambiaron los datos del Día del Bancario"})
        problemas.extend(_problemas_conectividad(previa, g, periodo))
    if periodo and not any(periodo in (c.get("meses") or []) for c in (g.get("conectividad") or [])):
        problemas.append({"problema": "no hay conectividad para el período", "detalle": periodo})
    if problemas:
        return _res("C1", "Estructura", False, f"{len(problemas)} diferencia(s) de estructura o celdas sin leer.", problemas)
    conservadas = conectividad_conservada(previa, g, periodo)
    resumen = ("Mismas ramas, categorías, jerarquías y adicionales que la grilla anterior."
               if previa is not None else "Estructura completa (no hay grilla anterior con qué compararla).")
    if conservadas:
        resumen += " " + texto_conservada(conservadas) + "."
    return _res("C1", "Estructura", True, resumen,
                [{"conservada": texto_conservada([c]), "meses": c.get("meses")} for c in conservadas])


# ---------------------------------------------------------------- C2
def c2_doble_lectura(lecturas: list) -> dict:
    """C2: las dos lecturas independientes coinciden celda por celda, nombres
    incluidos. Sin dos lecturas, no pasa."""
    if len(lecturas) < 2:
        return _res("C2", "Doble lectura", False, "Hace falta leer dos veces y hubo una sola lectura.")
    a, b = plano(lecturas[0]["contenido"]), plano(lecturas[1]["contenido"])
    dif = []
    for ruta in sorted(set(a) | set(b)):
        if ruta not in a or ruta not in b or a[ruta] != b[ruta]:
            dif.append({"ruta": ruta, "primera": a.get(ruta, "(no existe)"), "segunda": b.get(ruta, "(no existe)")})
    pi = [l.get("periodo_impreso") for l in lecturas[:2]]
    if pi[0] != pi[1]:
        dif.append({"ruta": "periodo_impreso", "primera": pi[0], "segunda": pi[1]})
    if dif:
        return _res("C2", "Doble lectura", False, f"Las dos lecturas difieren en {len(dif)} celda(s) de {len(set(a) | set(b))}.", dif)
    return _res("C2", "Doble lectura", True, f"Las dos lecturas coinciden en las {len(a)} celdas.")


# ---------------------------------------------------------------- C3
def _celda(g: dict, ruta: str):
    for c in celdas(g):
        if c["ruta"] == ruta:
            return c["valor"]
    return None


def c3_anclas(lectura: dict, comunicado: dict | None, tolerancias: dict | None = None) -> dict:
    """C3: el salario inicial (conformado de la categoría Inicial, en las tres
    ramas) y el ROE (monto anual del tramo 3,5 % a 8,75 % de la primera fila,
    dividido 12) de la grilla leída son los del texto del comunicado, al
    centavo; y, si el comunicado lo trae, el mínimo del Día del Bancario."""
    tol_general = _tol(tolerancias)["c3_centavos"]
    tol_roe = _tol(tolerancias)["c3_roe_centavos"]
    if not comunicado or not _num(comunicado.get("inicial")) or not _num(comunicado.get("roe")):
        return _res("C3", "Anclas del comunicado", False, "No hay comunicado con el inicial y el ROE para controlar.")
    g = lectura["contenido"]
    det = []

    def cmp(etiqueta, leido, esperado, tol=None):
        tol = tol_general if tol is None else tol
        ok = _num(leido) and abs(round(leido, 2) - esperado) <= tol + 1e-9
        det.append({"ancla": etiqueta, "grilla": leido, "comunicado": esperado, "coincide": bool(ok)})

    for rk, r in (g.get("ramas") or {}).items():
        ini = next((c for c in r.get("categorias", []) if c.get("anios") == 0), None)
        cmp(f"Conformado inicial · {r.get('nombre', rk)}", ini.get("conformado") if ini else None, comunicado["inicial"])
    anual = ((g.get("roe") or {}).get("filas") or [{}])[0].get("anual") or []
    roe_mes = round(anual[1] / 12, 2) if len(anual) > 1 and _num(anual[1]) else None
    cmp("ROE mensual (anual del tramo 3,5 % a 8,75 % ÷ 12)", roe_mes, comunicado["roe"], tol_roe)
    minimo = comunicado.get("dia_bancario_minimo")
    if _num(minimo):
        cmp("Día del Bancario · mínimo", (g.get("dia_bancario") or {}).get("minimo"), minimo)
    malas = [d for d in det if not d["coincide"]]
    if malas:
        return _res("C3", "Anclas del comunicado", False, f"{len(malas)} ancla(s) no coinciden con el comunicado.", malas)
    nota = "" if _num(minimo) else " (el comunicado no trae el mínimo del Día del Bancario)"
    return _res("C3", "Anclas del comunicado", True, f"Inicial y ROE coinciden con el comunicado al centavo{nota}.", det)


# ---------------------------------------------------------------- C4
def _redondea_a_un_decimal(x: float) -> float:
    return round(x * 10 + 1e-9) / 10


def _factor_de_mayor_cobertura(intervalos: list) -> tuple:
    """El factor f que cae dentro de la mayor cantidad de intervalos [lo, hi] (barrido de
    extremos), y los índices de los intervalos que NO lo contienen. Si todos se cruzan, es
    el centro de la intersección. Con un empate, el de menor índice (determinista)."""
    eventos = sorted([(lo, 0, i) for i, (lo, hi) in enumerate(intervalos)] + [(hi, 1, i) for i, (lo, hi) in enumerate(intervalos)])
    activos, mejor, mejor_lo = 0, -1, None
    for x, tipo, _ in eventos:
        if tipo == 0:
            activos += 1
            if activos > mejor:
                mejor, mejor_lo = activos, x
        else:
            activos -= 1
    cubren = [i for i, (lo, hi) in enumerate(intervalos) if lo <= mejor_lo <= hi]
    f = (max(intervalos[i][0] for i in cubren) + min(intervalos[i][1] for i in cubren)) / 2
    fuera = [i for i, (lo, hi) in enumerate(intervalos) if not lo <= f <= hi]
    return f, fuera


def _pares_que_escalan(contenido: dict, previa: dict) -> list:
    """Los pares (celda anterior, celda nueva) de importes que escalan con el factor y que están
    en las dos grillas. Una celda sin leer (nula) no forma par."""
    nuevas = {c["ruta"]: c for c in celdas(contenido)}
    pares = []
    for c in celdas(previa):
        n = nuevas.get(c["ruta"])
        if c["tipo"] in ESCALAN and n and _num(c["valor"]) and c["valor"] >= 1000 and _num(n["valor"]):
            pares.append((c, n))
    return pares


def _factor_de_celdas(contenido: dict, previa: dict, tol: dict) -> dict | None:
    """El factor del mes: el punto que cae en más intervalos de redondeo (ver `c4_factor_unico`).
    None si hay menos de TOPE_HASTA_FACTOR_MIN_CELDAS importes comparables."""
    pares = _pares_que_escalan(contenido, previa)
    if len(pares) < TOPE_HASTA_FACTOR_MIN_CELDAS:
        return None
    f_mediano = statistics.median(n["valor"] / c["valor"] for c, n in pares)
    margenes = []
    for c, n in pares:
        coef = n["coef"] if _num(n.get("coef")) else 1.0
        margenes.append(0.005 * (1 + f_mediano) + 0.005 * coef + tol["c4_extra"])
    intervalos = [((n["valor"] - h) / c["valor"], (n["valor"] + h) / c["valor"]) for (c, n), h in zip(pares, margenes)]
    f, fuera = _factor_de_mayor_cobertura(intervalos)
    return {"pares": pares, "margenes": margenes, "f": f, "fuera": fuera}


def c4_factor_unico(lectura: dict, previa: dict | None, comunicado: dict | None,
                    tolerancias: dict | None = None) -> dict:
    """C4 (D19): cada importe nuevo es el anterior por el MISMO factor, al centavo
    (dentro de lo que explica el redondeo), y ese factor redondea al porcentaje del
    comunicado.

    Para cada celda que escala, el factor tiene que caer en el intervalo que deja
    el redondeo: nuevo = redondeo(anterior × f) con el anterior ya redondeado, y en un
    básico o conformado la unidad (que se redondea al centavo antes de multiplicar por
    el coeficiente) suma otro medio centavo × coeficiente. Eso da un margen por celda
    h = 0,005 × (1 + f) + 0,005 × coef + `c4_extra` (default 0: ningún margen de más) y
    el intervalo f ∈ [(nuevo − h) / anterior, (nuevo + h) / anterior]. El factor es el
    punto que cae en más intervalos (no la mediana: el mismo cálculo no depende de qué
    celdas están mal) y la grilla pasa SOLO si ese factor está en el intervalo de TODAS;
    las celdas que lo dejan fuera se listan. La conectividad queda afuera
    (trimestral) y los topes `hasta` del ROE se aceptan iguales o escalados (enteros) con hasta
    1 peso de diferencia (D26: el sindicato a veces trunca); los importes siguen al centavo."""
    if previa is None:
        return _res("C4", "Factor único", None, "No hay grilla anterior: el control no aplica.")
    tol = _tol(tolerancias)
    nuevas = {c["ruta"]: c for c in celdas(lectura["contenido"])}
    cf = _factor_de_celdas(lectura["contenido"], previa, tol)
    if cf is None:
        n = len(_pares_que_escalan(lectura["contenido"], previa))
        return _res("C4", "Factor único", False, f"Solo {n} importes comparables: no alcanza para medir el factor.")
    pares, margenes, f, fuera = cf["pares"], cf["margenes"], cf["f"], cf["fuera"]
    det, desvio_max, exceso_max = [], 0.0, 0.0
    for k, ((c, n), h) in enumerate(zip(pares, margenes)):
        desvio = abs(n["valor"] - c["valor"] * f)
        desvio_max = max(desvio_max, desvio)
        exceso_max = max(exceso_max, desvio - h)
        if k in fuera:
            det.append({"ruta": c["ruta"], "etiqueta": c["etiqueta"], "anterior": c["valor"], "nuevo": n["valor"],
                        "esperado": round(c["valor"] * f, 2), "desvio": round(desvio, 4), "permitido": round(h, 4),
                        "problema": "no admite el mismo factor que las demás celdas al centavo"})
    # Topes `hasta` de los tramos de ROE (duda abierta): iguales o escalados.
    hasta_info = []
    for c in celdas(previa):
        if c["tipo"] == "hasta" and _num(c["valor"]):
            n = nuevas.get(c["ruta"])
            if not n or not _num(n["valor"]):
                det.append({"ruta": c["ruta"], "etiqueta": c["etiqueta"], "anterior": c["valor"], "nuevo": None,
                            "problema": "tope sin leer"})
            elif float(n["valor"]) != int(n["valor"]):
                det.append({"ruta": c["ruta"], "etiqueta": c["etiqueta"], "anterior": c["valor"], "nuevo": n["valor"],
                            "problema": "el tope del tramo tiene que ser un número entero de pesos"})
            elif n["valor"] == c["valor"]:
                hasta_info.append("igual")
            elif abs(n["valor"] - c["valor"] * f) <= min(tol["c4_hasta"], 1.0) + 1e-6:
                hasta_info.append("escalado")
            else:
                det.append({"ruta": c["ruta"], "etiqueta": c["etiqueta"], "anterior": c["valor"], "nuevo": n["valor"],
                            "esperado": f"{c['valor']} (igual) o {round(c['valor'] * f)} (escalado)",
                            "problema": "el tope del tramo ni se mantuvo ni escaló con el factor"})
    pct_factor = (f - 1) * 100
    pct_com = comunicado.get("porcentaje") if comunicado else None
    resumen_pct = ""
    if not _num(pct_com):
        det.insert(0, {"problema": "el comunicado no trae el porcentaje"})
    elif abs(pct_factor - pct_com) > 0.05 + 1e-9:
        det.insert(0, {"problema": "el factor no redondea al porcentaje del comunicado",
                       "factor": round(f, 6), "porcentaje_del_factor": round(pct_factor, 4), "comunicado": pct_com})
    else:
        resumen_pct = f" El factor {round(f, 6)} redondea a {_redondea_a_un_decimal(pct_factor)} % (comunicado: {pct_com} %)."
    info = {"factor": round(f, 8), "desvio_max": round(desvio_max, 4), "exceso_max": round(exceso_max, 4),
            "celdas_comparadas": len(pares), "topes_hasta": sorted(set(hasta_info))}
    if det:
        r = _res("C4", "Factor único", False,
                 f"{len(det)} celda(s) fuera del factor {round(f, 6)} (desvío máximo ${round(desvio_max, 2)}).", det)
    else:
        r = _res("C4", "Factor único", True,
                 f"{len(pares)} importes con un mismo factor {round(f, 6)}, desvío máximo ${round(desvio_max, 2)}.{resumen_pct}")
    r["medidas"] = info
    return r


# ---------------------------------------------------------------- C5
def c5_coherencia(lectura: dict, previa: dict | None = None, tolerancias: dict | None = None) -> dict:
    """C5: coherencia interna de la grilla leída. Básico = max(coeficiente ×
    unidad, básico mínimo de la rama); escalafón (coeficientes y básicos) no
    decreciente con la antigüedad y entre jerarquías; conformado no decreciente
    y mayor que el básico; adicionales y ROE ordenados; mínimo del Día del
    Bancario = suma fija + monto por coeficiente."""
    tol = _tol(tolerancias)["c5_pesos"]
    g = lectura["contenido"]
    det = []
    for rk, r in (g.get("ramas") or {}).items():
        nombre = r.get("nombre", rk)
        cats = r.get("categorias") or []
        ok_cat = [(i, c) for i, c in enumerate(cats) if _num(c.get("coef")) and _num(c.get("basico"))]
        piso_c = next((c for _, c in ok_cat if c.get("anios") == 0), None)
        if not piso_c:
            det.append({"problema": "no hay categoría Inicial con coeficiente y básico", "rama": nombre})
            continue
        piso = piso_c["basico"]
        sobre = [c["basico"] / c["coef"] for _, c in ok_cat if c["coef"] > 0 and c["basico"] > piso + 1]
        if len(sobre) < 3:
            det.append({"problema": "no alcanzan las categorías sobre el piso para medir la unidad", "rama": nombre})
            continue
        unidad = statistics.median(sobre)
        for i, c in ok_cat:
            esperado = max(round(c["coef"] * unidad, 2), piso)
            if abs(c["basico"] - esperado) > tol:
                det.append({"ruta": f"ramas.{rk}.categorias.{i}.basico", "etiqueta": f"{nombre} · {c['nombre']} · básico",
                            "leido": c["basico"], "esperado": esperado, "coef": c["coef"], "unidad": round(unidad, 3),
                            "problema": "el básico no es coeficiente × unidad ni el piso"})
        # Escalafón: la antigüedad (anios no nulo) y las jerarquías (anios nulo) por separado.
        for grupo, nombre_grupo in (([(i, c) for i, c in ok_cat if c.get("anios") is not None], "antigüedad"),
                                    ([(i, c) for i, c in ok_cat if c.get("anios") is None], "jerarquías")):
            grupo = sorted(grupo, key=lambda x: (x[1].get("anios") if nombre_grupo == "antigüedad" else x[0]))
            for (_, a), (j, b) in zip(grupo, grupo[1:]):
                for campo in ("coef", "basico"):
                    if b[campo] < a[campo] - 1e-9:
                        det.append({"ruta": f"ramas.{rk}.categorias.{j}.{campo}", "etiqueta": f"{nombre} · {b['nombre']} · {campo}",
                                    "problema": f"decrece respecto de «{a['nombre']}» ({nombre_grupo})",
                                    "anterior": a[campo], "leido": b[campo]})
        conf = [(i, c) for i, c in enumerate(cats) if _num(c.get("conformado"))]
        for k, (i, c) in enumerate(conf):
            if _num(c.get("basico")) and c["conformado"] <= c["basico"]:
                det.append({"ruta": f"ramas.{rk}.categorias.{i}.conformado", "etiqueta": f"{nombre} · {c['nombre']} · conformado",
                            "problema": "el conformado no supera al básico", "leido": c["conformado"], "basico": c["basico"]})
            if k and c["conformado"] < conf[k - 1][1]["conformado"] - 1e-9:
                det.append({"ruta": f"ramas.{rk}.categorias.{i}.conformado", "etiqueta": f"{nombre} · {c['nombre']} · conformado",
                            "problema": "el conformado decrece con la antigüedad", "leido": c["conformado"],
                            "anterior": conf[k - 1][1]["conformado"]})
    if not g.get("ramas"):
        det.append({"problema": "la grilla no tiene ramas"})
    adic = g.get("adicionales") or {}
    tit = adic.get("titulos") or {}
    orden = [tit.get(k) for k in ("secundario", "terciario", "universitario")]
    if all(_num(x) for x in orden) and not (orden[0] < orden[1] < orden[2]):
        det.append({"problema": "los títulos no crecen secundario < terciario < universitario", "leido": orden})
    if previa is not None:
        for k in ("titulos", "zona_patagonica"):
            ant, nue = (previa["adicionales"].get(k) or {}), (adic.get(k) or {})
            if set(ant) == set(nue) and all(_num(v) for v in nue.values()):
                if sorted(ant, key=lambda x: ant[x]) != sorted(nue, key=lambda x: nue[x]):
                    det.append({"problema": f"cambió el orden de los importes de {k}", "antes": ant, "ahora": nue})
    roe = g.get("roe") or {}
    filas = roe.get("filas") or []
    for i, f in enumerate(filas):
        a = f.get("anual") or []
        if a and a[0] != 0:
            det.append({"ruta": f"roe.filas.{i}.anual.0", "problema": "el primer tramo de ROE debería ser 0", "leido": a[0]})
        for j in range(1, len(a)):
            if _num(a[j]) and _num(a[j - 1]) and a[j] < a[j - 1]:
                det.append({"ruta": f"roe.filas.{i}.anual.{j}", "problema": "el ROE decrece al subir de tramo", "leido": a[j], "anterior": a[j - 1]})
        if i:
            for j, (x, y) in enumerate(zip(filas[i - 1].get("anual") or [], a)):
                if _num(x) and _num(y) and y < x:
                    det.append({"ruta": f"roe.filas.{i}.anual.{j}", "problema": "el ROE decrece al subir de fila", "leido": y, "anterior": x})
    topes = [f.get("hasta") for f in filas[:-1]]
    if all(_num(t) for t in topes) and topes != sorted(topes):
        det.append({"problema": "los topes de los tramos de ROE no crecen", "leido": topes})
    db = g.get("dia_bancario") or {}
    if all(_num(db.get(k)) for k in ("suma_fija", "por_coeficiente", "minimo")):
        if abs(round(db["suma_fija"] + db["por_coeficiente"], 2) - db["minimo"]) > 0.011:
            det.append({"ruta": "dia_bancario.minimo", "problema": "el mínimo no es suma fija + monto por coeficiente",
                        "leido": db["minimo"], "esperado": round(db["suma_fija"] + db["por_coeficiente"], 2)})
    for i, c in enumerate(g.get("conectividad") or []):
        v = [c.get("diario"), c.get("mas_de_4_dias"), c.get("mensual")]
        if all(_num(x) for x in v) and not (0 < v[0] <= v[1] <= v[2]):
            det.append({"ruta": f"conectividad.{i}", "problema": "la conectividad no crece diario ≤ más de 4 días ≤ mensual", "leido": v})
    if det:
        return _res("C5", "Coherencia interna", False, f"{len(det)} incoherencia(s) dentro de la grilla.", det)
    return _res("C5", "Coherencia interna", True, "Básicos = coeficiente × unidad (o el piso), escalafón y ROE ordenados.")


# ---------------------------------------------------------------- C6
def c6_periodo(periodo: str | None, vigente_periodo: str | None, comunicado: dict | None,
               lecturas: list) -> dict:
    """C6: el período es el mes siguiente al de la grilla vigente (un salto
    retiene), es el del comunicado y es el que el propio PDF imprime en sus
    encabezados («Septiembre 2026»)."""
    det = []
    if not periodo:
        return _res("C6", "Período", False, "No se pudo determinar el período.")
    if vigente_periodo is None:
        return _res("C6", "Período", None, "No hay grilla vigente: el control no aplica.")
    esperado = _mes_siguiente(vigente_periodo)
    if periodo != esperado:
        det.append({"problema": "no es el mes siguiente al vigente", "vigente": vigente_periodo, "periodo": periodo, "esperado": esperado})
    if comunicado and comunicado.get("periodo") != periodo:
        det.append({"problema": "el comunicado es de otro mes", "comunicado": comunicado.get("periodo"), "periodo": periodo})
    for i, l in enumerate(lecturas):
        pi = l.get("periodo_impreso")
        if pi != periodo:
            det.append({"problema": "el período impreso en el PDF no es el esperado" if pi else "no se leyó el período impreso en el PDF",
                        "lectura": i + 1, "impreso": pi, "periodo": periodo})
    if det:
        return _res("C6", "Período", False, "El período no coincide.", det)
    return _res("C6", "Período", True, f"{periodo} es el mes siguiente a {vigente_periodo} y coincide con el comunicado y con el PDF.")


def _mes_siguiente(periodo: str) -> str:
    a, m = int(periodo[:4]), int(periodo[5:7])
    return f"{a + 1:04d}-01" if m == 12 else f"{a:04d}-{m + 1:02d}"


# ---------------------------------------------------------------- D28
# D28 (SDN, 2026-11-16, la octubre real: una firma tapa UNA celda del PDF y la grilla quedó retenida
# por eso). Una celda que escala con el factor del mes y que ninguna de las dos lecturas pudo leer se
# completa por cálculo, valor vigente × factor, y la grilla se publica sola si todo lo demás pasa.
# Es la ÚNICA excepción a «nunca se completa un importe» y está acotada: a lo sumo esta cantidad de
# celdas por grilla. Con más, la grilla se retiene como siempre: dos o tres firmas sobre importes de
# una tabla ya son un PDF que una persona tiene que mirar, y cada celda completada es un dato que
# nadie leyó.
MAX_CELDAS_CALCULADAS = 2


def pesos_ar(v: float) -> str:
    """3622194.41 -> «3.622.194,41» (formato argentino)."""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _formatos_ar(v: float) -> tuple:
    return (pesos_ar(v), pesos_ar(v).replace(".", ""))


def parcial_compatible(parcial: str, valor: float) -> bool:
    """¿El valor es compatible, dígito por dígito, con lo que se alcanzaba a ver («3.?22.194,42», un «?»
    por dígito ilegible)? Se admite ±1 centavo en el valor por el redondeo (la unidad se redondea al
    centavo antes de multiplicar). Con o sin puntos de miles."""
    txt = re.sub(r"[\s$]", "", parcial or "")
    if not txt:
        return False
    for delta in (0.0, 0.01, -0.01):
        for f in _formatos_ar(round(valor + delta, 2)):
            if len(f) == len(txt) and all(t == "?" or t == ch for t, ch in zip(txt, f)):
                return True
    return False


def completar_celdas(lecturas: list, previa: dict | None, tolerancias: dict | None = None) -> dict:
    """D28. Devuelve {"lecturas": copias con las celdas completadas (o las mismas, si no hubo),
    "celdas": [una entrada por celda completada], "motivos": [por qué no se completó algo]}.

    Reglas: solo celdas que ESCALAN (básico, conformado, adicionales, ROE anual, Día del Bancario) y
    que existen con importe en la grilla anterior; nunca coeficientes, años, topes `hasta` ni
    conectividad. A lo sumo MAX_CELDAS_CALCULADAS. La celda tiene que estar sin leer (null) en las DOS
    lecturas, o en una y, en la otra, un valor que coincida con el calculado a ±0,01. El factor es el de
    C4 con las demás celdas; el valor, vigente × factor al centavo. Si alguna lectura dejó una lectura
    parcial («3.?22.194,42»), el valor calculado tiene que ser compatible con ella dígito por dígito.
    Todo o nada: si una celda candidata no cumple, no se completa ninguna. Que lo demás pase (C1 a C6 con
    las celdas puestas) lo verifica `controlar_completando`, no esta función."""
    sin = {"lecturas": lecturas, "celdas": [], "motivos": []}
    if previa is None or len(lecturas) < 2:
        return sin
    tol = _tol(tolerancias)
    ca = {c["ruta"]: c for c in celdas(lecturas[0]["contenido"])}
    cb = {c["ruta"]: c for c in celdas(lecturas[1]["contenido"])}
    cp = {c["ruta"]: c for c in celdas(previa)}
    candidatas = []
    for ruta, a in ca.items():
        b = cb.get(ruta)
        p = cp.get(ruta)
        if b is None or p is None or (a["valor"] is not None and b["valor"] is not None):
            continue
        if a["tipo"] not in ESCALAN or not _num(p["valor"]) or p["valor"] < 1000:
            continue
        if any(v is not None and not _num(v) for v in (a["valor"], b["valor"])):
            continue
        candidatas.append((ruta, a, b, p))
    if not candidatas:
        return sin
    etiquetas = [a["etiqueta"] for _, a, _, _ in candidatas]
    if len(candidatas) > MAX_CELDAS_CALCULADAS:
        return {**sin, "motivos": [{"problema": f"D28: hay {len(candidatas)} celdas que escalan sin leer y solo se completan hasta "
                                                f"{MAX_CELDAS_CALCULADAS} por grilla", "celdas": etiquetas}]}
    apartada = copy.deepcopy(lecturas[0]["contenido"])
    for ruta, *_ in candidatas:
        apartada = asignar(apartada, ruta, None)
    cf = _factor_de_celdas(apartada, previa, tol)
    if cf is None:
        return {**sin, "motivos": [{"problema": "D28: no hay suficientes importes leídos para medir el factor", "celdas": etiquetas}]}
    f = cf["f"]
    entradas, motivos = [], []
    for ruta, a, b, p in candidatas:
        calc = round(p["valor"] * f, 2)
        parciales = list(dict.fromkeys(t for t in (((l.get("parciales") or {}).get(ruta)) for l in lecturas[:2]) if t))
        leido = [v for v in (a["valor"], b["valor"]) if v is not None]
        problema = None
        if leido and abs(leido[0] - calc) > 0.01 + 1e-9:
            problema = f"D28: una lectura no pudo leer la celda y la otra leyó {leido[0]}, que no coincide con el valor calculado {calc}"
        elif any(not parcial_compatible(t, calc) for t in parciales):
            problema = f"D28: el valor calculado {calc} no es compatible con lo que se alcanzaba a ver ({' / '.join(parciales)})"
        if problema:
            motivos.append({"problema": problema, "ruta": ruta, "etiqueta": a["etiqueta"], "vigente": p["valor"],
                            "factor": round(f, 8), "calculado": calc, "lectura_parcial": parciales})
            continue
        f6 = f"{f:.6f}".replace(".", ",")
        texto = (f"{a['etiqueta']}: $ {pesos_ar(calc)} calculado (vigente × {f6}); tapado en el PDF"
                 + (f", se leía «{' / '.join(parciales)}»" if parciales else ""))
        entradas.append({"ruta": ruta, "etiqueta": a["etiqueta"], "valor_vigente": p["valor"], "factor": round(f, 8),
                         "valor_calculado": calc, "lectura_parcial": parciales,
                         "leido_en_una_lectura": leido[0] if leido else None, "texto": texto})
    if motivos:
        return {**sin, "motivos": motivos}
    nuevas = []
    for l in lecturas:
        cont = l["contenido"]
        for e in entradas:
            cont = asignar(cont, e["ruta"], e["valor_calculado"])
        nuevas.append({**l, "contenido": cont})
    return {"lecturas": nuevas, "celdas": entradas, "motivos": []}


def texto_calculadas(entradas: list) -> str:
    """La frase para la nota de la grilla y el aviso de la publicación."""
    if not entradas:
        return ""
    return " ".join(e["texto"] + "." for e in entradas) + " Incertidumbre de ±1 centavo por el redondeo (D28)."


# ---------------------------------------------------------------- todos
def _controlar_crudo(lecturas: list, previa: dict | None, comunicado: dict | None, periodo: str | None,
                     vigente_periodo: str | None = None, tolerancias: dict | None = None) -> list:
    defectos = [d for l in lecturas[:2] for d in (l.get("defectos") or [])]
    ctl = [
        ("C1", lambda: c1_estructura({**lecturas[0], "defectos": defectos}, previa, periodo)),
        ("C2", lambda: c2_doble_lectura(lecturas)),
        ("C3", lambda: c3_anclas(lecturas[0], comunicado, tolerancias)),
        ("C4", lambda: c4_factor_unico(lecturas[0], previa, comunicado, tolerancias)),
        ("C5", lambda: c5_coherencia(lecturas[0], previa, tolerancias)),
        ("C6", lambda: c6_periodo(periodo, vigente_periodo, comunicado, lecturas)),
    ]
    salida = []
    for clave, f in ctl:
        try:
            salida.append(f())
        except Exception as e:                               # un dato raro nunca se cuenta como «pasó»
            salida.append(_res(clave, clave, False, f"No se pudo evaluar el control ({type(e).__name__}: {e})."))
    return salida


def controlar_completando(lecturas: list, previa: dict | None, comunicado: dict | None, periodo: str | None,
                          vigente_periodo: str | None = None, tolerancias: dict | None = None) -> dict:
    """Los seis controles con la regla D28 aplicada. Devuelve {"resultados", "lecturas", "celdas_calculadas"}:
    las lecturas a usar (con las celdas completadas si D28 se aplicó y TODO lo demás pasa; si no, las mismas
    de entrada, y la grilla se retiene como siempre) y una entrada por celda completada. Los motivos por los
    que no se completó algo se suman al detalle de C1. Nunca levanta."""
    try:
        d = completar_celdas(lecturas, previa, tolerancias)
    except Exception as e:                                   # D28 es una ayuda: si falla, rige la regla de siempre
        d = {"lecturas": lecturas, "celdas": [], "motivos": [{"problema": f"D28: no se pudo evaluar ({type(e).__name__}: {e})"}]}
    if d["celdas"]:
        res = _controlar_crudo(d["lecturas"], previa, comunicado, periodo, vigente_periodo, tolerancias)
        if todos_pasan(res):
            c1 = res[0]
            c1["detalle"] = list(d["celdas"]) + c1["detalle"]
            c1["resumen"] += f" Se completó por cálculo {len(d['celdas'])} celda(s) que el PDF no dejaba leer (D28)."
            return {"resultados": res, "lecturas": d["lecturas"], "celdas_calculadas": d["celdas"]}
        d["motivos"] = [{"problema": "D28: la celda no se completó porque, con el valor calculado puesto, no pasan todos los controles ("
                                     + ", ".join(fallan(res)) + ")", "celdas": [e["etiqueta"] for e in d["celdas"]],
                         "controles": {r["control"]: r["resumen"] for r in res if r.get("pasa") is not True}}]
    res = _controlar_crudo(lecturas, previa, comunicado, periodo, vigente_periodo, tolerancias)
    if d["motivos"]:
        res[0]["detalle"] = (res[0]["detalle"] + d["motivos"])[:TOPE_DETALLE]
    return {"resultados": res, "lecturas": lecturas, "celdas_calculadas": []}


def controlar(lecturas: list, previa: dict | None, comunicado: dict | None, periodo: str | None,
              vigente_periodo: str | None = None, tolerancias: dict | None = None) -> list:
    """Los seis controles sobre la primera lectura (la segunda entra en C2), con la regla D28.
    `previa` es el contenido de la grilla vigente (None en el ensayo de una
    grilla sin anterior). Nunca levanta: un control que falla por un dato
    raro devuelve `pasa: False` con el error."""
    return controlar_completando(lecturas, previa, comunicado, periodo, vigente_periodo, tolerancias)["resultados"]


def todos_pasan(resultados: list) -> bool:
    return len(resultados) == 6 and all(r.get("pasa") is True for r in resultados)


def fallan(resultados: list) -> list:
    return [r["control"] for r in resultados if r.get("pasa") is not True]


def comparar_con_publicada(leida: dict, publicada: dict) -> dict:
    """La comparación celda por celda de una lectura contra una grilla ya
    publicada (el ensayo de lectura): cuántas celdas coinciden y la lista de las
    que no, con lo que dijo cada una. Una celda que la lectura no trae cuenta
    como distinta."""
    a, b = plano(leida), plano({k: publicada.get(k) for k in CLAVES_DATOS})
    et = {c["ruta"]: c["etiqueta"] for c in celdas({k: publicada.get(k) for k in CLAVES_DATOS})}
    dif = []
    for ruta in sorted(set(a) | set(b)):
        if ruta not in a or ruta not in b or a[ruta] != b[ruta]:
            dif.append({"ruta": ruta, "etiqueta": et.get(ruta, ruta), "publicada": b.get(ruta, "(no existe)"),
                        "leida": a.get(ruta, "(no existe)")})
    total = len(set(a) | set(b))
    return {"celdas": total, "iguales": total - len(dif), "distintas": len(dif), "detalle": dif[:TOPE_DETALLE],
            "mas": max(0, len(dif) - TOPE_DETALLE)}

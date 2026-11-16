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
  (hay una duda abierta: se aceptan iguales a los de antes o escalados por
  el mismo factor; el detalle dice cuál pasó).

Tolerancias (parámetros, con default ESTRICTO; se calibran con grillas
reales en el bloque 6 y SDN ve el número antes de fijarlo):
  c3_centavos   0,00  anclas del comunicado (inicial y mínimo del Día del Bancario), al centavo exacto
  c3_roe_centavos 0,01 el ROE sale de dividir un monto anual por 12: un centavo de redondeo
  c4_extra      0,01  pesos por encima de lo que explica el redondeo
  c4_hasta      1,5   pesos, en los topes `hasta` escalados
  c5_pesos      2,00  básico contra coeficiente × unidad (la grilla firmada de
                       agosto trae hasta ~1,7 en ordenanza: es la fuente)
"""
import copy
import statistics

TOLERANCIAS = {"c3_centavos": 0.0, "c3_roe_centavos": 0.01, "c4_extra": 0.01, "c4_hasta": 1.5, "c5_pesos": 2.0}

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

    for rk, r in (g.get("ramas") or {}).items():
        nombre_rama = r.get("nombre", rk)
        for i, c in enumerate(r.get("categorias") or []):
            base = f"ramas.{rk}.categorias.{i}"
            et = f"{nombre_rama} · {c.get('nombre')}"
            agregar(f"{base}.anios", f"{et} · años", c.get("anios"), "anios")
            agregar(f"{base}.coef", f"{et} · coeficiente", c.get("coef"), "coef")
            agregar(f"{base}.basico", f"{et} · básico", c.get("basico"), "basico", c.get("coef"))
            agregar(f"{base}.conformado", f"{et} · conformado", c.get("conformado"), "conformado", c.get("coef"))
    adic = g.get("adicionales") or {}
    for k, v in adic.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                agregar(f"adicionales.{k}.{k2}", f"Adicional · {k.replace('_', ' ')} · {k2}", v2, "adicional")
        else:
            agregar(f"adicionales.{k}", f"Adicional · {k.replace('_', ' ')}", v, "adicional")
    for i, c in enumerate(g.get("conectividad") or []):
        meses = "+".join(c.get("meses") or [])
        for k in ("diario", "mas_de_4_dias", "mensual"):
            agregar(f"conectividad.{i}.{k}", f"Conectividad {meses} · {k.replace('_', ' ')}", c.get(k), "conectividad")
    roe = g.get("roe") or {}
    tramos = roe.get("tramos") or []
    for i, f in enumerate(roe.get("filas") or []):
        agregar(f"roe.filas.{i}.hasta", f"ROE fila {i + 1} · tope del tramo de sueldo", f.get("hasta"), "hasta")
        for j, v in enumerate(f.get("anual") or []):
            tr = tramos[j] if j < len(tramos) else str(j)
            agregar(f"roe.filas.{i}.anual.{j}", f"ROE fila {i + 1} · {tr} · anual", v, "roe")
    db = g.get("dia_bancario") or {}
    for k, v in db.items():
        agregar(f"dia_bancario.{k}", f"Día del Bancario · {k.replace('_', ' ')}", v, "dia_bancario")
    return out


ESCALAN = ("basico", "conformado", "adicional", "roe", "dia_bancario")


def forma_valida(g: dict) -> list:
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
def _meses_de(g: dict) -> dict:
    return {tuple(c.get("meses") or []): c for c in (g.get("conectividad") or [])}


def c1_estructura(lectura: dict, previa: dict | None, periodo: str | None = None) -> dict:
    """C1: las mismas ramas, categorías (nombre, años y coeficiente), jerarquías,
    adicionales, tramos de ROE y valores nulos que la grilla anterior; nada falta
    ni sobra, ninguna celda sin leer, y la IA no anotó diferencias. En la
    conectividad se exige que exista una entrada que cubra el período y que las
    entradas de trimestres ya publicados no hayan cambiado."""
    g = lectura["contenido"]
    problemas = []
    for n in lectura.get("notas") or []:
        problemas.append({"problema": "nota de la lectura", "detalle": str(n)})
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
        # Conectividad: por trimestre. Lo ya publicado no cambia solo.
        pm, gm = _meses_de(previa), _meses_de(g)
        for meses, c in pm.items():
            if meses in gm:
                for k in ("diario", "mas_de_4_dias", "mensual"):
                    if gm[meses].get(k) != c.get(k):
                        problemas.append({"problema": "cambió la conectividad de un trimestre ya publicado",
                                          "etiqueta": f"{'+'.join(meses)} · {k}", "antes": c.get(k), "ahora": gm[meses].get(k)})
    if periodo and not any(periodo in (c.get("meses") or []) for c in (g.get("conectividad") or [])):
        problemas.append({"problema": "no hay conectividad para el período", "detalle": periodo})
    if problemas:
        return _res("C1", "Estructura", False, f"{len(problemas)} diferencia(s) de estructura o celdas sin leer.", problemas)
    return _res("C1", "Estructura", True,
                "Mismas ramas, categorías, jerarquías y adicionales que la grilla anterior."
                if previa is not None else "Estructura completa (no hay grilla anterior con qué compararla).")


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


def c4_factor_unico(lectura: dict, previa: dict | None, comunicado: dict | None,
                    tolerancias: dict | None = None) -> dict:
    """C4 (D19): cada importe nuevo es el anterior por el MISMO factor, dentro de
    lo que explica el redondeo al centavo, y ese factor redondea al porcentaje
    del comunicado. El factor es la mediana de los cocientes; cada celda se
    compara contra `anterior × factor` con un margen de 0,005 × (1 + factor)
    (los dos importes redondeados) + 0,005 × coeficiente (la unidad redondeada
    se multiplica por el coeficiente) + `c4_extra`. La conectividad queda afuera
    (trimestral) y los topes `hasta` del ROE se aceptan iguales o escalados."""
    if previa is None:
        return _res("C4", "Factor único", None, "No hay grilla anterior: el control no aplica.")
    tol = _tol(tolerancias)
    nuevas = {c["ruta"]: c for c in celdas(lectura["contenido"])}
    pares = []
    for c in celdas(previa):
        n = nuevas.get(c["ruta"])
        if c["tipo"] in ESCALAN and n and _num(c["valor"]) and c["valor"] >= 1000 and _num(n["valor"]):
            pares.append((c, n))
    if len(pares) < TOPE_HASTA_FACTOR_MIN_CELDAS:
        return _res("C4", "Factor único", False, f"Solo {len(pares)} importes comparables: no alcanza para medir el factor.")
    f = statistics.median(n["valor"] / c["valor"] for c, n in pares)
    det, desvio_max, exceso_max = [], 0.0, 0.0
    for c, n in pares:
        coef = n["coef"] if _num(n.get("coef")) else 1.0
        permitido = 0.005 * (1 + f) + 0.005 * coef + tol["c4_extra"]
        desvio = abs(n["valor"] - c["valor"] * f)
        desvio_max = max(desvio_max, desvio)
        exceso_max = max(exceso_max, desvio - permitido)
        if desvio > permitido:
            det.append({"ruta": c["ruta"], "etiqueta": c["etiqueta"], "anterior": c["valor"], "nuevo": n["valor"],
                        "esperado": round(c["valor"] * f, 2), "desvio": round(desvio, 4), "permitido": round(permitido, 4)})
    # Topes `hasta` de los tramos de ROE (duda abierta): iguales o escalados.
    hasta_info = []
    for c in celdas(previa):
        if c["tipo"] == "hasta" and _num(c["valor"]):
            n = nuevas.get(c["ruta"])
            if not n or not _num(n["valor"]):
                det.append({"ruta": c["ruta"], "etiqueta": c["etiqueta"], "anterior": c["valor"], "nuevo": None,
                            "problema": "tope sin leer"})
            elif n["valor"] == c["valor"]:
                hasta_info.append("igual")
            elif abs(n["valor"] - c["valor"] * f) <= tol["c4_hasta"]:
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


# ---------------------------------------------------------------- todos
def controlar(lecturas: list, previa: dict | None, comunicado: dict | None, periodo: str | None,
              vigente_periodo: str | None = None, tolerancias: dict | None = None) -> list:
    """Los seis controles sobre la primera lectura (la segunda entra en C2).
    `previa` es el contenido de la grilla vigente (None en el ensayo de una
    grilla sin anterior). Nunca levanta: un control que falla por un dato
    raro devuelve `pasa: False` con el error."""
    ctl = [
        ("C1", lambda: c1_estructura(lecturas[0], previa, periodo)),
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

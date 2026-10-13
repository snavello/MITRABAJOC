# -*- coding: utf-8 -*-
"""Grillas salariales bancarias (CCT 18/75) y el recibo que corresponde.

Puro: no importa `db`. Las grillas viven en `data/grillas_bancarias/AAAA-MM.json`,
una por mes, transcriptas del PDF firmado que publica La Bancaria (la de
agosto 2026, con sus fuentes, también en `docs/cct-1875-bancarios.md`).
Una grilla nueva es un archivo nuevo: la calculadora de /entornos la ofrece
sola y las constantes de abajo pasan a ser las de la más nueva.

Lo usan `cargar_bancaria.py` (el lote sintético), la Calculadora bancaria de
/entornos → Herramientas (`calcular_recibo`), el generador de recibos PDF de
prueba (`docs/recibos-bancaria-prueba/`) y `test_grilla_bancaria.py`.
"""
import csv
import glob
import json
import os

_AQUI = os.path.dirname(os.path.abspath(__file__))
CARPETA_GRILLAS = os.path.join(_AQUI, "data", "grillas_bancarias")
TOPES_CSV = os.path.join(_AQUI, "data", "topes_ss.csv")


def _cargar_grillas() -> dict:
    grillas = {}
    for ruta in sorted(glob.glob(os.path.join(CARPETA_GRILLAS, "*.json"))):
        with open(ruta, encoding="utf-8") as f:
            g = json.load(f)
        grillas[g["periodo"]] = g
    if not grillas:
        raise RuntimeError(f"No hay grillas bancarias en {CARPETA_GRILLAS}")
    return grillas


GRILLAS = _cargar_grillas()
PERIODO_VIGENTE = max(GRILLAS)
_VIGENTE = GRILLAS[PERIODO_VIGENTE]


def grilla(periodo: str = "") -> dict:
    """La grilla de ese mes, o la vigente si no se dice cuál."""
    if not periodo:
        return _VIGENTE
    if periodo not in GRILLAS:
        raise ValueError(f"No hay grilla bancaria para {periodo}.")
    return GRILLAS[periodo]


# ---------------------------------------------------------------- vigente
# Constantes de la grilla más nueva, con la forma que ya usan el lote y el
# generador de PDF (rama administrativa, la que simula el lote).
GRILLA = f"{_VIGENTE['nombre'].lower()} (firmada {'/'.join(reversed(_VIGENTE['firmada'].split('-')))})"

_ADMIN = _VIGENTE["ramas"]["administrativa"]["categorias"]
# (años de antigüedad desde, coeficiente, básico, conformado). El conformado
# existe solo hasta los 15 años: desde los 20 el básico ya lo supera.
ESCALA_ADMINISTRATIVA = [(c["anios"], c["coef"], c["basico"], c["conformado"])
                         for c in _ADMIN if c["anios"] is not None]
# Jerarquías que no salen de la antigüedad: nombre -> (coeficiente, básico).
JERARQUIAS = {c["nombre"]: (c["coef"], c["basico"]) for c in _ADMIN if c["anios"] is None}
# Art. 44: la categoría también la da la antigüedad (promociones automáticas).
CATEGORIA_POR_ANTIGUEDAD = [
    (35, "2º Jefe de División de 1º"), (30, "2º Jefe de División de 2º"),
    (25, "2º Jefe de División de 3º"), (20, "Jefe de Sección"),
    (15, "Ayudante de firma"), (0, "Auxiliar"),
]

# Adicionales: montos fijos por mes, iguales para toda categoría (el texto de
# 1975 los daba como % del inicial; la grilla vigente, no).
_ADIC = _VIGENTE["adicionales"]
FUNCION_CAJERO = _ADIC["funcion_cajero"]
FALLA_DE_CAJA = _ADIC["falla_caja"]
FALLA_DE_CAJA_MONEDA_EXTRANJERA = _ADIC["falla_caja_moneda_extranjera"]
TITULOS = dict(_ADIC["titulos"])
ZONA_PATAGONICA = dict(_ADIC["zona_patagonica"])
GUARDERIA = _ADIC["guarderia"]

# ROE: (tope del tramo de sueldo bruto, [montos ANUALES por tramo de ROE del
# banco]). Se cobra 1/12 por mes. Columnas en TRAMOS_ROE.
TRAMOS_ROE = list(_VIGENTE["roe"]["tramos"])
ROE_TABLA = [(f["hasta"], f["anual"]) for f in _VIGENTE["roe"]["filas"]]

# Día del Bancario (6 de noviembre): suma fija + coeficiente × monto, con mínimo.
DIA_BANCARIO_SUMA_FIJA = _VIGENTE["dia_bancario"]["suma_fija"]
DIA_BANCARIO_POR_COEFICIENTE = _VIGENTE["dia_bancario"]["por_coeficiente"]
DIA_BANCARIO_MINIMO = _VIGENTE["dia_bancario"]["minimo"]


def fila_de_escala(anios: int) -> tuple:
    """(desde, coeficiente, básico, conformado) del tramo cumplido más alto."""
    fila = ESCALA_ADMINISTRATIVA[0]
    for f in ESCALA_ADMINISTRATIVA:
        if anios >= f[0]:
            fila = f
    return fila


def categoria_de(anios: int) -> str:
    for desde, nombre in CATEGORIA_POR_ANTIGUEDAD:
        if anios >= desde:
            return nombre
    return "Auxiliar"


def roe_mensual(bruto: float, tramo_roe: int, g: dict = None) -> float:
    """El ROE del mes: la fila la elige el sueldo bruto (sin el ROE), la
    columna el ROE del banco; la tabla es anual."""
    for f in (g or _VIGENTE)["roe"]["filas"]:
        if f["hasta"] is None or bruto <= f["hasta"]:
            return round(f["anual"][tramo_roe] / 12, 2)
    return 0.0


def dia_del_bancario(coeficiente: float, g: dict = None) -> float:
    d = (g or _VIGENTE)["dia_bancario"]
    return round(max(d["minimo"], d["suma_fija"] + coeficiente * d["por_coeficiente"]), 2)


# ---------------------------------------------------------------- topes
def tope_ss(periodo: str) -> dict | None:
    """El tope de aportes de la seguridad social vigente en ese mes, de
    data/topes_ss.csv (la misma semilla de la tabla de topes de la app):
    la última fila con vigencia_desde <= período."""
    elegido = None
    with open(TOPES_CSV, encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["vigencia_desde"] <= periodo:
                elegido = fila
    if not elegido:
        return None
    return {"desde": elegido["vigencia_desde"], "maximo": float(elegido["tope_maximo"]),
            "minimo": float(elegido["base_minima"])}


# ---------------------------------------------------------------- calculadora
MODOS_CONECTIVIDAD = {"": "Sin conectividad", "diario": "Diario (por día)",
                      "mas_de_4_dias": "Más de 4 días", "mensual": "Mensual"}
APORTES = [("JUBILACION", "Jubilación (SIPA, Ley 24.241)", 0.11),
           ("PAMI", "Ley 19.032 (INSSJP)", 0.03),
           ("OBRASOCIAL", "Obra social", 0.03)]


def _pesos(n: float) -> str:
    """$ 1.234.567,89, como se lee en un recibo argentino."""
    return "$ " + f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class EntradaInvalida(ValueError):
    pass


def opciones(periodo: str = "") -> dict:
    """Lo que la pantalla necesita para armar los controles de esa grilla."""
    g = grilla(periodo)
    return {
        "periodo": g["periodo"], "nombre": g["nombre"], "firmada": g["firmada"],
        "fuentes": g.get("fuentes", []),
        "grillas": [{"periodo": p, "nombre": GRILLAS[p]["nombre"]} for p in sorted(GRILLAS, reverse=True)],
        "ramas": {k: {"nombre": r["nombre"],
                      "categorias": [{"nombre": c["nombre"], "anios": c["anios"], "coef": c["coef"],
                                      "basico": c["basico"]}
                                     for c in r["categorias"]]}
                  for k, r in g["ramas"].items()},
        "titulos": list(g["adicionales"]["titulos"]),
        "zonas": list(g["adicionales"]["zona_patagonica"]),
        "tramos_roe": g["roe"]["tramos"],
        "conectividad": MODOS_CONECTIVIDAD,
    }


def _conectividad(g: dict) -> dict:
    for c in g["conectividad"]:
        if g["periodo"] in c["meses"]:
            return c
    return g["conectividad"][0]


def _num(valor, nombre, minimo=0.0, maximo=None) -> float:
    if valor in (None, ""):
        return 0.0
    try:
        n = float(str(valor).replace(",", "."))
    except ValueError:
        raise EntradaInvalida(f"{nombre}: no es un número.")
    if n < minimo or (maximo is not None and n > maximo):
        raise EntradaInvalida(f"{nombre}: fuera de rango.")
    return n


def calcular_recibo(entrada: dict) -> dict:
    """El recibo que corresponde según la grilla, renglón por renglón.

    `entrada`: periodo, rama, categoria (índice en la rama), cajero,
    falla_me, titulo, zona, guarderia, conectividad + dias_conectividad,
    dia_bancario, tramo_roe, afiliado + cuota_pct, ganancias (a mano).
    Devuelve los renglones (código, concepto, sección, importe, nota) y los
    totales. Los supuestos (lo que la grilla no dice) van marcados."""
    g = grilla(entrada.get("periodo") or "")
    rama = g["ramas"].get(entrada.get("rama") or "administrativa")
    if not rama:
        raise EntradaInvalida("Rama desconocida.")
    try:
        cat = rama["categorias"][int(entrada.get("categoria", 0))]
    except (ValueError, TypeError, IndexError):
        raise EntradaInvalida("Categoría desconocida.")
    adic = g["adicionales"]
    renglones = []

    def agregar(codigo, concepto, seccion, importe, nota="", supuesto=False):
        renglones.append({"codigo": codigo, "concepto": concepto, "seccion": seccion,
                          "importe": round(importe, 2), "nota": nota, "supuesto": supuesto})

    coef = f"{cat['coef']:.2f}".replace(".", ",")
    agregar("BAS", "Sueldo básico", "haberes", cat["basico"], f"{rama['nombre']}, {cat['nombre']} (coef. {coef})")
    if cat["conformado"] and cat["conformado"] > cat["basico"]:
        agregar("CONFOR", "Complemento salario conformado", "haberes", cat["conformado"] - cat["basico"],
                "Hasta el conformado de la categoría. Nombre provisorio: la grilla no dice cómo lo imprime un banco.",
                supuesto=True)
    if entrada.get("cajero"):
        agregar("CAJFUN", "Adicional función cajero", "haberes", adic["funcion_cajero"])
        agregar("CAJFAL", "Falla de caja", "haberes", adic["falla_caja"])
    if entrada.get("falla_me"):
        agregar("CAJFME", "Falla de caja moneda extranjera", "haberes", adic["falla_caja_moneda_extranjera"])
    titulo = entrada.get("titulo") or ""
    if titulo:
        if titulo not in adic["titulos"]:
            raise EntradaInvalida("Título desconocido.")
        agregar("TITULO", f"Adicional título {titulo}", "haberes", adic["titulos"][titulo])
    zona = entrada.get("zona") or ""
    if zona:
        if zona not in adic["zona_patagonica"]:
            raise EntradaInvalida("Zona desconocida.")
        agregar("ZONA", "Adicional zona patagónica", "haberes", adic["zona_patagonica"][zona], zona)

    tramo = int(_num(entrada.get("tramo_roe", 1), "Tramo de ROE", 0, len(g["roe"]["tramos"]) - 1))
    bruto_sin_roe = sum(r["importe"] for r in renglones)
    roe = roe_mensual(bruto_sin_roe, tramo, g)
    if roe:
        agregar("ROE", "Participación en las ganancias (ROE)", "haberes", roe,
                f"ROE del banco {g['roe']['tramos'][tramo]}; tabla anual / 12, fila por el bruto sin ROE.")

    if entrada.get("guarderia"):
        agregar("GUARDE", "Guardería", "no_remunerativos", adic["guarderia"],
                "No remunerativo: la grilla no lo dice.", supuesto=True)
    modo = entrada.get("conectividad") or ""
    if modo:
        if modo not in MODOS_CONECTIVIDAD:
            raise EntradaInvalida("Modo de conectividad desconocido.")
        con = _conectividad(g)
        if modo == "diario":
            dias = int(_num(entrada.get("dias_conectividad", 1), "Días de conectividad", 1, 4))
            agregar("CONECT", "Mayores gastos de conectividad", "no_remunerativos", con["diario"] * dias,
                    f"{dias} día(s) × {_pesos(con['diario'])}. No remunerativo: la grilla no lo dice.", supuesto=True)
        else:
            agregar("CONECT", "Mayores gastos de conectividad", "no_remunerativos", con[modo],
                    f"{MODOS_CONECTIVIDAD[modo]}. No remunerativo: la grilla no lo dice.", supuesto=True)
    if entrada.get("dia_bancario"):
        agregar("DIABAN", "Día del Bancario", "no_remunerativos", dia_del_bancario(cat["coef"], g),
                "Suma fija + coeficiente × monto, con mínimo. No remunerativo según el acta de 2020.")

    remunerativo = round(sum(r["importe"] for r in renglones if r["seccion"] == "haberes"), 2)
    no_remunerativo = round(sum(r["importe"] for r in renglones if r["seccion"] == "no_remunerativos"), 2)

    tope = tope_ss(g["periodo"])
    base = remunerativo
    nota_base = ""
    if tope:
        base = min(max(remunerativo, tope["minimo"]), tope["maximo"])
        if base != remunerativo:
            nota_base = f"Sobre el tope vigente desde {tope['desde']} ({_pesos(tope['maximo'])}), no sobre el remunerativo."
    for codigo, concepto, pct in APORTES:
        agregar(codigo, concepto, "descuentos", base * pct, f"{pct * 100:g}%. {nota_base}".strip())
    cuota_pct = None
    if entrada.get("afiliado"):
        pct = cuota_pct = _num(entrada.get("cuota_pct", 2), "Cuota sindical", 0, 10)
        agregar("CUOTA", "Cuota sindical Asociación Bancaria", "descuentos", remunerativo * pct / 100,
                f"{pct:g}% del remunerativo. El convenio no fija el porcentaje.")
    ganancias = _num(entrada.get("ganancias"), "Ganancias")
    if ganancias:
        agregar("GANANC", "Impuesto a las Ganancias", "descuentos", ganancias, "Cargado a mano, no se calcula.")

    descuentos = round(sum(r["importe"] for r in renglones if r["seccion"] == "descuentos"), 2)
    return {
        "periodo": g["periodo"], "grilla": g["nombre"], "renglones": renglones,
        "totales": {"remunerativo": remunerativo, "no_remunerativo": no_remunerativo,
                    "bruto": round(remunerativo + no_remunerativo, 2), "descuentos": descuentos,
                    "neto": round(remunerativo + no_remunerativo - descuentos, 2),
                    "base_aportes": round(base, 2)},
        "tope": tope, "cuota_pct": cuota_pct,
    }


# Un renglón que el recibo real trae y el esperado no (la calculadora no lo
# tiene elegido): se muestra igual, con esperado $ 0 y qué tocar para que esté.
# Nunca se tilda solo, por lo mismo que la categoría (SDN, 2026-10-13).
FUERA_DEL_ESPERADO = {
    "BAS": ("Sueldo básico", "haberes", ""),
    "CONFOR": ("Complemento salario conformado", "haberes",
               "La categoría elegida no tiene complemento: revisá la categoría."),
    "CAJFUN": ("Adicional función cajero", "haberes", "Tildá «Cajero» en Adicionales si corresponde."),
    "CAJFAL": ("Falla de caja", "haberes", "Tildá «Cajero» en Adicionales si corresponde."),
    "CAJFME": ("Falla de caja moneda extranjera", "haberes",
               "Tildá «Falla de caja moneda extranjera» en Adicionales si corresponde."),
    "TITULO": ("Adicional título", "haberes", "Elegí el título en Adicionales si corresponde."),
    "ZONA": ("Adicional zona patagónica", "haberes", "Elegí la zona en Adicionales si corresponde."),
    "ROE": ("Participación en las ganancias (ROE)", "haberes",
            "El tramo de ROE elegido no paga: revisá el ROE del banco."),
    "GUARDE": ("Guardería", "no_remunerativos", "Tildá «Guardería» si corresponde."),
    "CONECT": ("Mayores gastos de conectividad", "no_remunerativos", "Elegí la conectividad si corresponde."),
    "DIABAN": ("Día del Bancario", "no_remunerativos", "Tildá «Día del Bancario» si corresponde."),
    "CUOTA": ("Cuota sindical Asociación Bancaria", "descuentos", "Tildá «Afiliado» si corresponde."),
    "GANANC": ("Impuesto a las Ganancias", "descuentos", "Cargá el importe en Ganancias si corresponde."),
}

# Renglones del convenio que, si no coinciden, pueden deberse a un control mal
# elegido (el ROE del banco, el título, la zona, la conectividad).
AJUSTABLES_SI_DIFIEREN = {"ROE", "TITULO", "ZONA", "CONECT"}


def ajuste_sugerido(codigo: str, importe: float, esperado: dict) -> dict | None:
    """Qué tocar en la calculadora para que un renglón del recibo esté, cuando
    el recibo lo dice sin dudas (SDN, 2026-10-13): {"campos": {control:
    valor}, "texto": "..."}. Se PROPONE con un botón "Ajustar al recibo",
    igual que la categoría; nunca se aplica solo. None si no hay un caso claro
    (un importe que no es ninguno de la grilla no se adivina)."""
    g = grilla(esperado["periodo"])
    adic = g["adicionales"]
    cerca = lambda a, b: abs(a - b) < 1
    simples = {"CAJFUN": ("cajero", "Tildar «Cajero»"), "CAJFAL": ("cajero", "Tildar «Cajero»"),
               "CAJFME": ("falla_me", "Tildar «Falla de caja moneda extranjera»"),
               "GUARDE": ("guarderia", "Tildar «Guardería»"),
               "DIABAN": ("dia_bancario", "Tildar «Día del Bancario»")}
    if codigo in simples:
        campo, texto = simples[codigo]
        return {"campos": {campo: True}, "texto": texto}
    if codigo == "TITULO":
        for nombre, valor in adic["titulos"].items():
            if cerca(importe, valor):
                return {"campos": {"titulo": nombre}, "texto": f"Elegir título {nombre}"}
    if codigo == "ZONA":
        for nombre, valor in adic["zona_patagonica"].items():
            if cerca(importe, valor):
                return {"campos": {"zona": nombre}, "texto": f"Elegir zona {nombre}"}
    if codigo == "CONECT":
        con = _conectividad(g)
        for modo in ("mas_de_4_dias", "mensual"):
            if cerca(importe, con[modo]):
                return {"campos": {"conectividad": modo}, "texto": f"Elegir conectividad {MODOS_CONECTIVIDAD[modo].lower()}"}
        for dias in range(1, 5):
            if cerca(importe, con["diario"] * dias):
                return {"campos": {"conectividad": "diario", "dias_conectividad": dias},
                        "texto": f"Elegir conectividad de {dias} día(s)"}
    if codigo == "ROE":
        base = sum(r["importe"] for r in esperado["renglones"] if r["seccion"] == "haberes" and r["codigo"] != "ROE")
        tramos = [t for t in range(len(g["roe"]["tramos"])) if cerca(roe_mensual(base, t, g), importe)]
        if len(tramos) == 1:
            return {"campos": {"tramo_roe": tramos[0]}, "texto": f"Elegir ROE del banco {g['roe']['tramos'][tramos[0]]}"}
    if codigo == "CUOTA":
        rem = esperado["totales"]["remunerativo"]
        pct = round(importe / rem * 100, 2) if rem else 0
        if 0 < pct <= 10:
            return {"campos": {"afiliado": True, "cuota_pct": pct}, "texto": f"Tildar «Afiliado» con cuota del {pct:g}%"}
    if codigo == "GANANC" and importe > 0:
        return {"campos": {"ganancias": round(importe, 2)}, "texto": f"Cargar Ganancias {_pesos(importe)}"}
    return None


TOLERANCIA_LEVE = 0.01   # hasta el 1% de lo esperado: diferencia pintada en amarillo


def gravedad(diferencia: float, esperado: float) -> str:
    """"coincide" (menos de $ 1), "leve" (hasta el 1% de lo esperado) o
    "grave" (más; también cualquier diferencia donde se esperaba $ 0). Solo
    decide el COLOR de la diferencia en pantalla (SDN, 2026-10-13): no cambia
    la tolerancia ni cuántos valores "no coinciden"."""
    if abs(diferencia) < 1:
        return "coincide"
    if esperado and abs(diferencia) <= abs(esperado) * TOLERANCIA_LEVE:
        return "leve"
    return "grave"


SECCIONES = ("haberes", "no_remunerativos", "descuentos")


def _extras(real: dict) -> list:
    salida = []
    for e in real.get("extras") or []:
        concepto = str(e.get("concepto") or "").strip()[:120]
        importe = _num(e.get("importe"), "Importe del renglón extra", -1e12)
        if concepto or importe:
            seccion = e.get("seccion") if e.get("seccion") in SECCIONES else "haberes"
            salida.append({"concepto": concepto or "(sin nombre)", "seccion": seccion, "importe": importe})
    return salida


def otros_del_recibo(esperado: dict, extras: list) -> dict:
    """La columna "Otros del recibo" (SDN, 2026-10-13): lo que el recibo trae y
    no es de convenio, A LA PAR de lo esperado y sin tocarlo. Se toma como dato
    (no se juzga) y arrastra lo que arrastraría en el recibo: un haber
    remunerativo suma a la base de los aportes (mismo % y mismo tope) y a la
    de la cuota sindical. Lo esperado de cada renglón pasa a ser convenio +
    otros, así una diferencia es de convenio y no de un concepto ajeno.

    Devuelve {"renglones": {codigo: importe}, "totales": {...}}: lo que suma
    cada renglón del convenio (los aportes y la cuota) y cada total."""
    rem = round(sum(e["importe"] for e in extras if e["seccion"] == "haberes"), 2)
    no_rem = round(sum(e["importe"] for e in extras if e["seccion"] == "no_remunerativos"), 2)
    desc = round(sum(e["importe"] for e in extras if e["seccion"] == "descuentos"), 2)
    por = {}
    if rem:
        conv = {r["codigo"]: r["importe"] for r in esperado["renglones"]}
        total_rem = esperado["totales"]["remunerativo"] + rem
        base = total_rem
        tope = esperado.get("tope")
        if tope:
            base = min(max(total_rem, tope["minimo"]), tope["maximo"])
        for codigo, _, pct in APORTES:
            por[codigo] = round(round(base * pct, 2) - conv.get(codigo, 0), 2)
        if esperado.get("cuota_pct") is not None and "CUOTA" in conv:
            por["CUOTA"] = round(round(total_rem * esperado["cuota_pct"] / 100, 2) - conv["CUOTA"], 2)
        por = {k: v for k, v in por.items() if v}
    descuentos = round(desc + sum(por.values()), 2)
    return {"renglones": por,
            "totales": {"remunerativo": rem, "no_remunerativo": no_rem, "bruto": round(rem + no_rem, 2),
                        "descuentos": descuentos, "neto": round(rem + no_rem - descuentos, 2)}}


def comparar(esperado: dict, real: dict) -> dict:
    """Renglón por renglón contra lo que dice el recibo real (leído por la IA
    o cargado a mano).

    `real`: {"renglones": {codigo: importe}, "extras": [{concepto, seccion,
    importe}], "totales": {bruto, descuentos, neto}}. Lo que no se cargó no
    se compara. Los extras van a la columna "Otros" (`otros_del_recibo`) y no
    se juzgan; cada diferencia es real - (esperado + otros), con su gravedad
    (`gravedad()`)."""
    cargados = {k: _num(v, f"Importe de {k}", -1e12) for k, v in (real.get("renglones") or {}).items()
                if v not in (None, "")}
    extras = _extras(real)
    otros = otros_del_recibo(esperado, extras)
    diferencias = []
    for r in esperado["renglones"]:
        if r["codigo"] in cargados:
            mas = otros["renglones"].get(r["codigo"], 0.0)
            espera = round(r["importe"] + mas, 2)
            dif = round(cargados[r["codigo"]] - espera, 2)
            fila = {"codigo": r["codigo"], "concepto": r["concepto"], "esperado": r["importe"],
                    "otros": mas, "real": cargados[r["codigo"]], "diferencia": dif,
                    "coincide": abs(dif) < 1, "gravedad": gravedad(dif, espera)}
            if not fila["coincide"] and r["codigo"] in AJUSTABLES_SI_DIFIEREN:
                fila["ajuste"] = ajuste_sugerido(r["codigo"], cargados[r["codigo"]], esperado)
            diferencias.append(fila)
    en_esperado = {r["codigo"] for r in esperado["renglones"]}
    for codigo, importe in cargados.items():
        if codigo in en_esperado or codigo not in FUERA_DEL_ESPERADO:
            continue
        concepto, seccion, como = FUERA_DEL_ESPERADO[codigo]
        diferencias.append({"codigo": codigo, "concepto": concepto, "seccion": seccion, "esperado": 0.0,
                            "otros": 0.0, "real": importe, "diferencia": round(importe, 2),
                            "coincide": abs(importe) < 1, "gravedad": gravedad(importe, 0),
                            "fuera": True, "como": como,
                            "ajuste": ajuste_sugerido(codigo, importe, esperado)})
    totales = []
    for clave in ("bruto", "descuentos", "neto"):
        v = (real.get("totales") or {}).get(clave)
        if v not in (None, ""):
            v = _num(v, f"Total {clave}", -1e12)
            mas = otros["totales"][clave]
            espera = round(esperado["totales"][clave] + mas, 2)
            dif = round(v - espera, 2)
            totales.append({"total": clave, "esperado": esperado["totales"][clave], "otros": mas, "real": v,
                            "diferencia": dif, "coincide": abs(dif) < 1, "gravedad": gravedad(dif, espera)})
    distintos = sum(1 for d in diferencias + totales if not d["coincide"])
    return {"renglones": diferencias, "extras": extras, "otros": otros, "totales": totales,
            "distintos": distintos}


# ---------------------------------------------------------------- recibo leído
# Del recibo que lee la IA (extractor.extraer) a los renglones de la
# calculadora. Se ubica por lo que dice la línea, no por el código: cada banco
# numera sus conceptos a su manera. Lo que no se reconoce va a "extras", a la
# vista, y nunca se suma a un renglón ajeno.
_AL_CODIGO_UNIVERSAL = {"jubilacion": "JUBILACION", "pami": "PAMI",
                        "obra_social": "OBRASOCIAL", "cuota_sindical": "CUOTA"}
_PALABRAS_HABERES = [   # el orden importa: "falla ... extranjera" antes que "falla"
    ("CONFOR", ("conformado",)),
    ("BAS", ("basico",)),
    ("ROE", ("roe", "participacion en las ganancias", "particip")),
    ("CAJFME", ("moneda extranjera", "m. extranjera", "caja m.e", "caja me", "falla m.e", "falla me")),
    ("CAJFAL", ("falla",)),
    ("CAJFUN", ("cajero", "funcion caj")),
    ("TITULO", ("titulo",)),
    ("ZONA", ("zona", "patagon")),
    ("GUARDE", ("guarder",)),
    ("CONECT", ("conectividad",)),
    ("DIABAN", ("dia del bancario", "dia bancario")),
]
_PALABRAS_DESCUENTOS = [
    ("JUBILACION", ("jubil", "sipa", "24.241", "24241")),
    ("PAMI", ("19.032", "19032", "inssjp", "pami")),
    ("OBRASOCIAL", ("obra social", "o.social", "o. social", "osba")),
    ("CUOTA", ("cuota sindical", "asociacion bancaria", "aporte sindical")),
    ("GANANC", ("ganancia",)),
]


def _llano(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def _importe(valor):
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def mapear_recibo_leido(recibo: dict) -> dict:
    """{"renglones": {codigo: importe}, "extras": [...], "totales": {...},
    "ubicados": n, "reintegros": n}: lo que se carga en "Chequear recibo".

    Los descuentos van en positivo, como los muestra la calculadora. Una
    línea entre los descuentos con el signo contrario al de los demás es un
    reintegro (validador.repartir_por_zona usa la misma regla): la
    calculadora no los contempla, así que va a extras con su signo."""
    lineas = [ln for ln in (recibo.get("lineas") or []) if _importe(ln.get("importe")) is not None]

    def seccion(ln):
        s = ln.get("seccion")
        if s in ("haberes", "no_remunerativos", "descuentos"):
            return s
        return "descuentos" if ln.get("tipo") == "aporte_trabajador" or _importe(ln["importe"]) < 0 else "haberes"

    signos = [1 if _importe(ln["importe"]) >= 0 else -1 for ln in lineas if seccion(ln) == "descuentos"]
    signo_desc = 1 if signos.count(1) >= signos.count(-1) else -1
    renglones, extras, reintegros = {}, [], 0
    for ln in lineas:
        sec = seccion(ln)
        imp = _importe(ln["importe"])
        texto = _llano(ln.get("descripcion"))
        codigo = None
        if sec == "descuentos":
            if signos and (1 if imp >= 0 else -1) != signo_desc:
                reintegros += 1
                extras.append({"concepto": f"{ln.get('descripcion') or '(sin nombre)'} (reintegro)",
                               "seccion": "descuentos", "importe": -abs(imp)})
                continue
            codigo = _AL_CODIGO_UNIVERSAL.get(ln.get("categoria_universal") or "")
            if not codigo:
                codigo = next((c for c, pals in _PALABRAS_DESCUENTOS if any(p in texto for p in pals)), None)
            imp = abs(imp)
        else:
            codigo = next((c for c, pals in _PALABRAS_HABERES if any(p in texto for p in pals)), None)
        if codigo and codigo not in renglones:
            renglones[codigo] = round(imp, 2)
        else:
            extras.append({"concepto": ln.get("descripcion") or "(sin nombre)", "seccion": sec,
                           "importe": round(imp, 2)})
    impresos = recibo.get("totales_impresos") or {}
    totales = {}
    for clave, origen in (("bruto", "remuneraciones"), ("descuentos", "descuentos"), ("neto", "neto")):
        v = _importe(impresos.get(origen))
        if v is not None:
            totales[clave] = round(abs(v), 2)
    return {"renglones": renglones, "extras": extras, "totales": totales,
            "ubicados": len(renglones), "reintegros": reintegros}


def categorias_por_basico(basico: float, periodo: str = "") -> list:
    """Las categorías de la grilla cuyo básico coincide con el leído ($ 1 de
    tolerancia). El piso hace que varias compartan básico: van todas."""
    if basico is None:
        return []
    return [{"rama": clave, "categoria": i, "nombre": c["nombre"]}
            for clave, rama in grilla(periodo)["ramas"].items()
            for i, c in enumerate(rama["categorias"]) if abs(c["basico"] - basico) < 1]

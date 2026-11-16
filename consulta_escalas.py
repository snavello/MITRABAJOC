"""Consulta de escalas del CCT 18/75: el motor PURO de «Convenio y escalas».

Plan: PLAN_CONVENIO_ESCALAS.md (D4 a D7, D10, D14 a D16, D22). No importa
`db`, no sale a la red y no mira el reloj: las grillas llegan desde afuera
como {periodo: contenido} (la misma forma que data/grillas_bancarias/*.json)
y las fechas viajan dentro de ellas.

Es una CONSULTA, no un control: la respuesta trae valores sueltos de la
grilla, cada uno con su etiqueta, y NUNCA un total, una suma, un veredicto
ni un campo que se le parezca. Nada se inventa ni se completa: si la grilla
no trae un dato, el concepto no sale.
"""
from __future__ import annotations

RAMAS = ("administrativa", "maestranza", "ordenanza")

TITULOS = (("sin", "Sin título"), ("secundario", "Secundario"),
           ("terciario", "Terciario"), ("universitario", "Universitario"))

PUBLICADO = "publicado"
REFERENCIA = "referencia"

# D4: texto fijo junto a los valores.
TEXTO_ALCANCE = ("Son valores sueltos de la grilla, no se suman: esto no es tu sueldo. "
                 "Faltan los conceptos de tu banco, los descuentos y los retroactivos.")

# D7: texto fijo de la evolución.
TEXTO_EVOLUCION = ("Es el valor de grilla de esta categoría, no lo que cobraste. "
                   "No incluye retroactivos, aguinaldo, adicionales personales ni "
                   "acuerdos de tu banco.")

NOTA_ROE_DEFECTO = "El monto real depende de tu banco"
NOTA_ROE_TRAMO = "Según el tramo de ROE que elegiste. El monto real depende de tu banco"
NOTA_CONFORMADO = ("Mínimo garantizado de la categoría: lo que la grilla asegura "
                   "como remuneración mínima")

TOPE_ANIOS = 60


class ConsultaInvalida(ValueError):
    """La selección o el período pedidos no son válidos (mensaje en castellano)."""


def _plata(valor) -> float:
    return round(float(valor), 2)


def _es_numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


# ------------------------------------------------------------- opciones
def opciones(grilla: dict) -> dict:
    """Lo que la pantalla de Selección necesita, de una grilla."""
    adic = grilla.get("adicionales") or {}
    titulos_grilla = adic.get("titulos") or {}
    ramas = []
    for clave in RAMAS:
        rama = (grilla.get("ramas") or {}).get(clave)
        if not rama:
            continue
        cats = rama.get("categorias") or []
        ramas.append({
            "clave": clave,
            "nombre": rama.get("nombre", clave.capitalize()),
            "anios": sorted({c["anios"] for c in cats if c.get("anios") is not None}),
            "jerarquias": [c["nombre"] for c in cats if c.get("anios") is None],
        })
    titulos = [{"clave": k, "rotulo": r} for k, r in TITULOS
               if k == "sin" or k in titulos_grilla]
    tramos = [{"indice": i, "rotulo": t}
              for i, t in enumerate((grilla.get("roe") or {}).get("tramos") or [])]
    return {"periodo": grilla.get("periodo"), "nombre": grilla.get("nombre"),
            "ramas": ramas, "titulos": titulos, "tramos_roe": tramos}


# ------------------------------------------------------------ selección
def _rama_de(sel: dict, grilla: dict):
    clave = sel.get("rama")
    if clave not in RAMAS or clave not in (grilla.get("ramas") or {}):
        raise ConsultaInvalida("Elegí una rama válida: administrativa, maestranza u ordenanza.")
    return clave, grilla["ramas"][clave]


def _categoria(rama: dict, anios, jerarquia):
    cats = rama.get("categorias") or []
    if jerarquia is not None:
        for c in cats:
            if c.get("anios") is None and c.get("nombre") == jerarquia:
                return c
        raise ConsultaInvalida("Ese cargo jerárquico no existe en la rama elegida.")
    # Años sin fila (ej. 17): el tramo cumplido más alto, como fila_de_escala.
    con_anios = sorted((c for c in cats if c.get("anios") is not None), key=lambda c: c["anios"])
    if not con_anios:
        raise ConsultaInvalida("La rama elegida no tiene escala por antigüedad.")
    elegida = con_anios[0]
    for c in con_anios:
        if anios >= c["anios"]:
            elegida = c
    return elegida


def validar_seleccion(sel: dict, grilla: dict) -> dict:
    """Devuelve la selección normalizada o levanta ConsultaInvalida.

    Normalizada: rama, anios (int o None), jerarquia (str o None), titulo
    ('' si no tiene), caja (bool), tramo_roe (int o None)."""
    if not isinstance(sel, dict):
        raise ConsultaInvalida("La selección no es válida.")
    rama_clave, rama = _rama_de(sel, grilla)

    anios_in, jer_in = sel.get("anios"), sel.get("jerarquia")
    anios = jer = None
    if jer_in not in (None, ""):
        if anios_in not in (None, ""):
            raise ConsultaInvalida("Elegí los años de antigüedad o un cargo jerárquico, no los dos.")
        if not isinstance(jer_in, str):
            raise ConsultaInvalida("El cargo jerárquico no es válido.")
        jer = jer_in
    else:
        if anios_in in (None, ""):
            raise ConsultaInvalida("Indicá los años de antigüedad o un cargo jerárquico.")
        if isinstance(anios_in, bool) or not isinstance(anios_in, (int, str)):
            raise ConsultaInvalida("Los años de antigüedad tienen que ser un número entero.")
        try:
            anios = int(anios_in)
        except ValueError:
            raise ConsultaInvalida("Los años de antigüedad tienen que ser un número entero.")
        if anios < 0 or anios > TOPE_ANIOS:
            raise ConsultaInvalida(f"Los años de antigüedad van de 0 a {TOPE_ANIOS}.")
    _categoria(rama, anios, jer)

    titulo = sel.get("titulo") or ""
    if titulo == "sin":
        titulo = ""
    if titulo and titulo not in dict(TITULOS):
        raise ConsultaInvalida("El título tiene que ser: sin título, secundario, terciario o universitario.")

    caja = sel.get("caja", False)
    if caja is None:
        caja = False
    if not isinstance(caja, bool):
        raise ConsultaInvalida("La función de caja es sí o no.")

    tramo = sel.get("tramo_roe")
    if tramo in (None, ""):
        tramo = None
    else:
        tramos = (grilla.get("roe") or {}).get("tramos") or []
        if isinstance(tramo, bool) or not isinstance(tramo, (int, str)):
            raise ConsultaInvalida("El tramo de ROE no es válido.")
        try:
            tramo = int(tramo)
        except ValueError:
            raise ConsultaInvalida("El tramo de ROE no es válido.")
        if tramo < 0 or tramo >= len(tramos):
            raise ConsultaInvalida("Ese tramo de ROE no existe.")
    return {"rama": rama_clave, "anios": anios, "jerarquia": jer,
            "titulo": titulo, "caja": caja, "tramo_roe": tramo}


# ------------------------------------------------------------- consulta
def _concepto(clave, rotulo, importe, etiqueta, nota, fuente) -> dict:
    return {"clave": clave, "rotulo": rotulo, "importe": _plata(importe),
            "etiqueta": etiqueta, "nota": nota, "fuente": fuente}


def _fila_roe(grilla: dict, bruto: float):
    for f in (grilla.get("roe") or {}).get("filas") or []:
        if f.get("hasta") is None or bruto <= f["hasta"]:
            return f
    return None


def _anual(fila, tramo):
    if not fila:
        return None
    anual = fila.get("anual") or []
    if tramo is None or tramo >= len(anual) or not _es_numero(anual[tramo]):
        return None
    return anual[tramo]


def _conformado_util(cat: dict):
    conf, bas = cat.get("conformado"), cat.get("basico")
    if _es_numero(conf) and _es_numero(bas) and conf > bas:
        return conf
    return None


def _pedir_grilla(grillas: dict, periodo):
    if not grillas:
        raise ConsultaInvalida("Todavía no hay una grilla publicada.")
    if periodo in (None, ""):
        periodo = max(grillas)
    if periodo not in grillas:
        raise ConsultaInvalida("No hay una grilla publicada para ese período.")
    return periodo, grillas[periodo]


def consultar(sel: dict, grillas: dict, periodo: str | None = None) -> dict:
    """Valores sueltos de la grilla para la selección, uno por concepto."""
    periodo, g = _pedir_grilla(grillas, periodo)
    s = validar_seleccion(sel, g)
    rama_clave, rama = _rama_de(s, g)
    cat = _categoria(rama, s["anios"], s["jerarquia"])
    adic = g.get("adicionales") or {}
    fuentes = list(g.get("fuentes") or [])
    cs = []

    if _es_numero(cat.get("basico")):
        cs.append(_concepto("basico", f"Sueldo básico, {cat['nombre']}", cat["basico"],
                            PUBLICADO, rama.get("nombre", rama_clave), fuentes))
    conf = _conformado_util(cat)
    if conf is not None:
        cs.append(_concepto("conformado", f"Salario conformado, {cat['nombre']}", conf,
                            PUBLICADO, NOTA_CONFORMADO, fuentes))
    titulo = s["titulo"]
    if titulo and _es_numero((adic.get("titulos") or {}).get(titulo)):
        cs.append(_concepto("titulo", f"Adicional por título {titulo}", adic["titulos"][titulo],
                            PUBLICADO, "", fuentes))
    if s["caja"]:
        if _es_numero(adic.get("funcion_cajero")):
            cs.append(_concepto("funcion_cajero", "Adicional función de cajero",
                                adic["funcion_cajero"], PUBLICADO, "", fuentes))
        if _es_numero(adic.get("falla_caja")):
            cs.append(_concepto("falla_caja", "Falla de caja", adic["falla_caja"],
                                PUBLICADO, "", fuentes))

    # ROE (D16): referencia siempre, nunca publicado para esta persona.
    tramos = (g.get("roe") or {}).get("tramos") or []
    if s["tramo_roe"] is None:
        inicial = next((c for c in rama.get("categorias") or [] if c.get("anios") == 0), None)
        base = None
        if inicial:
            base = inicial.get("conformado") if _es_numero(inicial.get("conformado")) else inicial.get("basico")
        anual = _anual(_fila_roe(g, base), 1) if _es_numero(base) and len(tramos) > 1 else None
        if anual is not None:
            cs.append(_concepto("roe", "Participación en las ganancias (ROE)", anual / 12,
                                REFERENCIA, NOTA_ROE_DEFECTO, fuentes))
    else:
        base = conf if conf is not None else cat.get("basico")
        anual = _anual(_fila_roe(g, base), s["tramo_roe"]) if _es_numero(base) else None
        if anual is not None:
            cs.append(_concepto("roe", f"Participación en las ganancias (ROE), banco con ROE de {tramos[s['tramo_roe']]}",
                                anual / 12, REFERENCIA, NOTA_ROE_TRAMO, fuentes))

    return {"periodo": g.get("periodo", periodo), "nombre": g.get("nombre"),
            "firmada": g.get("firmada"), "fuentes": fuentes,
            "seleccion": s, "categoria": cat["nombre"],
            "conceptos": cs, "alcance": TEXTO_ALCANCE}


# ------------------------------------------------------------ evolución
def _mes_anterior(periodo: str) -> str:
    a, m = int(periodo[:4]), int(periodo[5:7])
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


def _misma_categoria(rama: dict, cat_ref: dict):
    for c in rama.get("categorias") or []:
        if c.get("nombre") == cat_ref["nombre"] and c.get("anios") == cat_ref.get("anios"):
            return c
    return None


def evolucion(sel: dict, grillas: dict) -> dict:
    """Mes a mes un valor de grilla de la categoría (D7, D22)."""
    _, vigente = _pedir_grilla(grillas, None)
    s = validar_seleccion(sel, vigente)
    cat_ref = _categoria(vigente["ramas"][s["rama"]], s["anios"], s["jerarquia"])
    filas, anterior = [], None
    for per in sorted(grillas):
        g = grillas[per]
        rama = (g.get("ramas") or {}).get(s["rama"])
        cat = _misma_categoria(rama, cat_ref) if rama else None
        if not cat:
            continue
        conf = _conformado_util(cat)
        valor = conf if conf is not None else cat.get("basico")
        if not _es_numero(valor):
            continue
        pct = None
        if anterior and anterior[0] == _mes_anterior(per) and anterior[1]:
            pct = round((valor / anterior[1] - 1) * 100, 2)
        filas.append({"periodo": g.get("periodo", per), "nombre": g.get("nombre"),
                      "concepto": "conformado" if conf is not None else "basico",
                      "importe": _plata(valor), "variacion_pct": pct,
                      "etiqueta": PUBLICADO, "fuente": list(g.get("fuentes") or [])})
        anterior = (per, valor)
    return {"seleccion": s, "categoria": cat_ref["nombre"], "meses": filas,
            "alcance": TEXTO_EVOLUCION}

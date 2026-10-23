"""Los dos modelos de diseño de la app y sus paletas (PLAN_TEMAS.md).

Puro: no importa `db`. Dice qué modelos existen, cuál vale por defecto y cómo
se resuelve el que ve una persona -- su elección, si hizo una; si no, la de
su sindicato; y si el valor guardado no es uno conocido, el por defecto (un
valor viejo o mal escrito en la base nunca deja una página sin estilo).
"""

TEMAS = {
    # El orden es el de las pantallas de Apariencia: el por defecto primero.
    "laguna": {"num": 162, "nombre": "Laguna",
               "descripcion": "Portada en verde agua, turquesa y azul; el resto liviano y blanco."},
    "noticiero": {"num": 147, "nombre": "Noticiero",
                  "descripcion": "Papel claro, tinta índigo y un solo color vivo, como un diario."},
}
TEMA_DEFECTO = "laguna"

PALETAS = {
    "colm3na": "Colores de Colm3na",
    "sindicato": "Colores del sindicato",
}
PALETA_DEFECTO = "colm3na"


def tema_valido(valor) -> str | None:
    """El modelo normalizado, o None si no es uno del catálogo."""
    v = (valor or "").strip().lower()
    return v if v in TEMAS else None


def paleta_valida(valor) -> str | None:
    v = (valor or "").strip().lower()
    return v if v in PALETAS else None


def resolver_tema(preferencia, defecto_sindicato=None) -> str:
    """El modelo que ve una persona: el suyo, el de su sindicato o el general."""
    return tema_valido(preferencia) or tema_valido(defecto_sindicato) or TEMA_DEFECTO


def resolver_paleta(paleta_sindicato) -> str:
    return paleta_valida(paleta_sindicato) or PALETA_DEFECTO


# ---------------------------------------------------------------------------
# Prueba de lectura de la paleta del sindicato (PLAN_TEMAS.md, D4)
# ---------------------------------------------------------------------------
# Con la paleta "sindicato" los modelos pintan texto sobre los cuatro colores
# de marca. Antes de elegirla, el Super Admin ve si esas combinaciones se leen.
# Contraste WCAG 2.x: (L1 + 0.05) / (L2 + 0.05) con la luminancia relativa;
# 4,5:1 es el mínimo para texto común.

CONTRASTE_MINIMO = 4.5          # texto común
CONTRASTE_MINIMO_GRANDE = 3.0   # texto grande (saludo y títulos de la portada)
_BLANCO = "#ffffff"


def _rgb(color):
    """(r, g, b) de 0 a 255 desde "#rrggbb" o "#rgb"; None si no se entiende."""
    c = (color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    if len(c) != 6:
        return None
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def luminancia(color) -> float:
    """Luminancia relativa WCAG (0 = negro, 1 = blanco)."""
    def canal(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(color)
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(color_a, color_b) -> float:
    """Contraste WCAG entre dos colores, de 1 a 21."""
    la, lb = luminancia(color_a), luminancia(color_b)
    claro, oscuro = max(la, lb), min(la, lb)
    return round((claro + 0.05) / (oscuro + 0.05), 2)


def prueba_de_lectura(base, primario, acento, apoyo) -> list[dict]:
    """Las combinaciones de texto que usan los modelos con la paleta del
    sindicato, y un aviso en castellano por cada una que no llega a su
    mínimo (4,5:1 el texto común, 3:1 el grande).
    Lista vacía = los colores pasan la prueba. Pura.

    Cada aviso: {"clave", "combinacion", "contraste", "minimo", "aviso"}.
    `apoyo` no lleva texto encima en ningún modelo (es fondo suave y chips);
    se recibe para que la firma sea la de los cuatro colores de marca y se
    controla solo que sea un color legible."""
    nombres = {"base": base, "primario": primario, "acento": acento, "apoyo": apoyo}
    ilegibles = [n for n, c in nombres.items() if _rgb(c) is None]
    if ilegibles:
        return [{"clave": "color_" + n, "combinacion": f"Color {n}", "contraste": None,
                 "minimo": CONTRASTE_MINIMO,
                 "aviso": f"No pudimos leer el color {n} ({nombres[n] or 'vacío'}): "
                          "revisalo en los datos del sindicato."} for n in ilegibles]

    avisos = []

    def chequear(clave, combinacion, valor, aviso, minimo=CONTRASTE_MINIMO):
        if valor < minimo:
            avisos.append({"clave": clave, "combinacion": combinacion, "contraste": valor,
                           "minimo": minimo, "aviso": aviso})

    chequear("blanco_sobre_base", "Texto blanco sobre el color base",
             contraste(_BLANCO, base),
             "El color base es muy claro para llevar texto blanco encima: los "
             "encabezados y la portada se van a leer mal.")
    chequear("blanco_sobre_primario", "Texto blanco sobre el color primario",
             contraste(_BLANCO, primario),
             "El primario es muy claro para llevar texto blanco encima: lo vamos "
             "a oscurecer donde haga falta.")
    # El acento como TEXTO aparece de los dos lados: sobre las hojas claras
    # (enlaces, cifras destacadas) y sobre la base oscura (el saludo y los
    # títulos de la portada, texto grande: alcanza 3:1). Un acento claro
    # falla en la primera; uno oscuro, en la segunda.
    chequear("acento_sobre_claro", "El acento como texto sobre fondo claro",
             contraste(acento, _BLANCO),
             "El acento es muy claro para usarlo como texto sobre fondo claro: lo "
             "vamos a oscurecer donde haga falta.")
    chequear("acento_sobre_base", "El acento como texto sobre el color base",
             contraste(acento, base),
             "El acento es muy oscuro para usarlo como texto sobre el color base: "
             "lo vamos a aclarar donde haga falta.", CONTRASTE_MINIMO_GRANDE)
    sobre_acento = max(contraste(_BLANCO, acento), contraste(base, acento))
    chequear("texto_sobre_acento", "Texto sobre un botón del color acento",
             sobre_acento,
             "Ni el blanco ni el color base se leen bien sobre el acento: los "
             "botones van a llevar un acento corregido.")
    return avisos

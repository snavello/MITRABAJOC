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

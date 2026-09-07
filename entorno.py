"""En qué entorno corre la app (local / pruebas / demo / prod).

Se lee de la variable de entorno ENTORNO, que cada servicio de Render fija
en su configuración (ver DESPLIEGUE_RENDER.md). Sirve para dos cosas:

- Mostrar un distintivo visible ("PRUEBAS · v0.28.01") en los entornos
  que NO son de cara al cliente, para que nadie confunda una pantalla de
  pruebas con la demo en una presentación. En demo y prod no se muestra
  nada.
- Dejar el entorno en el "Acerca de" de cada app, junto a la versión.

Sin la variable, el distintivo NO se muestra: así el deploy que agrega
esta feature no cambia lo que ven los sindicatos en el servicio actual
aunque a alguien se le olvide fijar ENTORNO=demo. Que el silencio sea el
default seguro es a propósito.
"""
import os

ENTORNOS_VALIDOS = ("local", "pruebas", "demo", "prod")

# Entornos donde el distintivo se muestra. demo y prod NUNCA.
CON_DISTINTIVO = ("local", "pruebas")


def normalizar(valor):
    """Devuelve el entorno en minúsculas, o "" si no está definido o no es
    uno de los conocidos (un valor con error de tipeo no puede terminar
    mostrando un distintivo raro en la demo)."""
    valor = (valor or "").strip().lower()
    return valor if valor in ENTORNOS_VALIDOS else ""


def muestra_distintivo(valor):
    return normalizar(valor) in CON_DISTINTIVO


ENTORNO = normalizar(os.getenv("ENTORNO"))
MUESTRA_DISTINTIVO = muestra_distintivo(ENTORNO)

# URL pública de cada entorno desplegado (DESPLIEGUE_RENDER.md). La landing
# /entornos arma con esto sus 8 accesos, y le pide a cada uno /api/version
# para mostrar qué corre ahí. El orden es el de la pantalla.
URLS = {
    "pruebas": "https://mitrabajo-pruebas.onrender.com",
    "demo": "https://mitrabajo.onrender.com",
}

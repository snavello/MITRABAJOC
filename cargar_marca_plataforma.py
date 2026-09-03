"""Siembra la marca de la plataforma (Colm3na) en la base del entorno.

Por qué existe: el logo y los colores de "Mi Trabajo" viven SOLO como bytes
en la base (`ConfiguracionPlataforma`, patrón "Opción B" de logos, ver
CLAUDE.md). Se cargan a mano desde /plataforma, y ningún script de datos los
reponía. Consecuencia real, encontrada al levantar el entorno de Pruebas
(2026-09-03): una base nueva nace sin marca y todas las pantallas caen al
fallback `static/logo_mitrabajo.svg`, que es el placeholder original del
proyecto (un maletín gris), no Colm3na. Le pasaba a Pruebas y le iba a pasar
igual a Producción.

El arte oficial vive ahora en `static/marca/` (versionado en el repo), y este
script lo mete en la base. Así cualquier entorno nuevo se puede dejar igual
que la demo con un comando, sin depender de que alguien recuerde subir el
archivo a mano.

Uso:
    python cargar_marca_plataforma.py            # no pisa una marca ya cargada
    python cargar_marca_plataforma.py --forzar   # la reemplaza igual
"""
import sys
from pathlib import Path

import db

# Colores de la plataforma, tal como están en la demo (mitrabajo.onrender.com).
# No son los defaults de ConfiguracionPlataforma: si alguien los cambia desde
# /plataforma, actualizar acá también para que un entorno nuevo nazca igual.
COLOR_PRIMARIO = "#0a1421"
COLOR_SECUNDARIO = "#a0030b"
COLOR_ACENTO = "#7776a7"
PORTADA_CLARA = False

DIR_MARCA = Path("static/marca")
LOGO_CLARO = DIR_MARCA / "logo_plataforma_claro.png"
LOGO_OSCURO = DIR_MARCA / "logo_plataforma_oscuro.png"

MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".svg": "image/svg+xml", ".webp": "image/webp"}


def _leer(path: Path):
    """Devuelve (bytes, mime, nombre) del archivo, o (None, "", "") si falta."""
    if not path.exists():
        print(f"  ! falta {path} -- ese logo no se carga")
        return None, "", ""
    return path.read_bytes(), MIMES.get(path.suffix.lower(), "application/octet-stream"), path.name


def main():
    forzar = "--forzar" in sys.argv

    actual = db.marca_plataforma()
    if actual.get("logo") and not forzar:
        print("La plataforma YA tiene logo cargado. No se toca nada.")
        print("Si querés reemplazarlo igual: python cargar_marca_plataforma.py --forzar")
        return

    claro, mime_claro, nombre_claro = _leer(LOGO_CLARO)
    oscuro, mime_oscuro, nombre_oscuro = _leer(LOGO_OSCURO)
    if not claro and not oscuro:
        sys.exit(f"No hay ningún archivo de marca en {DIR_MARCA}/. Nada que cargar.")

    db.set_marca_plataforma(
        color_primario=COLOR_PRIMARIO,
        color_secundario=COLOR_SECUNDARIO,
        color_acento=COLOR_ACENTO,
        portada_clara=PORTADA_CLARA,
        logo_datos=claro, logo_mime=mime_claro, logo_flag=nombre_claro,
        logo_datos_oscuro=oscuro, logo_mime_oscuro=mime_oscuro, logo_oscuro_flag=nombre_oscuro,
    )

    print("Marca de plataforma cargada:")
    if claro:
        print(f"  logo fondo claro:  {nombre_claro} ({len(claro):,} bytes)")
    if oscuro:
        print(f"  logo fondo oscuro: {nombre_oscuro} ({len(oscuro):,} bytes)")
    print(f"  colores: primario {COLOR_PRIMARIO} / secundario {COLOR_SECUNDARIO} / "
          f"acento {COLOR_ACENTO}")
    print("\nVerificar en /logo-plataforma y /logo-plataforma-oscuro (tienen que dar 200).")


if __name__ == "__main__":
    main()

"""Copia TODOS los datos de la demo al entorno de Pruebas (pg_dump + pg_restore).

Es la EXCEPCIÓN, no la rutina. Lo normal es regenerar Pruebas con los
scripts de lote (`cargar_demo.py`, `cargar_lote_sindicato.py`,
`cargar_bancaria.py`), que son deterministas y no dependen de que otra base
esté sana. Esto es para la carga inicial, cuando la demo tiene datos y
usuarios que los scripts todavía no saben reproducir.

Qué hace, en orden:

  1. Chequea las guardas de dirección (ver abajo). Sin eso no hace nada.
  2. `pg_dump -Fc` de la base de DEMO a backups/ (con fecha).
  3. `pg_restore --clean --if-exists` de ese archivo sobre la base de PRUEBAS.
  4. Recuerda correr `alembic upgrade head` contra Pruebas.

LA GUARDA QUE IMPORTA: este script SIEMPRE lee de la demo y SIEMPRE escribe
en Pruebas, nunca al revés. Escribir un dump viejo sobre la demo sería el
peor accidente posible del proyecto, así que:

  - el destino tiene que decir "pruebas" en su URL, y el origen no;
  - las dos URLs tienen que ser distintas;
  - hay que pasar --si-borrar-pruebas a propósito.

Ninguna de las tres se puede saltear con un flag.

Antes de correrlo, en el .env local (nunca en el repo):
    DEMO_DATABASE_URL=...      External Database URL de la base de DEMO
    PRUEBAS_DATABASE_URL=...   External Database URL de la base de PRUEBAS

Uso:
    python clonar_demo_a_pruebas.py                      # ensayo, no toca nada
    python clonar_demo_a_pruebas.py --si-borrar-pruebas  # lo hace de verdad

OJO con los datos: hoy la demo tiene datos sintéticos. El día que tenga
trabajadores reales, copiarlos a un entorno con otros secretos y más gente
con acceso deja de ser inocuo -- los recibos son datos personales. Si eso
pasa, este script deja de ser la herramienta correcta.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import pg_cliente

load_dotenv()

RAIZ = Path(__file__).resolve().parent
BACKUPS = RAIZ / "backups"


def abortar(msg):
    print(f"\nABORTADO: {msg}")
    sys.exit(1)


def _nombre_base(url):
    """Último tramo de la URL, sin query: sirve para reconocer la base."""
    return url.rstrip("/").split("/")[-1].split("?")[0]


def revisar_direccion(origen, destino):
    """Las tres guardas. Ninguna es opcional."""
    if not origen:
        abortar("falta DEMO_DATABASE_URL en el .env (External Database URL de la base de demo).")
    if not destino:
        abortar("falta PRUEBAS_DATABASE_URL en el .env (External Database URL de la base de pruebas).")
    if origen.strip() == destino.strip():
        abortar("DEMO_DATABASE_URL y PRUEBAS_DATABASE_URL son la misma. No se copia nada.")

    base_destino = _nombre_base(destino)
    if "prueba" not in destino.lower():
        abortar(f"la base de DESTINO ('{base_destino}') no dice 'pruebas' en su URL.\n"
                "          Este script solo escribe en Pruebas. Si el destino es correcto pero se\n"
                "          llama de otra forma, renombrala o copiá a mano -- la guarda no se saltea.")
    if "prueba" in origen.lower():
        abortar("la base de ORIGEN dice 'pruebas'. El origen tiene que ser la DEMO.\n"
                "          ¿Están las dos variables invertidas en el .env?")
    return base_destino


def herramienta(nombre):
    """pg_dump/pg_restore del PATH, o los del Postgres de Docker de desarrollo."""
    if shutil.which(nombre):
        return [nombre], False
    if shutil.which("docker"):
        return ["docker", "compose", "exec", "-T", "postgres-dev", nombre], True
    abortar(f"no hay {nombre} ni docker en el PATH. Instalá el cliente de Postgres o "
            "levantá `docker compose up -d`.")


def version_de_servidor(origen, destino):
    """Versión de Postgres de cada base, y de paso confirma que las dos
    responden ANTES de empezar. La lógica vive en pg_cliente.py, compartida
    con promover_demo.py."""
    try:
        return {"demo": pg_cliente.version_de_servidor(origen, "la base de demo", cwd=RAIZ),
                "pruebas": pg_cliente.version_de_servidor(destino, "la base de pruebas", cwd=RAIZ)}
    except pg_cliente.ErrorPg as e:
        abortar(str(e))


def cliente_para(nombre, version_servidor):
    try:
        return pg_cliente.cliente_para(nombre, version_servidor)
    except pg_cliente.ErrorPg as e:
        abortar(str(e))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--si-borrar-pruebas", action="store_true",
                    help="confirma que la base de Pruebas se reemplaza por la de demo")
    args = ap.parse_args()

    origen = os.getenv("DEMO_DATABASE_URL", "").strip()
    destino = os.getenv("PRUEBAS_DATABASE_URL", "").strip()
    base_destino = revisar_direccion(origen, destino)

    print("Clonar DEMO -> PRUEBAS")
    print(f"  origen : la base de demo (solo lectura)")
    print(f"  destino: {base_destino}  <- SE REEMPLAZA POR COMPLETO")

    # Conectividad y versiones, ANTES de tocar nada: el ensayo sirve
    # justamente para que una URL mal copiada o un cliente viejo fallen acá y
    # no a mitad del dump.
    versiones = version_de_servidor(origen, destino)
    version = max(versiones.values())
    print(f"- Postgres: demo {versiones['demo']}, pruebas {versiones['pruebas']}")
    cmd_dump, modo = cliente_para("pg_dump", version)
    print(f"- Cliente pg_dump/pg_restore {version}: {modo}")

    if not args.si_borrar_pruebas:
        print("\nEnsayo: no se tocó nada.")
        print("Las guardas pasaron y las dos bases responden. Para hacerlo de verdad:")
        print("    python clonar_demo_a_pruebas.py --si-borrar-pruebas")
        return

    BACKUPS.mkdir(exist_ok=True)
    dump = BACKUPS / f"demo-{datetime.now():%Y-%m-%d-%H%M}.dump"

    print(f"\n1. Copiando la demo -> {dump.name}")
    with open(dump, "wb") as salida:
        r = subprocess.run([*cmd_dump, origen, "-Fc", "--no-owner", "--no-privileges"],
                           cwd=RAIZ, stdout=salida)
    if r.returncode != 0 or not dump.exists() or dump.stat().st_size == 0:
        abortar("el pg_dump de la demo falló. No se tocó Pruebas.")
    print(f"   {dump.stat().st_size // 1024} KB")

    cmd_restore, _ = cliente_para("pg_restore", version)
    print(f"\n2. Restaurando sobre {base_destino}")
    opciones = ["--clean", "--if-exists", "--no-owner", "--no-privileges", "-d", destino]
    with open(dump, "rb") as entrada:
        r = subprocess.run([*cmd_restore, *opciones], cwd=RAIZ, stdin=entrada)
    # pg_restore devuelve 1 por avisos benignos (objetos que no existían para
    # el --clean); lo que importa es que el paso 3 confirme el esquema.
    if r.returncode not in (0, 1):
        abortar(f"pg_restore falló con código {r.returncode}. Revisá la salida de arriba.")
    if r.returncode == 1:
        print("   (pg_restore avisó de objetos inexistentes al limpiar: normal en una base nueva)")

    print("\n3. Falta un paso, a mano:")
    print("   En la Shell de mitrabajo-pruebas en Render:")
    print("       python -m alembic upgrade head")
    print("   Deja el esquema al día con `main` por si la demo venía de una versión anterior.")
    print("   (Hoy las dos ramas tienen el mismo esquema, así que no debería hacer nada.)")
    print(f"\nListo. El dump quedó en {dump} por si hace falta volver atrás.")
    print("Verificá entrando a Pruebas con un usuario de la demo.")


if __name__ == "__main__":
    main()

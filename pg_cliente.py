"""Elegir un pg_dump/pg_restore que pueda hablar con el servidor de Render.

Por qué existe: `pg_dump` NO puede volcar un servidor más nuevo que él —
aborta con "server version mismatch" a mitad de la operación. Render
actualiza la versión de Postgres por su cuenta (hoy 18) y el contenedor de
desarrollo del proyecto es pg16, así que exigir el cliente justo instalado en
cada PC no era sostenible: se usa la imagen oficial `postgres:<version>` de
Docker, que siempre coincide.

Lo usan `clonar_demo_a_pruebas.py` y `promover_demo.py` (que hace el backup
de la demo antes de mergear). Vive acá para que no se arreglen por separado y
uno quede viejo: el bug apareció primero en el clonador y el de promoción
tenía exactamente el mismo, sin que nadie lo hubiera notado todavía.

Las funciones lanzan ErrorPg con un mensaje mostrable; cada script lo traduce
a su propio "abortar".
"""
import re
import shutil
import subprocess


class ErrorPg(Exception):
    """Algo que hay que contarle a la persona, no un traceback."""


def _mayor(texto):
    """Primer número de una cadena de versión ('16.15 (Debian...)' -> 16)."""
    m = re.search(r"(\d+)", texto or "")
    return int(m.group(1)) if m else 0


def _psql():
    if shutil.which("psql"):
        return ["psql"]
    if shutil.which("docker"):
        return ["docker", "compose", "exec", "-T", "postgres-dev", "psql"]
    raise ErrorPg("no hay psql ni docker en el PATH para consultar la base.")


def version_de_servidor(url, etiqueta="la base", cwd=None):
    """Versión mayor de Postgres del servidor. De paso confirma que responde:
    una URL mal copiada tiene que fallar acá y no a mitad del dump. psql sí
    puede hablar con un servidor más nuevo que él, así que para esta consulta
    alcanza con el cliente que haya."""
    r = subprocess.run([*_psql(), url, "-tAc", "SHOW server_version"],
                       cwd=cwd, text=True, capture_output=True)
    if r.returncode != 0:
        ultima = (r.stderr or "").strip().splitlines()
        raise ErrorPg(
            f"no me puedo conectar a {etiqueta}.\n"
            f"          Revisá que sea la External Database URL (no la Internal, que solo\n"
            f"          funciona dentro de Render), y que la base esté activa en Render.\n"
            f"          Dijo: {ultima[-1] if ultima else '?'}")
    return _mayor(r.stdout)


def cliente_para(nombre, version_servidor):
    """Comando de `nombre` (pg_dump / pg_restore) capaz de hablar con un
    servidor de esa versión. Devuelve (comando, de_donde_salio)."""
    local = shutil.which(nombre)
    if local:
        salida = subprocess.run([local, "--version"], text=True, capture_output=True).stdout
        if _mayor(salida.split("PostgreSQL")[-1]) >= version_servidor:
            return [local], "instalado"
    if shutil.which("docker"):
        return (["docker", "run", "--rm", "-i", f"postgres:{version_servidor}", nombre],
                f"imagen docker postgres:{version_servidor}")
    raise ErrorPg(
        f"hace falta un {nombre} de Postgres {version_servidor} (la versión del servidor) "
        f"y no hay\n          ni cliente local suficiente ni docker para traerlo.")

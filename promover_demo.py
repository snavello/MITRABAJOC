"""Promueve lo que hay en `main` a la DEMO (rama `demo`, que Render sigue).

Es EL comando de promoción: un solo lugar donde equivocarse. Qué hace, en
orden:

  1. Exige árbol de trabajo limpio y trae `origin/main` y `origin/demo`.
  2. Backup de la base de demo (pg_dump) si DEMO_DATABASE_URL está en el
     .env local -- la External Database URL de Render. Sin esa variable,
     avisa y sigue solo con --sin-backup (para que nadie promueva "sin
     querer" sin copia).
  3. Mergea `origin/main` en `demo`, crea el tag demo-AAAA-MM-DD-vX.Y.Z
     (la versión sale de version.py de lo que se promueve) y pushea rama
     y tag. Render redeploya la demo solo.

Con --solo-pr NO mergea ni pushea: imprime el link para abrir el Pull
Request main -> demo en GitHub (el flujo de la semana 3 del plan, cuando
las reglas de rama exijan aprobación de Sd). El backup se hace igual.

Uso (desde la raíz del repo, en la PC con git configurado):
    python promover_demo.py               # merge + tag + push
    python promover_demo.py --solo-pr     # solo backup + link del PR
    python promover_demo.py --sin-backup  # sin DEMO_DATABASE_URL a mano

El cliente de pg_dump lo elige `pg_cliente.py` segun la version del
servidor de Render (usa el instalado si alcanza, si no la imagen oficial
`postgres:<version>` de Docker). Los dumps quedan en backups/ (gitignored);
se conservan los 5 mas nuevos y el resto se borra solo, avisando cual.
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import pg_cliente

load_dotenv()

RAIZ = Path(__file__).resolve().parent
BACKUPS = RAIZ / "backups"


def git(*args, capturar=True):
    r = subprocess.run(["git", *args], cwd=RAIZ, text=True,
                       capture_output=capturar)
    if r.returncode != 0:
        salida = (r.stderr or r.stdout or "").strip() if capturar else ""
        abortar(f"git {' '.join(args)} falló" + (f":\n{salida}" if salida else ""))
    return (r.stdout or "").strip()


def abortar(msg):
    print(f"\nABORTADO: {msg}")
    sys.exit(1)


def exigir_arbol_limpio():
    if git("status", "--porcelain"):
        abortar("hay cambios sin commitear. Commiteá o guardalos con `git stash` antes de promover.")


def version_en(ref):
    """VERSION_TRABAJADOR tal cual está en version.py del commit `ref`."""
    contenido = git("show", f"{ref}:version.py")
    m = re.search(r'VERSION_TRABAJADOR\s*=\s*"([^"]+)"', contenido)
    return m.group(1) if m else "0"


def backup_demo(sin_backup):
    url = os.getenv("DEMO_DATABASE_URL", "").strip()
    if not url:
        if sin_backup:
            print("- Sin DEMO_DATABASE_URL: se promueve SIN backup (--sin-backup).")
            return None
        abortar("DEMO_DATABASE_URL no está en el .env (External Database URL de la base de "
                "demo en Render). Cargala, o pasá --sin-backup si de verdad no querés copia.")
    # El pg_dump tiene que ser de la MISMA versión del servidor o más nuevo, o
    # aborta con "server version mismatch". Render actualiza Postgres por su
    # cuenta (hoy 18) y el contenedor de desarrollo es pg16: pg_cliente.py
    # resuelve cuál usar. Sin esto el backup fallaba y la promoción se abortaba
    # entera -- el mismo bug que apareció primero en clonar_demo_a_pruebas.py.
    try:
        version = pg_cliente.version_de_servidor(url, "la base de demo", cwd=RAIZ)
        cmd_dump, de_donde = pg_cliente.cliente_para("pg_dump", version)
    except pg_cliente.ErrorPg as e:
        abortar(str(e))
    BACKUPS.mkdir(exist_ok=True)
    destino = BACKUPS / f"demo-{datetime.now():%Y-%m-%d-%H%M}.dump"
    print(f"- Backup de la base de demo (Postgres {version}, {de_donde}) -> {destino.name}")
    with open(destino, "wb") as salida:
        r = subprocess.run([*cmd_dump, url, "-Fc", "--no-owner", "--no-privileges"],
                           cwd=RAIZ, stdout=salida)
    if r.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
        abortar("el backup falló; no se promueve sin copia.")
    print(f"  {destino.stat().st_size // 1024} KB")
    return destino


DUMPS_A_CONSERVAR = 5


def podar_backups(recien_creado):
    """Deja solo los DUMPS_A_CONSERVAR dumps más nuevos y borra los demás.

    Cada promoción crea un dump de ~37 MB y nadie se acuerda de limpiarlos.
    Dos recaudos, porque borrar copias de la demo en silencio sería peor que
    el desorden: el dump recién creado NUNCA se toca, y lo que se borra se
    imprime en pantalla.
    """
    dumps = sorted(BACKUPS.glob("demo-*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    sobrantes = [d for d in dumps[DUMPS_A_CONSERVAR:] if d != recien_creado]
    if not sobrantes:
        return
    print(f"- Podando backups viejos (se conservan los {DUMPS_A_CONSERVAR} más nuevos):")
    for d in sobrantes:
        mb = d.stat().st_size // (1024 * 1024)
        try:
            d.unlink()
            print(f"    borrado {d.name} ({mb} MB)")
        except OSError as e:
            print(f"    NO se pudo borrar {d.name}: {e}")


def url_del_pr():
    remoto = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remoto)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}/compare/demo...main?expand=1"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--solo-pr", action="store_true",
                    help="no mergea ni pushea: imprime el link del PR main -> demo")
    ap.add_argument("--sin-backup", action="store_true",
                    help="promueve aunque no haya DEMO_DATABASE_URL")
    args = ap.parse_args()

    print("Promoción a DEMO")
    exigir_arbol_limpio()
    rama_original = git("rev-parse", "--abbrev-ref", "HEAD")
    print("- Trayendo origin/main y origin/demo")
    git("fetch", "origin", "main", "demo")

    if git("rev-parse", "origin/main") == git("rev-parse", "origin/demo"):
        print("- demo ya está al día con main. Nada que promover.")
        return

    cambios = git("log", "--oneline", "origin/demo..origin/main")
    print(f"- Commits que van a la demo ({len(cambios.splitlines())}):")
    for linea in cambios.splitlines():
        print(f"    {linea}")

    dump = backup_demo(args.sin_backup)
    if dump:
        podar_backups(dump)

    version = version_en("origin/main")
    tag = f"demo-{datetime.now():%Y-%m-%d}-v{version}"

    if args.solo_pr:
        link = url_del_pr()
        print(f"\nAbrí el PR main -> demo (título sugerido: 'Promover a demo {tag}'):")
        print(f"  {link or 'https://github.com/<org>/<repo>/compare/demo...main'}")
        print("Cuando se apruebe y mergee, Render redeploya la demo solo. "
              f"Después, el tag: git tag {tag} origin/demo && git push origin {tag}")
        return

    print(f"- Mergeando origin/main en demo y etiquetando {tag}")
    git("checkout", "-B", "demo", "origin/demo")
    git("merge", "--no-edit", "origin/main")
    if git("tag", "-l", tag):
        abortar(f"el tag {tag} ya existe (¿dos promociones el mismo día con la misma versión? "
                "Subí la versión en version.py antes).")
    git("tag", "-a", tag, "-m", f"Promoción a demo {tag}")
    git("push", "origin", "demo", tag)
    git("checkout", rama_original)
    print(f"\nListo: demo = main, tag {tag} pusheado. Render está redeployando la demo.")
    print("Verificá en unos minutos el 'Acerca de' de la demo: tiene que mostrar la versión "
          f"{version}.")


if __name__ == "__main__":
    main()

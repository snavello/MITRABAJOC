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

El pg_dump se busca primero en el PATH y, si no está, dentro del Postgres
de Docker de desarrollo (`docker compose exec postgres-dev pg_dump`), que
lo trae sin instalar nada. Los dumps quedan en backups/ (gitignored).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

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
    BACKUPS.mkdir(exist_ok=True)
    destino = BACKUPS / f"demo-{datetime.now():%Y-%m-%d-%H%M}.dump"
    if shutil.which("pg_dump"):
        cmd = ["pg_dump", url, "-Fc", "-f", str(destino)]
        print(f"- Backup de la base de demo con pg_dump local -> {destino.name}")
        r = subprocess.run(cmd, cwd=RAIZ)
    elif shutil.which("docker"):
        print(f"- Backup de la base de demo con el pg_dump del Docker de desarrollo -> {destino.name}")
        r = subprocess.run(["docker", "compose", "exec", "-T", "postgres-dev",
                            "pg_dump", url, "-Fc"], cwd=RAIZ, stdout=open(destino, "wb"))
    else:
        abortar("no hay pg_dump ni docker en el PATH para hacer el backup. "
                "Instalá el cliente de Postgres, levantá `docker compose up -d`, o pasá --sin-backup.")
    if r.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
        abortar("el backup falló; no se promueve sin copia.")
    print(f"  {destino.stat().st_size // 1024} KB")
    return destino


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

    backup_demo(args.sin_backup)

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

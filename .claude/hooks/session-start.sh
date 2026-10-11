#!/bin/bash
# Prepara una sesión de Claude Code en la nube para correr la suite, igual
# que el CI: Postgres 16 con pgvector, un venv con Python 3.12 y las
# variables que exige la app (valores de descarte, los mismos de ci.yml).
#
# Existe porque cada sesión nueva arrancaba sin Postgres levantado, sin la
# extensión vector y con dependencias que no instalan con el pip del
# sistema: unos 10 minutos de preparación a mano cada vez (2026-10-11).
#
# Es idempotente: lo que ya está no se vuelve a hacer. Solo corre en la nube.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"
RAIZ="$(pwd)"

# ---------- Postgres 16 + pgvector ----------
if [ ! -f /usr/share/postgresql/16/extension/vector.control ]; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql-16-pgvector >/dev/null
fi
if ! pg_isready -q -h localhost -p 5432; then
  pg_ctlcluster 16 main start
fi
for _ in $(seq 1 30); do
  pg_isready -q -h localhost -p 5432 && break
  sleep 1
done
su postgres -c "psql -qc \"ALTER USER postgres PASSWORD 'postgres'\""
if [ -z "$(su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='mitrabajo'\"")" ]; then
  su postgres -c "psql -qc 'CREATE DATABASE mitrabajo'"
fi

# ---------- Python: venv con 3.12 (el de .python-version) ----------
PY=python3.12
command -v "$PY" >/dev/null 2>&1 || PY=python3
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
# Solo se reinstala si cambió requirements.txt: el contenedor queda en caché.
HUELLA="$(cat requirements.txt | sha256sum | cut -d' ' -f1)"
if [ "$(cat .venv/.huella-requirements 2>/dev/null || true)" != "$HUELLA" ]; then
  .venv/bin/pip install -q -U pip setuptools wheel
  # pytest y bandit con las versiones de requirements-dev.txt; Playwright no
  # (los robots E2E no corren en la nube).
  .venv/bin/pip install -q -r requirements.txt pytest==9.1.1 bandit==1.9.4
  echo "$HUELLA" > .venv/.huella-requirements
fi

# ---------- Variables de la sesión ----------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  cat >> "$CLAUDE_ENV_FILE" <<VARS
export PATH="$RAIZ/.venv/bin:\$PATH"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/mitrabajo"
export SESSION_SECRET="ci-secreto-descartable-larguisimo"
export PLATAFORMA_PASSWORD="ci-plataforma-descartable"
export PLATAFORMA_CUIT="20000000000"
export ENTORNO="pruebas"
VARS
fi

echo "Entorno listo: Postgres 16 + pgvector, .venv ($(.venv/bin/python --version)) y variables del CI."

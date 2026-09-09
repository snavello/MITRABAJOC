#!/usr/bin/env bash
# Corre los dos tests de estrés de punta a punta contra BASE_URL (staging,
# NUNCA producción) y deja todo en carga/log/AAAA-MM-DD_HHMM/. Ver
# carga/README.md para los pasos previos (MOCK_EXTRACTOR, preparar_datos.py).
#
# Uso:
#   BASE_URL=https://mitrabajo-pruebas.onrender.com \
#   RENDER_API_KEY=rnd_xxx RENDER_WEB_SERVICE_ID=srv-xxx RENDER_DB_ID=dpg-xxx \
#   ./carga/correr.sh
# RENDER_API_KEY/RENDER_WEB_SERVICE_ID/RENDER_DB_ID son opcionales -- sin
# ellos, servidor.log queda con los campos de CPU/RAM/conexiones en null y
# el informe deja marcado el hueco (pedir capturas de Metrics).
set -euo pipefail
cd "$(dirname "$0")"

BASE_URL="${BASE_URL:?Falta BASE_URL, ej: https://mitrabajo-pruebas.onrender.com}"
if [[ "$BASE_URL" == *"onrender.com"* && "$BASE_URL" != *"pruebas"* ]]; then
  echo "ABORTAR: BASE_URL no parece ser el servicio de Pruebas ($BASE_URL)." \
       "Este script nunca debe apuntar a demo/producción." >&2
  exit 1
fi

if ! command -v k6 >/dev/null 2>&1; then
  echo "Falta k6. Instalar con:" >&2
  echo "  curl -sSL -o /tmp/k6.tar.gz https://github.com/grafana/k6/releases/download/v0.54.0/k6-v0.54.0-linux-amd64.tar.gz" >&2
  echo "  tar xzf /tmp/k6.tar.gz -C /tmp && sudo cp /tmp/k6-v0.54.0-linux-amd64/k6 /usr/local/bin/" >&2
  exit 1
fi

if [[ ! -f usuarios.csv ]]; then
  echo "Falta carga/usuarios.csv -- correr primero:" >&2
  echo "  DATABASE_URL=<la de mitrabajo-pruebas-db> python carga/preparar_datos.py" >&2
  exit 1
fi

CARPETA="log/$(date -u +%Y-%m-%d_%H%M)"
mkdir -p "$CARPETA"
echo "BASE_URL=$BASE_URL" > "$CARPETA/config.txt"
echo "fecha_utc=$(date -u -Iseconds)" >> "$CARPETA/config.txt"
echo "Resultados en $CARPETA"

# Monitor de servidor: un solo proceso para los dos tests, servidor.log
# queda con timestamps absolutos -- resumen.py los recorta por ventana.
python3 monitor_servidor.py "$CARPETA/servidor.log" &
MONITOR_PID=$!
trap 'kill $MONITOR_PID 2>/dev/null || true' EXIT

echo "=== Test 1: lecturas (50 -> 800 concurrentes, ~21 min) ==="
# k6 devuelve código != 0 cuando un threshold se cruza -- ESPERABLE a alta
# concurrencia, no es una falla del script. set -e está activo, así que hay
# que capturar el código sin dejar que mate el resto de la corrida.
set +e
BASE_URL="$BASE_URL" k6 run --out "json=$CARPETA/test1_lecturas.json" \
  --summary-export "$CARPETA/test1_resumen_k6.json" \
  k6/test1_lecturas.js 2>&1 | tee "$CARPETA/test1_stdout.log"
RC1=${PIPESTATUS[0]}
set -e
echo "(Test 1 terminó con código $RC1 -- 0 = sin thresholds cruzados, no 0 = alguno se cruzó, ver resumen.csv)"

echo "=== Test 2: recibos (200 lectores + ráfagas 2/5/10/20, ~17 min) ==="
set +e
BASE_URL="$BASE_URL" k6 run --out "json=$CARPETA/test2_recibos.json" \
  --summary-export "$CARPETA/test2_resumen_k6.json" \
  k6/test2_recibos.js 2>&1 | tee "$CARPETA/test2_stdout.log"
RC2=${PIPESTATUS[0]}
set -e
echo "(Test 2 terminó con código $RC2 -- 0 = sin thresholds cruzados, no 0 = alguno se cruzó, ver resumen.csv)"

kill "$MONITOR_PID" 2>/dev/null || true
trap - EXIT

echo "=== Armando resumen.csv ==="
python3 resumen.py "$CARPETA"

echo "Listo. Revisar $CARPETA/resumen.csv y completar carga/INFORME.md."

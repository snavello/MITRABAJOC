# Test de carga -- volver a correrlo

1. En Render, servicio `mitrabajo-pruebas` → Environment: `MOCK_EXTRACTOR=1`
   (y opcional `MOCK_EXTRACTOR_LATENCIA`, default 15s). Redeploy. **Nunca**
   en `mitrabajo-demo`.
2. Sembrar datos (una vez; corre contra la base real de Pruebas):
   `DATABASE_URL=<External Database URL de mitrabajo-pruebas-db> python carga/preparar_datos.py`
   Crea 1.000 trabajadores (clave `1234`) y `carga/usuarios.csv`.
3. Instalar k6 si hace falta (ver `correr.sh --help` o el bloque de abajo).
4. Correr todo:
   ```
   BASE_URL=https://mitrabajo-pruebas.onrender.com \
   RENDER_API_KEY=rnd_xxx RENDER_WEB_SERVICE_ID=srv-xxx RENDER_DB_ID=dpg-xxx \
   ./carga/correr.sh
   ```
   Las tres variables de Render son opcionales: sin ellas, `servidor.log`
   queda con CPU/RAM/conexiones en `null` (pedir capturas de la pestaña
   Metrics de Render para completar el informe a mano).
5. Resultados en `carga/log/AAAA-MM-DD_HHMM/`: JSON crudo de cada test,
   `resumen.csv` (por escalón: p50/p95/p99, % error, rps, CPU/RAM/conexiones
   máx.) y `servidor.log`. Volver a armar el resumen solo:
   `python carga/resumen.py carga/log/AAAA-MM-DD_HHMM/`.
6. Volcar los números a `carga/INFORME.md`.

**Test 3 -- filtro frenético del Panel Sindical** (`k6/test3_panel.js`,
2 minutos). Reproduce el cuelgue de Pruebas del 2026-09-18: un admin cambia el
filtro de empresa 30 veces en 60 s, disparando los 12 pedidos del panel juntos y
abandonándolos a los 250 ms, mientras 20 lectores recorren la app del
trabajador. Es opcional en `correr.sh`: se corre solo si está `ADMIN_CLAVE`
(clave de un admin de sindicato con el módulo `dashboard`; `ADMIN_CUIT` default
`20111111110`, el Super Admin de UOM de la demo):
```
BASE_URL=https://mitrabajo-pruebas.onrender.com ADMIN_CLAVE=<clave> ./carga/correr.sh
```
o suelto: `BASE_URL=... ADMIN_CLAVE=... k6 run carga/k6/test3_panel.js`.
Criterios (los imprime al final, con `APROBADO` / `NO APROBADO`, y los deja en
`test3_resumen.json`): **0 respuestas 500** (un 503 es esperable: es el
servidor diciendo "ocupado"), lectores sin fallas, y el **p95 de los lectores
durante la tormenta no pasa de 2 veces el de la fase base**. Con MOCK_EXTRACTOR=1,
nunca en demo. `resumen.py` todavía no levanta este test.

Instalar k6 (binario estático, sin apt):
```
curl -sSL -o /tmp/k6.tar.gz https://github.com/grafana/k6/releases/download/v0.54.0/k6-v0.54.0-linux-amd64.tar.gz
tar xzf /tmp/k6.tar.gz -C /tmp && sudo cp /tmp/k6-v0.54.0-linux-amd64/k6 /usr/local/bin/
```

**Nunca** apuntar `BASE_URL` a `mitrabajo-demo` ni a producción -- `correr.sh`
lo valida, pero revisar dos veces igual.

Mapeo de rutas: como "Mis Aportes" y "Credencial" son pestañas dentro de
`/app` (no páginas propias), el journey de lecturas usa `/app/inicio`
(home), `/app/notificaciones` (novedades), `/app` (recibo + aportes) y
`/api/credencial/qr` (credencial) -- ver `carga/k6/test1_lecturas.js`.

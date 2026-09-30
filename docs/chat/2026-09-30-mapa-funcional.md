# Mapa funcional de la plataforma (reemplaza a graphify)
Fecha: 2026-09-30 · Herramienta: Code · Origen: sesión de Claude Code (rama chore/mapa-funcional)
Estado: acordado
Quién: SDN

## Qué es

`mapa_funcional.py` genera `mapa-funcional/mapa.html`: la plataforma vista
por **funcionalidad**, que es como la piensa una persona, en vez de por
archivo o por función.

- **Nivel 1 — app**: Común, Afiliado, Empresa, Sindicato, Plataforma, Entornos.
- **Nivel 2 — funcionalidad**: los nombres de las pestañas (Tu Recibo,
  Trámites, Panel Sindical, Uso de IA, Sala de mando…). 49 en total; las 245
  rutas quedaron asignadas, ninguna sin clasificar.
- **Nivel 3 — de qué está hecha cada una**: pantalla (plantilla y JS), rutas,
  código (con nombre en castellano: "Georreferenciación de domicilios", no
  "geo"), tablas y servicios externos, más el módulo contratado y el permiso
  que la habilitan.

Dos vistas en la misma página:
- **Lista**: la funcionalidad elegida en cinco columnas unidas por líneas;
  tocar una caja muestra sus funciones y en qué otras funcionalidades se usa
  ("si cambio `CuentaTrabajador`, ¿qué se afecta?").
- **Grafo**: el isotipo de Colm3na al centro, las seis apps y sus
  funcionalidades. Un clic despliega lo que usa una funcionalidad; otro clic
  en otra la SUMA sin mover lo anterior, y lo que comparten queda como un
  solo nodo unido a ambas (con la lista "En común" al costado).

## Cómo se arma (decisiones)

- **Todo sale del código, leído con `ast`**: rutas de los decoradores de
  main.py, llamadas entre funciones de los módulos de la app, clases
  `table=True` de db.py y también su nombre dentro del SQL escrito a mano
  (dashboard.py, reportes), y servicios por librería (anthropic, fastembed,
  tesserocr, pypdfium2, pywebpush, sentry_sdk), URL o variable de entorno
  (GRAFANA_, TELEGRAM_, RENDER_API_KEY…), incluido el cliente creado a nivel
  de módulo o importado dentro de una función.
- **Lo único a mano** es `FUNCIONALIDADES` (prefijo de ruta → funcionalidad)
  y los nombres legibles. Una ruta que no encaje aparece en "Sin clasificar",
  a la vista: el olvido se nota.
- **No se recorren los guardianes de sesión** (`exigir_*`, `sesion_actual`…):
  los usan todas las rutas y solo repetirían lo mismo en cada funcionalidad.
  Tampoco se muestran `fechas`, `errores` ni `version`.
- **Límite dicho en la página**: no ve llamadas dinámicas (getattr, callbacks
  por texto). Es orientación; manda el código. Sindicato · "Ingreso y
  portada" muestra 34 tablas porque `/admin` arma el panel entero: es cierto.
- El HTML no se versiona (`mapa-funcional/` en `.gitignore`); el grafo carga
  vis-network de jsdelivr, así que sin conexión solo anda la vista Lista.

## Por qué no graphify

Se instaló el 2026-09-26 (`docs/chat/2026-09-26-graphify-orientacion.md`) y
se desinstaló hoy (`uv tool uninstall graphifyy`; el skill nunca se registró):
- por función son 5.700 nodos y el visor del navegador se traba;
- por archivo no dice nada: `main.py` tiene las rutas de las cinco apps y
  `db.py` las 64 tablas, y los nombres de archivo ("geo", "chequeo") no
  explican qué hacen;
- trae relaciones falsas marcadas como seguras (los `@app.get`/`@app.post`
  de main.py atribuidos a dos helpers de `carga/`).

Se sacó del repo todo lo suyo: `graphify-out/`, `.graphifyignore`, las
reglas de `.claude/settings.json` y de `.gitignore`, y su entrada de
CLAUDE.md. `uv` queda instalado (winget), no molesta.

## Uso

```
python mapa_funcional.py
```

Escribe y abre `mapa-funcional/mapa.html`. Regenerarlo después de sumar
rutas o funcionalidades; si aparece algo en "Sin clasificar", agregar su
regla en `FUNCIONALIDADES`.

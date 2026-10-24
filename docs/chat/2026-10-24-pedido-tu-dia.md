# Pedido: widget "Tu día" en la portada del afiliado (Laguna y Noticiero)

Mockup de referencia (cuatro pantallas + panel): https://claude.ai/artifact/NcBidsBxZKHQbcLevVothS
Si podés leerlo, tomá de ahí medidas y estética; este texto manda si algo difiere.

## 1. Qué es

Una franja **de una sola línea**, accesoria, en la portada del afiliado (`/app/inicio`,
`templates/portada.html`). Tiene dos partes:

- **Fija**: el clima de la localidad del afiliado con ícono (en escritorio, además, la hora y el
  pronóstico de mañana y pasado).
- **Rotativa**: UNA línea que cambia sola cada N segundos entre los rubros que el sindicato
  habilitó (efemérides, mercados, salud, etc.). Tocarla abre una hoja con el detalle.

No es una tarjeta con varios renglones: es una franja de 50–60 px de alto. Nada de
la rotación lo escribe el sindicato (para eso están las Noticias, y no se tienen que pisar).

## 2. Dónde va

- **Escritorio (≥ 900 px)**: adentro de `.pt-gremio`, a la DERECHA del saludo, en la misma fila,
  alineada abajo con el saludo (`align-items: flex-end`). El saludo ocupa `flex: 1 1 340px`; la
  franja, `flex: 0 1 600px`. Si no entra, baja debajo del saludo (`flex-wrap: wrap`).
  Hoy `.pt-gremio-hola` contiene `.fila-hola`; envolvé ambos en una fila nueva sin romper
  las reglas que ya tienen las dos hojas de modelo.
- **Teléfono (< 900 px)**: debajo del saludo, ancho completo con 16 px de margen lateral.
  - Laguna: tarjeta blanca que se monta sobre el final de la laguna (`margin-top: -28px`).
  - Noticiero: entre el saludo y la cinta de titulares (`.pt-tick`), que queda a 20 px debajo.
- Si el sindicato no tiene el módulo o apagó todo, la franja no se dibuja (ni su hueco).

## 3. Contenido

### 3.1 Parte fija

| Pieza | Escritorio | Teléfono |
|---|---|---|
| Hora y fecha | `08:42` + `VIE 29/5` debajo | NO (el teléfono ya muestra la hora) |
| Clima hoy | ícono 28 px + temperatura actual | ícono 24 px + temperatura |
| Pronóstico | mañana y pasado: ícono 17 px + máxima | NO |
| Alerta SMN | puntito ámbar sobre el ícono del clima | igual |

- **Hora**: la de Buenos Aires. El servidor manda la hora en la respuesta (regla de `fechas.py`:
  nada de `datetime.now()` en Python) y el cliente la hace avanzar a partir de ahí, nunca con el
  reloj del dispositivo como fuente de la fecha.
- **Ubicación del clima** (en este orden): coordenadas del domicilio de `CuentaTrabajador`
  (`latitud`/`longitud`) → centroide de su localidad con Georef (`geo.py`, que ya cachea en
  `GeoCache`) → coordenadas de su seccional → sin clima (la franja queda solo con la rotación).
  Las coordenadas NUNCA viajan al navegador: la respuesta trae el nombre de la localidad y el
  clima, nada más. No se pide la ubicación del teléfono.
- **Íconos**: SVG de línea, `stroke-width` 1.5–1.7, `fill: none`, sumados al sprite de la portada
  como `<g id="ic-clima-…">` (sol, parcial, nublado, lluvia, tormenta, nieve, niebla, viento). Un
  mapa código-del-proveedor → ícono en el servidor. Nunca emojis.
- **Alerta del SMN**: solo cuando hay una vigente para la zona. Dos efectos: el puntito ámbar
  (15 px, sobre la esquina superior derecha del ícono) y un ítem de alerta que entra PRIMERO en
  la rotación con su rótulo en ámbar. El ámbar es color de ESTADO: fijo, nunca de la paleta del
  sindicato (`--lg-amb`/`--lg-amb-f` en Laguna; `--nt-amb`/`--nt-amb-fondo` en Noticiero).

### 3.2 Rubros que rotan (cada uno lo prende o apaga el sindicato)

Cada ítem tiene: `rubro`, `chip` (rótulo corto, una palabra o un año), `linea` (≤ 60
caracteres en escritorio, ≤ 40 pensado para teléfono, el resto se corta con elipsis), y para la
hoja de detalle `titulo`, `texto`, `fuente` (OBLIGATORIA en todos menos el saludo).

| Rubro | Chip de ejemplo | De dónde sale |
|---|---|---|
| Saludos | `Hoy` | Cumpleaños: `CuentaTrabajador.fecha_nacimiento` (mes-día = hoy). Aniversario: `Trabajador.fecha_afiliacion` ("Hoy cumplís 8 años en el gremio"). Si la fecha no está cargada, no sale. |
| Efemérides nacionales y obreras | `1969` | `data/tu_dia/efemerides.json`, archivo propio (ver 3.3). |
| Mercados | `Dólar` / `Merval` | Oficial: API del BCRA. Blue y MEP: DolarApi (no oficial). Merval: CONFIRMAR fuente antes de prometerlo (BYMA publica con demora pero sin API documentada); si no hay una confiable, el ítem Merval no sale. Una vez por día, "al cierre de ayer". Dos ítems: dólares y Merval. |
| Datos curiosos | `¿Sabías?` | `data/tu_dia/curiosos.json` |
| Ciencia y técnica | `Ciencia` | `data/tu_dia/ciencia.json` (CONICET, CONAE, INTI, INTA; sin política) |
| Salud | `Salud` | `data/tu_dia/salud.json` (Ministerio de Salud; campañas por mes, p. ej. antigripal en otoño) |
| Entretenimiento | `Juego` | `data/tu_dia/juego.json`: pregunta + 3 opciones + respuesta + explicación |
| Tus derechos como consumidor | `Derechos` | `data/tu_dia/consumidor.json`; cada ítem con su NORMA citada (p. ej. "Ley 24.240, art. 34") |

- **Todos ven lo mismo el mismo día**: el ítem de cada JSON se elige con la fecha de Buenos Aires
  como semilla (determinista), no al azar por request.
- **Orden de la rotación**: alerta (si hay) → saludo (si hay) → los demás en el orden en que el
  sindicato los tiene en su configuración.

### 3.3 Los archivos curados (`data/tu_dia/*.json`)

- Formato común: lista de objetos con `id`, `chip`, `linea`, `titulo`, `texto`, `fuente` y los
  campos propios del rubro. Efemérides suma `mmdd` ("05-29"), `anio`, `tipo` (`nacional` |
  `obrera`) y `politica` (bool, para fechas con carga política como el 17 de octubre).
- Efemérides: armá un BORRADOR de los 366 días con la fuente de cada fecha (educ.ar, Ley 27.399,
  AGN; las obreras con el CeDInCI / Biblioteca Nacional). Texto propio, no copiado de Wikipedia.
  Queda marcado `revisado: false` hasta que una persona lo revise; marcá con `dudosa: true` toda
  fecha de la que no estés seguro en vez de inventarla. Los demás JSON arrancan con 30 ítems cada
  uno, con el mismo criterio.
- Nada de esto se carga a la base: son archivos versionados, como `data/precios_ia.json`.

## 4. Configuración del sindicato

- **Módulo opt-in** `"tu_dia"` en `modulos.py` (`MODULOS`, fuera de `MODULOS_INICIALES`): lo prende
  plataforma por sindicato. Sin módulo, ni la franja ni el endpoint (403 con `_exigir_modulo`).
- **Dónde lo configura el sindicato**: un bloque "Tu día" en la pestaña Apariencia de `/admin`
  (ya es `SECCION_SUPER_ADMIN`). Contenido (ver la pantalla "Panel del sindicato" del mockup):
  - "Siempre a la vista" (solo lectura): hora y fecha, clima, alertas.
  - "Rubros que rotan": un interruptor por rubro, con descripción corta y contador "N de 8
    prendidos". Mercados trae la casilla "Incluir el dólar blue" (apagada por defecto).
    Efemérides trae "Incluir fechas con carga política" (apagada por defecto).
  - "Cambia cada": 6 / 10 / 15 segundos (6 por defecto).
  - Botón "Guardar los rubros".
- **Dónde se guarda**: `Sindicato.tu_dia`, columna JSON con `db.JSON_TIPO` (NUNCA `JSON` pelado),
  con migración Alembic. Forma: `{"rubros": ["saludo","efemerides","salud","consumidor"],
  "blue": false, "politicas": false, "intervalo": 6}`. NULL = los valores por defecto (los cuatro
  rubros de ese ejemplo prendidos). Un rubro o intervalo fuera del catálogo no se guarda.

## 5. Servidor

- **Endpoint** `GET /api/tu-dia` con la sesión del trabajador (cookie `sesion_trabajador`, CUIL
  por `_cuil_seguro`, sindicato de la sesión, jamás de un parámetro). Devuelve:
  ```json
  {"hora_ba": "2026-05-29T08:42:00", "intervalo": 6,
   "clima": {"localidad": "Avellaneda", "temp": 11, "icono": "parcial",
             "pronostico": [{"dia": "mañana", "icono": "lluvia", "max": 13},
                            {"dia": "sáb", "icono": "sol", "max": 14}]},
   "alerta": {"nivel": "amarilla", "texto": "Tormentas fuertes desde las 18 h", "fuente": "SMN"},
   "items": [{"rubro": "efemerides", "chip": "1969", "linea": "…", "titulo": "…",
              "texto": "…", "fuente": "…"}]}
  ```
  `clima` y `alerta` pueden ser `null`. Si no queda ningún ítem ni clima, `items: []` y la franja
  no se dibuja.
- **La portada NO espera esta respuesta**: la página se renderiza sin la franja y el JS la pide
  después de cargar; mientras tanto, nada (o un esqueleto del mismo alto, para no mover lo de
  abajo).
- **Servicios externos** (clima, alertas, BCRA, DolarApi): siempre desde el servidor, nunca desde
  el navegador (la CSP queda como está: no se suma ningún origen). Un módulo nuevo `tu_dia.py`
  (puro donde se pueda: elección del ítem del día, armado de la lista, filtros) y uno
  `tu_dia_fuentes.py` con las llamadas. Timeout de 2 s por llamada; si falla, esa pieza va `null`
  y el resto sale igual. Nunca un 500 por un tercero.
- **Caché**: por clave (coordenadas redondeadas a 2 decimales para el clima; "dia" para
  mercados). TTL: clima 30 min, alertas 10 min, mercados hasta el día siguiente. En la base
  (tabla genérica o `GeoCache` si cuadra) y no solo en memoria: Render corre un worker por núcleo.
- **Proveedor del clima: A CONFIRMAR con SDN antes de escribir esa parte.** Open-Meteo es gratis
  solo para uso no comercial (Colm3na necesitaría el plan pago); el SMN publica pronóstico y
  alertas pero sin API documentada. Dejá la interfaz del proveedor detrás de una función para
  cambiarlo sin tocar el resto.
- Una sesión de base por request, como siempre (CLAUDE.md, "Una sesión de base por request").

## 6. Interacción

- Rota sola cada `intervalo` segundos. **Se pausa** al pasar el mouse, cuando la franja tiene foco
  y cuando la pestaña no está visible (`visibilitychange`).
- **Tocar la línea abre la hoja de detalle**: reusá la familia de modal de la noticia
  (`.overlay.overlay-articulo` + `.modal-articulo`, con un id nuevo, p. ej. `overlay-tudia`), así
  `modales.js` y `movimiento.css` la cubren solos. Si creás una familia nueva, sumala a `CAJAS` y
  `FONDOS_MOV` de `modales.js` y a `movimiento.css` (`test_modales.py` lo controla). En la hoja:
  chip, título, texto, fuente; el juego muestra las 3 opciones y la respuesta al elegir; mercados,
  la tabla con oficial, blue (si está habilitado), MEP y Merval. Al cerrar la hoja, la rotación
  sigue desde el ítem siguiente.
- **Cambio de ítem**: la línea sale hacia arriba con fundido y entra la nueva desde abajo, con
  `--mov-medio` y `--ease-mueve` de `movimiento.css` (nunca números sueltos). Con "reducir
  movimiento": solo fundido, sin desplazamiento.
- Todo texto que venga de los JSON o de terceros se pone con `textContent`, nunca `innerHTML`.

## 7. Diseño por modelo

Todo color sale de las variables del modelo (`--lg-*`, `--nt-*`), así la paleta del sindicato
(`data-paleta="sindicato"`) funciona sola. El CSS va en las hojas de cada modelo
(`static/temas/laguna-portada.css`, `static/temas/noticiero-portada.css`) bajo
`html[data-tema="…"]`, y la estructura común en el bloque "Portadas v2" de `marca.css` con
prefijo `pt-` (propuesta: `.pt-dia`, `.pt-dia-hora`, `.pt-dia-clima`, `.pt-dia-pron`,
`.pt-dia-sep`, `.pt-dia-linea`, `.pt-dia-chip`, `.pt-dia-texto`, `.pt-dia-alerta`). Ninguna
selección o rótulo se marca con una barra de color al costado.

### 7.1 Laguna

**Escritorio** (sobre la laguna oscura, efecto vidrio):
- Caja: alto 60 px, `border-radius: 12px`, fondo `rgba(255,255,255,.07)`, borde
  `1px solid rgba(255,255,255,.16)`, padding `0 8px 0 16px`, `gap: 14px`.
- Hora: Manrope 300, 22 px, blanca, `tabular-nums`; fecha debajo: 10 px, 700, `letter-spacing:
  .14em`, `--lg-sobre-osc`.
- Separadores: 1 × 32 px, `rgba(255,255,255,.16)`.
- Clima: ícono 28 px en `--lg-fluor`; temperatura Manrope 300, 22 px, blanca; pronóstico 12 px
  `--lg-sobre-osc` con ícono 17 px del mismo color.
- Línea: botón de 44 px de alto que ocupa el resto (`flex: 1; min-width: 0`). Chip: 11 px, 700,
  mayúsculas, `letter-spacing: .14em`, color `--lg-fluor-txt`, sin fondo. Texto: Manrope 500,
  13,5 px, blanco, una línea con elipsis. Flecha 16 px en `--lg-agua` al final.
- Chip de alerta: fondo `--lg-amb-f`, texto `--lg-amb`, 11 px, 700, radio 4 px, alto 22 px.

**Teléfono** (tarjeta clara):
- Caja: alto 52 px, `margin: -28px 16px 0`, fondo blanco, radio 12 px, sombra
  `inset 0 0 0 1px` (azul al 8%) + `0 14px 28px -20px` (azul al 55%), padding `0 4px 0 12px`.
- Clima: ícono 24 px en `--lg-turq`; temperatura Manrope 400, 20 px, `--lg-azul`.
- Separador 1 × 26 px, azul al 12%.
- Chip: 10,5 px, 700, `letter-spacing: .12em`, `--lg-turq-osc`. Texto 13 px, 500, `--lg-azul`.
  Flecha 15 px `--lg-azgris`. Chip de alerta igual que en escritorio, 20 px de alto.

### 7.2 Noticiero

**Escritorio** (recuadro de diario sobre el papel):
- Caja: alto 60 px, fondo `--nt-carta`, borde `1px solid --nt-linea` con
  `border-top: 3px solid --nt-tinta`, sin radio, padding `0 6px 0 16px`.
- Hora: Anton 24 px; fecha debajo: Barlow Condensed 700, 12 px, `letter-spacing: .8px`,
  `--nt-tinta-2`.
- Separadores 1 × 32 px `--nt-linea`.
- Clima: ícono 28 px en `--nt-indigo-2`; temperatura Anton 26 px; pronóstico Barlow Condensed
  700, 15 px, `--nt-tinta-2`, ícono 17 px.
- Chip: fondo `--nt-indigo`, texto `--nt-marfil`, Barlow Condensed 700, 13 px, mayúsculas,
  `letter-spacing: 1px`, alto 22 px, sin radio. Texto: Archivo 500, 14 px, `--nt-tinta`, elipsis.
  Flecha 16 px `--nt-tinta-3`.
- Chip de alerta: fondo `--nt-amb-fondo`, `inset 0 0 0 1px --nt-amb`, texto `--nt-amb`.

**Teléfono**:
- Caja: alto 50 px, `margin: 0 16px`, mismo recuadro que en escritorio, padding `0 2px 0 12px`.
- Clima: ícono 24 px `--nt-indigo-2`; temperatura Anton 22 px.
- Chip 12,5 px, alto 20 px; texto Archivo 13 px. La cinta `.pt-tick` queda 20 px debajo.

## 8. Accesibilidad

- `<aside class="pt-dia" aria-label="Tu día">`. El bloque del clima lleva un `aria-label` con la
  frase completa ("Avellaneda: 11 grados, parcialmente nublado. Mañana 13, sábado 14.").
- La línea es un `<button>` real con `aria-label` = "chip: línea. Tocá para ver el detalle".
- La zona que rota NO es `aria-live` (anunciaría cada 6 segundos).
- Contraste 4,5:1 en los dos modelos y con la paleta del sindicato (los tonos ya corregidos por
  `temas.paleta_legible` están en `--lg-fluor-txt`, `--nt-coral-ind`, etc.).
- Blanco táctil de 44 px como mínimo para la línea.

## 9. Pruebas (`test_tu_dia.py` y los que ya existen)

- Un rubro apagado no viene en `items`; el blue solo con `blue: true`; una efeméride `politica`
  solo con `politicas: true`.
- Sin el módulo: el endpoint da 403 y la portada no dibuja la franja.
- Un tercero que falla o tarda más de 2 s: 200 con `clima: null` (o sin mercados), nunca 500.
- El saludo solo el día del cumpleaños o del aniversario; sin fecha cargada, no sale.
- Aislamiento: la configuración de un sindicato no afecta a otro; el sindicato sale de la sesión.
- Todos los ítems de los JSON tienen `fuente`; todos los de consumidor citan una norma; ningún
  `chip` pasa de 14 caracteres ni una `linea` de 80.
- La elección del ítem del día es determinista para una fecha dada.
- La respuesta no trae coordenadas.
- Siguen en verde `test_fechas.py`, `test_modales.py` y `test_migraciones.py` (esquema de modelo =
  esquema de Alembic). Todo archivo nuevo de `/static/` va con sello `?v=` (`sello_static`).

## 10. Cierre

- Versión: Trabajador sube el minor; Admin también (bloque de configuración); Plataforma si
  tocás el catálogo de módulos que ella ve.
- Bitácora, "Estado actual" y HISTORIAL.md según "Bitácora y cierre de bloque" de CLAUDE.md.

## Fuera de este pedido (para después)

Ajedrez del día (Lichess), paso de la Estación Espacial, imagen del día de Wikimedia, sismos
del INPRES y sudoku del día: no requieren precarga, pero SDN todavía no los eligió.

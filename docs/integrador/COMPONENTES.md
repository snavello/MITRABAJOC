# Cómo se escribe una parte del documento integrador

Cada capítulo es un archivo `partes/NN-nombre.html` con FRAGMENTOS de HTML
(nada de `<html>`, `<head>`, `<style>` ni `<script>`). `armar.py` los junta
en orden, arma el índice y la navegación lateral desde los encabezados,
incrusta capturas, fuentes y logo, y escribe
`recursos/colm3na-integrador.html`. La hoja de estilos es `estilo.css`:
**no se agregan estilos en línea salvo dentro de los SVG**.

## Para quién y cómo

- Lectores: gente que entra al equipo (desarrollo, implementación, comercial)
  y funcionarios de los sindicatos que no conocen el detalle. Primero se
  explica en castellano llano qué es y para qué sirve; después, en un
  recuadro `nota tecnico`, cómo está hecho (módulos, tablas, rutas, reglas).
- Castellano rioplatense, tercera persona y voseo cuando se le habla al
  lector ("mirá la figura"). Frases cortas. Nada de marketing vacío: cada
  ventaja con un ejemplo concreto.
- La plataforma se llama **Colm3na** (nunca "Mi Trabajo" salvo como nombre
  histórico del repo). Los actores: afiliado/trabajador, sindicato (panel),
  plataforma (Colm3na como operador), empresa/empleador.
- Fechas en formato argentino ("12 de noviembre de 2026"), importes con
  punto de miles y coma decimal.
- **Fuente de verdad, en este orden**: el código en `main` (es lo que corre)
  > `CLAUDE.md` ("Estado actual", "Decisiones tomadas") > `HISTORIAL.md` >
  `BITACORA.md` > `docs/*.md` > planes `PLAN_*.md`/`SPRINT_*.md` (se
  congelan al acordarse: pueden haber cambiado después) > los HTML de
  `recursos/` (varios están ATRASADOS). Ante una diferencia, manda el código
  y se escribe lo que hoy corre. Lo pendiente se marca como pendiente
  (`nota pendiente` o `chip`), nunca como hecho.
- Nada de datos personales reales, claves, tokens, PIN ni URLs internas con
  secretos. Los accesos de la demo NO van en este documento.

## Estructura de un capítulo

```html
<section class="capitulo" id="cap-5">
  <header class="cap-cab">
    <span class="cap-num">05</span>
    <h2>Descripción funcional</h2>
    <p class="cap-bajada">Una o dos frases que dicen qué se aprende acá.</p>
  </header>
  <p class="lead">Párrafo de entrada, un poco más grande.</p>

  <h3 id="cap-5-recibos"><span class="n">5.2</span>Auditoría de recibos</h3>
  <p>…</p>
  <h4>Un subtema</h4>
  …
</section>
```

- `h2` solo en la cabecera del capítulo; `h3` para secciones (con `id`
  único que empiece por el id del capítulo y con `<span class="n">5.2</span>`);
  `h4` para subsecciones; `h5` para rótulos chicos. El índice y el riel se
  arman solos desde `h2` y `h3`.
- Un mismo archivo puede tener la continuación de un capítulo: en ese caso
  NO abre `<section class="capitulo">` con cabecera, sino
  `<section class="capitulo continua" id="cap-5b">` sin `cap-cab`, y sigue
  la numeración de `h3` que le toca.

## Componentes

**Recuadros** (`rot` es el rótulo):
```html
<div class="nota"><span class="rot">Para entender</span><p>…</p></div>
<div class="nota regla"><span class="rot">Regla vigente</span><p>…</p></div>
<div class="nota tecnico"><span class="rot">Para técnicos</span><p>Módulo <code>validador.py</code>…</p></div>
<div class="nota ejemplo"><span class="rot">Ejemplo</span><p>…</p></div>
<div class="nota alerta"><span class="rot">Cuidado</span><p>…</p></div>
<div class="nota pendiente"><span class="rot">Pendiente</span><p>…</p></div>
```

**Captura real** (la imagen la pone `armar.py` desde `capturas/`; las
claves están en `capturas/LISTA.md` y `capturas/manifest.json`):
```html
<figure class="fig captura" data-captura="s-panel-sindical">
  <figcaption>El Panel Sindical: … (qué mirar en la imagen)</figcaption>
</figure>
```
Dos o tres juntas (por ejemplo, móvil al lado de móvil):
```html
<div class="par-capturas">
  <figure class="fig captura" data-captura="t-recibo-subir"><figcaption>…</figcaption></figure>
  <figure class="fig captura" data-captura="t-recibo-resultado"><figcaption>…</figcaption></figure>
</div>
```
Texto al lado de un móvil: `<div class="lado"><div>…texto…</div><figure class="fig captura" data-captura="t-credencial">…</figure></div>`
(o `lado izq` con la figura primero). `armar.py` agrega la clase `movil`
sola. Si la captura no existe, la figura se omite: el texto no tiene que
depender de ella ("como se ve en la figura" solo si la captura existe en el
manifest; mirá el manifest y la imagen con Read antes de describirla).

**Diagrama** (SVG en línea, dibujado a mano):
```html
<figure class="fig diagrama">
  <svg viewBox="0 0 860 360" role="img" aria-label="…">…</svg>
  <figcaption>Qué muestra el diagrama.</figcaption>
</figure>
```
Reglas de los SVG: `viewBox` de 860 de ancho (alto libre), sin `width`/
`height` fijos; texto con `font-size` 12 a 16 (nunca menos de 11);
`font-family` se hereda (no la pongas), salvo títulos de caja en
`font-family="Barlow Condensed" font-weight="700"`. Colores SOLO de esta
paleta (fondo claro, imprimible):
- tinta `#0a1421`, texto `#16243a`, texto2 `#4c5d75`, línea `#dbe2ea`,
  suave `#eef2f7`, blanco `#ffffff`
- miel (marca Colm3na) `#f0a01e`, miel oscura `#a86400`, miel suave `#fff6e5`
- azul `#2e5c8a` / suave `#eaf1f8`; verde `#0d7a5f` / `#e8f5f0`;
  rojo `#c0392b` / `#fbeceb`; ámbar `#b8860b` / `#fbf4e0`;
  violeta `#6b4fa0` / `#f1edf8`
Cajas con `rx="10"`, borde de 1,5 px, flechas con un `<marker>` definido en
el mismo SVG (ids únicos por figura: prefijalos, p. ej. `f5a-flecha`). Los
colores de estado (verde OK, rojo error, ámbar aviso) solo para estados.
Probá que el SVG sea válido (etiquetas cerradas, `&amp;` en vez de `&`).

**Tabla**:
```html
<div class="tabla-cont"><table class="tabla">
  <thead><tr><th>Módulo</th><th>Qué hace</th></tr></thead>
  <tbody><tr><td>…</td><td>…</td></tr></tbody>
</table></div>
```
`<td class="num">` para cifras.

**Tarjetas**: `<div class="grilla-3"><div class="tarjeta miel"><h4>…</h4><p>…</p></div>…</div>`
(variantes de borde: `miel azul verde violeta rojo`; `oscura` para destacar
una sola). Ícono opcional: `<div class="ico"><svg viewBox="0 0 24 24"><path d="…"/></svg></div>`
(trazo de línea, sin relleno).

**Cifras**: `<div class="cifras"><div class="cifra"><b>99,8 %</b><span>lecturas exactas…</span></div>…</div>`

**Pasos**: `<ol class="pasos"><li><b>Título del paso</b>Descripción…</li>…</ol>`

**Chips**: `<span class="chip verde">Hecho</span>`, `ambar` En prueba,
`violeta` Pendiente, `azul`, `miel`, `rojo`.

**Cita**: `<p class="cita">…</p>`. **Separador**: `<div class="separador"></div>`.

## Glosario

Cada parte deja además `partes/NN-nombre.glosario.json`: una lista de
`{"termino": "…", "definicion": "una o dos frases llanas"}` con los
términos técnicos o propios que usó (8 a 20). `armar.py` los junta,
deduplica y arma el glosario final.

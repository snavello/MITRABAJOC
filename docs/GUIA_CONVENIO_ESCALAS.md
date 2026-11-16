# Guía para validar «Convenio y escalas»

Una página para quien prueba la herramienta en **Pruebas** (en Demo no existe: da 404). Plan: `PLAN_CONVENIO_ESCALAS.md`. Reglas: `CLAUDE.md` → «Herramientas → Convenio y escalas».

## Cómo entrar

1. Ingresá a `/entornos` de Pruebas con tu usuario de plataforma (o con el pase de la landing, si está habilitado) → pestaña **Herramientas** → tarjeta **Convenio y escalas** → «Abrir» (`/entornos/herramientas/convenio-escalas`).
2. La herramienta se ve como la app del afiliado, con la marca de **La Bancaria** y el afiliado de prueba (CUIL 27999999994). Si La Bancaria no está en la base de Pruebas, cae a los colores de Colm3na.
3. Arriba hay una franja «Solo para validar» con el selector de **modelo** (Laguna, Noticiero) y de **paleta** (Colm3na, La Bancaria). No guarda nada: cambia la URL (`?tema=` y `?paleta=`). Probá las **cuatro combinaciones**, en escritorio y en teléfono.

## Qué mirar

**Escala vigente.** Elegí rama (Administrativa, Maestranza, Ordenanza), años de antigüedad o «Tengo un cargo jerárquico», título y función de caja, y «Ver la escala».
- Cada valor es un concepto suelto de la grilla, con su etiqueta **Publicado** (período, fecha de publicación y enlace al PDF) o **Referencia** (el ROE: «El monto real depende de tu banco»). Con un tramo de ROE elegido, muestra el valor de la tabla para ese tramo, también como Referencia.
- Control cruzado: «Administrativa, 6 años, universitario, sin caja» con la grilla de agosto 2026 tiene que coincidir al centavo con `data/grillas_bancarias/2026-08.json`.
- «Recordar mi selección» la guarda con su fecha en este navegador; «Cambiar» la edita.
- Al final, la evolución mes a mes de **un** valor (el conformado; el básico en un cargo jerárquico) solo con los meses que tengan grilla publicada, con el texto fijo de que no es lo que cobró.
- Si hay un comunicado nuevo sin grilla publicada, aparece el cartel «Hay una actualización publicada el dd/mm. La estamos cargando.»

**Convenio.** Fichas por situación, el índice completo de artículos y el buscador (por palabra o por número de artículo). Cada ficha trae el texto **literal** del artículo, un resumen «en simple» marcado **«Resumen sin revisar por el sindicato»** y, si el artículo tiene un valor en la grilla (por ejemplo el 25), ese importe con su etiqueta. Las situaciones son provisorias.

**Estado de las grillas** (para el equipo, no para el afiliado): `/entornos/herramientas/convenio-escalas/estado`. Se abre con el botón «Estado de las grillas» de la tarjeta de Herramientas.

## Qué NO tiene que aparecer

- Ningún **total**, suma de conceptos, veredicto, semáforo ni comparación con un recibo o con un importe tipeado.
- Ningún valor sin etiqueta **Publicado** o **Referencia**.
- Ninguna salida hacia «Tu recibo». El texto fijo de alcance («Son valores sueltos de la grilla, no se suman: esto no es tu sueldo…») siempre visible junto a los valores.
- Colores o fondos ilegibles en cualquiera de las cuatro combinaciones, texto cortado en teléfono, foco invisible al navegar con teclado.

Si ves algo así, anotá la combinación, la selección elegida y la captura.

## La vista de estado

- **Resumen** y tabla **Grillas**: período, estado (publicada, retenida, reemplazada, descartada), origen (semilla, automática, manual) y de qué nota salió. Al tocar una, el detalle muestra cada uno de los **seis controles** (C1 estructura, C2 doble lectura, C3 anclas del comunicado, C4 factor único, C5 coherencia interna, C6 período) con las celdas que no pasaron.
- **Buscar ahora**: una pasada completa (busca, lee si hay una nota nueva, controla, publica o retiene). Tarda varios minutos y **gasta IA**; como mucho una por minuto.
- **Ensayo de lectura**: elegís un período que ya tiene grilla publicada, el proceso lo lee de nuevo desde el sitio y lo compara celda por celda **sin publicar nada**. Es la medida de cuánto se puede confiar en la lectura (agosto 2026 contra la transcripción a mano).
- **Una retenida**: abrila, mirá qué control falló, corregí las celdas contra el PDF y «Guardar correcciones y volver a controlar»; si pasan todos, «Publicar». «Volver a leer la nota» la relee; «Descartar» la saca. Todo queda con quién y cuándo. Mientras tanto la vigente sigue siendo la anterior.
- Un **trimestre nuevo de conectividad** deja la grilla retenida siempre: se revisa contra el PDF.

## Prender el proceso diario

En Render, servicio de **Pruebas**: `ESCALAS_AUTO=1` (opcional `ESCALAS_HORAS`, default `10:00,16:00` de Buenos Aires). Necesita `ANTHROPIC_API_KEY`, `MOCK_EXTRACTOR=0` y, para los avisos, `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`. El modelo de lectura se elige en `/plataforma` → Uso de IA → Modelos (`grilla_salarial`, default Sonnet 5.5). Detalle en `DESPLIEGUE_RENDER.md`.

## Todavía no está

La prueba real del plan (ensayo de agosto y carga de septiembre en Pruebas), la acción para marcar un resumen como revisado, y el pase a la app del afiliado.

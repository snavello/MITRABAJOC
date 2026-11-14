# QA de pantallas — Mesa de implementación (2026-11-14)

Navegador real (Playwright/Chromium), dos contextos (equipo y sindicato), 1280x800, 360x740 y con `prefers-reduced-motion`. Capturas en `disenos/qa-pant-*.png`.

## Defectos

| # | Sev. | Dónde | Qué pasaba | Estado |
|---|---|---|---|---|
| P-01 | Media | /entornos → Implementación | La tarjeta «Usuarios del sindicato en .» se veía vacía antes de elegir proyecto (`.sala-tarjeta` es flex y pisaba `[hidden]`); su formulario enviaba sin hacer nada. | Corregido (`.impl-caja[hidden]`) |
| P-02 | Media | mesa.js, 401 | Con la sesión vencida al enviar, la pantalla redirigía y se perdía el borrador; el equipo caía en el ingreso del SINDICATO sin salida. | Corregido: al enviar no se redirige, mensaje con el borrador a salvo; el equipo va a /entornos; el ingreso del sindicato suma «¿Sos del equipo?» |
| P-03 | Media | mesa.js `parseHash` | `#buscar?q=%E0%A4%A` lanzaba `URI malformed` y la vista quedaba sin responder. | Corregido |
| P-04 | Media | Faltante | El equipo no tenía botón para exportar el ZIP. | Corregido: «Exportar todo (ZIP)» en la mesa (escritorio) y en cada proyecto de /entornos |
| P-05 | Baja | Nueva tarjeta / responder | 6 archivos o más de 40 MB subían todo para recién ahí fallar. | Corregido: se avisa antes, con el mismo tope que el servidor |
| P-06 | Baja | `#t9999` | Mostraba «No existe la tarjeta #9999» con un «Probar de nuevo» inútil. | Corregido: «No existe o no lo podés ver» + Volver |
| P-07 | Baja | `#buscar?q=` | «9 tarjetas con «»». | Corregido: vuelve a Pendientes |
| P-08 | Media | Teléfono | Botones chicos (Ficha, Bajar, Borrar, Volver, Responder con…, Tarjeta para este hito, resumen) de 38 px o menos; en /entornos 30 px. | Corregido (44 px con puntero táctil o ≤860 px) |
| P-09 | Baja | Textos | «Tocá una» (en escritorio no se toca). | Corregido |
| P-10 | Baja | Tarjeta aprobada | Triple redundancia «Aprobada · Aprobada · APROBADA». | Corregido: la tarjeta resuelta muestra un solo sello y «por quién · cuándo» |
| P-11 | Baja | Equipo → «Cargar hitos de La Bancaria» | Se ofrece siempre y, si ya tiene hitos, termina en 409 (con mensaje visible). El servidor no informa si hay hitos. | Corregido: la lista suma `tiene_hitos` y `n_hitos`; el botón solo si no hay plan («Plan cargado: N hitos») |
| P-12 | Baja | Avisos | El toast «Tarjeta creada.» tapa unos segundos el selector de estado en escritorio. | Corregido: el aviso va arriba, sin capturar el puntero |
| P-13 | Baja | cambiar-clave | El token firmado viaja en la URL (GET). | Aceptado: mismo patrón que `/admin/cambiar-clave` |
| P-14 | Info | Mensaje sin red | Dice «Revisá tu internet» también si el que cayó es el servidor. | Corregido: «Sin conexión» (`navigator.onLine`) distinto de «El servidor no respondió» |

## Resistió

Aprobación: solo la ve el lado que no la pidió (el que la pidió ve solo el redactor); diálogo con foco, Esc y foco de vuelta. Nota interna: ni el sindicato la ve, ni la encuentra por código (`EN0002-2` da «No existe o no lo podés ver», `legales` no devuelve nada) ni por texto. Texto hostil (`<img onerror>`, `<script>`, emojis, 5.000 W sin espacios, archivo de 250 letras, nombre de proyecto y de usuario con HTML): nada se ejecuta, sin scroll horizontal a 360 px en ninguna vista. Doble clic no duplica (también en Crear proyecto). Enlaces en texto, copiar código (portapapeles y aviso), hashes `#PE0001`, `#pe0002`, `#AR000001`, `#HI0001`, `#EN0001-1`, inexistentes y `PE00041`/`XPE0004`. 429 con mensaje claro en nueva y en responder. 21 MB, título 500, texto 5.001: mensajes junto al control. Sin errores de consola ni violaciones de CSP (solo los 401/404/429 esperados). Rótulos en todos los controles, foco visible, contraste AA en todas las vistas y los seis colores de tipo. Recorrido completo (proyecto, usuario, clave propia, hitos, pedido, entrega con datos personales, nota, aprobación, error, aviso con «Lo leyeron», hitos, carpetas, aprobaciones, cerrar y reabrir, ZIP de 18 archivos) sin fallos.

## Tests
`test_implementacion_pantalla.py` suma `test_qa_pantallas_correcciones_de_cliente` (45 en verde junto con `test_implementacion_acceso.py`).

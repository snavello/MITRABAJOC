# Laboratorio de modelos — ficha rectora

Herramienta de `/entornos` → Herramientas (2026-10-29, pedido de SDN). Es el
**banco de pruebas de `/plataforma`, replicado y adaptado**: el mismo recibo
leído por varios modelos, lado a lado, con tiempo y costo, pero **aislado de
la app real** y **abierto a otros proveedores** (Kimi de Moonshot, Qwen de
Alibaba). Sirve para contestar con números si un modelo más barato lee
recibos igual de bien que el que corre en producción, antes de tocar nada.

Ruta: `/entornos/herramientas/laboratorio-modelos`. Motor:
`laboratorio_modelos.py`. Catálogo de proveedores:
`data/laboratorio_modelos.json`. Tests: `test_laboratorio_modelos.py`.

## Qué hace y qué no

- **Mismo prompt para todos.** El sistema y el esquema son los de
  `extractor.py`, sin adaptar a ningún proveedor. Si un modelo necesita
  otro prompt para leer un recibo, eso es parte de lo que se mide.
- **No toca la app.** Ninguna ruta de trabajador, sindicato ni plataforma
  importa el laboratorio, y el laboratorio no cambia el modelo de ningún
  uso (`db.modelo_ia`). Lo que se elige acá no llega a los afiliados.
- **Cada proveedor con su clave, por variable de entorno.** Sin la
  variable, el modelo se ve en la lista pero no se puede tildar, y la
  pantalla dice qué variable falta. La clave nunca sale al navegador.
- **Cada corrida es un ensayo guardado** (`CasoHerramienta`,
  `herramienta="laboratorio"`), **sin identidad**: nombre, CUIL y legajo se
  borran antes de guardar. Quedan importes, códigos, clasificaciones y los
  números de cada llamada (tokens, tiempo, costo). Estados nuevo / revisado
  / aplicado / descartado; CSV con una fila por modelo y ensayo.
- **Resumen por modelo**: sobre todos los ensayos no descartados, cuántas
  veces se lo probó, cuántas contestó, tiempo mediano, costo promedio y
  coincidencia con la referencia. Es una medida de acuerdo, no de verdad.
- **Las lecturas de Anthropic se registran en Uso de IA** (`/plataforma`)
  como tipo `prueba`, igual que el banco: son gasto real de la misma clave.
  Las de los otros proveedores quedan solo en el ensayo: Uso de IA es el
  consumo de Anthropic y mezclar monedas de facturación distintas lo
  arruinaría.
- **Tapar antes de mandar.** Si el enmascarado está disponible
  (`ENMASCARADO` ≠ `apagado`), la casilla viene tildada: todos los modelos
  reciben la versión con nombre, CUIL, legajo y CUIT cubiertos y la
  identidad se rearma del lado nuestro. Un recibo real que sale hacia un
  proveedor nuevo es justo donde más vale (Ley 25.326).
- **`MOCK_EXTRACTOR=1` se avisa en rojo**: con el mock prendido, las
  lecturas de los modelos de Anthropic devuelven un recibo fijo sin llamar
  a la API; los otros proveedores sí se llaman. Para comparar en serio hay
  que apagar el mock en Render.

## Cómo se habla con cada proveedor

Anthropic va por `extractor.extraer` (la misma llamada de la app, incluido
`effort: low` para los que razonan). Los demás hablan el **formato OpenAI**
(`POST <base_url>/chat/completions`): sistema + usuario con la imagen como
`image_url` en data URL base64 y el esquema como texto, `max_tokens` 8.000,
`temperature` 0, `response_format: json_object` cuando el catálogo lo marca,
y los parámetros propios del proveedor en `extra` (hoy, `reasoning_effort:
low` para Kimi, que razona siempre). Se parsea `message.content` (los
modelos que razonan devuelven el razonamiento aparte, en
`reasoning_content`, y no interesa). Un `finish_reason: length` es
`ErrorLectura` con el uso adentro (se pagó); un status distinto de 200 es
`ErrorProveedor`, sin uso (no se cobró).

Un proveedor nuevo es una entrada en `data/laboratorio_modelos.json`
(`id`, `nombre`, `estilo: openai`, `base_url`, `variable`, `variable_url`
opcional, `leido`, `fuente`, `modelos[]` con `id`, `nombre`, `entrada`,
`salida`, `contexto`, `vision: true`, `json_mode`, `extra`), no código.

## Paso a paso: obtener la clave de cada proveedor (verificado el 2026-10-29)

Antes de nada, una aclaración de nombres: **Kimi K3 y Qwen 3.8 existen**.
Kimi K3 salió en julio de 2026 y ya tiene sucesor, **Kimi K3.1 Pro**
(23-oct-2026), que Moonshot recomienda y es más barato. Qwen 3.8 es la
familia vigente de Alibaba (`qwen3.8-max`, `qwen3.8-flash`, `qwen3.8-27b`);
todos leen imágenes.

### Alibaba Cloud Model Studio (Qwen) — empezar por acá

Es el que tiene **cupo gratis de verdad**: 1.000.000 de tokens POR MODELO,
válidos 90 días, solo en la región Singapur, sin tarjeta para activarlo
según la documentación (no se pudo verificar que no la pida en algún
paso). Con `qwen3.8-flash` ese millón alcanza para varios cientos de recibos
(una foto de 2,6 megapíxeles son unos 2.600 tokens).

1. Crear la cuenta internacional en
   https://account.alibabacloud.com/register/intl_register.htm → tipo
   *Individual* → mail y contraseña → país **Argentina** (no se puede
   cambiar después; fija la moneda en dólares) → verificación por mail o
   SMS.
2. Completar el registro: segundo factor (celular o mail de seguridad).
   Los datos de pago no se exigen para crear la cuenta, pero sí "antes de
   comprar servicios pagos o activar la mayoría de los free trials". La
   entidad que factura a Argentina es Alibaba Cloud (Singapore) y acepta
   Visa, Mastercard, Amex, PayPal, Apple/Google Pay; no prepagas ni
   virtuales. Verificación de identidad con pasaporte: no la pide fuera de
   China.
3. Entrar a https://modelstudio.console.alibabacloud.com/ap-southeast-1
   (región **Singapur**) y aceptar los términos: eso activa Model Studio y
   el cupo gratis. Avisan al llegar al 20 % restante; al agotarse pasa a
   pago por uso salvo que se prenda "Free Quota Only".
4. *API Key* → región Singapur → *Create API Key*. Se muestra una sola vez.
   Cargarla en Render (Pruebas) como `DASHSCOPE_API_KEY`.
5. Opcional pero recomendado: copiar el *Workspace ID* y cargar
   `DASHSCOPE_BASE_URL=https://<WorkspaceId>.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`.
   Sin eso, el laboratorio usa el host legado
   `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, que anda pero
   tiene tope de 16 MiB por pedido (alcanza: el archivo entra hasta 10 MB).

Con imagen, el modo JSON que aplica es `json_object` (la documentación dice
que `json_schema` no acepta entradas multimodales). Límite de uso de una
cuenta nueva: "dinámico" según el gasto del mes para los 3.8; el cupo gratis
no cambia la velocidad.

### Moonshot AI (Kimi)

**No regala nada a cuentas internacionales**: hay que recargar un mínimo de
US$ 1 antes de la primera llamada, y con eso la cuenta queda en el nivel 0
(1 pedido concurrente, 3 pedidos por minuto, 1,5 M de tokens por día; cifras
de terceros, la tabla oficial se dibuja con JS y no se pudo leer). Al
acumular US$ 5 de recarga regalan un voucher de US$ 5; con US$ 10
acumulados sube de nivel. El bono gratis de ¥15 es solo para cuentas con
celular de China continental.

1. Entrar a https://platform.kimi.ai (la plataforma internacional; antes
   platform.moonshot.ai) y registrarse con mail o con Google.
2. Recargar US$ 1 o más. La documentación oficial solo lista Alipay, WeChat
   Pay y transferencia; que acepte tarjeta internacional lo dicen guías de
   terceros, no Moonshot: **hay que mirar la pantalla de recarga**. Si no
   acepta la tarjeta, la alternativa es OpenRouter (abajo).
3. Crear la clave en https://platform.kimi.ai/console/api-keys (se muestra
   una vez). Cargarla en Render (Pruebas) como `MOONSHOT_API_KEY`.
4. La base es `https://api.moonshot.ai/v1` (ya está en el catálogo). Una
   clave de platform.kimi.ai **no** sirve en la plataforma china
   (api.moonshot.cn) ni al revés.

Los modelos del catálogo son `kimi-k3.1-pro` y `kimi-k3`. La serie K2 se
cierra a cuentas nuevas el 2026-10-31 y no se lista. Kimi razona siempre; el
laboratorio le pide `reasoning_effort: low`, como a los Claude que razonan.
Imagen en base64 (no acepta URL remota), formatos JPEG/PNG/WebP/GIF/BMP/HEIC,
cuerpo total del pedido hasta 100 MB.

### Si una tarjeta argentina no entra: OpenRouter

OpenRouter (https://openrouter.ai) revende los dos con la **misma API
OpenAI** y una sola clave, cobra con tarjeta internacional o cripto y
ofrece `moonshotai/kimi-k3` (US$ 3/15, el endpoint oficial de Moonshot),
`moonshotai/kimi-k3.1-pro` (2/10), `qwen/qwen3.8-flash` (0,15/0,47) y
`qwen/qwen3.8-max-0902` (2/6), sin cupo gratis. Si hace falta, se suma como
proveedor en `data/laboratorio_modelos.json` con `base_url
https://openrouter.ai/api/v1` y variable `OPENROUTER_API_KEY`, y los ids
con el prefijo del proveedor; es una entrada en el JSON, no código.

## Comparativa honesta (precios de lista al 2026-10-29, USD por millón de tokens)

| Modelo | Entrada | Salida | Costo aprox. de UN recibo (2.500 tokens de entrada, 1.800 de salida) | Para empezar |
|---|---|---|---|---|
| Claude Sonnet 4.6 (producción hoy) | 3,00 | 15,00 | US$ 0,034 | ya está |
| Claude Haiku 5.5 | 0,10 | 0,50 | US$ 0,0012 | ya está |
| Kimi K3.1 Pro | 2,00 | 10,00 | US$ 0,023 | recargar US$ 1, 3 pedidos/min |
| Kimi K3 | 3,00 | 15,00 | US$ 0,034 | ídem |
| Qwen 3.8 Max | 2,00 | 6,00 | US$ 0,016 | 1 M tokens gratis / 90 días |
| Qwen 3.8 Flash | 0,15 | 0,47 | US$ 0,0012 | 1 M tokens gratis / 90 días |
| Qwen 3.8 27B | 0,50 | 3,00 | US$ 0,0066 | 1 M tokens gratis / 90 días |

Lo que estos números NO dicen, y el laboratorio sí:

- **Si leen bien.** El precio de lista es lo único comparable sin probar.
  Si Qwen 3.8 Flash clasifica mal una línea de aporte en uno de cada diez
  recibos, el ahorro de veinte veces no vale nada: esa clasificación
  alimenta la cuota sindical y el tope del 2 %. Por eso el resumen por
  modelo mide coincidencia con la referencia y la tabla línea por línea
  marca cada diferencia. Treinta recibos distintos es el mínimo para que
  el porcentaje diga algo; con tres, no dice nada.
- **Que Kimi K3 no es más barato que Sonnet 4.6.** Tiene el mismo precio
  de lista; K3.1 Pro es un tercio más barato. Lo que puede justificarlo es
  la calidad, no el costo, y eso hay que medirlo.
- **Los tokens de imagen se cuentan distinto en cada proveedor.** Qwen cobra
  (alto × ancho) / 1.024 + 2 con un tope por defecto de ~2.560 tokens por
  imagen; Moonshot los calcula "dinámicamente" según resolución; Anthropic
  los cuenta a (alto × ancho) / 750. Dos modelos con el mismo precio de
  lista pueden cobrar distinto el mismo recibo. El laboratorio muestra los
  tokens reales que devolvió cada API, que es lo que vale.
- **Tiempo.** Un modelo abierto servido desde Singapur o desde China puede
  tardar bastante más que Claude desde Render (Ohio). El laboratorio mide
  el tiempo pegado a la llamada; con el techo de 180 segundos.
- **Datos personales fuera del país.** Mandar recibos reales a un
  proveedor chino es transferencia internacional de datos sensibles
  (afiliación sindical, Ley 25.326). Para el laboratorio: tapar antes de
  mandar y usar recibos de prueba o del lote sintético. Para producción,
  es una decisión que no se toma por precio.
- **Lo que no se verificó** (y hay que mirar al crear las cuentas): la
  tabla oficial de precios y niveles de Moonshot (JS), si platform.kimi.ai
  acepta tarjeta internacional, si Alibaba exige medio de pago cargado para
  el cupo gratis, y si `json_schema` funciona con imagen en Qwen Singapur
  (los documentos se contradicen; el laboratorio usa `json_object`, que sí
  está documentado con imagen).

## Primer ensayo sugerido

1. Cargar `DASHSCOPE_API_KEY` en Pruebas (y `MOONSHOT_API_KEY` cuando la
   recarga entre). Si Pruebas sigue con `MOCK_EXTRACTOR=1`, apagarlo o
   leer el aviso rojo: los Claude no se estarían comparando.
2. Diez recibos de `docs/recibos-bancaria-prueba/` (sintéticos, sin
   persona real) con Claude Sonnet 4.6 + Qwen 3.8 Flash + Qwen 3.8 Max +
   Kimi K3.1 Pro, tapado tildado.
3. Mirar la tabla línea por línea de cada ensayo, marcar los ensayos como
   revisados y leer el resumen por modelo. Después, recibos reales tapados.

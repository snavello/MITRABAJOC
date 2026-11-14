# PLAN_IMPLEMENTACION.md — Mesa de implementación

Acordado con SDN el 2026-11-14, pregunta por pregunta. Una vez acordado no se
edita: lo que cambie después va a HISTORIAL.md.

## Qué es

Un menú **Implementación** en `/entornos` que reúne lo que se usa para poner
en marcha un sindicato:

1. **Herramientas** de implementación (las que hoy están en la pestaña
   Herramientas y sirven a la puesta en marcha).
2. **Plan**: el plan general (documento de lectura) y el plan operativo
   (etapas e hitos que se siguen desde la pantalla).
3. **Mesa**: una ticketera mínima entre el equipo y el sindicato, con
   tarjetas grandes por color, un flujo único, tablero, carpetas de entrada y
   salida, y el registro de aprobaciones.

El criterio que manda sobre todo lo demás: **que no haya que explicarla**.
Si una opción necesita instrucciones, no entra.

## Decisiones

- **I1. Acceso.** El equipo la ve en `/entornos` → Implementación (con las
  herramientas internas). El sindicato entra por una dirección propia,
  `/implementacion`, y ve solo la mesa, las carpetas y el plan operativo.
- **I2. Usuarios.** El sindicato entra con **usuarios propios** de la
  herramienta, que da de alta el equipo (nombre, mail, clave transitoria que
  se cambia en el primer ingreso). El equipo entra con su usuario nominal de
  plataforma. Cookie propia por rol, en `COOKIES_POR_ROL`.
- **I3. Entorno.** Vive en **Pruebas** (decisión de SDN, contra la
  recomendación de usar la Demo). Consecuencias que el desarrollo tiene que
  cubrir: las tablas `Impl*` se declaran datos reales —`clonar_demo_a_pruebas.py`
  y cualquier recarga las excluyen, con test— y existe una **exportación
  completa** (ZIP con tarjetas, hilo, aprobaciones y archivos) para
  resguardo y para mudarla cuando haya producción.
- **I4. Por proyecto.** Un proyecto por sindicato, con sus etapas, tarjetas,
  carpetas y usuarios. Sin selector mientras haya uno solo. Un usuario del
  sindicato ve únicamente su proyecto; un id ajeno es 404. El proyecto puede
  no tener sindicato de Colm3na asociado (la implementación empieza antes del
  alta).
- **I5. Archivos.** Cualquier documento hasta 20 MB, bytes en la base. Al
  subir se marca si **contiene datos personales**: esos solo los bajan el
  equipo y quien los subió. Toda descarga queda registrada (quién, cuándo).
  Un archivo se puede borrar y queda la constancia de que existió (nombre,
  tamaño, quién lo subió, quién lo borró). Las imágenes NO pasan por
  `imagenes.achicar`: son documentos (excepción declarada en `test_imagenes.py`).
- **I6. Avisos.** **Solo mail** (Resend, `correo.py`), a quien le toca, de
  los dos lados: título y enlace, nunca el contenido ni archivos. Sin
  Telegram. Con el canal apagado, la herramienta funciona igual y el globo en
  pantalla es el único aviso.
- **I7. Etapas.** Las **seis fases** del plan v0.2 de La Bancaria, con 5 a 8
  hitos cada una, redactados de nuevo. Las 66 tareas del artifact viejo se
  revisan una por una: las vigentes entran como hitos o tarjetas iniciales.
  Etapas e hitos se editan desde la pantalla (solo el equipo).
- **I8. Notas internas.** Desde la primera versión. Cada respuesta del equipo
  puede ser «solo equipo»; se filtra **en la consulta**, nunca viaja al
  navegador del sindicato. Test fail-closed sobre toda ruta que devuelva hilo.
- **I9. Plan general.** Un solo «Plan general de implementación», genérico
  para cualquier sindicato, que fusiona «Implementación en el sindicato»
  (2026-09-04) y el Plan Maestro v1.2 y se pone al día. **Ante la duda vale
  el documento más nuevo.** Sin costos ni decisiones empresarias. Los viejos
  quedan en Recursos marcados «reemplazado». El plan v0.2 de La Bancaria
  sigue como plan particular.

## La mesa

**Seis tipos de tarjeta**, cada uno con color e ícono fijos (no toman la
marca de nadie):

| Tipo | Para qué | Cómo cierra |
|---|---|---|
| Pedido | Algo que un lado necesita del otro | Respondida → Cerrada |
| Consulta | Una pregunta | Respondida → Cerrada |
| Entrega de archivo | Subir un archivo pedido o enviar uno | Cerrada al recibirlo |
| Aprobación | Autorización formal | Aprobada / Rechazada, con quién y cuándo; inmutable |
| Error | Algo que no funciona | Respondida → Cerrada |
| Aviso | Informar, sin esperar respuesta | Nace cerrada; registra quién la leyó |

**Un flujo**: Abierta → En curso → Respondida → Cerrada (y Reabrir). Cada
tarjeta dice siempre **a quién le toca**: «espera al sindicato» o «espera a
Colm3na». Responder y cambiar de estado es un solo acto, como en Trámites.

**Cada tarjeta**: número correlativo por proyecto, título, tipo, etapa,
responsable, fecha límite opcional, hilo tipo chat, adjuntos, y opcionalmente
el hito del plan al que pertenece. Crear una pide tres cosas: tipo (se elige
tocando una tarjeta grande), título y texto.

**Vistas**: «Me toca» (por defecto), tablero por estado, avance por etapa,
Carpetas (Entrada = lo que mandó el sindicato, Salida = lo que mandó el
equipo; son vistas de los adjuntos, ordenadas por etapa, no una carga aparte)
y Aprobaciones (el registro, con descarga en CSV).

**Trazabilidad**: toda acción (crear, responder, cambiar estado, reasignar,
subir, bajar, borrar, aprobar) deja un evento con quién y cuándo, que no se
edita ni se borra.

## Bloques

1. **Modelo y motor**: `implementacion.py` (puro: tipos, estados,
   transiciones, a quién le toca), modelos `Impl*` en db.py, migración,
   resguardos de I3.
2. **Acceso**: usuarios propios, login `/implementacion`, primer ingreso,
   cookie por rol, alta de usuarios desde `/entornos`.
3. **Mesa**: rutas y pantallas de tarjetas, hilo, notas internas, archivos,
   aprobaciones, vistas, avisos por mail.
4. **Plan operativo**: etapas e hitos editables, avance, semilla de La
   Bancaria (I7).
5. **Menú Implementación** en `/entornos`: reagrupar herramientas, enlaces al
   plan general y a la mesa.
6. **Plan general** fusionado (I9) y Recursos.
7. **QA**: aislamiento entre proyectos, notas internas, archivos con datos
   personales, robot E2E de un pedido de punta a punta en los dos modelos de
   diseño.

Antes del bloque 3: mockup de las pantallas para que SDN elija.

## Diseño (elegido por SDN sobre el mockup, 2026-11-14)

- **I10. Dirección B, «Sala de mando», con fondo claro.** Barra lateral
  (barra inferior en teléfono), indicadores arriba y tarjetas en cuadrícula
  con la cabecera del color de su tipo; tarjeta abierta con ficha lateral y
  el hilo al lado; el plan como tira de seis segmentos con avance. Todo
  sobre fondo claro, no oscuro. Mockup: `disenos/mesa-implementacion-propuestas.html`
  (fuera de git).
- **I11. La vista por defecto se llama «Mis pendientes»**, no «Me toca».

## Códigos y relaciones (pedido de SDN, 2026-11-14)

Todo lo que se genera tiene un código para poder nombrarlo, adjuntarlo o
referirlo («ver pedido PE0001», «hay errores en el archivo AR000123»).

- **I12. Un contador por tipo, por proyecto.** Tarjetas: `PE` pedido, `CO`
  consulta, `EN` entrega, `AP` aprobación, `ER` error, `AV` aviso, con
  cuatro dígitos (PE0001). Archivos: `AR` con seis (AR000123). El código
  nace con la cosa y no cambia nunca.
- **I13. Relaciones de dos maneras.** (1) Escribir un código en cualquier
  texto lo vuelve enlace y deja anotada la relación en las dos puntas
  («menciona» / «mencionada en»). (2) El botón «Responder con…» de una
  tarjeta abierta crea una tarjeta nueva ya vinculada («responde a» /
  «respondida con»); un archivo subido en esa respuesta queda ligado a la
  original. Cada tarjeta y cada archivo muestra su bloque «Relacionadas».
  Un código de otro proyecto, o de algo que el sindicato no puede ver (nota
  interna), no enlaza ni revela que existe.
- **I14. También hitos y mensajes.** Hitos: `HI0001`. Mensajes: el código de
  su tarjeta más su orden en el hilo (`PE0004-3`), que enlaza directo a ese
  mensaje. Las etapas se nombran por su nombre. Un buscador único: se
  escribe un código y lleva a la cosa.

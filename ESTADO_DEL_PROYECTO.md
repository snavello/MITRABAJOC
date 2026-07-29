# Mi Trabajo — Estado del proyecto

Documento para retomar el trabajo sin perder contexto. Si abrís un chat nuevo,
subí este archivo junto con `validador-demo.zip` y pediá continuar desde donde
dice "Próximo paso".

_Última actualización: durante el desarrollo de la versión nueva (lista de 12 puntos), con el Bloque 1 terminado._

---

## 1. Qué es Mi Trabajo

Aplicación web para que trabajadores sindicalizados argentinos verifiquen si su
recibo de sueldo tiene bien calculados los aportes (jubilación, obra social,
cuota sindical, etc.) según el convenio de su sindicato. El trabajador saca una
foto del recibo o sube el PDF, una IA lo lee, y el sistema valida los aportes
contra las fórmulas del convenio.

Evolucionó de una app para un solo sindicato (AEFIP como caso de prueba) a una
**plataforma multi-sindicato**: la misma app puede servir a varios sindicatos a
la vez, cada uno con su marca, sus conceptos y sus trabajadores, en aislamiento
total. El objetivo comercial es mostrarla a sindicatos y a un potencial inversor
como algo escalable, no como una app suelta.

---

## 2. Arquitectura y stack (decisiones tomadas)

- **Backend:** FastAPI (Python) + Jinja2 para las plantillas.
- **Base de datos:** SQLite mediante SQLModel. Archivo único, sin servidor de
  base aparte. En Render vive en un disco persistente (`/var/data/validador.db`
  vía la variable `DB_PATH`).
- **IA:** API de Anthropic (modelo `claude-sonnet-4-6`) para leer recibos y
  comprobantes de aportes. Se necesita `ANTHROPIC_API_KEY`.
- **Autenticación:** claves hasheadas con PBKDF2 (nunca texto plano). Sesiones
  como cookies firmadas con HMAC. Módulo `auth.py`. Variables `PLATAFORMA_PASSWORD`
  `SESSION_SECRET` y `PLATAFORMA_CUIT` (CUIT del admin de plataforma).
- **Python 3.12 fijado** con el archivo `.python-version` (Python 3.14 rompe
  SQLModel con el error "Field 'id' requires a type annotation").
- **Despliegue:** GitHub + Render (plan gratuito). Ya está desplegado y funcionando.

### Archivos del proyecto (dentro de validador-demo.zip)
- `main.py` — servidor y todas las rutas.
- `db.py` — modelos SQLModel y acceso a datos.
- `auth.py` — hash de claves y sesiones.
- `extractor.py` — lee recibos y comprobantes de aportes con IA.
- `validador.py` — motor de validación de fórmulas.
- `semaforo.py` — lógica del semáforo de aportes.
- `cargar_demo.py` — carga 2 sindicatos de demostración.
- `chequeo.py` — autodiagnóstico de la instalación.
- `templates/` — 7 plantillas HTML (trabajador, admin, plataforma, sus logins, selector).
- `static/` — logos.
- `data/seed_aefip.json` — semilla inicial de conceptos y fórmulas de AEFIP.

---

## 3. Los tres roles (modelo de usuarios)

1. **Admin de plataforma** — entra en `/plataforma` con clave fija
   (`PLATAFORMA_PASSWORD`). Da de alta sindicatos con sus datos y colores de
   marca, y crea los administradores de cada sindicato.
2. **Admin de sindicato** — entra en `/admin` con usuario + clave. Gestiona
   conceptos, fórmulas, trabajadores y reportes **solo de su sindicato**
   (aislamiento total, verificado).
3. **Trabajador** — entra en `/ingresar`. Se registra validando que su CUIL
   está en la lista de su sindicato y elige una clave. **Identidad única:** un
   CUIL + una clave para toda la plataforma. **Empadronamiento por sindicato:**
   el mismo CUIL puede estar en varios sindicatos; al entrar, si está en uno solo
   va directo, si está en varios elige cuál. La app se pinta con la marca del
   sindicato elegido.

### Accesos de la demo (los crea cargar_demo.py)
- Plataforma: clave de `PLATAFORMA_PASSWORD` (default `plataforma-demo-2026`).
- Admin UOM: `admin@uom.org` / `uom-demo`.
- Admin Gastronómica: `admin@fega.org` / `fega-demo`.
- Trabajador pluriempleo (en ambos sindicatos): CUIL `27222222224`.
- Trabajador de un solo sindicato: CUIL `20111111119` (UOM).

---

## 4. Decisiones importantes ya tomadas (para no rediscutir)

- **Aislamiento entre sindicatos: total.** Cada uno ve solo lo suyo. La idea de
  un padrón de CUIL común quedó como futura, no se implementa ahora.
- **Marca por sindicato:** formato único para todos; el color cambia solo en
  puntos predeterminados. Color **primario** (obligatorio) = encabezado y pie.
  Color **secundario** (opcional) = fondo de botones. Color **acento** (opcional)
  = reservado, sin uso visible aún. Si falta uno opcional, cae a un valor por
  defecto. **El semáforo NUNCA toma la marca**: usa sus colores fijos de estado
  (verde=pagado, amarillo=parcial, rojo=impago), porque tienen significado propio.
- **Semáforo de aportes (ARCA):** la consulta pública de ARCA (sin clave fiscal)
  existe, se ingresa con CUIL/DNI + captcha "no soy un robot". Se decidió NO
  automatizar el captcha (frágil y zona gris legal). El flujo elegido: el
  trabajador va a ARCA con un botón, resuelve el captcha él mismo, y sube la
  captura/PDF del resultado, que la IA lee para armar el semáforo. El prellenado
  del CUIL al abrir ARCA se descartó (la página usa POST, no acepta CUIL por URL).
  ARCA cubre jubilación y obra social, NO ART (eso solo con clave fiscal).
  El parser de la tabla de ARCA está hecho y probado; reconoce los estados
  pagado/parcial/impago/no_presentada/no_declarado.
- **Claves:** siempre hasheadas. Nunca texto plano.
- **Alcance de la demo:** 2 sindicatos con marca distinta + los 3 logins
  funcionando, para mostrar a un inversor "misma plataforma, distinta identidad".

---

## 5. La lista de 12 puntos de la versión nueva (EN CURSO)

Estado de cada punto:

1. **Colores de marca en app trabajador Y sindicato.** ✅ HECHO (Bloque 1).
   El header del panel del sindicato ahora toma el color primario; se corrigió
   el contraste del texto (blanco sobre color).
2. **Pestañas navegables** en las 3 apps. ✅ HECHO (Bloque 2). Sindicato: 5 pestañas con Reportes por defecto. Trabajador: barra inferior con 4 pestañas. Plataforma: 3 pestañas (Sindicatos, Nuevo sindicato, Nuevo administrador).
   por defecto en sindicato. Aplica a las 3 apps. ⏳ PENDIENTE (próximo bloque).
3. **ABM completo de trabajadores.** ✅ HECHO (Bloque 3). Alta manual con todos los datos (cuil, nombre, calle/número/piso, ciudad, provincia [lista 23+CABA], teléfono, mail; obligatorios cuil y nombre), alta masiva pegando datos separados por coma, modificación, consulta y baja lógica (recuperable). Con sub-pestañas Listado/Alta manual/Alta masiva.
4. **CUIL y nombre visibles en la app del trabajador.** ✅ HECHO (Bloque 5). Barra de identidad bajo el header con nombre, CUIL y salir.
5. **Bug: empleado de AEFIP veía chequeos de cuotas de UOM/Gastronómico.** ✅
   HECHO (Bloque 1). La validación ahora usa solo fórmulas/conceptos del sindicato
   del trabajador. Se reforzó el caso límite: si no se determina el sindicato,
   avisa con error en vez de validar en falso.
6. **Ver los datos del reporte en el panel.** ✅ HECHO (Bloque 5). Cada reporte tiene botón "Ver" que despliega el detalle (JSON legible).
7. **Cuadro de carga de Aprendizaje.** ✅ HECHO (Bloque 5). Se corrigió el desborde (display block, width 100%) y se aclaró subir de 3 a 10 recibos.
8. **4 pestañas del trabajador** (Tu Recibo, Novedades, Mis Aportes, Capacitación). ✅ HECHO (Bloque 2). Estructura creada: Tu Recibo (flujo del recibo) y Mis Aportes (semáforo) funcionan; Novedades y Capacitación muestran "próximamente".
9. **Logo del sindicato en PNG.** ✅ HECHO (Bloque 6). El alta y la edición aceptan logo (PNG/JPG/WebP/SVG), se guarda en static/logos/ y se muestra en la tabla de plataforma y en el header de la app del trabajador.
10. **Todos los usuarios se identifican con CUIT/CUIL.** ✅ HECHO (Bloque 4). Plataforma: login con CUIT + clave (variable nueva PLATAFORMA_CUIT, default 20000000000). Admin de sindicato: entra con CUIT/CUIL en vez de mail. Trabajador: ya era CUIL. Todos normalizan el número (con o sin guiones). Los admins de demo ahora son CUIT 20111111110 (UOM) y 20222222220 (Gastronómica).
11. **Editar y borrar sindicatos.** ✅ HECHO (Bloque 6). Editar rellena el formulario; borrar elimina en cascada (admins, trabajadores, conceptos, fórmulas, reportes) con aviso de datos huérfanos y confirmación.
12. **Ver admins al clickear el número.** ✅ HECHO (Bloque 6). El número de admins es un enlace que despliega la lista (CUIT y nombre de cada admin).

---

## 6. Cómo trabajamos (método)

- Se construye **por bloques**, probando cada uno antes de avanzar.
- Se verifica la lógica de verdad (no simulada): se prueban las rutas y funciones.
- Las maquetas se entregan como **archivos HTML abribles** o capturas, porque en
  el entorno de trabajo las imágenes generadas a veces llegan en blanco al chat.
- Nota del entorno: el servidor web de prueba a veces se reinicia solo (limitación
  del entorno de desarrollo, no del código); cuando pasa, se verifica la lógica
  directamente en Python. En Render funciona normal.

---

## 7. Próximo paso

HECHO hasta Bloque 3. Puntos completados: 1, 2, 3, 5, 8.

Siguiente: **identidad CUIT/CUIL para todos los usuarios** (punto 10), y luego 4, 6, 7, 9, 11, 12.

_(Referencia histórica del Bloque 2:_
convertir las "sábanas" de las tres apps en pestañas donde se ve una sección a
la vez. En el sindicato, Reportes por defecto. En el trabajador, crear la
estructura de 4 pestañas (Tu Recibo default; Novedades y Capacitación como
"próximamente"; Mis Aportes con el semáforo).

Después seguirían: ABM de trabajadores (punto 3), identidad CUIT/CUIL (punto 10),
y el resto de mejoras (4, 6, 7, 9, 11, 12).

### Para retomar en un chat nuevo
Subí `validador-demo.zip` (tiene el Bloque 1 incorporado) y este documento, y
decí: "Seguimos con Mi Trabajo, Bloque 2 (pestañas), según el ESTADO_DEL_PROYECTO".

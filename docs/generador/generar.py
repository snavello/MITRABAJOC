"""Arma recursos/documentacion-tecnica.html a partir de datos.json
(extraer.py), contenido.py (textos) y diagramas.py (SVG). Regenerar desde la
raíz del repo:

    python docs/generador/extraer.py && python docs/generador/generar.py

La fecha de la edición y el commit se toman solos (hoy y `git rev-parse`).
Si cambió la portada, rehacer la miniatura en recursos/ (ver HISTORIAL.md,
"Documentación técnica generada")."""
import json
import subprocess
from collections import defaultdict
from datetime import date
from html import escape as e
from pathlib import Path

import contenido as C
import diagramas as D

AQUI = Path(__file__).parent
datos = json.loads((AQUI / "datos.json").read_text(encoding="utf-8"))
TABLAS, MIGS, RUTAS = datos["tablas"], datos["migraciones"], datos["rutas"]
POR_TABLA = {t["tabla"]: t for t in TABLAS}
N_COL = sum(len(t["columnas"]) for t in TABLAS)
N_BYTES = sum(1 for t in TABLAS for c in t["columnas"] if c["bytes"])
N_JSON = sum(1 for t in TABLAS for c in t["columnas"] if c["json"])
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_de_hoy() -> str:
    d = date.today()
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _commit_actual() -> str:
    """Hash corto del commit desde el que se genera; "local" si no hay git."""
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=AQUI, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "local"


FECHA_DOC = _fecha_de_hoy()
COMMIT = _commit_actual()


# ---------- helpers de HTML ----------
def tabla(cabeceras, filas, cls=""):
    th = "".join(f"<th>{c}</th>" for c in cabeceras)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in f) + "</tr>" for f in filas)
    return f'<div class="tabla-scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def figura(svg, caption):
    return f'<figure>{svg}<figcaption>{caption}</figcaption></figure>'


def cod(s):
    return f"<code>{e(s)}</code>"


def chip(texto, cls="b-todos"):
    return f'<span class="badge {cls}">{e(texto)}</span>'


# ---------- 1. FUNCIONALIDADES ----------
def vista_funcionalidades():
    roles = [
        ("Trabajador", "/ingresar → /app/inicio → /app", "CUIL + clave. Una identidad para todos los sindicatos donde está empadronado; si tiene varios, elige y la app se pinta con esa marca.", "b-colm3na", [
            ("Tu Recibo", "Sube foto o PDF, la IA lo lee, se valida contra las fórmulas del convenio vigentes en ese período. Puede reportarlo o enviarlo consentido como prueba de afiliado cotizante. Historial propio."),
            ("Credencial", "Carnet digital con filigrana, foto, código y firma de la autoridad; el QR lleva un código que vence a los diez minutos y se renueva solo."),
            ("Novedades", "Noticias del sindicato en hilo cronológico, con detalle en modal."),
            ("Mis Aportes", "Semáforo ARCA: el trabajador resuelve el captcha él mismo, sube la captura y la IA la lee. Verde, amarillo o rojo por mes; el resultado queda guardado."),
            ("Capacitación", "Guía fija de plataforma sobre el recibo nuevo (Ley 27.802, Decreto 407/2026). Contenido por sindicato: pendiente."),
            ("Trámites", "Formularios dinámicos del sindicato con validaciones en vivo, expediente numerado, cinco estados y chat con adjuntos."),
            ("Fuera de la barra", "Bandeja de notificaciones, consultas al convenio (piloto, sin entrada en el menú), perfil con foto, PWA instalable con Web Push."),
        ]),
        ("Sindicato", "/admin → /admin/inicio → /admin", "CUIT + clave de un administrador. Ve y administra solo lo de su sindicato; el tenant sale de la cookie, nunca de un parámetro.", "b-sindicato", [
            ("Panel Sindical", "Diez KPIs, ocho paneles con filtrado cruzado, explorador paginado con detalle anonimizado y el Asistente que traduce una pregunta a filtros. Módulo opt-in."),
            ("Reportes · Afiliados cotizantes", "Recibos reportados y envíos voluntarios de los trabajadores."),
            ("Fórmulas · Conceptos · Aprendizaje", "El catálogo del convenio: reglas con vigencia y tolerancia (la expresión se prueba antes de guardar), conceptos con alias, fusión de provisorios, conceptos universales, y aprendizaje en lote desde recibos."),
            ("Trabajadores · Seccionales · Administradores", "Padrón con alta manual y masiva, credenciales, bajas lógicas; sedes; y los propios administradores en autoservicio."),
            ("Noticias · Beneficios · Notificaciones", "Contenido con vigencia, imágenes y destino por seccional; notificaciones dirigidas por CUIL, empresa, seccional o provincia con vista previa de cuántos las reciben."),
            ("Trámites", "Bandeja con chat y cambio de estado; constructor de formularios con validaciones (bloquea o avisa) y banco de pruebas que corre el mismo motor que el envío real."),
            ("Empleadores · Convenio", "Empresas, notificaciones y trámites hacia empresas; carga de convenios y actas en PDF con estado de indexación y vista previa de fragmentos."),
        ]),
        ("Plataforma", "/plataforma → /plataforma/inicio → /plataforma", "CUIT + clave fija de entorno; no hay usuario en la base. Es el único rol que ve todos los sindicatos.", "b-legal", [
            ("Sindicatos", "Alta y edición con marca completa (el color base se valida como oscuro), logo, firma, autoridad y los módulos habilitados. Borrado destructivo."),
            ("Marca · Config. legal · Topes SS", "Logos claro y oscuro de Colm3na, tope de cuota sindical del 2 % y las vigencias de topes de base imponible con su estado de verificación."),
            ("Uso de IA · Con alerta", "Consumo real de la API por sindicato y modelo; recibos que la IA marcó con señales de adulteración, con el archivo original."),
            ("Panel Sindical", "Umbrales del semáforo por empresa y el flag del carril de consultas al bot."),
            ("Cambiar clave", "Transitorio, marcado para retirar antes de producción real: cambia la clave de cualquier usuario."),
        ]),
        ("Empresa", "/ingresar-empresa → /empresa/inicio → /empresa", "CUIT + clave con autorregistro; el CUIT tiene que estar de alta en algún sindicato con el módulo Empleadores. Sin versión propia.", "b-sistemas", [
            ("Notificaciones", "Mensajes del sindicato a la empresa, con adjuntos y lectura. Sistema separado del de trabajadores a propósito."),
            ("Trámites", "Formularios externos, envío con las mismas validaciones, seguimiento por expediente y chat con el sindicato."),
        ]),
    ]
    tarjetas = ""
    for nombre, ruta, intro, cls, pestanas in roles:
        filas = "".join(f'<div class="item"><div class="chk"></div><div><div class="it-h"><span class="t">{e(t)}</span></div><div class="fun">{e(d)}</div></div></div>' for t, d in pestanas)
        tarjetas += f'''<section class="bloque" id="f-{nombre.lower()}">
<div class="bh"><div><span class="badge {cls}">{e(nombre)}</span><h2 style="margin-top:6px">{e(nombre)}</h2><div class="sub">{e(ruta)}</div><p>{e(intro)}</p></div></div>
{filas}</section>'''
    modulos = [
        ("recibos", "Tu recibo", "Verificación de recibos; en admin, Reportes, Fórmulas, Conceptos, Aprendizaje y Afiliados cotizantes.", "inicial"),
        ("aportes", "Mis aportes", "Semáforo ARCA.", "inicial"), ("credencial", "Credencial", "Credencial digital con QR efímero y verificación pública.", "inicial"),
        ("capacitacion", "Capacitación", "Pestaña de contenido formativo.", "inicial"), ("noticias", "Noticias", "Novedades y su ABM.", "inicial"),
        ("beneficios", "Beneficios", "Carrusel de beneficios y su ABM.", "inicial"),
        ("notificaciones", "Notificaciones", "Mensajes dirigidos sindicato → trabajador.", "opt-in"),
        ("tramites", "Trámites", "Formularios dinámicos, expedientes, estados y chat.", "opt-in"),
        ("empleadores", "Empleadores", "El cuarto actor completo: empresas, su login, notificaciones y trámites externos.", "opt-in"),
        ("convenio", "Consultas sobre el convenio", "Piloto RAG: carga de PDFs y consultas del trabajador.", "opt-in"),
        ("dashboard", "Panel Sindical", "KPIs, gráficos, explorador y Asistente.", "opt-in"),
    ]
    t_mod = tabla(["Clave", "Nombre", "Qué habilita", "Al dar de alta"],
                  [(cod(k), e(n), e(q), chip(a, "b-funcional" if a == "inicial" else "b-todos")) for k, n, q, a in modulos])
    return f'''
<div class="doc">
<h2 id="f-que">1. Qué es</h2>
<p>Mi Trabajo es una aplicación web para que trabajadores sindicalizados argentinos verifiquen si su recibo de sueldo tiene bien calculados los aportes según el convenio de su sindicato. El trabajador sube una foto o un PDF, una IA lo transcribe y el sistema compara cada aporte contra las fórmulas del convenio. Es una <b>plataforma multi-sindicato</b>: la misma app sirve a varios gremios, cada uno con su marca, su catálogo y sus trabajadores, en aislamiento total.</p>
<p>Alrededor de esa función central crecieron cuatro aplicaciones con login propio, un panel de gestión para el sindicato, un panel de plataforma, un actor más (la empresa) y dos pilotos con IA: consultas al convenio y un asistente del Panel Sindical.</p>
<div class="nota"><b>Regla de oro:</b> el modelo lee, el código juzga y el sindicato es dueño de las reglas. Nada de lo que devuelve la IA se evalúa crudo: todo importe pasa por <code>a_numero()</code>, una línea ilegible queda afuera con alerta, y una fórmula que no evalúa saltea su chequeo sin tumbar el recibo.</div>

<h2 id="f-roles">2. Los cuatro roles</h2>
<p>Cada rol tiene su puerta, su credencial y su propia cookie de sesión firmada. Un mismo navegador puede tener las cuatro sesiones vivas a la vez sin que se pisen. Todas vencen a los quince minutos sin uso y se renuevan en cada request.</p>
{figura(D.roles_puertas(), "Las cuatro puertas. La sesión de plataforma se valida contra variables de entorno, no contra una tabla.")}
{tarjetas}

<h2 id="f-modulos">3. Módulos por sindicato</h2>
<p>El admin de plataforma tilda, por sindicato, qué módulos tiene activos. Eso decide qué tarjetas ve el trabajador y qué pestañas ve el admin, y el backend lo hace cumplir con 403: no alcanza con esconder el botón. Trabajadores y Seccionales quedan siempre visibles.</p>
{t_mod}

<h2 id="f-transversal">4. Transversal</h2>
<ul>
<li><b>PWA instalable con Web Push.</b> Manifest, service worker que no cachea nada a propósito, banner de instalación discreto y avisos de novedades de trámites; sin claves VAPID el canal queda apagado en silencio.</li>
<li><b>Credencial con QR efímero.</b> Token permanente más un código firmado que vence a los diez minutos; una captura de pantalla deja de verificar apenas pasa la ventana. La página pública nunca muestra el DNI.</li>
<li><b>Alerta de adulteración.</b> Al leer el recibo, la IA marca con alta certeza señales de edición en totales, CUIL, CUIT o fechas. No bloquea al trabajador; el archivo queda para plataforma.</li>
<li><b>Uso de IA medido.</b> Cada llamada al modelo registra tipo, modelo y tokens reales por sindicato.</li>
<li><b>Landing de entornos.</b> En local y Pruebas existe <code>/entornos</code>: los ocho accesos con la versión que corre en cada uno y el catálogo de Recursos (documentación con miniatura y fecha, subida desde la misma página). Toda la landing está detrás de un PIN de ocho dígitos que deja un pase de treinta días. En la demo responde 404.</li>
<li><b>Distintivo de entorno.</b> «PRUEBAS · v0.29.01» abajo a la izquierda solo en local y Pruebas; en la demo, nada.</li>
</ul>

<h2 id="f-pendientes">5. Lo que la doc anterior ya no cuenta y lo que sigue pendiente</h2>
<ul>
<li>Desde la versión 0.03 de agosto se sumaron: el cuarto rol (Empresa), notificaciones y trámites de los dos lados, empleadores, el Panel Sindical con Asistente, el RAG del convenio, Web Push, la credencial con QR efímero, seccionales, módulos por sindicato, los dos entornos con Alembic en el deploy y la landing con Recursos.</li>
<li>Capacitación tiene solo la guía fija de plataforma («Entendé tu nuevo recibo de sueldo», ley nacional); el contenido propio por sindicato sigue pendiente.</li>
<li>«Cambiar clave» en plataforma es transitorio y hay que retirarlo antes de producción real.</li>
<li>Pendientes de diseño: módulos STD y PRO del Panel Sindical (el explorador ya pasa por una guarda separada para ese momento), índice HNSW en pgvector cuando el volumen lo justifique, y la retención de datos identificatorios.</li>
</ul>
</div>'''


# ---------- 2. ARQUITECTURA ----------
def vista_arquitectura():
    stack = [
        ("Backend", "FastAPI 0.115.5 + Uvicorn 0.32.1", "Un solo módulo de rutas, sin routers separados. Python 3.12.8 fijado: 3.14 rompe SQLModel."),
        ("Vistas", "Jinja2 3.1.4", "21 plantillas server-rendered; el JS de cada pantalla vive embebido en su HTML, sin build."),
        ("ORM y datos", "SQLModel 0.0.22 · psycopg 3.2.3 · pgvector 0.4.2", "41 tablas. Postgres 16 en Render; SQLite solo como fallback sin Docker y en los tests."),
        ("Migraciones", "Alembic 1.19.0", "49 revisiones en cadena lineal. Corren en el Pre-Deploy de Render; en Postgres nunca create_all."),
        ("IA", "anthropic ≥ 0.69", "Tres modelos: Sonnet 4.6 lee recibos y hace OCR, Opus 5 responde sobre el convenio, Sonnet 5 traduce preguntas a filtros."),
        ("Embeddings", "fastembed 0.8.0 (pinneado exacto)", "multilingual-e5-large, 1024 dimensiones, locales en ONNX. La versión de la librería es parte de la identidad del vector."),
        ("PDF", "pdf2image 1.17.0 · pypdf 6.16.1", "PDF a PNG para la IA; texto nativo del convenio con pypdf."),
        ("Push y QR", "pywebpush 2.5.0 · segno 1.6.6", "Web Push a la PWA; QR en SVG sin Pillow."),
        ("Autenticación", "propia, sin terceros", "PBKDF2-HMAC-SHA256 con 100.000 iteraciones; cookies firmadas HMAC-SHA256, sin store de sesiones."),
        ("Deploy", "GitHub + Render, dos servicios", "Pruebas sigue main; Demo sigue demo y solo cambia con promover_demo.py."),
        ("Desarrollo", "Docker (pgvector/pgvector:pg16) · Playwright 1.62", "Postgres local con paridad; robots E2E aparte de la suite unitaria."),
    ]
    cookies = [
        ("trabajador", "sesion_trabajador", "cuil_trab · sind_elegido", "CuentaTrabajador.clave_hash"),
        ("sindicato", "sesion_sindicato", "—", "UsuarioSindicato (usuario = CUIT)"),
        ("plataforma", "sesion_plataforma", "—", "PLATAFORMA_CUIT + PLATAFORMA_PASSWORD, en tiempo constante"),
        ("empleador", "sesion_empleador", "cuit_emp · sind_elegido_emp", "CuentaEmpleador.clave_hash"),
    ]
    modelos = [
        ("claude-sonnet-4-6", "extractor.py · rag.py (OCR)", "Lee recibos y comprobantes de ARCA; transcribe páginas escaneadas del convenio. Salida estructurada, sin cálculo."),
        ("claude-opus-5", "rag.py", "Responde sobre el convenio con los ocho fragmentos recuperados; el control de «no lo encontré» es el prompt, no un umbral."),
        ("claude-sonnet-5", "asistente.py", "Traduce la pregunta del admin a los filtros del panel con una herramienta; effort low, hasta tres vueltas."),
    ]
    variables = [
        ("DATABASE_URL", "Postgres interno de Render; si falta, SQLite."), ("ENTORNO", "local, pruebas, demo o prod: distintivo y existencia de /entornos."),
        ("PIN_ENTORNOS", "PIN de ocho dígitos de la landing."), ("ANTHROPIC_API_KEY", "Una por entorno, con tope de gasto."),
        ("PLATAFORMA_CUIT · PLATAFORMA_PASSWORD", "El login de plataforma."), ("SESSION_SECRET", "Firma cookies y pases; cambiarlo desloguea a todos."),
        ("VAPID_PRIVATE_KEY · VAPID_PUBLIC_KEY · VAPID_CLAIM_EMAIL", "Web Push; sin las tres, apagado."), ("PYTHON_VERSION", "3.12.8, redundante a propósito."),
        ("DEMO_DATABASE_URL · PRUEBAS_DATABASE_URL", "Solo en la PC de quien promueve o clona."),
    ]
    decisiones = [
        ("Bytes en la base, nunca disco", f"No hay disco persistente en Render. {N_BYTES} columnas de bytes: logos, firmas, fotos, imágenes, adjuntos, PDFs del convenio y recursos, cada una con su MIME y servida por una ruta propia con sello de versión."),
        ("Todo lo de /static/ lleva sello", "Cache de una hora más ?v= con mtime y tamaño del archivo. Sin sello, quien ya visitó la app ve el HTML nuevo con el CSS viejo; pasó el 3 de septiembre con marca.css."),
        ("El tenant sale de la cookie", "Ninguna ruta acepta sindicato_id por parámetro. En el Panel y en el RAG el aislamiento vive en el WHERE de cada consulta."),
        ("Aislamiento total entre trabajador y empresa", "Notificaciones y trámites se duplican en tablas y rutas separadas en vez de compartirlas. Más código, cero mezcla de identidades."),
        ("El semáforo nunca toma la marca", "Colores fijos de estado; lo mismo para ok, error y aviso."),
        ("El captcha de ARCA no se automatiza", "Frágil y zona gris legal: el trabajador lo resuelve y sube la captura."),
        ("Cada error tiene código", "Catálogo en errores.py; solo los de lectura pueden decir «probá con otra foto», y hay un test que lo verifica."),
        ("Una sola implementación de las validaciones de trámites", "evaluar_envio() la usan el envío real, el banco de pruebas del constructor y el espejo en JS del trabajador."),
        ("El service worker no cachea", "Con deploy en cada push, cachear dejaría al trabajador pegado a una versión vieja."),
        ("Chart.js vendoreado y Playwright solo en desarrollo", "Nada del frontend depende de un CDN; requirements.txt no instala lo que Render no necesita."),
    ]
    return f'''
<div class="doc">
<h2 id="a-stack">1. Stack</h2>
{tabla(["Capa", "Tecnología", "Nota"], [(e(a), e(b), e(c)) for a, b, c in stack])}

<h2 id="a-vista">2. Vista general</h2>
<p>Aplicación server-rendered clásica: un proceso FastAPI arma el HTML con Jinja2 y lo devuelve; la interactividad es JavaScript vanilla embebido en cada plantilla. La IA es un servicio externo que entra y sale por tres módulos; nunca se la llama desde <code>main.py</code>.</p>
{figura(D.vista_general(), "Un proceso concentra rutas, render y reglas. Los módulos de lógica no dependen de FastAPI ni entre sí, por eso se testean aislados.")}

<h2 id="a-recibo">3. Flujo de punta a punta: leer y validar un recibo</h2>
{figura(D.flujo_recibo(), "La lectura y la validación son dos llamadas separadas: entre una y otra el trabajador confirma lo leído y el sistema propone los conceptos que el sindicato todavía no tiene.")}
<p>Detalles que definen el comportamiento:</p>
<ul>
<li>Si el CUIL leído no es el de la sesión, la validación se corta ahí: no se cargan conceptos, no queda historial.</li>
<li>Los conceptos nuevos entran como «por revisar», tagueados con el CUIT del empleador; si son un aporte de ley se vinculan al genérico por <code>codigo_generico</code>, para que una sola fórmula controle a todos los empleadores.</li>
<li>Se usa la fórmula vigente en el período del recibo, no la actual; si ninguna regía, ese concepto no se chequea.</li>
<li>Los topes de base imponible se aplican por período y nunca se usa el más cercano: sin tope para ese mes, se evalúa sin topear y se avisa una sola vez.</li>
<li>Cada verificación se guarda, esté en orden o no, con columnas analíticas que el Panel Sindical agrega con índices.</li>
</ul>

<h2 id="a-auth">4. Autenticación y sesión</h2>
{tabla(["Rol", "Cookie de sesión", "Cookies de identidad", "Se valida contra"], [(e(a), cod(b), e(c), e(d)) for a, b, c, d in cookies])}
<p>Un 401 o 403 en una navegación de página redirige al login correcto en vez de mostrar el JSON de FastAPI; un 403 con sesión válida del rol correcto (módulo apagado, CUIL ajeno) sigue devolviendo JSON. Cualquier excepción imprevista devuelve un código del catálogo más una referencia de ocho caracteres rastreable en el log.</p>

<h2 id="a-multi">5. Multi-sindicato</h2>
{figura(D.multi_sindicato(), "Identidad global y empadronamiento por sindicato se unen por valor (el CUIL o el CUIT como texto), no por clave foránea: una persona existe como cuenta antes de estar empadronada y puede estar en tres gremios sin duplicar identidad.")}

<h2 id="a-ia">6. La IA: tres modelos, tres trabajos</h2>
{tabla(["Modelo", "Dónde", "Para qué"], [(cod(a), e(b), e(c)) for a, b, c in modelos])}
<p>Toda llamada registra sus tokens reales en <code>usoia</code>. El cliente se inyecta en el Asistente para probar el circuito completo sin gastar créditos.</p>

<h2 id="a-rag">7. Consultas al convenio (RAG)</h2>
{figura(D.rag_pipeline(), "La indexación corre en un hilo aparte (unos nueve minutos por convenio) y ninguna sobrevive a un reinicio: al arrancar, lo que quedó «procesando» se marca como error. La búsqueda filtra por sindicato y convenio en el WHERE: un fragmento ajeno no puede llegar al modelo.")}
<p>Los embeddings se generan en lotes de ocho (246 fragmentos de una vez piden un gigabyte); e5 es asimétrico, así que los documentos usan <code>passage_embed</code> y la pregunta <code>query_embed</code>. Al trabajador se le muestran solo las fuentes citadas, no los ocho fragmentos, y la respuesta sale con un disclaimer fijo.</p>

<h2 id="a-asistente">8. Asistente del Panel Sindical</h2>
{figura(D.asistente_panel(), "El modelo nunca genera SQL ni ve filas: devuelve siempre el estado completo de filtros, que se valida con el mismo parser que usa el frontend, y el resumen se escribe sobre los agregados reales. Tope de 300 consultas por sindicato por día.")}

<h2 id="a-entornos">9. Entornos y despliegue</h2>
{figura(D.entornos_deploy(), "Dos servicios de Render con su propia base. El Pre-Deploy corre las migraciones antes de recibir tráfico: si una falla, el deploy se cancela y sigue la versión anterior.")}
{tabla(["Variable", "Para qué"], [(cod(a), e(b)) for a, b in variables])}

<h2 id="a-decisiones">10. Decisiones vigentes</h2>
{"".join(f'<div class="dec"><div><h4>{e(t)}</h4><div class="cuerpo">{e(d)}</div></div></div>' for t, d in decisiones)}
</div>'''


# ---------- 3. COMPONENTES ----------
def vista_componentes():
    mods = tabla(["Módulo", "Tamaño", "Responsabilidad"], [(cod(a), e(b), e(c)) for a, b, c in C.MODULOS])
    scripts = tabla(["Script", "Qué hace"], [(cod(a), e(b)) for a, b in C.SCRIPTS])
    tpl = ""
    for grupo, filas in C.TEMPLATES:
        tpl += f"<h3>{e(grupo)}</h3>" + tabla(["Plantilla", "Ruta", "Para qué"], [(cod(a), cod(b), e(c)) for a, b, c in filas])
    static = tabla(["Archivo", "Qué es"], [(cod(a), e(b)) for a, b in C.STATIC])
    docs = tabla(["Documento", "Qué contiene"], [(cod(a), e(b)) for a, b in C.DOCS])
    # rutas agrupadas
    por_grupo = defaultdict(list)
    sin_ficha = []
    for r in RUTAS:
        ficha = C.RUTAS.get((r["metodo"], r["path"]))
        if not ficha:
            sin_ficha.append(r)
            continue
        por_grupo[ficha[0]].append((r, ficha))
    rutas_html = ""
    for clave, nombre in C.GRUPOS:
        items = por_grupo.get(clave, [])
        if not items:
            continue
        filas = [(chip(r["metodo"], "b-funcional" if r["metodo"] == "GET" else "b-dev"), cod(r["path"]), e(f[1]), e(f[2])) for r, f in items]
        rutas_html += f'<details class="grupo"><summary>{e(nombre)} <small>{len(items)}</small></summary>{tabla(["", "Ruta", "Rol", "Qué hace"], filas)}</details>'
    if sin_ficha:
        filas = [(chip(r["metodo"]), cod(r["path"]), "", e(r["doc"][:120])) for r in sin_ficha]
        rutas_html += f'<details class="grupo"><summary>Sin clasificar <small>{len(sin_ficha)}</small></summary>{tabla(["", "Ruta", "Rol", "Docstring"], filas)}</details>'
    n_get = sum(1 for r in RUTAS if r["metodo"] == "GET")
    return f'''
<div class="doc">
<h2 id="c-modulos">1. Módulos de Python</h2>
<p><code>main.py</code> es el único punto de entrada: importa todos los módulos de lógica y es el único que renderiza plantillas. Ninguno de los módulos de lógica depende de otro ni de FastAPI.</p>
{mods}
<h2 id="c-scripts">2. Scripts de operación</h2>
{scripts}
<h2 id="c-rutas">3. Rutas HTTP</h2>
<p>{len(RUTAS)} rutas, todas en <code>main.py</code>: {n_get} GET y {len(RUTAS) - n_get} POST. No hay PUT ni DELETE: todo el ABM es POST con formularios o JSON. Además hay dos manejadores de excepciones, dos middlewares, un evento de arranque y el montaje de <code>/static</code>.</p>
{rutas_html}
<h2 id="c-templates">4. Plantillas</h2>
<p>Patrón repetido para los tres roles con login: portada de tarjetas más panel interior. Cualquier rol nuevo debería seguirlo.</p>
{tpl}
<h2 id="c-static">5. Estáticos y sistema de diseño</h2>
{static}
<p>Cuatro colores por sindicato inyectados desde la base (<code>--marca-base</code>, validado como oscuro; <code>--marca-primario</code>; <code>--marca-acento</code>; <code>--marca-apoyo</code>), grises y estados fijos, cuerpo en <code>system-ui</code>, cifras en monoespaciada tabular, Barlow Condensed solo en títulos. Logos a 76 px, 61 en móvil.</p>
<h2 id="c-tests">6. Cómo se prueba</h2>
<ul>
<li><b>61 archivos <code>test_*.py</code></b> en la raíz, cada uno con su base SQLite temporal creada antes del primer <code>import db</code>. Se corren <b>uno por proceso</b>: los módulos comparten estado de import y se contaminan si se batchean. <code>conftest.py</code> vacía <code>DATABASE_URL</code> para que el <code>.env</code> local no los mande al Postgres de Docker.</li>
<li><b>Dos robots E2E</b> con Playwright en <code>e2e/</code>: humo del Panel Sindical y el ciclo completo de un trámite con dos actores. Necesitan servidor y Postgres levantados; el flujo de lectura por IA no se robotiza porque gastaría créditos.</li>
<li><b>Sets de aceptación a mano</b>, nunca en CI: el del RAG (troceo, modelo y prompt), el del Asistente contra la API real, y la medición del Panel con 50.000 recibos (criterio: menos de un segundo; medido, 80 ms el peor).</li>
</ul>
<pre>for f in test_*.py; do .venv/Scripts/python.exe -m pytest "$f" -q || break; done</pre>
<h2 id="c-docs">7. Documentación en el repo</h2>
{docs}
</div>'''


# ---------- 4. MODELO DE DATOS ----------
def _fila_columna(c):
    marcas = []
    if c["pk"]:
        marcas.append(chip("PK", "b-colm3na"))
    if c["fk"]:
        marcas.append(chip("FK → " + c["fk"].split(".")[0], "b-sindicato"))
    if c["unique"]:
        marcas.append(chip("único", "b-legal"))
    elif c["index"]:
        marcas.append(chip("índice", "b-sistemas"))
    if c["json"]:
        marcas.append(chip("JSON", "b-comunicacion"))
    if c["bytes"]:
        marcas.append(chip("bytes", "b-bot"))
    if c["vector"]:
        marcas.append(chip("vector 1024", "b-funcional"))
    tipo = c["tipo"].replace("Optional[", "").rstrip("]")
    if c["vector"]:
        tipo = "Vector(1024)"
    elif c["json"]:
        tipo = "json"
    default = c["default"]
    if default in (None, "None") or c["pk"]:
        default = ""
    elif default.startswith("Field("):
        default = ""
    return (cod(c["nombre"]), cod(tipo + ("?" if c["nullable"] else "")), e(default or ""), " ".join(marcas))


def vista_datos():
    areas_html = ""
    for area, (nombre, color) in D.AREAS.items():
        nombres = [n for n, a in D.AREA_DE.items() if a == area]
        if area == "identidad":
            nombres = ["sindicato"] + nombres
        bloques = ""
        for n in nombres:
            t = POR_TABLA[n]
            desc = C.TABLAS.get(n, t["doc"].split(". ")[0])
            cols = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in _fila_columna(c)) + "</tr>" for c in t["columnas"])
            n_fk = ", ".join(sorted({c["fk"].split(".")[0] for c in t["columnas"] if c["fk"]})) or "—"
            bloques += f'''<details class="tabla-det" id="t-{n}"><summary><code>{n}</code><span class="meta">{len(t["columnas"])} columnas · FK a {e(n_fk)}</span></summary>
<p class="desc">{e(desc)}</p>
<div class="tabla-scroll"><table class="cols"><thead><tr><th>Columna</th><th>Tipo</th><th>Default</th><th>Marcas</th></tr></thead><tbody>{cols}</tbody></table></div></details>'''
        areas_html += f'<h3 style="color:{color}">{e(nombre)}</h3>{bloques}'
    migs = tabla(["#", "Revisión", "Fecha", "Qué cambia"],
                 [(str(i + 1), cod(m["rev"]), e(m["fecha"][:10]), e(m["titulo"]) + (f' <small>({", ".join(m["crea_tabla"])})</small>' if m["crea_tabla"] else ""))
                  for i, m in enumerate(MIGS)])
    por_valor = [
        ("cuentatrabajador.cuil ↔ trabajador.cuil", "La identidad y el empadronamiento. Todo el rastro del trabajador (recibos, envíos, trámites, notificaciones, push, consultas) se enlaza por el CUIL como texto."),
        ("cuentaempleador.cuit ↔ empleador.cuit", "Espejo exacto para las empresas; también tramiteempleador y los destinatarios de notificaciones a empresas."),
        ("formula.target → concepto.codigo", "La fórmula referencia el código del concepto genérico, no su id; concepto.codigo_generico apunta del específico de un empleador al genérico."),
        ("*.formulario_id → tipotramite.id", "Noticias, beneficios, notificaciones y notas del chat apuntan a un formulario con un entero sin FK, a propósito: un tipo se puede borrar y la interfaz muestra «ya no disponible»."),
        ("tramite.origen_tramite_id → tramite.id", "Trámites encadenados desde el chat, sin FK."),
        ("destino_seccionales", "Noticias y beneficios guardan la lista de seccionales en JSON, no en una tabla de cruce; vacía significa todas."),
    ]
    return f'''
<div class="doc">
<h2 id="d-der">1. Diagrama entidad-relación</h2>
<p>{len(TABLAS)} tablas y {N_COL} columnas. Todas menos seis cuelgan de <code>sindicato</code>, directa o indirectamente: ese es el eje del aislamiento. No hay <code>Relationship()</code> de ORM: todas las relaciones son claves foráneas escalares, y unas cuantas son por valor.</p>
{figura(D.der(TABLAS).replace('class="dia"', 'class="dia dia-xl"'), "Las áreas son las del código, no las del negocio. Las líneas dibujadas son las FK entre tablas de una misma área; las FK a sindicato se resumen en el hexágono para no llenar el lienzo de 25 líneas convergentes.")}

<h2 id="d-valor">2. Relaciones por valor</h2>
<p>Existen en el código y en el diagrama conceptual, pero no hay constraint en la base. Son las punteadas del diagrama.</p>
{tabla(["Enlace", "Por qué así"], [(cod(a), e(b)) for a, b in por_valor])}

<h2 id="d-tablas">3. Tablas, columna por columna</h2>
<p>Generado del código. Tipo con <code>?</code> significa nullable; las marcas dicen PK, FK, índice o único, JSON (jsonb en Postgres), bytes en la base y el vector de pgvector.</p>
{areas_html}

<h2 id="d-migraciones">4. Migraciones</h2>
{figura(D.tira_migraciones(MIGS), f"{len(MIGS)} revisiones Alembic del 3 de agosto al 7 de septiembre, una sola cabeza. Cada una es un paso incremental; nunca se reescribe una vieja.")}
{migs}

<h2 id="d-capa">5. La capa de datos</h2>
<ul>
<li><b>Motor dual.</b> Con <code>DATABASE_URL</code> se usa Postgres (la URL de Render se reescribe a <code>postgresql+psycopg://</code>); sin ella, SQLite. El pool lleva keepalives agresivos para que una conexión cortada por un proxy se detecte en un minuto y no en veinte.</li>
<li><b>Alembic manda en Postgres.</b> <code>init_db()</code> no crea tablas en Postgres; solo en SQLite sigue el <code>create_all</code>. El entorno de Alembic usa el mismo engine y los mismos modelos que la app.</li>
<li><b>JSON como jsonb.</b> Las {N_JSON} columnas JSON se declaran con variante jsonb en Postgres y JSON común en SQLite; la excepción es <code>consultaconvenio.fragmentos_usados</code>, que quedó como json.</li>
<li><b>Bytes en la base.</b> {N_BYTES} columnas de bytes, siempre con su MIME al lado y un flag para saber si hay algo sin traer los datos. Los listados seleccionan columnas explícitas para no arrastrar blobs.</li>
<li><b>pgvector.</b> La extensión se crea en la migración del RAG; Docker usa la imagen <code>pgvector/pgvector:pg16</code> porque la oficial no la trae. Dimensión 1024 medida contra el convenio real (recall@8 del 94 %). Sin índice HNSW todavía: con pocos miles de fragmentos gana el escaneo secuencial.</li>
<li><b>Índices compuestos del Panel.</b> Cinco índices que empiezan por <code>sindicato_id</code>, porque los agregados filtran por tenant más rango de fecha.</li>
<li><b>Semilla.</b> Una base nueva queda vacía hasta <code>cargar_demo.py</code> o un alta desde plataforma; lo único que se siembra solo son los topes de seguridad social, que son de ley.</li>
</ul>
</div>'''


# ---------- índices laterales ----------
def lateral(items, extra=""):
    links = "".join(f'<a class="blk" href="#{i}"><b>{n}</b><span>{e(t)}</span></a>' for n, (i, t) in enumerate(items, 1))
    return f'<aside class="side"><div class="panel"><h3>En esta sección</h3>{links}</div>{extra}</aside>'


LAT_F = [("f-que", "Qué es"), ("f-roles", "Los cuatro roles"), ("f-modulos", "Módulos por sindicato"), ("f-transversal", "Transversal"), ("f-pendientes", "Qué cambió y qué sigue")]
LAT_A = [("a-stack", "Stack"), ("a-vista", "Vista general"), ("a-recibo", "Flujo del recibo"), ("a-auth", "Autenticación"), ("a-multi", "Multi-sindicato"),
         ("a-ia", "La IA"), ("a-rag", "Consultas al convenio"), ("a-asistente", "Asistente del Panel"), ("a-entornos", "Entornos y despliegue"), ("a-decisiones", "Decisiones vigentes")]
LAT_C = [("c-modulos", "Módulos de Python"), ("c-scripts", "Scripts"), ("c-rutas", "Rutas HTTP"), ("c-templates", "Plantillas"), ("c-static", "Estáticos y diseño"), ("c-tests", "Cómo se prueba"), ("c-docs", "Documentación")]
LAT_D = [("d-der", "Diagrama"), ("d-valor", "Relaciones por valor"), ("d-tablas", "Tablas"), ("d-migraciones", "Migraciones"), ("d-capa", "La capa de datos")]

CSS = open(AQUI / "estilos.css", encoding="utf-8").read()


def pagina():
    numeros = f'''<div class="datos">
<div><b>0.29.01</b>Trabajador</div><div><b>0.29.06</b>Sindicato</div><div><b>0.23.02</b>Plataforma</div>
<div><b>{len(RUTAS)}</b>rutas HTTP</div><div><b>{len(TABLAS)}</b>tablas</div><div><b>{len(MIGS)}</b>migraciones</div><div><b>61</b>archivos de test</div>
</div>'''
    return f'''<title>Mi Trabajo — Documentación técnica</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&display=swap">
<style>{CSS}</style>
<header class="top">
  <div class="eyebrow">Colm3na · Mi Trabajo · Documentación técnica</div>
  <h1>Cómo está hecho Mi Trabajo</h1>
  <p>Cuatro reportes generados desde el código real al {FECHA_DOC} (rama <code>main</code>, commit <code>{COMMIT}</code>): qué hace cada rol, cómo se arma una respuesta, qué archivos componen el sistema y cómo se guardan los datos. Reemplaza la edición del 14 de agosto (versión 0.03).</p>
  {numeros}
</header>
<nav class="tabs" id="tabs">
  <button class="on" data-v="funcionalidades">Funcionalidades</button>
  <button data-v="arquitectura">Arquitectura</button>
  <button data-v="componentes">Componentes</button>
  <button data-v="datos">Modelo de datos</button>
  <span class="sync">generado del código · regenerable</span>
</nav>
<div class="wrap">
<section class="vista on" id="v-funcionalidades"><div class="grid2">{lateral(LAT_F)}{vista_funcionalidades()}</div></section>
<section class="vista" id="v-arquitectura"><div class="grid2">{lateral(LAT_A)}{vista_arquitectura()}</div></section>
<section class="vista" id="v-componentes"><div class="grid2">{lateral(LAT_C)}{vista_componentes()}</div></section>
<section class="vista" id="v-datos"><div class="grid2">{lateral(LAT_D)}{vista_datos()}</div></section>
<p class="foot">Colm3na · Mi Trabajo — Documentación técnica, edición del {FECHA_DOC}. Se genera con tres scripts (extraer, diagramar, generar) que leen db.py, main.py y migrations/; los textos de contexto se mantienen en contenido.py. Las cifras de esta página son del commit {COMMIT}.</p>
</div>
<script>
(function(){{
  const botones=document.querySelectorAll('#tabs button');
  function mostrar(v,empujar){{
    document.querySelectorAll('.vista').forEach(s=>s.classList.toggle('on',s.id==='v-'+v));
    botones.forEach(b=>b.classList.toggle('on',b.dataset.v===v));
    if(empujar)history.replaceState(null,'','#'+v);
    window.scrollTo({{top:0}});
  }}
  botones.forEach(b=>b.addEventListener('click',()=>mostrar(b.dataset.v,true)));
  // #a-recibo abre la vista de arquitectura y baja al ancla
  function porAncla(){{
    const h=location.hash.slice(1); if(!h)return;
    const vistas={{f:'funcionalidades',a:'arquitectura',c:'componentes',d:'datos',t:'datos'}};
    if(document.getElementById('v-'+h)){{mostrar(h,false);return;}}
    const v=vistas[h.split('-')[0]]; if(!v)return;
    mostrar(v,false);
    const el=document.getElementById(h); if(el){{ if(el.tagName==='DETAILS')el.open=true; el.scrollIntoView({{block:'start'}}); }}
  }}
  document.addEventListener('click',ev=>{{const a=ev.target.closest('a[href^="#"]'); if(!a)return; const id=a.getAttribute('href').slice(1); const el=document.getElementById(id); if(!el)return; ev.preventDefault(); history.replaceState(null,'','#'+id); porAncla();}});
  window.addEventListener('hashchange',porAncla);
  porAncla();
}})();
</script>'''


if __name__ == "__main__":
    salida = AQUI.parents[1] / "recursos" / "documentacion-tecnica.html"
    html = pagina()
    salida.write_text(html, encoding="utf-8")
    faltan = [(r["metodo"], r["path"]) for r in RUTAS if (r["metodo"], r["path"]) not in C.RUTAS]
    print(f"escrito {salida.name}: {len(html) // 1024} KB; rutas sin ficha: {faltan}")

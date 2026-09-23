"""Diagramas SVG inline de la documentación técnica. Todo en currentColor
salvo los pocos acentos con significado (miel = lo que cruza a la IA,
agua = frontera del tenant, verde = persistencia). Sin scripts ni estilos
dentro del SVG: las clases se estilan desde la página.
"""
from html import escape as e

# ---------- primitivas ----------
DEFS = '''<defs>
<marker id="fl" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5 0 10z" fill="currentColor"/></marker>
<marker id="flm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5 0 10z" fill="#f0a01e"/></marker>
<marker id="fla" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5 0 10z" fill="#a0030b"/></marker>
<pattern id="panal" width="60" height="52" patternUnits="userSpaceOnUse"><path d="M15 1l13 7.5v15L15 31 2 23.5v-15zM45 1l13 7.5v15L45 31 32 23.5v-15zM30 27l13 7.5v15L30 52 17 44.5v-15z" fill="none" stroke="currentColor" stroke-width=".6" opacity=".18"/></pattern>
</defs>'''


def caja(x, y, w, h, titulo, sub="", cls="caja", r=10, sub2=""):
    inv = "-inv" if cls == "caja-p" else ""
    t = f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/>'
    dy = -6 if sub2 else 0
    if sub:
        t += f'<text class="tit{inv}" x="{x + w / 2}" y="{y + h / 2 - 6 + dy}" text-anchor="middle">{e(titulo)}</text>'
        t += f'<text class="sub{inv}" x="{x + w / 2}" y="{y + h / 2 + 11 + dy}" text-anchor="middle">{e(sub)}</text>'
    else:
        t += f'<text class="tit{inv}" x="{x + w / 2}" y="{y + h / 2 + 5}" text-anchor="middle">{e(titulo)}</text>'
    if sub2:
        t += f'<text class="sub{inv}" x="{x + w / 2}" y="{y + h / 2 + 27 + dy}" text-anchor="middle">{e(sub2)}</text>'
    return t


def hexa(cx, cy, rad, cls="hex"):
    import math
    pts = " ".join(f"{cx + rad * math.cos(math.radians(60 * i - 30)):.1f},{cy + rad * math.sin(math.radians(60 * i - 30)):.1f}"
                   for i in range(6))
    return f'<polygon class="{cls}" points="{pts}"/>'


def flecha(x1, y1, x2, y2, label="", cls="fle", marker="fl", dy=-6, dash=False, lx=None, ly=None):
    d = ' stroke-dasharray="5 4"' if dash else ""
    t = f'<line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#{marker})"{d}/>'
    if label:
        mx = lx if lx is not None else (x1 + x2) / 2
        my = ly if ly is not None else (y1 + y2) / 2 + dy
        t += f'<text class="lab" x="{mx}" y="{my}" text-anchor="middle">{e(label)}</text>'
    return t


def codo(puntos, label="", cls="fle", marker="fl", lx=None, ly=None, dash=False):
    d = ' stroke-dasharray="5 4"' if dash else ""
    pts = " ".join(f"{x},{y}" for x, y in puntos)
    t = f'<polyline class="{cls}" points="{pts}" fill="none" marker-end="url(#{marker})"{d}/>'
    if label:
        t += f'<text class="lab" x="{lx}" y="{ly}" text-anchor="middle">{e(label)}</text>'
    return t


def texto(x, y, s, cls="lab", anchor="start"):
    return f'<text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}">{e(s)}</text>'


def svg(w, h, cuerpo, aria):
    return (f'<svg class="dia" viewBox="0 0 {w} {h}" role="img" aria-label="{e(aria)}" '
            f'xmlns="http://www.w3.org/2000/svg">{DEFS}{cuerpo}</svg>')


# ---------- 1. Vista general ----------
def vista_general():
    b = []
    # Navegador
    b.append('<rect class="zona" x="20" y="20" width="230" height="470" rx="14"/>')
    b.append(texto(135, 46, "NAVEGADOR", "zona-t", "middle"))
    apps = [("Trabajador", "/app · PWA instalable"), ("Sindicato", "/admin · Panel Sindical"),
            ("Plataforma", "/plataforma"), ("Empresa", "/empresa")]
    for i, (t, s) in enumerate(apps):
        b.append(caja(40, 70 + i * 78, 190, 60, t, s))
    b.append(texto(135, 400, "HTML servido + fetch JSON", "sub", "middle"))
    b.append(texto(135, 418, "JS vanilla, sin build", "sub", "middle"))
    b.append(texto(135, 462, "4 cookies de sesión,", "sub", "middle"))
    b.append(texto(135, 478, "una por rol", "sub", "middle"))
    # Servidor
    b.append('<rect class="zona" x="300" y="20" width="560" height="470" rx="14"/>')
    b.append(texto(580, 46, "UN PROCESO FASTAPI · RENDER", "zona-t", "middle"))
    b.append(caja(320, 66, 520, 84, "main.py", "172 rutas · Jinja2 · middlewares de sesión y cache", "caja-p", 12,
                  "auth.py: PBKDF2 + cookies HMAC firmadas"))
    mods = [("validador.py", "reglas y topes"), ("extractor.py", "lee recibos y ARCA"), ("semaforo.py", "estados ARCA"),
            ("dashboard.py", "agregados SQL"), ("asistente.py", "pregunta → filtros"), ("rag.py", "convenio: PDF → vector"),
            ("validaciones_tramite.py", "motor de formularios"), ("push.py", "Web Push VAPID"), ("recursos.py", "landing y PIN")]
    for i, (t, s) in enumerate(mods):
        col, fila = i % 3, i // 3
        b.append(caja(320 + col * 176, 176 + fila * 72, 164, 58, t, s, "caja-m", 8))
    b.append(texto(580, 420, "Cada módulo de lógica es puro: no importa FastAPI ni a los otros", "sub", "middle"))
    b.append(texto(580, 438, "main.py es el único que renderiza y el único que los llama", "sub", "middle"))
    # Datos y externos
    b.append('<rect class="zona" x="910" y="20" width="230" height="470" rx="14"/>')
    b.append(texto(1025, 46, "AFUERA DEL PROCESO", "zona-t", "middle"))
    b.append('<path class="caja-db" d="M950 84c0-12 34-20 75-20s75 8 75 20v96c0 12-34 20-75 20s-75-8-75-20z"/>')
    b.append('<ellipse class="caja-db-tapa" cx="1025" cy="84" rx="75" ry="20"/>')
    b.append(texto(1025, 130, "Postgres 16", "tit", "middle"))
    b.append(texto(1025, 148, "41 tablas · Alembic", "sub", "middle"))
    b.append(texto(1025, 164, "pgvector · bytes en la base", "sub", "middle"))
    b.append(caja(940, 236, 170, 66, "API de Anthropic", "Sonnet 4.6 · Opus 5", "caja-ia", 10))
    b.append(caja(940, 330, 170, 56, "Servicio push", "del navegador", "caja", 10))
    b.append(caja(940, 414, 170, 56, "ARCA", "lo visita el trabajador", "caja", 10))
    # Flechas
    b.append(flecha(232, 100, 318, 100, "HTML · JSON", lx=275, ly=88))
    b.append(codo([(842, 110), (900, 110), (900, 130), (948, 130)], "SQLModel", lx=900, ly=96))
    b.append(codo([(658, 236), (658, 252), (880, 252), (880, 269), (938, 269)], "recibo · ARCA · convenio · filtros",
                  cls="fle-m", marker="flm", lx=800, ly=244))
    b.append(codo([(838, 350), (938, 350)], "notifica", lx=888, ly=338))
    b.append(codo([(940, 440), (900, 440), (900, 470), (250, 470), (250, 440)], "captura de Mis Aportes, a mano",
                  lx=600, ly=460, dash=True))
    return svg(1160, 500, "".join(b), "Vista general: navegador con cuatro apps, un proceso FastAPI con main.py y "
               "sus módulos de lógica, Postgres con pgvector, la API de Anthropic y el servicio push.")


# ---------- 2. Flujo de un recibo ----------
def flujo_recibo():
    lanes = [("Trabajador", 90), ("main.py", 290), ("extractor.py", 490), ("API Anthropic", 690),
             ("validador.py", 890), ("db.py", 1090)]
    b = []
    for nombre, x in lanes:
        b.append(caja(x - 70, 16, 140, 40, nombre, "", "caja-l", 8))
        b.append(f'<line class="carril" x1="{x}" y1="60" x2="{x}" y2="560"/>')
    pasos = [
        (90, 290, 92, "1 · POST /api/leer con la foto o el PDF"),
        (290, 490, 132, "2 · extraer(contenido)"),
        (490, 690, 172, "3 · imagen base64 + esquema JSON"),
        (690, 490, 212, "4 · datos del recibo, tokens, alerta de adulteración"),
        (490, 290, 252, "5 · (recibo, uso)"),
        (290, 1090, 292, "6 · registrar UsoIA; si hay alerta, ReciboSospechoso con el archivo"),
        (290, 90, 332, "7 · preview + conceptos que el sindicato no tiene"),
        (90, 290, 372, "8 · POST /api/validar con el recibo confirmado"),
        (290, 890, 412, "9 · validar(conceptos, fórmulas vigentes en el período, topes SS)"),
        (890, 290, 452, "10 · discrepancias, totales, alertas legales"),
        (290, 1090, 492, "11 · ReciboVerificado + columnas analíticas del Panel"),
        (290, 90, 532, "12 · veredicto: en orden / con diferencias"),
    ]
    for x1, x2, y, lab in pasos:
        ia = "Anthropic" in lab or x2 == 690 or x1 == 690
        cls, mk = ("fle-m", "flm") if (x2 == 690 or x1 == 690) else ("fle", "fl")
        b.append(flecha(x1 + (8 if x2 > x1 else -8), y, x2 - (8 if x2 > x1 else -8), y, "", cls, mk))
        anchor_x = min(x1, x2) + 14
        b.append(texto(anchor_x, y - 8, lab, "lab"))
    b.append(texto(590, 590, "La IA solo transcribe lo impreso. Todo el cálculo pasa por validador.py, que no depende de la IA y se testea con datos fijos.", "sub", "middle"))
    return svg(1180, 604, "".join(b), "Secuencia de leer y validar un recibo: el trabajador sube el archivo, "
               "extractor.py lo manda a la API de Anthropic, main.py registra el uso y muestra la vista previa, "
               "y validador.py compara contra las fórmulas del sindicato antes de guardar el ReciboVerificado.")


# ---------- 3. Multi-sindicato ----------
def multi_sindicato():
    b = []
    b.append(caja(60, 20, 980, 54, "Admin de plataforma", "el único rol que cruza la frontera: alta de sindicatos, marca, módulos, topes, uso de IA", "caja-p", 12))
    for i, (nombre, x) in enumerate([("Sindicato A", 60), ("Sindicato B", 560)]):
        b.append(f'<rect class="tenant" x="{x}" y="110" width="480" height="250" rx="14"/>')
        b.append(texto(x + 20, 138, nombre.upper(), "zona-t"))
        b.append(texto(x + 460, 138, "marca · módulos · admins", "sub", "end"))
        filas = [("trabajador", "empadronamiento (cuil, seccional, credencial)"),
                 ("empleador", "alta de la empresa (cuit)"),
                 ("concepto · formula · tramite · noticia · …", "todo con sindicato_id")]
        for j, (t, s) in enumerate(filas):
            b.append(caja(x + 20, 156 + j * 64, 440, 52, t, s, "caja-t", 8))
    b.append(caja(200, 410, 260, 60, "cuentatrabajador", "CUIL único + clave · foto", "caja-g", 10))
    b.append(caja(640, 410, 260, 60, "cuentaempleador", "CUIT único + clave", "caja-g", 10))
    # enlaces por valor (dashed)
    b.append(flecha(300, 408, 250, 210, "", "fle-a", "fla", dash=True))
    b.append(flecha(360, 408, 760, 210, "", "fle-a", "fla", dash=True))
    b.append(texto(430, 300, "por valor: cuil", "lab-a", "middle"))
    b.append(flecha(700, 408, 300, 274, "", "fle-a", "fla", dash=True))
    b.append(flecha(800, 408, 800, 274, "", "fle-a", "fla", dash=True))
    b.append(texto(820, 350, "por valor: cuit", "lab-a"))
    b.append(texto(550, 500, "Una identidad global, N empadronamientos. Ninguna ruta acepta sindicato_id por parámetro: el tenant sale siempre de la cookie del rol.", "sub", "middle"))
    return svg(1100, 516, "".join(b), "Modelo multi-sindicato: la plataforma arriba, dos sindicatos con sus tablas "
               "propias, y abajo las identidades globales cuentatrabajador y cuentaempleador enlazadas por CUIL y CUIT.")


# ---------- 4. RAG del convenio ----------
def rag_pipeline():
    b = []
    b.append(texto(20, 30, "INDEXACIÓN (admin, en un hilo aparte)", "zona-t"))
    fila1 = [("PDF del convenio", "o de un acta"), ("pypdf", "texto nativo u OCR"), ("troceo", "por artículo y título"),
             ("fastembed", "e5-large · 1024 dims")]
    for i, (t, s) in enumerate(fila1):
        b.append(caja(20 + i * 210, 46, 180, 60, t, s, "caja", 10))
        if i < 3:
            b.append(flecha(202 + i * 210, 76, 228 + i * 210, 76))
    b.append('<path class="caja-db" d="M880 56c0-10 30-16 70-16s70 6 70 16v190c0 10-30 16-70 16s-70-6-70-16z"/>')
    b.append('<ellipse class="caja-db-tapa" cx="950" cy="56" rx="70" ry="16"/>')
    b.append(texto(950, 128, "fragmentoconvenio", "tit", "middle"))
    b.append(texto(950, 146, "texto · sección · tipo_fuente", "sub", "middle"))
    b.append(texto(950, 162, "embedding Vector(1024)", "sub", "middle"))
    b.append(texto(950, 178, "sindicato_id desnormalizado", "sub", "middle"))
    b.append(flecha(832, 76, 878, 76, "INSERT", lx=855, ly=64))
    b.append(texto(20, 172, "CONSULTA (trabajador, /app/convenio)", "zona-t"))
    fila2 = [("pregunta", "elige el convenio"), ("fastembed", "mismo modelo"), ("búsqueda coseno", "k = 8 · filtra sindicato + convenio"),
             ("Claude Opus 5", "responde citando artículos")]
    for i, (t, s) in enumerate(fila2):
        cls = "caja-ia" if i == 3 else "caja"
        b.append(caja(20 + i * 210, 188, 180, 60, t, s, cls, 10))
        if i < 3:
            b.append(flecha(202 + i * 210, 218, 228 + i * 210, 218))
    b.append(flecha(878, 218, 832, 218, "<=>", lx=855, ly=206))
    b.append(codo([(650, 250), (650, 282), (950, 282), (950, 264)], "consultaconvenio: pregunta, fragmentos usados, hubo respuesta",
                  lx=800, ly=300))
    b.append(texto(20, 334, "Las notas «(Ex Artículo N modificado por Acta…)» van en notas_acta, fuera del embedding: son 116 casi iguales y harían parecer al 60 % de los artículos.", "sub"))
    return svg(1060, 350, "".join(b), "Pipeline del RAG del convenio: el PDF se extrae, trocea y vectoriza con "
               "fastembed a Postgres con pgvector; la pregunta del trabajador se vectoriza igual, se busca por "
               "coseno filtrando por sindicato y convenio, y Claude responde citando los artículos.")


# ---------- 5. Asistente del Panel ----------
def asistente_panel():
    b = []
    pasos = [("Admin", "pregunta escrita o dictada"), ("asistente.py", "prompt + ficha del sindicato"),
             ("Claude", "devuelve filtros JSON"), ("dashboard.py", "agregados SQL con esos filtros"),
             ("Panel", "aplica filtros y resume")]
    for i, (t, s) in enumerate(pasos):
        cls = "caja-ia" if t == "Claude" else ("caja-p" if t == "Panel" else "caja")
        b.append(caja(20 + i * 210, 30, 180, 62, t, s, cls, 10))
        if i < 4:
            b.append(flecha(202 + i * 210, 61, 228 + i * 210, 61, "", "fle-m" if i in (1, 2) else "fle", "flm" if i in (1, 2) else "fl"))
    b.append(codo([(530, 94), (530, 130), (110, 130), (110, 94)], "ficha determinista del afiliado, sin IA, cuando la pregunta es por una persona",
                  lx=320, ly=150, dash=True))
    b.append(codo([(740, 94), (740, 176), (320, 176)], "consultaasistente: pregunta, respuesta, filtros, tokens · tope diario",
                  lx=530, ly=196))
    return svg(1060, 210, "".join(b), "Asistente del Panel Sindical: la pregunta del admin pasa por asistente.py, "
               "Claude devuelve filtros en JSON, dashboard.py corre los agregados y el panel aplica los filtros y "
               "resume con los números reales; cada consulta queda registrada.")


# ---------- 6. Entornos y promoción ----------
def entornos_deploy():
    b = []
    b.append(caja(20, 60, 220, 120, "Tu PC", "rama propia · Postgres en Docker", "caja", 12, "uvicorn --reload · alembic upgrade head"))
    b.append(f'<rect class="tenant-p" x="300" y="30" width="330" height="200" rx="14"/>')
    b.append(texto(320, 56, "PRUEBAS · mitrabajo-pruebas.onrender.com", "zona-t"))
    b.append(caja(320, 70, 290, 50, "rama main", "cada push redeploya", "caja-t", 8))
    b.append(caja(320, 130, 290, 50, "Pre-Deploy: alembic upgrade head", "Postgres de Pruebas · ENTORNO=pruebas", "caja-t", 8))
    b.append(texto(465, 210, "distintivo ámbar · /entornos con PIN y Recursos", "sub", "middle"))
    b.append(f'<rect class="tenant-d" x="740" y="30" width="330" height="200" rx="14"/>')
    b.append(texto(760, 56, "DEMO · mitrabajo.onrender.com", "zona-t"))
    b.append(caja(760, 70, 290, 50, "rama demo", "solo recibe merges de main", "caja-t", 8))
    b.append(caja(760, 130, 290, 50, "Pre-Deploy: alembic upgrade head", "Postgres de Demo · ENTORNO=demo", "caja-t", 8))
    b.append(texto(905, 210, "sin distintivo · sin landing · la ven sindicatos e inversor", "sub", "middle"))
    b.append(flecha(242, 120, 298, 120, "git push origin main", lx=270, ly=104))
    b.append(flecha(632, 120, 738, 120, "promover_demo.py", lx=685, ly=104))
    b.append(texto(685, 138, "backup + merge + tag", "sub", "middle"))
    b.append(texto(545, 262, "Cada entorno tiene su propia base. Sobre demo no se programa nunca; main va siempre adelante de demo, así las migraciones estrenan en Pruebas.", "sub", "middle"))
    return svg(1090, 280, "".join(b), "Los tres lugares de un cambio: la PC del desarrollador, Pruebas que sigue la "
               "rama main con redeploy automático y migraciones en el Pre-Deploy, y Demo que solo cambia con "
               "promover_demo.py.")


# ---------- 7. DER por áreas (generado) ----------
AREAS = {
    "identidad": ("Identidad y padrón", "#2e5c8a"),
    "convenio": ("Catálogo del convenio", "#0f8a6a"),
    "recibos": ("Recibos y reportes", "#a0030b"),
    "comunicacion": ("Comunicación", "#7a2e8f"),
    "tramites": ("Trámites", "#b8600f"),
    "empleadores": ("Empleadores", "#2e5c8a"),
    "rag": ("Convenio: consultas (RAG)", "#0f8a6a"),
    "plataforma": ("Plataforma y global", "#4c5d75"),
}

# posiciones (x, y) de cada tabla en el lienzo del DER
POS = {
    # identidad (arriba a la izquierda)
    "cuentatrabajador": (40, 90), "trabajador": (40, 170), "seccional": (240, 170), "usuariosindicato": (240, 90),
    # empleadores (izquierda, medio)
    "cuentaempleador": (40, 330), "empleador": (240, 330),
    # catálogo del convenio (centro arriba)
    "concepto": (480, 90), "formula": (480, 170), "topebaseimponible": (680, 170),
    # recibos (derecha arriba)
    "reciboverificado": (920, 90), "enviosindicato": (1120, 90), "reporte": (920, 170), "recibosospechoso": (1120, 170), "usoia": (1320, 130),
    # comunicación (derecha medio)
    "noticia": (920, 330), "beneficio": (1120, 330), "notificacion": (920, 410), "notificaciondestinatario": (1120, 410),
    "notificacionempleador": (920, 490), "notificacionempleadordestinatario": (1120, 490),
    # trámites (centro/derecha abajo)
    "tipotramite": (480, 330), "campotramite": (680, 330), "tramite": (480, 410), "respuestatramite": (680, 410),
    "notatramite": (480, 490), "tramitelog": (680, 490),
    "tipotramiteempleador": (480, 620), "campotramiteempleador": (680, 620), "tramiteempleador": (480, 700),
    "respuestatramiteempleador": (680, 700), "notatramiteempleador": (480, 780), "tramiteempleadorlog": (680, 780),
    # rag (abajo izquierda)
    "convenio": (40, 620), "documentoconvenio": (40, 700), "fragmentoconvenio": (240, 700), "consultaconvenio": (240, 620),
    # plataforma / global (abajo derecha)
    "consultaasistente": (920, 620), "configuracionplataforma": (1120, 620), "suscripcionpush": (920, 700),
    "recurso": (1120, 700),
}
AREA_DE = {
    **{t: "identidad" for t in ("cuentatrabajador", "trabajador", "seccional", "usuariosindicato")},
    **{t: "empleadores" for t in ("cuentaempleador", "empleador")},
    **{t: "convenio" for t in ("concepto", "formula", "topebaseimponible")},
    **{t: "recibos" for t in ("reciboverificado", "enviosindicato", "reporte", "recibosospechoso", "usoia")},
    **{t: "comunicacion" for t in ("noticia", "beneficio", "notificacion", "notificaciondestinatario",
                                   "notificacionempleador", "notificacionempleadordestinatario")},
    **{t: "tramites" for t in ("tipotramite", "campotramite", "tramite", "respuestatramite", "notatramite", "tramitelog",
                               "tipotramiteempleador", "campotramiteempleador", "tramiteempleador",
                               "respuestatramiteempleador", "notatramiteempleador", "tramiteempleadorlog")},
    **{t: "rag" for t in ("convenio", "documentoconvenio", "fragmentoconvenio", "consultaconvenio")},
    **{t: "plataforma" for t in ("consultaasistente", "configuracionplataforma", "suscripcionpush", "recurso")},
}
MARCOS = [  # (área, x, y, w, h)
    ("identidad", 24, 50, 400, 190), ("empleadores", 24, 290, 400, 110), ("convenio", 464, 50, 400, 190),
    ("recibos", 904, 50, 600, 190), ("comunicacion", 904, 290, 400, 280), ("tramites", 464, 290, 400, 560),
    ("rag", 24, 580, 400, 190), ("plataforma", 904, 580, 400, 190),
]
ANCHO, ALTO = 180, 48
# enlaces por valor que el DER muestra punteados
POR_VALOR = [("cuentatrabajador", "trabajador", "cuil"), ("cuentaempleador", "empleador", "cuit"),
             ("formula", "concepto", "target = codigo")]


def der(tablas):
    por_nombre = {t["tabla"]: t for t in tablas}
    b = []
    for area, x, y, w, h in MARCOS:
        nombre, color = AREAS[area]
        b.append(f'<rect class="marco" x="{x}" y="{y}" width="{w}" height="{h}" rx="12" stroke="{color}"/>')
        b.append(f'<text class="marco-t" x="{x + 12}" y="{y + 20}" fill="{color}">{e(nombre.upper())}</text>')
    # FK entre tablas (sin las que van a sindicato: se marcan con el hexágono)
    for t in tablas:
        for c in t["columnas"]:
            if c["fk"] and not c["fk"].startswith("sindicato."):
                destino = c["fk"].split(".")[0]
                if t["tabla"] in POS and destino in POS:
                    x1, y1 = POS[t["tabla"]]
                    x2, y2 = POS[destino]
                    b.append(_enlace(x1, y1, x2, y2, c["nombre"]))
    for a, bb, lab in POR_VALOR:
        x1, y1 = POS[a]
        x2, y2 = POS[bb]
        b.append(_enlace(x1, y1, x2, y2, lab, dash=True))
    for nombre, (x, y) in POS.items():
        t = por_nombre.get(nombre)
        if not t:
            continue
        color = AREAS[AREA_DE[nombre]][1]
        b.append(f'<rect class="tabla" x="{x}" y="{y}" width="{ANCHO}" height="{ALTO}" rx="8"/>')
        b.append(f'<rect x="{x}" y="{y}" width="6" height="{ALTO}" rx="3" fill="{color}"/>')
        b.append(f'<text class="tabla-n" x="{x + 14}" y="{y + 20}">{e(nombre)}</text>')
        tags = []
        cols = t["columnas"]
        if any(c["fk"] == "sindicato.id" for c in cols):
            b.append(hexa(x + ANCHO - 14, y + 12, 7, "hex-t"))
        elif nombre != "sindicato":
            tags.append("global")
        n_json = sum(1 for c in cols if c["json"])
        n_bytes = sum(1 for c in cols if c["bytes"])
        if any(c["vector"] for c in cols):
            tags.append("vector 1024")
        if n_json:
            tags.append(f"json×{n_json}")
        if n_bytes:
            tags.append(f"bytes×{n_bytes}")
        tags.append(f"{len(cols)} col")
        b.append(f'<text class="tabla-s" x="{x + 14}" y="{y + 37}">{e(" · ".join(tags))}</text>')
    # sindicato, la raíz, al centro
    cx, cy = 664, 262
    b.append(hexa(cx, cy, 34, "hex-raiz"))
    b.append(texto(cx, cy - 2, "sindicato", "tabla-n-inv", "middle"))
    b.append(texto(cx, cy + 12, "25 col · raíz", "tabla-s-inv", "middle"))
    b.append(texto(cx + 48, cy - 4, "el hexágono chico en una tabla = tiene sindicato_id (FK a la raíz)", "sub"))
    b.append(texto(cx + 48, cy + 12, "«global» = no lo tiene; línea punteada = relación por valor, sin FK", "sub"))
    return svg(1530, 870, "".join(b), "Diagrama entidad-relación por áreas: 41 tablas agrupadas en identidad y "
               "padrón, empleadores, catálogo del convenio, recibos, comunicación, trámites, consultas del convenio "
               "y plataforma; el hexágono marca las que cuelgan de sindicato y las líneas punteadas las relaciones por valor.")


def _enlace(x1, y1, x2, y2, label, dash=False):
    # de borde a borde, eligiendo el lado más cercano
    ax, ay = x1 + ANCHO / 2, y1 + ALTO / 2
    bx, by = x2 + ANCHO / 2, y2 + ALTO / 2
    if abs(ax - bx) > abs(ay - by):
        sx = x1 + ANCHO if bx > ax else x1
        ex = x2 if bx > ax else x2 + ANCHO
        sy, ey = ay, by
    else:
        sy = y1 + ALTO if by > ay else y1
        ey = y2 if by > ay else y2 + ALTO
        sx, ex = ax, bx
    d = ' stroke-dasharray="5 4"' if dash else ""
    cls = "fle-a" if dash else "fle-fk"
    mk = "fla" if dash else "fl"
    mx, my = (sx + ex) / 2, (sy + ey) / 2 - 5
    return (f'<line class="{cls}" x1="{sx}" y1="{sy}" x2="{ex}" y2="{ey}" marker-end="url(#{mk})"{d}/>'
            f'<text class="lab-fk" x="{mx}" y="{my}" text-anchor="middle">{e(label)}</text>')


# ---------- 8. Tira de migraciones ----------
def tira_migraciones(migs):
    from datetime import date
    fechas = [date.fromisoformat(m["fecha"][:10]) for m in migs]
    d0, d1 = min(fechas), max(fechas)
    total = (d1 - d0).days or 1
    x0, x1, y = 40, 1040, 70
    b = [f'<line class="eje" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}"/>']
    # ticks semanales
    from datetime import timedelta
    dia = d0
    while dia <= d1:
        x = x0 + (dia - d0).days / total * (x1 - x0)
        b.append(f'<line class="tick" x1="{x:.0f}" y1="{y}" x2="{x:.0f}" y2="{y + 8}"/>')
        # `%-d` (día sin cero a la izquierda) es de glibc y en Windows revienta
        # con "Invalid format string": se arma a mano, que anda en los dos.
        etiqueta = f"{dia.day} " + dia.strftime("%b").replace("Aug", "ago").replace("Sep", "sep")
        b.append(texto(x, y + 24, etiqueta, "lab", "middle"))
        dia += timedelta(days=7)
    apilado = {}
    hitos = {"cbe17211376d": "esquema inicial", "a8c25f9b6d31": "trámites", "826e9627293a": "empleadores",
             "f4d1a7c39e02": "RAG + pgvector", "a1d45b0c9e11": "Panel Sindical", "a9d4e7f2c831": "Web Push",
             "9c4e2f7a1b3d": "recursos"}
    for m, f in zip(migs, fechas):
        n = apilado.get(f, 0)
        apilado[f] = n + 1
        x = x0 + (f - d0).days / total * (x1 - x0)
        cy = y - 10 - n * 9
        cls = "punto-h" if m["rev"] in hitos else "punto"
        b.append(f'<circle class="{cls}" cx="{x:.0f}" cy="{cy}" r="3.5"><title>{e(m["fecha"][:10] + " · " + m["titulo"])}</title></circle>')
        if m["rev"] in hitos:
            b.append(f'<line class="tick" x1="{x:.0f}" y1="{cy - 6}" x2="{x:.0f}" y2="{y - 84}"/>')
            b.append(texto(x, y - 90, hitos[m["rev"]], "lab-h", "middle"))
    b.append(texto(x1, y + 44, f"{len(migs)} migraciones, cadena lineal sin ramas · un punto por migración, apilados por día", "sub", "end"))
    return svg(1080, 130, "".join(b), "Tira de tiempo de las 49 migraciones Alembic, del esquema inicial del 3 de "
               "agosto a la tabla de recursos del 7 de septiembre, con los hitos marcados.")


# ---------- 9. Roles y puertas ----------
def roles_puertas():
    b = []
    roles = [("Trabajador", "/ingresar", "CUIL + clave", "sesion_trabajador · cuil_trab · sind_elegido"),
             ("Admin de sindicato", "/admin", "CUIT + clave", "sesion_sindicato"),
             ("Admin de plataforma", "/plataforma", "CUIT + clave de entorno", "sesion_plataforma"),
             ("Empresa", "/ingresar-empresa", "CUIT + clave (autorregistro)", "sesion_empleador · cuit_emp · sind_elegido_emp")]
    for i, (rol, ruta, cred, cookies) in enumerate(roles):
        y = 20 + i * 76
        b.append(hexa(50, y + 30, 24, "hex-t"))
        b.append(texto(50, y + 34, str(i + 1), "tit", "middle"))
        b.append(caja(100, y, 210, 60, rol, ruta, "caja", 10))
        b.append(flecha(312, y + 30, 356, y + 30))
        b.append(caja(360, y, 250, 60, cred, "PBKDF2 · 100.000 iteraciones", "caja-m", 10))
        b.append(flecha(612, y + 30, 656, y + 30, "cookie firmada", lx=634, ly=y + 18))
        b.append(caja(660, y, 400, 60, cookies, "HMAC-SHA256 · 15 min sin uso · se renueva en cada request", "caja-t", 10))
    return svg(1080, 330, "".join(b), "Las cuatro puertas: cada rol tiene su login, su credencial y su propia "
               "cookie de sesión firmada, con vencimiento por inactividad.")

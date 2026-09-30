"""Mapa funcional de Colm3na: app -> funcionalidad -> pantalla, rutas, código, datos y servicios.

Todo sale del CÓDIGO, leído con `ast` (no de un grafo inferido):
  - las rutas, de los decoradores `@app.get/post/...` de main.py;
  - qué código corre cada ruta, siguiendo las llamadas entre funciones de los
    módulos de la app (sin entrar a los guardianes de sesión, que tocan lo
    mismo en todas y solo meterían ruido);
  - qué tablas toca, por el uso de las clases `table=True` de db.py;
  - qué servicios externos, por las librerías y URLs que usan esas funciones.
Lo único escrito a mano es FUNCIONALIDADES (qué ruta es de qué funcionalidad)
y los nombres legibles. Una ruta que no encaje queda en "Sin clasificar", a
la vista.

Orientación, no verdad: las llamadas dinámicas (getattr, callbacks por
string) no se ven. Ante la duda, manda el código.

Uso:  python mapa_funcional.py        (escribe mapa-funcional/mapa.html y lo abre)
En Pruebas/local también se ve en /entornos -> pestaña "Mapa funcional"
(main.py lo genera desde el código desplegado y lo guarda en memoria).
"""
import ast
import base64
import collections
import json
import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).parent
SALIDA = RAIZ / "mapa-funcional" / "mapa.html"

# ---------------------------------------------------------------- funcionalidades
# (app, funcionalidad, regex sobre la ruta, pantalla por defecto). Gana la primera.
FUNCIONALIDADES = [
    ("Común", "Salud del servicio", r"^/(healthz|readyz)$", None),
    ("Común", "Portada pública", r"^/$", "inicio.html"),
    ("Común", "Marca de la plataforma", r"^/logo-plataforma", None),

    ("Afiliado", "Ingreso y registro", r"^/(ingresar$|trabajador/|app/(elegir|cambiar))", "trabajador_login.html"),
    ("Afiliado", "Portada", r"^/app/inicio$", "portada.html"),
    ("Afiliado", "Página de la app (carga inicial)", r"^/app$", "trabajador.html"),
    ("Afiliado", "Tu Recibo", r"^/api/(leer|validar|reportar|mis-recibos|enviar-sindicato)", "trabajador.html"),
    ("Afiliado", "Mis Aportes (semáforo ARCA)", r"^/api/aportes", "trabajador.html"),
    ("Afiliado", "Credencial", r"^/(api/credencial|v/)", "trabajador.html"),
    ("Afiliado", "Novedades y beneficios", r"^/(api/(noticia|beneficio)|noticia-imagen|beneficio-imagen)", "trabajador.html"),
    ("Afiliado", "Notificaciones y push", r"^/(api/(notificacion|mis-notificaciones|push)|app/notificaciones|notificacion-adjunto|sw\.js)", "trabajador.html"),
    ("Afiliado", "Trámites", r"^/(api/tramite|tramite-nota-adjunto|tramite-respuesta-archivo)", "trabajador.html"),
    ("Afiliado", "Encuestas", r"^/api/encuesta", "trabajador.html"),
    ("Afiliado", "Consultas al convenio", r"^/(app/convenio|api/convenio)", None),
    ("Afiliado", "Perfil y domicilio", r"^/(api/(perfil|geocodificar|localidades|seccionales)|perfil-foto)", None),

    ("Empresa", "Ingreso y registro", r"^/(ingresar-empresa|empresa/(login|registro|salir|elegir|cambiar))", None),
    ("Empresa", "Portada", r"^/empresa/inicio$", None),
    ("Empresa", "Página de la app (carga inicial)", r"^/empresa$", None),
    ("Empresa", "Perfil", r"^/(api/empresa/perfil|perfil-empleador-foto)", "empresa.html"),
    ("Empresa", "Notificaciones", r"^/(api/empresa/notificacion|notificacion-empresa-adjunto)", "empresa.html"),
    ("Empresa", "Trámites", r"^/(api/empresa/tramite|tramite-empresa-)", "empresa.html"),

    ("Sindicato", "Ingreso y portada", r"^/admin/(login|salir|inicio)$", None),
    ("Sindicato", "Página del panel (carga inicial)", r"^/admin$", None),
    ("Sindicato", "Panel Sindical", r"^/admin/dashboard", "dashboard.html"),
    ("Sindicato", "Reportes", r"^/admin/reportes", "admin.html"),
    ("Sindicato", "Reglas de control", r"^/admin/formula", "admin.html"),
    ("Sindicato", "Conceptos", r"^/admin/concepto", "admin.html"),
    ("Sindicato", "Trabajadores (padrón)", r"^/admin/trabajador", "admin.html"),
    ("Sindicato", "Aprendizaje", r"^/admin/aprender", "admin.html"),
    ("Sindicato", "Noticias", r"^/admin/noticia", "admin.html"),
    ("Sindicato", "Beneficios", r"^/admin/beneficio", "admin.html"),
    ("Sindicato", "Notificaciones", r"^/admin/notificacion", "admin.html"),
    ("Sindicato", "Trámites", r"^/admin/tramite", "admin.html"),
    ("Sindicato", "Empleadores", r"^/admin/empleador", "admin.html"),
    ("Sindicato", "Convenio (RAG)", r"^/admin/convenio", "admin.html"),
    ("Sindicato", "Seccionales", r"^/admin/seccional", "admin.html"),
    ("Sindicato", "Áreas y Usuarios", r"^/admin/(area|usuario)", "admin.html"),
    ("Sindicato", "Encuestas", r"^/admin/encuesta", "admin.html"),
    ("Sindicato", "Marca del sindicato", r"^/(logo|firma)/", None),

    ("Plataforma", "Cambiar clave (transitoria, sacar antes de producción)", r"^/plataforma/reset-clave", "plataforma.html"),
    ("Plataforma", "Ingreso y usuarios nominales", r"^/plataforma/(login|salir|inicio|completar|usuario|usuarios|admins)", None),
    ("Plataforma", "Página del panel (carga inicial)", r"^/plataforma$", None),
    ("Plataforma", "Sindicatos y marca", r"^/plataforma/(sindicato|marca)", "plataforma.html"),
    ("Plataforma", "Configuración y topes", r"^/plataforma/(config|tope)", "plataforma.html"),
    ("Plataforma", "Uso de IA", r"^/plataforma/(modelos-ia|probar-modelos|enmascarado)", "plataforma.html"),
    ("Plataforma", "Recibos con alerta", r"^/plataforma/recibos-sospechosos", "plataforma.html"),
    ("Plataforma", "Trabajadores de la plataforma", r"^/plataforma/trabajadores", "plataforma.html"),

    ("Entornos", "Acceso y versión", r"^/(entornos/(login|pin|salir)$|api/version)", None),
    ("Entornos", "Página de la landing (carga inicial)", r"^/entornos$", None),
    ("Entornos", "Recursos", r"^/recursos", None),
    ("Entornos", "Sala de mando", r"^/(entornos|api/entornos)/esquema", None),
    ("Entornos", "Observabilidad", r"^/(entornos|api/entornos)/observabilidad", "_observabilidad.html"),
    ("Entornos", "Seguridad (XSK)", r"^/api/entornos/xsanders", None),
    ("Entornos", "Planes de Render", r"^/(entornos|api/entornos)/planes", "_planes.html"),
    ("Entornos", "Tests de carga", r"^/(entornos|api/entornos)/(tests|informe)", None),
    ("Entornos", "Mapa funcional", r"^/(entornos|api/entornos)/mapa", None),
]

NOMBRES = {
    "main": "Rutas (main.py)", "db": "Acceso a datos", "auth": "Claves y sesiones",
    "extractor": "Lectura con IA", "validador": "Motor de validación",
    "semaforo": "Semáforo de aportes", "enmascarado": "Enmascarado de datos personales",
    "lectores": "Lectura local (PDF y OCR)", "preparacion": "Preparación antes de la IA",
    "precios_ia": "Precios y modelos de IA", "rag": "Consultas al convenio (RAG)",
    "asistente": "Asistente del Panel", "validaciones_tramite": "Validaciones de trámites",
    "dashboard": "Agregados del Panel Sindical", "resultados_encuesta": "Resultados de encuestas",
    "encuestas": "Reglas de encuestas", "geo": "Georreferenciación de domicilios",
    "esquema": "Indicadores de la Sala de mando", "recursos": "Catálogo de Recursos",
    "render_admin": "Cambio de plan en Render", "render_planes": "Catálogo de planes de Render",
    "planificador": "Planificador de planes", "telegram": "Avisos por Telegram",
    "sentry_config": "Envío de errores a Sentry", "resumen_diario": "Resumen diario",
    "push": "Notificaciones push", "permisos": "Permisos por área",
    "modulos": "Módulos contratados", "entorno": "Entorno (local/pruebas/demo)",
    "qr": "Código QR", "filigrana": "Filigrana de la credencial", "chequeo": "Autodiagnóstico",
    "pg_cliente": "Cliente de Postgres", "empaquetar": "Empaquetado de descargas (sin conexión)",
    "mapa_funcional": "Generador del mapa funcional",
    "observabilidad.panel": "Semáforo de Observabilidad", "observabilidad.metricas_panel": "Gráficos de Grafana",
    "observabilidad.sentry_panel": "Lectura de errores de Sentry", "observabilidad.metricas_dia": "Métricas del día",
    "observabilidad.reglas": "Reglas de alertas", "observabilidad.hilo_colector": "Colector de métricas (hilo)",
    "observabilidad.colector_render": "Colector de métricas de Render", "observabilidad.remote_write": "Envío de métricas a Grafana",
    "xsk.motor.tablero": "Tablero de seguridad (XSK)", "xsk.motor.registro": "Registro de hallazgos (XSK)",
}
# Infraestructura que usa todo el mundo: no suma información en un mapa funcional.
OCULTOS = {"fechas", "errores", "version"}
# Guardianes de sesión/permiso: todas las rutas los usan; no se entra en ellos.
NO_SEGUIR = re.compile(r"^(_?exigir|sesion_actual|_cuil_seguro|_cuit_seguro|sindicato_activo|"
                       r"_rol_de|_panel_de|_sello_static|_es_navegacion|_contexto_base|marca_|"
                       r"_pase_landing)")
# Consultas de "¿está configurado?": una pantalla que muestra si Telegram tiene
# clave o si hay OCR instalado NO llama a Telegram ni corre el OCR. El módulo
# queda a la vista (la funcionalidad sí depende de él), pero no se entra.
RX_SQL_TABLA = re.compile(r'\b(?:from|join|update|into)\s+"?(\w+)', re.I)
SOLO_CONSULTA = re.compile(r"^(configurado|habilitado|disponible|token|\w*_disponible|\w*_habilitado)$")

SERVICIOS_LIB = {
    "anthropic": "API de Anthropic (Claude)", "fastembed": "Embeddings locales (fastembed)",
    "tesserocr": "OCR local (Tesseract)", "pytesseract": "OCR local (Tesseract)",
    "pypdfium2": "Lectura de PDF (pypdfium2)", "pywebpush": "Web Push",
    "sentry_sdk": "Sentry", "smtplib": "Correo (SMTP)",
}
SERVICIOS_HOST = [
    (r"api\.anthropic", "API de Anthropic (Claude)"), (r"apis\.datos\.gob\.ar", "Georef"),
    (r"nominatim", "Nominatim (OpenStreetMap)"), (r"api\.telegram\.org", "Telegram"),
    (r"grafana\.net|grafana", "Grafana Cloud"), (r"sentry\.io", "Sentry"),
    (r"api\.render\.com", "Render API"), (r"render\.com/pricing", "Render (precios)"),
    (r"api\.github\.com", "GitHub API"), (r"onrender\.com", "Otros entornos (Render)"),
    # Variables de entorno con las claves de cada servicio: la URL suele venir de ahí.
    (r"ANTHROPIC_API_KEY", "API de Anthropic (Claude)"), (r"GRAFANA_", "Grafana Cloud"),
    (r"SENTRY_", "Sentry"), (r"TELEGRAM_", "Telegram"), (r"RENDER_API_KEY", "Render API"),
    (r"VAPID_", "Web Push"),
]


# ---------------------------------------------------------------- lectura del código
def cargar_modulos():
    rutas = [p for p in RAIZ.glob("*.py") if not re.match(r"(test_|conftest)", p.name)]
    rutas += [p for d in ("observabilidad", "xsk/motor") for p in (RAIZ / d).glob("*.py")]
    mods = {}
    for p in rutas:
        nombre = ".".join(p.relative_to(RAIZ).with_suffix("").parts)
        try:
            mods[nombre] = (ast.parse(p.read_text(encoding="utf-8")), p)
        except SyntaxError:
            pass
    return mods


class Indice:
    def __init__(self, mods):
        self.mods = mods
        self.funcs = {}          # (mod, nombre) -> nodo
        self.alias = {}          # mod -> {alias: modulo local}
        self.desde = {}          # mod -> {nombre: (modulo local, nombre)}
        self.externos = {}       # mod -> {alias: paquete externo}
        self.urls = {}           # mod -> {CONSTANTE: servicio}
        self.docs = {}
        for m, (arbol, _) in mods.items():
            doc = ast.get_docstring(arbol) or ""
            self.docs[m] = re.split(r"(?<=[.:])\s|\n\n", doc.strip(), maxsplit=1)[0][:140] if doc else ""
            al, de, ex, ur = {}, {}, {}, {}
            for n in arbol.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.funcs[(m, n.name)] = n
            for n in ast.walk(arbol):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name in mods:
                            al[a.asname or a.name] = a.name
                        else:
                            ex[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    for a in n.names:
                        full = f"{n.module}.{a.name}"
                        if full in mods:
                            al[a.asname or a.name] = full
                        elif n.module in mods:
                            de[a.asname or a.name] = (n.module, a.name)
                        else:
                            ex[a.asname or a.name] = n.module.split(".")[0]
            for n in arbol.body:
                if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                    s = ast.unparse(n.value)
                    raices = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
                    srv = next((v for rx, v in SERVICIOS_HOST if re.search(rx, s)), None) or next(
                        (SERVICIOS_LIB[ex[r]] for r in raices if r in ex and ex[r] in SERVICIOS_LIB), None)
                    objetivos = n.targets if isinstance(n, ast.Assign) else [n.target]
                    for t in objetivos:
                        if srv and isinstance(t, ast.Name):
                            ur[t.id] = srv
            self.alias[m], self.desde[m], self.externos[m], self.urls[m] = al, de, ex, ur
        arbol_db = mods["db"][0]
        self.tablas = {c.name for c in arbol_db.body if isinstance(c, ast.ClassDef)
                       and any(k.arg == "table" and getattr(k.value, "value", None) is True
                               for k in c.keywords)}
        # SQLModel nombra la tabla con el nombre de la clase en minúsculas: así
        # aparece en el SQL escrito a mano (dashboard.py, reportes...).
        self.tabla_sql = {t.lower(): t for t in self.tablas}

    def resolver(self, m, nodo):
        """Qué función local o tabla nombra una expresión (Name o Attribute)."""
        if isinstance(nodo, ast.Name):
            n = nodo.id
            if (m, n) in self.funcs:
                return ("f", (m, n))
            if n in self.desde[m]:
                dm, dn = self.desde[m][n]
                if dm == "db" and dn in self.tablas:
                    return ("t", dn)
                if (dm, dn) in self.funcs:
                    return ("f", (dm, dn))
            if m == "db" and n in self.tablas:
                return ("t", n)
        elif isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
            base = self.alias[m].get(nodo.value.id)
            if base:
                if base == "db" and nodo.attr in self.tablas:
                    return ("t", nodo.attr)
                if (base, nodo.attr) in self.funcs:
                    return ("f", (base, nodo.attr))
        return None

    def analizar(self, clave):
        """Llamadas, tablas y servicios que usa UNA función (sin recursión)."""
        m, _ = clave
        f = self.funcs[clave]
        llama, tablas, servicios = set(), set(), set()
        # Los comentarios de documentación no son código: una docstring que
        # diga "saca el nombre from el trabajador" no toca la tabla Trabajador.
        docstrings = {id(x.body[0].value) for x in ast.walk(f)
                      if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and x.body
                      and isinstance(x.body[0], ast.Expr) and isinstance(x.body[0].value, ast.Constant)}
        for n in ast.walk(f):
            if id(n) in docstrings:
                continue
            if isinstance(n, (ast.Name, ast.Attribute)):
                r = self.resolver(m, n)
                if r and r[0] == "f" and r[1] != clave:
                    llama.add(r[1])
                elif r and r[0] == "t":
                    tablas.add(r[1])
                raiz = n.id if isinstance(n, ast.Name) else (n.value.id if isinstance(n.value, ast.Name) else None)
                if raiz in self.externos[m] and self.externos[m][raiz] in SERVICIOS_LIB:
                    servicios.add(SERVICIOS_LIB[self.externos[m][raiz]])
                if isinstance(n, ast.Name) and n.id in self.urls[m]:
                    servicios.add(self.urls[m][n.id])
                if isinstance(n, ast.Name) and n.id in self.desde[m]:
                    dm, dn = self.desde[m][n.id]      # p. ej. `from extractor import client`
                    if dn in self.urls.get(dm, {}):
                        servicios.add(self.urls[dm][dn])
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                # SQL escrito a mano: solo el nombre que sigue a FROM/JOIN/UPDATE/INTO.
                tablas.update(self.tabla_sql[x.lower()] for x in RX_SQL_TABLA.findall(n.value)
                              if x.lower() in self.tabla_sql)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and ("://" in n.value or n.value.isupper()):
                for rx, srv in SERVICIOS_HOST:
                    if re.search(rx, n.value):
                        servicios.add(srv)
        return llama, tablas, servicios


def rutas_de_main(idx):
    arbol = idx.mods["main"][0]
    out = []
    for n in arbol.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ("get", "post", "put", "delete", "patch")
                    and d.args and isinstance(d.args[0], ast.Constant)):
                plantillas = sorted({c.value for c in ast.walk(n) if isinstance(c, ast.Constant)
                                     and isinstance(c.value, str) and c.value.endswith(".html")})
                modulos = sorted({c.args[-1].value for c in ast.walk(n) if isinstance(c, ast.Call)
                                  and getattr(c.func, "id", getattr(c.func, "attr", "")) == "_exigir_modulo"
                                  and c.args and isinstance(c.args[-1], ast.Constant)})
                out.append({"metodo": d.func.attr.upper(), "ruta": d.args[0].value,
                            "funcion": n.name, "plantillas": plantillas, "modulos": modulos})
    return out


def js_de_plantilla(nombre):
    p = RAIZ / "templates" / nombre
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8", errors="ignore")
    # Solo un <script src=...> de verdad: un comentario que nombra un .js no lo carga.
    return sorted({j for j in re.findall(r"""<script[^>]+src=["'][^"']*static/([\w\-/]+\.js)""", txt)
                   if "vendor" not in j and ".min." not in j})


# Una plantilla es pantalla de una ruta si la LLAMA: fetch(...) o action= de un
# formulario, en la plantilla o en el JS propio que carga. Los enlaces de
# navegación y las imágenes (el logo está en todas) no cuentan.
RX_LLAMADA = re.compile(r"""(?:fetch\(\s*|action=\s*)[`'"](/[^`'"?#$]*)""")


def llamadas_de_plantillas():
    """{plantilla: {path o prefijo que llama}} (un prefijo si el path sigue con
    una variable: fetch('/api/tramite/' + id))."""
    out = {}
    for pl in (RAIZ / "templates").glob("*.html"):
        textos = [pl.read_text(encoding="utf-8", errors="ignore")]
        textos += [(RAIZ / "static" / j).read_text(encoding="utf-8", errors="ignore")
                   for j in js_de_plantilla(pl.name) if (RAIZ / "static" / j).exists()]
        out[pl.name] = {x for tx in textos for x in RX_LLAMADA.findall(tx)}
    return out


def plantilla_llama(llamados, ruta):
    base = ruta.split("{", 1)[0]
    for x in llamados:
        if "{" in ruta:
            if x.startswith(base) or (base.endswith("/") and x == base.rstrip("/")):
                return True
        elif x == ruta or x.rstrip("/") == ruta:
            return True
    return False


def nombre_mod(m):
    return NOMBRES.get(m, NOMBRES.get(m.split(".")[-1], m.split(".")[-1].replace("_", " ").capitalize()))


def armar():
    idx = Indice(cargar_modulos())
    cache = {}

    def info(k):
        if k not in cache:
            cache[k] = idx.analizar(k)
        return cache[k]

    def es_utilidad(k):
        """Función privada de OTRO módulo que no llama a nada del proyecto ni
        toca tablas ni servicios: una utilidad (limpiar un CUIL, normalizar un
        texto). Contarla como uso del módulo entero lo mezclaría todo."""
        return k[1].startswith("_") and k in idx.funcs and not any(info(k))

    permisos = {}
    for n in ast.walk(idx.mods["main"][0]):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PERMISOS_RUTAS" for t in n.targets) \
                and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    permisos[k.value] = v.value

    grupos = collections.OrderedDict()
    sin_clasificar = []
    for r in rutas_de_main(idx):
        for app, func, rx, pant in FUNCIONALIDADES:
            if re.search(rx, r["ruta"]):
                grupos.setdefault((app, func, pant), []).append(r)
                break
        else:
            sin_clasificar.append(r)

    orden = {(a, f): i for i, (a, f, _, _) in enumerate(FUNCIONALIDADES)}
    llamadas = llamadas_de_plantillas()
    funcionalidades = []
    for (app, func, pant), rutas in sorted(grupos.items(), key=lambda kv: orden[kv[0][:2]]):
        nodos, aristas = {}, set()

        def nodo(id_, col, etiqueta, **extra):
            nodos.setdefault(id_, {"id": id_, "col": col, "label": etiqueta, **extra})

        # De lo que DEVUELVE una ruta no cuentan los parciales (_algo.html: un
        # nombre citado en el código no es una pantalla) ni el login que se
        # muestra cuando no hay sesión, salvo en las funcionalidades de ingreso.
        devueltas = {p for r in rutas for p in r["plantillas"]
                     if not p.startswith("_") and ("Ingreso" in func or not p.endswith("_login.html"))}
        plantillas = sorted(devueltas | ({pant} if pant else set())
                            | {pl for pl, ll in llamadas.items() if any(plantilla_llama(ll, r["ruta"]) for r in rutas)})
        for p in plantillas:
            nodo("p:" + p, 0, p, js=js_de_plantilla(p))
            aristas.add(("p:" + p, "m:main"))
        nodo("m:main", 1, f"Rutas ({len(rutas)})", mod="main")
        funciones_por_mod = collections.defaultdict(set)
        visto = set()
        pendientes = [("main", r["funcion"]) for r in rutas]
        while pendientes:
            k = pendientes.pop()
            if k in visto or k not in idx.funcs:
                continue
            visto.add(k)
            llama, tablas, servicios = info(k)
            m = k[0]
            if m in OCULTOS:
                continue
            funciones_por_mod[m].add(k[1])
            origen = "m:" + m
            for t in tablas:
                nodo("t:" + t, 3, t)
                aristas.add((origen, "t:" + t))
            for s in servicios:
                nodo("s:" + s, 4, s)
                aristas.add((origen, "s:" + s))
            for d in llama:
                if NO_SEGUIR.match(d[1]) or d[0] in OCULTOS:
                    continue
                if d[0] != m and es_utilidad(d):
                    continue    # p. ej. validador._norm_cuil: no es "usar el motor de validación"
                if d[0] != m:
                    aristas.add((origen, "m:" + d[0]))
                if SOLO_CONSULTA.match(d[1]):
                    funciones_por_mod[d[0]].add(d[1])
                    continue
                pendientes.append(d)
        for m, fs in funciones_por_mod.items():
            if m != "main":
                nodo("m:" + m, 2, nombre_mod(m), mod=m)
            nodos["m:" + m]["funciones"] = sorted(fs)
        aristas = [a for a in aristas if a[0] in nodos and a[1] in nodos and a[0] != a[1]]
        mods_contratados = sorted({x for r in rutas for x in r["modulos"]})
        secciones = sorted({permisos[r["ruta"]] for r in rutas if r["ruta"] in permisos})
        funcionalidades.append({
            "app": app, "nombre": func, "rutas": rutas, "nodos": list(nodos.values()),
            "aristas": aristas, "modulos": mods_contratados, "permisos": secciones})

    modulos_doc = {m: {"nombre": nombre_mod(m), "doc": idx.docs.get(m, ""),
                       "archivo": str(idx.mods[m][1].relative_to(RAIZ)).replace("\\", "/")}
                   for m in idx.mods}
    # En Render no hay .git: el commit desplegado viene en RENDER_GIT_COMMIT.
    commit = os.environ.get("RENDER_GIT_COMMIT", "")[:7]
    if not commit:
        try:
            commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ,
                                    capture_output=True, text=True).stdout.strip()
        except OSError:
            commit = ""
    return {"funcionalidades": funcionalidades, "sin_clasificar": sin_clasificar,
            "modulos": modulos_doc, "commit": commit,
            "total_rutas": sum(len(f["rutas"]) for f in funcionalidades) + len(sin_clasificar)}


PAGINA = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Colm3na — Mapa funcional</title>
<script src="__VIS__"></script>
<style>
/* Estética de /entornos (templates/entornos.html): la "colmena nocturna" de
   los logins -- fondo oscuro de marca, grano, títulos en Barlow Condensed y
   el ámbar de Pruebas como acento. */
@font-face{font-family:'Barlow Condensed';font-weight:700;font-style:normal;src:url('__FUENTE__') format('woff2')}
:root{--tinta:#152238;--agua:#1a7a6b;--ambar:#ffb020;--texto:#e8edf5;--suave:rgba(232,237,245,.58);
 --panel:rgba(9,15,26,.62);--linea:rgba(255,255,255,.13);--caja:rgba(255,255,255,.06);
 --c0:#a78bfa;--c1:#5b8ff9;--c2:#34d1b5;--c3:#ffb020;--c4:#ff6b7d;
 --display:'Barlow Condensed','Arial Narrow',sans-serif;--mono:ui-monospace,'Cascadia Mono',Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--texto);
 display:grid;grid-template-columns:280px 1fr 330px;height:100vh;
 background:radial-gradient(900px 480px at 78% -10%,color-mix(in srgb,var(--agua) 26%,transparent),transparent 62%),
  linear-gradient(160deg,#0d1626 20%,var(--tinta) 70%,color-mix(in srgb,var(--tinta) 72%,#4a6da8))}
body::before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.07;mix-blend-mode:overlay;z-index:0;
 background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
nav,main,aside{position:relative;z-index:1}
nav,aside{overflow:auto;background:var(--panel);backdrop-filter:blur(6px)}
nav{border-right:1px solid var(--linea)}aside{border-left:1px solid var(--linea);padding:18px}
.marca{display:flex;align-items:center;gap:10px;margin:16px 16px 2px}.marca img{height:34px;width:auto}
nav h1{font-family:var(--display);font-size:26px;line-height:1;letter-spacing:1.5px;text-transform:uppercase;margin:0}
nav .sub{margin:4px 16px 10px;color:var(--suave);font-size:12px}
.acciones{display:flex;flex-wrap:wrap;gap:6px;margin:0 16px 12px}
.acciones a,.acciones button{appearance:none;cursor:pointer;border:1px solid var(--linea);background:var(--caja);color:var(--texto);
 border-radius:999px;padding:4px 11px;font:inherit;font-size:12px;text-decoration:none}
.acciones a:hover,.acciones button:hover{background:rgba(255,255,255,.14)}
.acciones .fuerte{background:var(--ambar);color:#1b1508;border-color:var(--ambar);font-weight:600}
.acciones form{margin:0}
nav h2{font-family:var(--display);font-size:15px;letter-spacing:1.5px;text-transform:uppercase;color:var(--ambar);margin:16px 16px 4px}
nav a.it{display:flex;justify-content:space-between;gap:8px;padding:5px 16px;color:inherit;text-decoration:none;cursor:pointer}
nav a.it:hover{background:rgba(255,255,255,.07)}
nav a.it.act{background:rgba(255,176,32,.14);font-weight:600;box-shadow:inset 3px 0 0 var(--ambar)}
nav a.it small{color:var(--suave);font-family:var(--mono);font-size:11px}
main{overflow:auto;padding:20px 24px}
h2.t{margin:0;font-family:var(--display);font-size:30px;line-height:1.05;letter-spacing:1px;text-transform:uppercase}
.chips{margin:8px 0 14px;display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;padding:2px 9px;border-radius:99px;background:var(--caja);border:1px solid var(--linea);color:var(--texto)}
.cols{display:grid;grid-template-columns:repeat(5,1fr);gap:0 26px;position:relative;margin-top:6px}
.cabe{font-family:var(--display);font-size:14px;letter-spacing:1.5px;text-transform:uppercase;color:var(--suave);margin-bottom:8px}
.col{display:flex;flex-direction:column;gap:8px}
.n{background:rgba(13,22,38,.78);border:1px solid var(--linea);border-left:4px solid var(--c);border-radius:8px;padding:6px 9px;
 cursor:pointer;position:relative;z-index:1;font-size:13px}
.n:hover,.n.sel{border-color:rgba(255,255,255,.6);border-left-color:var(--c)}.n.apagado{opacity:.22}
.n small{display:block;color:var(--suave);font-size:11px}
svg.lin{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0}
svg.lin path{fill:none;stroke:rgba(255,255,255,.22);stroke-width:1.3}svg.lin path.on{stroke:var(--ambar);stroke-width:2}
svg.lin path.off{opacity:.1}
aside h3{margin:0 0 4px;font-family:var(--display);font-size:22px;letter-spacing:.5px;text-transform:uppercase}
aside .doc{color:var(--suave);margin-bottom:12px}aside b{color:#fff}
aside ul{padding-left:18px;margin:4px 0 12px}aside li{margin:2px 0}
a{color:#9cc3ff}aside a,.inicio .app a{cursor:pointer}
code{font-family:var(--mono);font-size:12px;background:rgba(255,255,255,.1);padding:1px 5px;border-radius:4px}
.rutas{margin-top:22px}.rutas summary{cursor:pointer;color:var(--suave)}
.rutas table{border-collapse:collapse;margin-top:6px;font-size:12px}.rutas td{padding:2px 10px 2px 0}
.aviso{font-size:12px;color:var(--suave);background:var(--caja);border:1px solid var(--linea);border-radius:8px;padding:8px 10px;margin-top:14px}
.inicio p{color:var(--suave);max-width:760px}
.inicio .apps{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;margin-top:16px}
.inicio .app{background:var(--panel);border:1px solid var(--linea);border-radius:14px;padding:14px 16px}
.inicio .app h3{margin:0 0 6px;font-family:var(--display);font-size:20px;letter-spacing:1px;text-transform:uppercase;color:var(--ambar)}
.inicio .app a{display:block;padding:1px 0}
.modos{display:flex;gap:4px;margin:0 16px 8px}
.modos button{flex:1;appearance:none;border:1px solid var(--linea);background:transparent;color:var(--texto);border-radius:999px;padding:5px;cursor:pointer;font:inherit;font-size:13px}
.modos button.on{background:#fff;color:var(--tinta);border-color:#fff;font-weight:600}
nav a.it.exp{background:rgba(255,176,32,.14);font-weight:600;box-shadow:inset 3px 0 0 var(--ambar)}
main.grafo{padding:0;position:relative;overflow:hidden}#g{position:absolute;inset:0}
.barra{position:absolute;top:12px;left:14px;z-index:2;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.barra button{appearance:none;border:1px solid var(--linea);background:var(--panel);color:var(--texto);border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit;font-size:12px}
.barra button:hover{background:rgba(255,255,255,.14)}
.ley{background:var(--panel);border:1px solid var(--linea);border-radius:999px;padding:5px 12px;font-size:12px;color:var(--suave)}
.ley i{display:inline-block;width:10px;height:10px;margin:0 4px 0 9px;vertical-align:-1px}
@media (max-width:1000px){body{grid-template-columns:1fr;height:auto}nav,aside{border:0}.cols{grid-template-columns:1fr}svg.lin{display:none}}
</style></head><body>
<nav id="nav"></nav><main id="main"></main><aside id="det"></aside>
<script>
const D=__DATOS__;
const LOGO="__LOGO__";
const COLS=["Pantalla","Rutas","Código","Datos","Servicios"],COLOR=["var(--c0)","var(--c1)","var(--c2)","var(--c3)","var(--c4)"];
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const apps=[...new Set(D.funcionalidades.map(f=>f.app))];
const usos={};D.funcionalidades.forEach((f,i)=>f.nodos.forEach(n=>(usos[n.id]=usos[n.id]||[]).push(i)));
let actual=-1,sel=null,modo='lista';const exp=new Set();
function nav(){let h=`<div class="marca">${LOGO?`<img src="${LOGO}" alt="">`:""}<h1>Mapa funcional</h1></div>
 <div class="sub">${D.generado?esc(D.generado)+" · ":""}${D.commit?"commit "+esc(D.commit)+" · ":""}${D.total_rutas} rutas</div>
 <div class="acciones">__ACCIONES__</div>
 <div class="modos"><button class="${modo==='lista'?'on':''}" onclick="setModo('lista')">Lista</button><button class="${modo==='grafo'?'on':''}" onclick="setModo('grafo')">Grafo</button></div>`;
 if(modo==='lista')h+=`<a class="it ${actual<0?'act':''}" onclick="ir(-1)">Vista general</a>`;
 apps.forEach(a=>{h+=`<h2>${esc(a)}</h2>`;D.funcionalidades.forEach((f,i)=>{if(f.app!==a)return;
  h+=modo==='lista'?`<a class="it ${i===actual?'act':''}" onclick="ir(${i})">${esc(f.nombre)}<small>${f.rutas.length}</small></a>`
   :`<a class="it ${exp.has(i)?'exp':''}" onclick="alternar(${i})">${esc(f.nombre)}<small>${f.rutas.length}</small></a>`})});
 if(D.sin_clasificar.length)h+=`<h2>Revisar</h2><a class="it" onclick="sinClasificar()">Sin clasificar<small>${D.sin_clasificar.length}</small></a>`;
 document.getElementById("nav").innerHTML=h}
function ir(i){if(modo!=="lista"){modo="lista";document.getElementById("main").classList.remove("grafo")}actual=i;sel=null;nav();i<0?general():vista(D.funcionalidades[i]);detalleInicial();try{history.replaceState(null,"","#"+i)}catch(e){}}
function general(){let h=`<div class="inicio"><h2 class="t">Colm3na por funcionalidad</h2>
 <p>Cada funcionalidad muestra qué pantalla la usa, qué rutas la atienden, qué código corre, qué tablas toca y qué servicios externos llama. Todo sale del código.</p><div class="apps">`;
 apps.forEach(a=>{h+=`<div class="app"><h3>${esc(a)}</h3>`;D.funcionalidades.forEach((f,i)=>{if(f.app===a){
  const t=f.nodos.filter(n=>n.col===3).length,s=f.nodos.filter(n=>n.col===4).length;
  h+=`<a onclick="ir(${i})">${esc(f.nombre)} <small style="color:var(--suave)">· ${t} tablas${s?` · ${s} servicios`:''}</small></a>`}});h+="</div>"});
 document.getElementById("main").innerHTML=h+"</div></div>"}
function vista(f){let h=`<h2 class="t">${esc(f.app)} · ${esc(f.nombre)}</h2><div class="chips">`;
 f.modulos.forEach(m=>h+=`<span class="chip">módulo contratado: ${esc(m)}</span>`);
 f.permisos.forEach(p=>h+=`<span class="chip">permiso: ${esc(p)}</span>`);
 h+=`</div><div class="cols" id="cols"><svg class="lin" id="lin"></svg>`;
 COLS.forEach((c,ci)=>{h+=`<div><div class="cabe">${c}</div><div class="col">`;
  f.nodos.filter(n=>n.col===ci).sort((a,b)=>a.label.localeCompare(b.label)).forEach(n=>{
   const otras=(usos[n.id]||[]).length-1;
   h+=`<div class="n" id="${esc(n.id)}" style="--c:${COLOR[ci]}" onclick="elegir('${esc(n.id)}')">${esc(n.label)}${n.funciones&&ci!==1?`<small>${n.funciones.length} funciones</small>`:''}${otras>0&&ci>1?`<small>+ en ${otras} funcionalidades más</small>`:''}</div>`});
  h+="</div></div>"});
 h+=`</div><details class="rutas"><summary>Las ${f.rutas.length} rutas</summary><table>`+
  f.rutas.map(r=>`<tr><td><code>${r.metodo}</code></td><td><code>${esc(r.ruta)}</code></td><td>${esc(r.funcion)}()</td></tr>`).join("")+
  `</table></details><div class="aviso">Orientación, no verdad: se leen las llamadas directas entre funciones; las dinámicas no se ven. Los guardianes de sesión no se recorren para no repetir lo mismo en todas. Una función que sirve a afiliados y a empresas según un parámetro trae las tablas de las dos: el mapa no sabe qué rama corre.</div>`;
 document.getElementById("main").innerHTML=h;requestAnimationFrame(lineas)}
function lineas(){const f=D.funcionalidades[actual];if(!f)return;const cols=document.getElementById("cols"),svg=document.getElementById("lin");
 if(!cols)return;const b=cols.getBoundingClientRect();let h="";
 f.aristas.forEach(([a,z])=>{const A=document.getElementById(a),Z=document.getElementById(z);if(!A||!Z)return;
  let ra=A.getBoundingClientRect(),rz=Z.getBoundingClientRect();if(ra.left>rz.left){[ra,rz]=[rz,ra]}
  const x1=ra.right-b.left,y1=ra.top+ra.height/2-b.top,x2=rz.left-b.left,y2=rz.top+rz.height/2-b.top,m=(x1+x2)/2;
  const same=Math.abs(ra.left-rz.left)<5;const d=same?`M${ra.left-b.left},${y1} C${ra.left-b.left-30},${y1} ${ra.left-b.left-30},${y2} ${ra.left-b.left},${y2}`:`M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2}`;
  const cl=sel?((a===sel||z===sel)?"on":"off"):"";h+=`<path d="${d}" class="${cl}"/>`});
 svg.innerHTML=h;document.querySelectorAll(".n").forEach(n=>{n.classList.toggle("sel",n.id===sel);
  n.classList.toggle("apagado",!!sel&&n.id!==sel&&!f.aristas.some(([a,z])=>(a===sel&&z===n.id)||(z===sel&&a===n.id)))})}
function elegir(id){sel=sel===id?null:id;lineas();if(!sel)return detalleInicial();
 const f=D.funcionalidades[actual],n=f.nodos.find(x=>x.id===id);let h="";
 if(id.startsWith("m:")){const m=D.modulos[n.mod]||{};h+=`<h3>${esc(n.label)}</h3><div class="doc"><code>${esc(m.archivo||"")}</code><br>${esc(m.doc||"")}</div>
  <b>Funciones que usa esta funcionalidad</b><ul>${(n.funciones||[]).map(x=>`<li><code>${esc(x)}</code></li>`).join("")}</ul>`}
 else if(id.startsWith("p:")){h+=`<h3>${esc(n.label)}</h3><div class="doc">Plantilla en <code>templates/</code></div>${n.js&&n.js.length?`<b>JavaScript que carga</b><ul>${n.js.map(j=>`<li><code>static/${esc(j)}</code></li>`).join("")}</ul>`:""}`}
 else if(id.startsWith("t:")){h+=`<h3>${esc(n.label)}</h3><div class="doc">Tabla (modelo en <code>db.py</code>)</div>`}
 else{h+=`<h3>${esc(n.label)}</h3><div class="doc">Servicio externo o librería con recurso propio</div>`}
 const u=(usos[id]||[]).filter(i=>i!==actual);
 h+=`<b>También lo usan</b>${u.length?`<ul>${u.map(i=>`<li><a onclick="ir(${i})">${esc(D.funcionalidades[i].app)} · ${esc(D.funcionalidades[i].nombre)}</a></li>`).join("")}</ul>`:"<p>Ninguna otra funcionalidad.</p>"}`;
 document.getElementById("det").innerHTML=h}
function detalleInicial(){document.getElementById("det").innerHTML=actual<0?
 `<h3>Cómo se lee</h3><div class="doc">Elegí una funcionalidad a la izquierda. Tocá cualquier caja para ver qué hace y qué otras funcionalidades la usan: sirve para saber qué se afecta si la cambiás.</div>`:
 `<h3>Tocá una caja</h3><div class="doc">Se resaltan sus conexiones y acá ves el detalle y en qué otras funcionalidades aparece.</div>`}
function sinClasificar(){actual=-2;nav();document.getElementById("main").innerHTML=`<h2 class="t">Rutas sin clasificar</h2>
 <p>No encajan en ninguna funcionalidad de <code>mapa_funcional.py</code>. Sumarles una regla.</p><table>`+
 D.sin_clasificar.map(r=>`<tr><td><code>${r.metodo}</code></td><td><code>${esc(r.ruta)}</code></td><td>${esc(r.funcion)}()</td></tr>`).join("")+"</table>"}
window.addEventListener("resize",()=>requestAnimationFrame(lineas));

// ------------------------------------------------------------ vista Grafo
const COL_APP={"Común":"#94a3b8","Afiliado":"#5b8ff9","Empresa":"#3ecfae","Sindicato":"#ff6b7d","Plataforma":"#a78bfa","Entornos":"#ffb020"};
const TIPO=[{shape:"triangle",color:"#a78bfa",size:10},null,{shape:"dot",color:"#34d1b5",size:10},
            {shape:"square",color:"#ffb020",size:8},{shape:"hexagon",color:"#ff6b7d",size:12}];
const FUENTE={color:"#e8edf5",strokeWidth:4,strokeColor:"#0d1626"};
let red=null,gN=null,gE=null;const refN=new Map(),refE=new Map();
const compInfo={};D.funcionalidades.forEach(f=>f.nodos.forEach(n=>{if(!compInfo[n.id])compInfo[n.id]=n}));
function setModo(m){modo=m;nav();if(m==="grafo")montarGrafo();else ir(actual<-1?-1:actual)}
function nodoFunc(i){const f=D.funcionalidades[i],e=exp.has(i);return{id:"f:"+i,label:f.nombre,shape:"dot",size:e?18:12,
 color:{background:COL_APP[f.app],border:e?"#ffffff":COL_APP[f.app]},borderWidth:e?4:1,font:{...FUENTE,size:15},
 title:f.app+" · "+f.nombre+" — "+f.rutas.length+" rutas. Clic: desplegar / replegar"}}
function montarGrafo(){const mn=document.getElementById("main");mn.classList.add("grafo");
 mn.innerHTML=`<div id="g"></div><div class="barra"><button onclick="limpiar()">Limpiar</button><button onclick="enfocar()">Enfocar desplegadas</button><button onclick="red&&red.fit({animation:true})">Ver todo</button>
 <span class="ley">Funcionalidad ● (clic para desplegar)<i style="background:#a78bfa;clip-path:polygon(50% 0,100% 100%,0 100%)"></i>Pantalla<i style="background:#34d1b5;border-radius:50%"></i>Código<i style="background:#ffb020"></i>Tabla<i style="background:#ff6b7d;clip-path:polygon(25% 0,75% 0,100% 50%,75% 100%,25% 100%,0 50%)"></i>Servicio</span></div>`;
 gN=new vis.DataSet();gE=new vis.DataSet();refN.clear();refE.clear();
 // Centro: el isotipo de Colm3na (5 veces el ícono de una funcionalidad), unido a las seis apps.
 if(LOGO)gN.add({id:"c:colm3na",shape:"image",image:LOGO,size:60,mass:8,title:"Colm3na"});
 apps.forEach(a=>gN.add({id:"a:"+a,label:a.toUpperCase(),shape:"box",margin:10,mass:3,color:{background:COL_APP[a],border:COL_APP[a]},font:{color:"#0d1626",size:18,face:"Barlow Condensed, Arial Narrow, sans-serif",bold:true}}));
 if(LOGO)apps.forEach(a=>gE.add({id:"c|a:"+a,from:"c:colm3na",to:"a:"+a,color:{color:COL_APP[a],opacity:.6},width:3,length:170}));
 D.funcionalidades.forEach((f,i)=>{gN.add(nodoFunc(i));gE.add({id:"a:"+f.app+"|f:"+i,from:"a:"+f.app,to:"f:"+i,color:{color:COL_APP[f.app],opacity:.5},width:2})});
 red=new vis.Network(document.getElementById("g"),{nodes:gN,edges:gE},{
  physics:{solver:"forceAtlas2Based",forceAtlas2Based:{gravitationalConstant:-90,springLength:110,avoidOverlap:.6},stabilization:{iterations:500}},
  edges:{smooth:{type:"continuous"},color:{color:"rgba(255,255,255,.28)",highlight:"#ffb020",hover:"#ffffff"}},interaction:{hover:true,tooltipDelay:150}});
 red.on("stabilizationIterationsDone",()=>red.setOptions({physics:{enabled:false}}));
 red.on("click",p=>{if(!p.nodes.length)return;const id=p.nodes[0];
  if(id.startsWith("f:"))alternar(+id.slice(2));else if(!/^[ac]:/.test(id))detalleComp(id)});
 const previas=[...exp];exp.clear();previas.forEach(i=>desplegar(i,true));acomodar();detalleGrafo()}
function acomodar(n){red.setOptions({physics:{enabled:true}});red.stabilize(n||300)}
function congelar(v){gN.update(gN.getIds().map(id=>({id,fixed:v})))}
function alternar(i){if(modo!=="grafo")return;exp.has(i)?replegar(i):desplegar(i);nav()}
function desplegar(i,sinAcomodar){const f=D.funcionalidades[i],fid="f:"+i;exp.add(i);
 const base=red?red.getPositions([fid])[fid]:null;if(!sinAcomodar)congelar(true);
 const mapa=id=>id==="m:main"?fid:id;
 const nuevos=f.nodos.filter(n=>n.id!=="m:main"&&!gN.get(n.id)).sort((a,b)=>a.col-b.col||a.label.localeCompare(b.label));
 const radio=110+nuevos.length*7;
 f.nodos.forEach(n=>{if(n.id==="m:main")return;if(!refN.has(n.id))refN.set(n.id,new Set());refN.get(n.id).add(i)});
 nuevos.forEach((n,k)=>{const s=TIPO[n.col],ang=2*Math.PI*k/nuevos.length;
   gN.add({id:n.id,label:n.label,shape:s.shape,size:s.size,color:{background:s.color,border:s.color},
   font:{...FUENTE,size:12,strokeWidth:3},
   x:base?base.x+radio*Math.cos(ang):undefined,y:base?base.y+radio*Math.sin(ang):undefined,fixed:false,
   title:COLS[n.col]+": "+n.label})});
 f.aristas.forEach(([a,z])=>{const A=mapa(a),Z=mapa(z),eid=A+"|"+Z;if(A===Z)return;
  if(!refE.has(eid))refE.set(eid,new Set());refE.get(eid).add(i);if(!gE.get(eid))gE.add({id:eid,from:A,to:Z,arrows:{to:{enabled:true,scaleFactor:.4}}})});
 gN.update(nodoFunc(i));if(!sinAcomodar){acomodar(60);red.once("stabilizationIterationsDone",()=>{congelar(false);enfocar()})}detalleGrafo()}
function enfocar(){const ids=[...refN.keys(),...[...exp].map(i=>"f:"+i)];if(ids.length)red.fit({nodes:ids,animation:{duration:500}});else red.fit({animation:true})}
function replegar(i){exp.delete(i);
 refE.forEach((s,eid)=>{if(s.delete(i)&&!s.size){refE.delete(eid);gE.remove(eid)}});
 refN.forEach((s,id)=>{if(s.delete(i)&&!s.size){refN.delete(id);gN.remove(id)}});
 gN.update(nodoFunc(i));detalleGrafo()}
function limpiar(){[...exp].forEach(replegar);nav();red.fit({animation:true})}
function detalleGrafo(){const l=[...exp];document.getElementById("det").innerHTML=
 `<h3>Grafo</h3><div class="doc">Clic en una funcionalidad (en el grafo o a la izquierda) para desplegar su pantalla, código, tablas y servicios. Se van sumando: lo que dos funcionalidades comparten queda como un solo nodo unido a ambas. Otro clic la repliega.</div>`+
 (l.length?`<b>Desplegadas</b><ul>${l.map(i=>`<li><a onclick="alternar(${i})">${esc(D.funcionalidades[i].app)} · ${esc(D.funcionalidades[i].nombre)}</a> <small style="color:var(--suave)">(clic: replegar)</small></li>`).join("")}</ul>`:"")+
 (l.length>1?compartidos():"")}
function compartidos(){const c=[...refN].filter(([id,s])=>s.size>1).map(([id])=>compInfo[id]).sort((a,b)=>a.col-b.col);
 return `<b>En común entre las desplegadas</b>${c.length?`<ul>${c.map(n=>`<li><a onclick="detalleComp('${esc(n.id)}')">${esc(n.label)}</a> <small style="color:var(--suave)">${COLS[n.col].toLowerCase()}</small></li>`).join("")}</ul>`:"<p>Nada en común.</p>"}`}
function detalleComp(id){const n=compInfo[id];if(!n)return;if(red&&gN.get(id))red.selectNodes([id]);
 let h=`<h3>${esc(n.label)}</h3>`;
 if(id.startsWith("m:")){const m=D.modulos[n.mod]||{};h+=`<div class="doc"><code>${esc(m.archivo||"")}</code><br>${esc(m.doc||"")}</div>`}
 else h+=`<div class="doc">${COLS[n.col]}</div>`;
 const u=usos[id]||[];h+=`<b>Lo usan ${u.length} funcionalidades</b><ul>${u.map(i=>`<li><a onclick="alternar(${i})">${exp.has(i)?"✓ ":""}${esc(D.funcionalidades[i].app)} · ${esc(D.funcionalidades[i].nombre)}</a></li>`).join("")}</ul>
 <div class="aviso">Clic en una para desplegarla (o replegarla) en el grafo. <a onclick="detalleGrafo()">Volver al resumen</a></div>`;
 document.getElementById("det").innerHTML=h}

const ini=parseInt((location.hash||"#-1").slice(1));ir(isNaN(ini)||!D.funcionalidades[ini]?-1:ini);
</script></body></html>"""


def pagina(datos, vis_src, logo_src, fuente_src, acciones_html=""):
    """El HTML completo. Lo usan la versión local (main, abajo) y /entornos/mapa
    (main.py), cada uno con sus rutas a la librería del grafo, el isotipo y la
    fuente: en la app van por /static/ con su sello; en local, relativas."""
    return (PAGINA.replace("__DATOS__", json.dumps(datos, ensure_ascii=False))
            .replace("__VIS__", vis_src).replace("__LOGO__", logo_src)
            .replace("__FUENTE__", fuente_src).replace("__ACCIONES__", acciones_html))


PROMPT_MD = RAIZ / "docs" / "prompts" / "MAPA_FUNCIONAL.md"
PROMPT_HTML = RAIZ / "recursos" / "prompt-mapa-funcional.html"


def publicar_prompt():
    """docs/prompts/MAPA_FUNCIONAL.md -> recursos/prompt-mapa-funcional.html, el
    Recurso de /entornos. El Markdown es la fuente: se edita ahí y se vuelve a
    publicar con `python mapa_funcional.py --publicar-prompt`. Usa markdown-it
    (solo en la PC de quien publica; la app sirve el HTML ya hecho)."""
    from markdown_it import MarkdownIt
    cuerpo = MarkdownIt("commonmark").enable("table").render(PROMPT_MD.read_text(encoding="utf-8"))
    # El bloque del prompt (el único ```text) lleva botón de copiar.
    cuerpo = cuerpo.replace('<pre><code class="language-text">',
                            '<div class="copiar"><button type="button" onclick="copiar(this)">Copiar el prompt</button></div>'
                            '<pre class="prompt"><code class="language-text">', 1)
    PROMPT_HTML.write_text(PAGINA_PROMPT.replace("__CUERPO__", cuerpo), encoding="utf-8")
    print(f"{PROMPT_HTML.relative_to(RAIZ)} publicado desde {PROMPT_MD.relative_to(RAIZ)}")


PAGINA_PROMPT = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Colm3na — Prompt: mapa funcional</title>
<style>
@font-face{font-family:'Barlow Condensed';font-weight:700;src:url('/static/fonts/barlow-condensed-bold.woff2') format('woff2')}
:root{--tinta:#152238;--agua:#1a7a6b;--ambar:#ffb020;--texto:#e8edf5;--suave:rgba(232,237,245,.62);--linea:rgba(255,255,255,.14);
 --display:'Barlow Condensed','Arial Narrow',sans-serif;--mono:ui-monospace,'Cascadia Mono',Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;padding:34px 16px 70px;font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--texto);
 background:radial-gradient(900px 480px at 78% -10%,color-mix(in srgb,var(--agua) 26%,transparent),transparent 62%),
  linear-gradient(160deg,#0d1626 20%,var(--tinta) 70%,color-mix(in srgb,var(--tinta) 72%,#4a6da8)) fixed}
main{max-width:920px;margin:0 auto}
h1{font-family:var(--display);font-size:44px;line-height:1.02;letter-spacing:1.5px;text-transform:uppercase;margin:0 0 12px}
h2{font-family:var(--display);font-size:28px;letter-spacing:1px;text-transform:uppercase;color:var(--ambar);margin:34px 0 8px}
p,li{color:var(--texto)}a{color:#9cc3ff}strong{color:#fff}hr{border:0;border-top:1px solid var(--linea);margin:28px 0}
code{font-family:var(--mono);font-size:.88em;background:rgba(255,255,255,.1);padding:1px 5px;border-radius:4px}
pre{background:rgba(9,15,26,.72);border:1px solid var(--linea);border-radius:14px;padding:18px 20px;overflow:auto;font-size:13px;line-height:1.55}
pre code{background:none;padding:0;white-space:pre-wrap}
pre.prompt{border-color:rgba(255,176,32,.55);box-shadow:0 0 0 5px rgba(255,176,32,.08)}
.copiar{display:flex;justify-content:flex-end;margin:0 0 -6px}
.copiar button{appearance:none;cursor:pointer;border:0;border-radius:999px;padding:7px 16px;font:inherit;font-size:13px;font-weight:600;background:var(--ambar);color:#1b1508}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0;display:block;overflow-x:auto}
th,td{border:1px solid var(--linea);padding:6px 8px;text-align:left;vertical-align:top}th{color:var(--ambar);font-weight:600}
</style></head><body><main>
__CUERPO__
</main>
<script>
function copiar(b){const t=b.parentElement.nextElementSibling.innerText;
 navigator.clipboard.writeText(t).then(()=>{b.textContent="Copiado";setTimeout(()=>b.textContent="Copiar el prompt",1800)},
 ()=>{b.textContent="Seleccioná y copiá a mano"})}
</script></body></html>"""


def main():
    if "--publicar-prompt" in sys.argv:
        return publicar_prompt()
    import fechas
    datos = armar()
    datos["generado"] = "Generado " + fechas.ahora_texto()
    SALIDA.parent.mkdir(exist_ok=True)
    logo = RAIZ / "static" / "colmena_dorada.webp"   # el isotipo, sin la palabra
    logo_uri = ("data:image/webp;base64," + base64.b64encode(logo.read_bytes()).decode()) if logo.exists() else ""
    SALIDA.write_text(pagina(datos, "../static/vendor/vis-network/vis-network.min.js", logo_uri,
                             "../static/fonts/barlow-condensed-bold.woff2"), encoding="utf-8")
    print(f"{SALIDA.relative_to(RAIZ)}: {len(datos['funcionalidades'])} funcionalidades, "
          f"{datos['total_rutas']} rutas, {len(datos['sin_clasificar'])} sin clasificar")
    if "--no-abrir" not in sys.argv:
        webbrowser.open(SALIDA.as_uri())


if __name__ == "__main__":
    main()

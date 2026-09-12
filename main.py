"""Servidor de Mi Trabajo: la app y todas sus rutas (FastAPI + Jinja2).

Los datos viven en Postgres (db.py; SQLite solo en tests). Las rutas están
agrupadas por actor, cada grupo con su encabezado de comentario:

  Público y PWA   /, /sw.js, /logo/{id}, verificación pública de credencial,
                  /api/version
  Trabajador      /ingresar, /app/inicio, /app (Tu recibo, Mis aportes,
                  Credencial, Capacitación, Novedades, Trámites),
                  /app/notificaciones, /app/convenio, /api/leer,
                  /api/validar, /api/reportar, /api/enviar-sindicato, ...
  Sindicato       /admin/inicio, /admin (quince pestañas), /admin/dashboard
                  (Panel Sindical + Asistente) y los ABM de padrón,
                  catálogo, contenido, notificaciones, trámites, empleadores
                  y convenio
  Empresa         /ingresar-empresa, /empresa/inicio, /empresa
  Plataforma      /plataforma (sindicatos, módulos, marca, configuración)
  Interno         /entornos (landing con PIN) y /recursos/...

Cada rol tiene su cookie (COOKIES_POR_ROL) y el sindicato de cada request
sale SIEMPRE de la cookie, nunca de un parámetro. El listado completo de
rutas, con rol y descripción, está en la documentación técnica generada
(`recursos/documentacion-tecnica.html`, pestaña Componentes).

Arrancar con:  uvicorn main:app --reload   (ver README.md)
"""

import traceback
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Form, Cookie, Response, Body, Header, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response as BinResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from sqlmodel import select

import encuestas
import fechas
import db
import auth
import validaciones_tramite
import push
import errores
from errores import ErrorApp
from db import (Area, Concepto, Formula, Reporte, Sindicato, UsuarioSindicato, Trabajador,
                CuentaTrabajador, EnvioSindicato, ReciboVerificado, ConfiguracionPlataforma, Noticia,
                Beneficio, Seccional, ReciboSospechoso, Notificacion, NotificacionDestinatario,
                TipoTramite, CampoTramite, Tramite, RespuestaTramite, NotaTramite, TramiteLog,
                Empleador, CuentaEmpleador, NotificacionEmpleador, NotificacionEmpleadorDestinatario,
                TipoTramiteEmpleador, CampoTramiteEmpleador, TramiteEmpleador, RespuestaTramiteEmpleador,
                NotaTramiteEmpleador, TramiteEmpleadorLog,
                Convenio, DocumentoConvenio, FragmentoConvenio, ConsultaConvenio)
from extractor import extraer, extraer_aportes
from validador import (validar, detectar_nuevos, detectar_provisorios, buscar_similar,
                        rangos_se_superponen, cuil_no_coincide, error_de_expresion,
                        CATEGORIAS_UNIVERSALES)
from filigrana import filigrana_svg
from qr import qr_svg, url_verificacion, codigo_efimero, verificar_codigo_efimero, TTL_QR_SEGUNDOS
from semaforo import calcular_semaforo, advertencia_ultimo_deposito
from version import VERSION_TRABAJADOR, VERSION_ADMIN, VERSION_PLATAFORMA, FECHA_VERSION
import entorno
import permisos as permisos_mod
from permisos import SECCION_SUPER_ADMIN
import recursos
import render_admin
import render_planes
import planificador
from modulos import MODULOS, MODULOS_INICIALES
import dashboard
import asistente
import rag

import mimetypes
mimetypes.add_type("font/woff2", ".woff2")  # algunos Windows no lo traen registrado -> se servía como text/plain

app = FastAPI(title="Mi Trabajo — validador de recibos")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/sw.js")
def service_worker():
    """Servido desde la raíz (no /static/sw.js) a propósito: el scope
    maximo permitido de un service worker es la carpeta donde vive el
    archivo -- si estuviera bajo /static/, no podria pedir scope /app."""
    return FileResponse("static/sw.js", media_type="application/javascript",
                         headers={"Service-Worker-Allowed": "/app"})


def _es_navegacion_de_pagina(request: Request) -> bool:
    """True si esto es un <form> de página completa (pide text/html), no una
    llamada fetch/JS -- esas nunca mandan ese Accept y ya saben leer el JSON
    de error (`await r.json()`), no hay que redirigirlas a ningún lado."""
    return "text/html" in request.headers.get("accept", "")


def _panel_de(path: str) -> str | None:
    """A qué pantalla volver según el prefijo de la ruta que falló.
    /empresa y /api/empresa se chequean ANTES que /app y /api genéricos --
    si no, cualquier ruta de la API del empleador (que también empieza con
    /api) caería en la rama de trabajador y redirigiría al login equivocado."""
    if path.startswith("/plataforma"):
        return "/plataforma"
    if path.startswith("/admin"):
        return "/admin"
    if path.startswith("/empresa") or path.startswith("/api/empresa"):
        return "/ingresar-empresa"
    if path.startswith("/app") or path.startswith("/api"):
        return "/ingresar"
    return None


def _rol_de(path: str) -> str | None:
    """Qué rol de sesión corresponde a esa área -- mismo mapeo que
    _panel_de, para saber qué cookie de sesión mirar."""
    if path.startswith("/plataforma"):
        return "plataforma"
    if path.startswith("/admin"):
        return "sindicato"
    if path.startswith("/empresa") or path.startswith("/api/empresa"):
        return "empleador"
    if path.startswith("/app") or path.startswith("/api"):
        return "trabajador"
    return None


@app.exception_handler(Exception)
async def error_no_manejado(request: Request, exc: Exception):
    """Red de seguridad: sin esto, cualquier excepción no prevista devuelve
    el 500 de texto plano de Starlette (no JSON) -- y el frontend, que
    siempre espera JSON (`await r.json()`), explota con "unexpected token"
    en vez de mostrar el banner de error de siempre. No reemplaza arreglar
    la causa real (se loguea completa para poder diagnosticarla después),
    solo evita que una excepción cualquiera tire la pantalla abajo.

    Para un <form> de página completa (no fetch/JS), esto además evita el
    mismo problema que sesion_vencida_o_denegada de acá abajo: un 500 crudo
    reemplazaba TODA la pantalla por el JSON -- "error técnico feo en
    pantalla negra" que un usuario ve igual con la sesión bien, si lo que
    falló fue otra cosa (ej. un hipo transitorio de conexión a la base;
    Postgres en Render puede cerrar conexiones ociosas -- el engine ya usa
    pool_pre_ping + pool_recycle=300 para mitigarlo, pero no elimina un
    error de red puntual en el medio de un request). Se vuelve al panel
    con un aviso en vez del JSON crudo; la excepción se loguea igual."""
    # Referencia corta para poder encontrar ESTE error en el log del
    # servidor: se imprime junto al traceback y se le muestra a la persona.
    # Es lo único que hace rastreable un error que, por definición, no
    # sabíamos que podía pasar (si supiéramos, tendría su propio código en
    # errores.py y no llegaría hasta acá).
    ref = uuid.uuid4().hex[:8]
    codigo = errores.codigo_de_ruta(request.url.path)
    print(f"[{codigo} ref={ref}] {request.method} {request.url.path}")
    traceback.print_exc()
    if _es_navegacion_de_pagina(request):
        destino = _panel_de(request.url.path)
        if destino:
            return RedirectResponse(f"{destino}?error=guardado&ref={ref}", status_code=303)
    # El mensaje tiene que ser genérico DE VERDAD: este handler cubre TODAS
    # las rutas de la app (recibos, trámites, notificaciones, aportes). Cuando
    # decía "probá con una foto más nítida" mandaba a cualquiera a sacar la
    # foto de nuevo por un error que no tenía nada que ver -- pasó con una
    # fórmula mal cargada, que no se arregla con una foto mejor.
    cuerpo = errores.cuerpo(codigo)
    cuerpo["ref"] = ref
    return JSONResponse(status_code=500, content=cuerpo)


@app.exception_handler(HTTPException)
async def sesion_vencida_o_denegada(request: Request, exc: HTTPException):
    """Los formularios de /admin y /plataforma son POST de página completa
    (no fetch): si la sesión venció (15 min sin uso) y la ruta responde
    403/401 con el HTTPException de siempre, el navegador reemplazaba TODA
    la pantalla por el JSON crudo de FastAPI -- "error técnico feo en
    pantalla negra" que solo se arreglaba reingresando a mano. Para ese
    caso puntual (sesión inválida o del rol equivocado -- ej. otra pestaña
    logueada como trabajador pisó la cookie que esta pantalla necesitaba,
    ver COOKIES_POR_ROL -- + navegación de página, no una llamada
    fetch/JS) se redirige a la pantalla de login correspondiente en vez de
    mostrar el JSON.

    Y desde el sistema de Áreas, el mismo tratamiento para un 403 con sesión
    VÁLIDA al que le falta el PERMISO (entrada 2 del BACKLOG): con muchos
    más usuarios acotados, la chance de que alguien llegue a un formulario
    que no le corresponde subió bastante, y comerse el JSON crudo en
    pantalla completa es la peor forma de enterarse. Vuelve al panel con un
    aviso legible.

    El resto de los 403 con sesión válida (módulo no habilitado, CUIL ajeno,
    llamadas fetch/JS) sigue devolviendo JSON como siempre: ahí el JSON es
    la respuesta correcta, porque quien la lee es código."""
    if exc.status_code in (401, 403) and _es_navegacion_de_pagina(request):
        rol = _rol_de(request.url.path)
        destino = _panel_de(request.url.path)
        if destino and (not rol or not sesion_actual(request, rol)):
            return RedirectResponse(destino, status_code=303)
        # Sesión válida pero sin PERMISO de sección: al panel con un aviso.
        # Se distingue por el código y no por el status, porque un 403 puede
        # venir de otras cosas (módulo no habilitado, CUIL ajeno) donde el
        # JSON es la respuesta correcta -- hay un test que lo fija.
        if destino and getattr(exc, "codigo", None) == "sinpermiso":
            return RedirectResponse(f"{destino}?err=sinpermiso", status_code=303)
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": exc.detail,
                                 "codigo": getattr(exc, "codigo", None)})


@app.middleware("http")
async def sin_cache_en_paneles(request: Request, call_next):
    """Los paneles se arman en el servidor con datos de la base. Sin esto el
    navegador los cachea y, al volver a una pestaña después de dar de alta algo,
    se ve la versión vieja hasta forzar recarga. No toca /logo ni /static."""
    respuesta = await call_next(request)
    if respuesta.headers.get("content-type", "").startswith("text/html"):
        respuesta.headers["Cache-Control"] = "no-store, must-revalidate"
    elif request.url.path.startswith("/static/"):
        # Assets vendoreados (Chart.js, dashboard.js, marca.css, fuentes):
        # cache de una hora + sello ?v= en la URL para romperlo al deployar
        # -- mismo patrón que /logo/{id} (docs/DASHBOARD.md §5.8).
        respuesta.headers["Cache-Control"] = "public, max-age=3600"
    return respuesta


@app.middleware("http")
async def renovar_sesion_por_actividad(request: Request, call_next):
    """Sesión de 15 minutos SIN uso (no un límite fijo desde el login): cada
    request autenticado reemite el token con la marca de tiempo actual y
    corre la cookie de expiración. Un usuario activo nunca se desloguea solo;
    uno inactivo 15 minutos sí. Si el token ya venció, no se toca -- sigue
    inválido y la ruta redirige a login como siempre.

    OJO: si la propia ruta (login/logout/elegir sindicato) ya puso un
    Set-Cookie para este nombre, hay que respetarlo tal cual y NO pisarlo
    con el valor que traía el request -- si no, un login nunca "prendería"
    de verdad: esta renovación reemitiría la sesión VIEJA por encima.

    Recorre las CUATRO cookies de rol (ver COOKIES_POR_ROL): un mismo
    request puede traer más de una sesión válida a la vez (ej. una pestaña
    de trabajador manda igual la cookie de sindicato si esa sesión sigue
    viva en el navegador) -- se renuevan todas las que estén presentes y
    vigentes, no solo la del rol que esa ruta puntual necesita.

    OJO: las cookies "extra" (identidad + sindicato elegido, no la sesión
    en sí) se renuevan en un tuple aparte, NO salen gratis de
    COOKIES_POR_ROL -- si se agrega un rol nuevo con sus propias cookies
    de identidad, hay que sumarlas ahí a mano o esa sesión pierde su
    identidad/sindicato elegido a los 15 minutos aunque el rol siga vigente."""
    respuesta = await call_next(request)

    def _ya_seteada(nombre: str) -> bool:
        prefijo = f"{nombre}=".encode()
        return any(k == b"set-cookie" and v.startswith(prefijo) for k, v in respuesta.raw_headers)

    hubo_sesion_valida = False
    for rol, nombre_cookie in COOKIES_POR_ROL.items():
        token = request.cookies.get(nombre_cookie, "")
        payload = auth.leer_sesion(token) if token else None
        if payload and payload.get("rol") == rol:
            hubo_sesion_valida = True
            if not _ya_seteada(nombre_cookie):
                nuevo = auth.crear_sesion(rol, payload.get("uid", 0), payload.get("sid", 0))
                respuesta.set_cookie(nombre_cookie, nuevo, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    if hubo_sesion_valida:
        for cookie_extra in ("cuil_trab", "sind_elegido", "cuit_emp", "sind_elegido_emp"):
            valor = request.cookies.get(cookie_extra)
            if valor and not _ya_seteada(cookie_extra):
                respuesta.set_cookie(cookie_extra, valor, httponly=True,
                                      max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return respuesta


@app.get("/logo/{sindicato_id}")
def servir_logo(sindicato_id: int):
    """Sirve el logo de un sindicato guardado en la base (Opción B)."""
    with db.get_session() as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind or not sind.logo_datos:
            raise HTTPException(404, "Sin logo")
        return BinResponse(
            content=sind.logo_datos,
            media_type=sind.logo_mime or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )


@app.get("/firma/{sindicato_id}")
def servir_firma(sindicato_id: int):
    """Firma digitalizada de la autoridad, para la credencial del trabajador."""
    with db.get_session() as s:
        sind = s.get(Sindicato, sindicato_id)
        if not sind or not sind.firma_datos:
            raise HTTPException(404, "Sin firma")
        return BinResponse(
            content=sind.firma_datos,
            media_type=sind.firma_mime or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )


@app.get("/noticia-imagen/{noticia_id}/{n}")
def servir_imagen_noticia(noticia_id: int, n: int):
    """Sirve la imagen 1 o 2 de una noticia, guardada en la base (mismo
    patrón que el logo del sindicato)."""
    if n not in (1, 2):
        raise HTTPException(404, "Imagen inválida")
    with db.get_session() as s:
        noticia = s.get(Noticia, noticia_id)
        datos = (noticia.imagen1_datos if n == 1 else noticia.imagen2_datos) if noticia else None
        mime = (noticia.imagen1_mime if n == 1 else noticia.imagen2_mime) if noticia else ""
        if not noticia or not datos:
            raise HTTPException(404, "Sin imagen")
        return BinResponse(
            content=datos, media_type=mime or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )


@app.get("/beneficio-imagen/{beneficio_id}")
def servir_imagen_beneficio(beneficio_id: int):
    """Sirve la imagen de un beneficio (una sola, es la que se expone en el
    carrusel), guardada en la base -- mismo patrón que el logo/noticias."""
    with db.get_session() as s:
        b = s.get(Beneficio, beneficio_id)
        if not b or not b.imagen_datos:
            raise HTTPException(404, "Sin imagen")
        return BinResponse(
            content=b.imagen_datos, media_type=b.imagen_mime or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )


@app.get("/logo-plataforma")
def servir_logo_plataforma():
    """Logo de la plataforma para FONDO CLARO (logins). Si no cargó
    ninguno, las templates caen al SVG estático de siempre (no se llama a
    esta ruta en ese caso)."""
    with db.get_session() as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg or not cfg.logo_datos:
            raise HTTPException(404, "Sin logo")
        return BinResponse(
            content=cfg.logo_datos,
            media_type=cfg.logo_mime or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )


@app.get("/logo-plataforma-oscuro")
def servir_logo_plataforma_oscuro():
    """Logo de la plataforma para FONDO OSCURO (encabezados de admin/
    trabajador/empresa/plataforma). Las templates que lo piden ya resuelven
    el fallback al logo claro / SVG estático si este todavía no se cargó."""
    with db.get_session() as s:
        cfg = s.get(ConfiguracionPlataforma, 1)
        if not cfg or not cfg.logo_datos_oscuro:
            raise HTTPException(404, "Sin logo")
        return BinResponse(
            content=cfg.logo_datos_oscuro,
            media_type=cfg.logo_mime_oscuro or "application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )
templates = Jinja2Templates(directory="templates")
# Entorno (local/pruebas/demo/prod) disponible en TODAS las plantillas sin
# pasarlo en cada TemplateResponse: el distintivo de _entorno.html y la fila
# del "Acerca de" lo leen de acá. Ver entorno.py.
templates.env.globals["entorno"] = entorno.ENTORNO
templates.env.globals["distintivo_entorno"] = entorno.MUESTRA_DISTINTIVO


def _sello_static(nombre: str) -> str:
    """Sello de versión de un archivo de /static, para romper la caché.

    /static sale con Cache-Control de una hora. Sin sello, un cambio de CSS
    tarda hasta 60 minutos en llegarle a quien ya visitó la app: mientras
    tanto ve el HTML NUEVO con la hoja VIEJA, que es peor que ver la versión
    anterior entera. Pasó de verdad el 2026-09-03 con marca.css: las clases
    del modal de noticia no existían todavía en la hoja cacheada y el modal
    salió sin fondo y con las fotos a tamaño natural.

    El sello sale del archivo (mtime + tamaño), no de version.py: así cambia
    aunque alguien toque el CSS sin subir la versión, y en desarrollo se
    refresca sin reiniciar. El stat por request es despreciable.
    """
    try:
        st = (Path("static") / nombre).stat()
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return ""


templates.env.globals["sello_static"] = _sello_static


@app.on_event("startup")
def _startup():
    db.init_db()
    # Ninguna indexación de convenio sobrevive a un reinicio: corre en un
    # hilo de ESTE proceso. Lo que quedó en "procesando" está muerto y hay
    # que decirlo, o el admin ve un cartel que no avanza nunca.
    # try/except a propósito, y no por prolijidad: si el código nuevo llega a
    # Render ANTES de que corra `alembic upgrade head`, la tabla todavía no
    # existe y esta consulta tumba el arranque de TODA la app -- no solo de
    # esta feature. Verificado: sin las tablas, el startup revienta con
    # UndefinedTable y el servicio no levanta.
    # El arranque nunca puede depender de una migración que quizá no corrió.
    # El planificador de planes de Render: un hilo que aplica las reglas
    # programadas en la solapa "Planes". Solo en Pruebas, que es el único
    # entorno donde esa solapa existe.
    if entorno.ENTORNO == "pruebas":
        try:
            if planificador.arrancar():
                print("[planificador] hilo de planes programados en marcha")
        except Exception as e:
            print(f"[planificador] no arrancó ({type(e).__name__}: {e})")

    try:
        colgadas = db.rescatar_indexaciones_colgadas()
        if colgadas:
            print(f"[convenio] {colgadas} indexacion(es) interrumpida(s) marcadas como error")
    except Exception as e:
        print(f"[convenio] no se pudo revisar indexaciones colgadas ({type(e).__name__}). "
              f"Normal si la migración del convenio todavía no corrió.")


# ================= App del trabajador =================
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("trabajador.html", {
        "request": request, "sindicato": db.nombre_sindicato(),
        "marca_plataforma": db.marca_plataforma(),
        # Demo anónima sin sindicato real: solo tiene sentido mostrar "Tu
        # recibo" -- las demás pestañas dependen de un sindicato/login.
        "modulos": {"recibos"},
    })


@app.post("/api/leer")
async def api_leer(request: Request, archivo: UploadFile = File(...)):
    contenido = await archivo.read()
    try:
        # La llamada a la IA es sincrónica y puede tardar varios segundos --
        # se corre en un hilo aparte para no bloquear el worker de FastAPI
        # (y con él, a todos los demás pedidos) mientras se espera la respuesta.
        recibo, uso = await run_in_threadpool(extraer, contenido, archivo.content_type)
    except Exception:
        raise ErrorApp("E-RECIBO-01")
    sid = sindicato_activo_trabajador(request)
    # Se registra apenas se llama a la IA -- el costo ya se generó, sea cual
    # sea el resultado (confianza baja, o si el trabajador nunca confirma).
    db.registrar_uso_ia(sid or None, request.cookies.get("cuil_trab", ""), "recibo",
                         uso["modelo"], uso["tokens_entrada"], uso["tokens_salida"])
    if recibo.get("confianza") == "baja":
        raise ErrorApp("E-RECIBO-02")
    # Alerta de posible adulteración (totales, CUIL, CUIT del empleador o
    # fechas): no bloquea el proceso, solo avisa y guarda una copia del
    # archivo original para que la plataforma la pueda revisar.
    alerta = recibo.get("alerta_adulteracion") or {}
    if alerta.get("detectada"):
        db.registrar_recibo_sospechoso(
            sid or None, request.cookies.get("cuil_trab", ""), recibo.get("periodo") or "",
            alerta.get("motivo") or "", contenido, archivo.content_type, archivo.filename or "",
        )
    cuit_empleador = _norm_cuil((recibo.get("empleador") or {}).get("cuit"))
    nuevos = detectar_nuevos(db.conceptos_como_dicts(sid), recibo["lineas"], cuit_empleador)
    return {
        "recibo": recibo, "conceptos_nuevos": nuevos,
        "advertencia_deposito": advertencia_ultimo_deposito(recibo),
        "alerta_adulteracion": alerta if alerta.get("detectada") else None,
    }


@app.post("/api/validar")
def api_validar(request: Request, payload: dict):
    recibo = payload["recibo"]
    nuevos = payload.get("conceptos_nuevos", [])
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise ErrorApp("E-SESION-01")

    cuil_sesion = request.cookies.get("cuil_trab", "")

    # Si el recibo no es de quien inició sesión, cortar ACÁ: no se cargan
    # conceptos nuevos al catálogo, no se valida nada, y no queda en el
    # historial — es como si no se hubiera subido nada.
    if cuil_no_coincide(recibo, cuil_sesion):
        return validar([], [], recibo, cuil_sesion=cuil_sesion)

    # Alta de conceptos nuevos como pendientes, EN EL SINDICATO del trabajador.
    # Se taguean con el CUIT del empleador de ESTE recibo (si se pudo leer):
    # así el código crudo de cada empleador no compite por el mismo casillero
    # que el de otro que use ese mismo código para algo distinto.
    if nuevos and sid:
        cuit_empleador = _norm_cuil((recibo.get("empleador") or {}).get("cuit"))
        with db.get_session() as s:
            catalogo_actual = s.exec(select(Concepto).where(Concepto.sindicato_id == sid)).all()
            existentes = {(c.codigo, c.cuit_empleador or "") for c in catalogo_actual}
            # Códigos genéricos ya cargados: si la IA identificó un aporte de
            # ley (jubilación/PAMI/obra social) en esta línea, y el sindicato
            # YA tiene el genérico correspondiente, se vincula automáticamente
            # (codigo_generico) al darlo de alta — así no queda un concepto
            # "huérfano" bajo el código crudo del empleador, sin conectar con
            # la fórmula del genérico (bug real encontrado con un recibo de
            # AFIP: el concepto quedaba creado pero la fórmula de JUBILACION
            # nunca lo encontraba).
            genericos_actuales = {c.codigo for c in catalogo_actual if not c.cuit_empleador}
            for n in nuevos:
                clave = (n["codigo"], cuit_empleador or "")
                if clave not in existentes:
                    codigo_universal = CATEGORIAS_UNIVERSALES.get(n.get("categoria_universal"))
                    codigo_generico = (
                        codigo_universal
                        if codigo_universal and codigo_universal in genericos_actuales
                        and codigo_universal != n["codigo"]
                        else None
                    )
                    s.add(Concepto(
                        sindicato_id=sid,
                        codigo=n["codigo"], nombre=n["descripcion"], tipo=n["tipo"],
                        remunerativo=n.get("remunerativo", True),
                        alias=[n["descripcion"]], pendiente_revision=True,
                        cuit_empleador=cuit_empleador or None,
                        codigo_generico=codigo_generico,
                    ))
                    existentes.add(clave)
            s.commit()

    # Validar SOLO con conceptos y fórmulas de ESE sindicato. cuil_sesion viene
    # de la cookie (identidad real), no de lo que haya leído la IA del recibo.
    resultado = validar(db.conceptos_como_dicts(sid), db.formulas_como_dicts(sid), recibo,
                         tope_sindical_pct=db.obtener_tope_sindical(),
                         cuil_sesion=cuil_sesion, topes=db.topes_como_dicts())

    # Historial privado del trabajador: se registra CADA verificación, esté todo
    # en orden o no.
    with db.get_session() as s:
        registro = ReciboVerificado(
            sindicato_id=sid, cuil=cuil_sesion or resultado.get("cuil", ""),
            periodo=resultado.get("periodo", ""),
            fecha=fechas.ahora().strftime("%d/%m/%Y %H:%M"),
            estado=resultado.get("estado", ""),
            detalle={"recibo": recibo, "resultado": resultado},
            # Columnas analíticas del Panel Sindical (docs/DASHBOARD.md):
            # lo mismo que ya viaja en `detalle`, pero consultable en SQL.
            **dashboard.campos_analiticos(recibo, resultado),
        )
        s.add(registro)
        s.commit()
        resultado["recibo_verificado_id"] = registro.id

    return resultado


@app.post("/api/reportar")
def api_reportar(request: Request, payload: dict):
    """payload = {"recibo": {...}, "resultado": {...}} — se guarda el recibo
    completo, no solo el resultado, para que el sindicato pueda ver los
    conceptos igual que los ve el trabajador en el preview.

    Un recibo reportado (con inconsistencias) prueba igual que hubo
    retención de cuota sindical, así que además del Reporte (para que el
    sindicato lo revise) se registra como EnvioSindicato -- el mismo padrón
    de afiliados cotizantes que ya arma /api/enviar-sindicato para los
    recibos sin discrepancias. No reemplaza al Reporte, se suma."""
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise ErrorApp("E-SESION-01")
    resultado = payload.get("resultado") or {}
    fecha = fechas.ahora().strftime("%d/%m/%Y %H:%M")
    monto = (resultado.get("retencion_sindical") or {}).get("total", 0.0)
    with db.get_session() as s:
        s.add(Reporte(
            sindicato_id=sid, fecha=fecha,
            cuil=resultado.get("cuil", ""), periodo=resultado.get("periodo", ""),
            estado="nuevo", detalle=payload,
        ))
        s.add(EnvioSindicato(
            sindicato_id=sid, cuil=resultado.get("cuil", ""),
            periodo=resultado.get("periodo", ""), monto_cuota=monto,
            fecha=fecha, detalle=payload,
        ))
        recibo_id = resultado.get("recibo_verificado_id")
        if recibo_id:
            registro = s.get(ReciboVerificado, recibo_id)
            if registro and registro.sindicato_id == sid:
                registro.enviado_sindicato = True
                registro.fecha_envio = fecha
                s.add(registro)
        s.commit()
    return {"ok": True}


@app.post("/api/enviar-sindicato")
def api_enviar_sindicato(request: Request, payload: dict):
    """Envío voluntario y explícito del trabajador: comparte los datos de su
    recibo (incluida la retención de cuota sindical) con su sindicato, para que
    lo use como prueba de afiliado cotizante (art. 21 bis, Dto 407/2026).
    payload = {"recibo": {...}, "resultado": {...}} (lo mismo que se guarda en
    el historial propio del trabajador — ver ReciboVerificado). "resultado"
    trae "recibo_verificado_id" del intento EXACTO que se está enviando."""
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise ErrorApp("E-SESION-01")
    resultado = payload.get("resultado") or {}
    monto = (resultado.get("retencion_sindical") or {}).get("total", 0.0)
    fecha = fechas.ahora().strftime("%d/%m/%Y %H:%M")
    with db.get_session() as s:
        s.add(EnvioSindicato(
            sindicato_id=sid, cuil=resultado.get("cuil", ""),
            periodo=resultado.get("periodo", ""), monto_cuota=monto,
            fecha=fecha, detalle=payload,
        ))
        recibo_id = resultado.get("recibo_verificado_id")
        if recibo_id:
            registro = s.get(ReciboVerificado, recibo_id)
            if registro and registro.sindicato_id == sid:
                registro.enviado_sindicato = True
                registro.fecha_envio = fecha
                s.add(registro)
        s.commit()
    return {"ok": True}


@app.get("/api/mis-recibos")
def api_mis_recibos(request: Request):
    """Historial privado del trabajador: todos los recibos que verificó,
    estén enviados a su sindicato o no."""
    cuil = request.cookies.get("cuil_trab", "")
    if not cuil:
        raise ErrorApp("E-SESION-02")
    with db.get_session() as s:
        recibos = s.exec(select(ReciboVerificado).where(ReciboVerificado.cuil == cuil)
                         .order_by(ReciboVerificado.id.desc())).all()
        nombres = {sind.id: sind.nombre for sind in s.exec(select(Sindicato)).all()}
    return [{
        "id": r.id, "sindicato": nombres.get(r.sindicato_id, ""),
        "periodo": r.periodo, "fecha": r.fecha, "estado": r.estado,
        "enviado": r.enviado_sindicato, "fecha_envio": r.fecha_envio,
        "detalle": r.detalle,
    } for r in recibos]


@app.post("/api/aportes")
async def api_aportes(request: Request, archivo: UploadFile = File(...)):
    """Lee el comprobante de aportes de ARCA que sube el trabajador y arma el
    semáforo. Lo persiste (si hay sesión de trabajador con sindicato
    resuelto) para que no se pierda al navegar o recargar la página."""
    contenido = await archivo.read()
    try:
        datos, uso = await run_in_threadpool(extraer_aportes, contenido, archivo.content_type)
    except Exception:
        raise ErrorApp("E-APORTE-01")
    cuil = request.cookies.get("cuil_trab", "")
    sid = sindicato_activo_trabajador(request)
    db.registrar_uso_ia(sid or None, cuil, "aportes",
                         uso["modelo"], uso["tokens_entrada"], uso["tokens_salida"])
    if datos.get("confianza") == "baja" or not datos.get("meses"):
        raise ErrorApp("E-APORTE-02")
    resultado = calcular_semaforo(datos)
    if cuil and sid:
        db.guardar_semaforo(cuil, sid, resultado)
    return resultado


@app.get("/api/noticia/{noticia_id}")
def api_noticia(noticia_id: int, request: Request):
    """Detalle completo de una noticia (texto completo + flags de imagen)
    para el overlay de la portada/pestaña Novedades. Aísla por sindicato: no
    devuelve una noticia de un sindicato ajeno al del trabajador logueado."""
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No pudimos determinar tu sindicato. Volvé a ingresar.")
    n = db.noticia_por_id(noticia_id)
    if not n or n["sindicato_id"] != sid:
        raise HTTPException(404, "Noticia no encontrada")
    return {
        "id": n["id"], "titulo": n["titulo"], "bajada": n["bajada"],
        "texto_completo_html": _texto_con_links(n["texto_completo"]),
        "antiguedad": _antiguedad(n["creada"]),
        "tiene_imagen1": n["tiene_imagen1"], "tiene_imagen2": n["tiene_imagen2"],
        # solo si el formulario sigue activo: decide si se muestra el ícono
        "formulario_id": db.formulario_activo_de(sid, n["formulario_id"]),
    }


@app.get("/api/beneficio/{beneficio_id}")
def api_beneficio(beneficio_id: int, request: Request):
    """Detalle completo de un beneficio para el overlay del carrusel de la
    portada. Aísla por sindicato, igual que api_noticia."""
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No pudimos determinar tu sindicato. Volvé a ingresar.")
    b = db.beneficio_por_id(beneficio_id)
    if not b or b["sindicato_id"] != sid:
        raise HTTPException(404, "Beneficio no encontrado")
    return {
        "id": b["id"], "rubro": b["rubro"],
        "descripcion_html": _texto_con_links(b["descripcion"]),
        "link": b["link"], "tiene_imagen": b["tiene_imagen"],
        "formulario_id": db.formulario_activo_de(sid, b["formulario_id"]),
    }


# ================= Panel del sindicato =================
# Qué sección del panel exige cada ruta de /admin (ver permisos.py). El
# chequeo vive DENTRO de exigir_sindicato(), que todas estas rutas ya
# llamaban desde antes -- resuelve la sección mirando la ruta que FastAPI
# acaba de matchear. Un solo lugar que gatea, en vez de 73 lugares donde
# olvidarse. Y si una ruta nueva no se agrega acá, el acceso se RECHAZA en
# vez de quedar abierta (falla cerrado); test_areas_rutas.py recorre
# app.routes y avisa antes de que eso llegue a producción.
PERMISOS_RUTAS = {
    "/admin/trabajador":                    "trabajadores",
    "/admin/trabajador/generar-credencial": "trabajadores",
    "/admin/trabajador/masivo":             "trabajadores",
    "/admin/trabajador/baja":               "trabajadores",
    "/admin/trabajador/alta-logica":        "trabajadores",

    # La gestión de usuarios es del Super Admin y de nadie más: no es una
    # sección asignable (ver SECCION_SUPER_ADMIN en permisos.py).
    "/admin/usuario":                       SECCION_SUPER_ADMIN,
    "/admin/usuario/editar":                SECCION_SUPER_ADMIN,
    "/admin/usuario/baja":                  SECCION_SUPER_ADMIN,
    "/admin/usuario/alta-logica":           SECCION_SUPER_ADMIN,
    "/admin/area":                          SECCION_SUPER_ADMIN,
    "/admin/area/estado":                   SECCION_SUPER_ADMIN,

    "/admin/concepto":                      "conceptos",
    "/admin/concepto/borrar":               "conceptos",
    "/admin/concepto/confirmar":            "conceptos",
    "/admin/concepto/fusionar":             "conceptos",
    "/admin/conceptos-universales":         "conceptos",
    "/admin/formula":                       "formulas",
    "/admin/formula/borrar":                "formulas",
    "/admin/aprender":                      "aprendizaje",
    "/admin/aprender/aplicar":              "aprendizaje",

    "/admin/noticia":                       "noticias",
    "/admin/noticia/borrar":                "noticias",
    "/admin/beneficio":                     "beneficios",
    "/admin/beneficio/borrar":              "beneficios",
    "/admin/seccional":                     "seccionales",
    "/admin/seccional/borrar":              "seccionales",

    "/admin/notificacion":                  "notificaciones",
    "/admin/notificacion/preview":          "notificaciones",
    "/admin/notificacion/{notificacion_id}/destinatarios": "notificaciones",

    # Responder un trámite y diseñar el formulario son permisos distintos:
    # quien edita el formulario elige el área receptora.
    "/admin/encuesta":                      "encuestas",
    "/admin/encuesta/disclaimer":           "encuestas",
    "/admin/encuesta/publicar":             "encuestas",
    "/admin/encuesta/cerrar":               "encuestas",
    "/admin/encuesta/destinatarios":        "encuestas",
    "/admin/encuesta/borrar":               "encuestas",
    "/admin/encuesta/duplicar":             "encuestas",

    "/admin/tramite-tipo":                  "tramites_formularios",
    "/admin/tramite-tipo/probar":           "tramites_formularios",
    "/admin/tramite-tipo/borrar":           "tramites_formularios",
    "/admin/tramite/{tramite_id}":          "tramites_recibidos",
    "/admin/tramite/{tramite_id}/nota":     "tramites_recibidos",
    # Derivar es parte de atender el trámite, no de diseñar el formulario:
    # va con "recibidos". Quién puede hacerlo de verdad lo decide además
    # _exigir_responder_tramite (solo el área que lo tiene).
    "/admin/tramite/{tramite_id}/pase":     "tramites_recibidos",
    "/admin/tramites-nuevos-cantidad":      "tramites_recibidos",

    # Las 3 subpestañas de Empleadores, cada una con su permiso.
    "/admin/empleador":                     "emp_empresas",
    "/admin/empleador/baja":                "emp_empresas",
    "/admin/empleador/alta-logica":         "emp_empresas",
    "/admin/empleador/importar-cuits":      "emp_empresas",
    "/admin/notificacion-empresa":          "emp_notificaciones",
    "/admin/notificacion-empresa/preview":  "emp_notificaciones",
    "/admin/notificacion-empresa/{notificacion_empleador_id}/destinatarios": "emp_notificaciones",
    "/admin/tramite-tipo-empresa":          "emp_tramites_formularios",
    "/admin/tramite-tipo-empresa/borrar":   "emp_tramites_formularios",
    "/admin/tramite-empresa/{tramite_id}":  "emp_tramites_recibidos",
    "/admin/tramite-empresa/{tramite_id}/estado": "emp_tramites_recibidos",
    "/admin/tramite-empresa/{tramite_id}/nota":   "emp_tramites_recibidos",
    "/admin/tramites-empresa-nuevos-cantidad":    "emp_tramites_recibidos",

    # Convenio (RAG). Cargar y reindexar documentos es tarea de quien
    # administra el contenido, no de quien contesta trámites.
    "/admin/convenio":                                  "convenio",
    "/admin/convenio/documento":                        "convenio",
    "/admin/convenio/documento/{documento_id}/estado":     "convenio",
    "/admin/convenio/documento/{documento_id}/fragmentos": "convenio",
    "/admin/convenio/documento/{documento_id}/vigencia":   "convenio",
    "/admin/convenio/documento/{documento_id}/borrar":     "convenio",
    "/admin/convenio/documento/{documento_id}/reindexar":  "convenio",
    "/admin/convenio/{convenio_id}/anteriores":            "convenio",

    # Panel Sindical. Son todos endpoints de agregados que alimentan la
    # misma página; no tiene sentido partirlos en permisos distintos. El
    # explorador conserva ADEMÁS su gate de módulo propio
    # (_exigir_dashboard_detalle), que existe para el día que dashboard se
    # parta en STD y PRO -- son dos ejes: el módulo dice qué contrató el
    # sindicato, la sección quién puede entrar.
    "/admin/dashboard/asistente":              "dashboard",
    "/admin/dashboard/kpis":                   "dashboard",
    "/admin/dashboard/serie-recibos":          "dashboard",
    "/admin/dashboard/validacion":             "dashboard",
    "/admin/dashboard/diferencias-empresa":    "dashboard",
    "/admin/dashboard/tramites-seccional":     "dashboard",
    "/admin/dashboard/notificaciones":         "dashboard",
    "/admin/dashboard/formato-semana":         "dashboard",
    "/admin/dashboard/semaforo":               "dashboard",
    "/admin/dashboard/consultas":              "dashboard",
    "/admin/dashboard/explorador/{fuente}":    "dashboard",
    "/admin/dashboard/afiliados":              "dashboard",
    "/admin/dashboard/filtros":                "dashboard",
    "/admin/dashboard/detalle/recibo/{recibo_id}":    "dashboard",
    "/admin/dashboard/detalle/tramite/{tramite_id}":  "dashboard",
    "/admin/dashboard/detalle/notificaciones":        "dashboard",
    "/admin/dashboard/detalle/notificacion/{notificacion_id}/destinatarios": "dashboard",
    "/admin/dashboard/detalle/consulta/{consulta_id}": "dashboard",
}

# Las únicas rutas de /admin que no exigen sección: entrar, salir, y las
# páginas que se arman con lo que cada uno puede ver. Gatearlas dejaría a un
# usuario de área sin poder ni siquiera abrir el panel.
#
# /admin/dashboard está acá por la misma razón que /admin, no por descuido:
# es una PÁGINA, y ya resuelve la falta de módulo mandando de vuelta al
# panel en vez de tirar 403. Su permiso se chequea adentro del handler, con
# el mismo criterio -- una pantalla que redirige es mejor que un 403 seco.
# Sus endpoints de datos (/admin/dashboard/*) sí están todos gateados.
RUTAS_ADMIN_SIN_PERMISO = {"/admin", "/admin/inicio", "/admin/login", "/admin/salir",
                           "/admin/dashboard"}


def _exigir_permiso_de_ruta(request: Request, ses: dict) -> None:
    """Chequea que el usuario de la sesión pueda tocar ESTA ruta.

    La sección sale de PERMISOS_RUTAS usando la ruta que FastAPI matcheó
    (`request.scope["route"].path`), no la URL escrita: así
    "/admin/tramite/57/nota" se resuelve por "/admin/tramite/{tramite_id}/nota"
    y no hay que parsear nada a mano."""
    ruta = getattr(request.scope.get("route"), "path", "")
    if ruta in RUTAS_ADMIN_SIN_PERMISO:
        return
    seccion = PERMISOS_RUTAS.get(ruta)
    if not seccion:
        # Ruta sin clasificar: se rechaza. Es la mitad que importa del
        # "falla cerrado" -- una ruta nueva nace cerrada, no abierta.
        raise _sin_permiso("Esta sección del panel no está habilitada.")
    uid = ses.get("uid", 0)

    def _sin_permiso(mensaje: str) -> HTTPException:
        """403 marcado como "falta el permiso de sección", para que el
        handler lo mande al panel con un aviso en vez de dejar el JSON crudo
        en pantalla completa (entrada 2 del BACKLOG)."""
        e = HTTPException(403, mensaje)
        e.codigo = "sinpermiso"
        return e

    if seccion == SECCION_SUPER_ADMIN:
        # Entran los DOS administradores: el general y el de seccional. Lo
        # que los distingue no es la puerta sino el ALCANCE de lo que
        # pueden tocar del otro lado, que lo imponen las rutas con
        # _exigir_alcance_area / _exigir_alcance_usuario. Si el corte fuera
        # acá, el admin local no podría administrar nada de su delegación,
        # que es todo el sentido del rol.
        if not db.administra_areas_y_usuarios(uid):
            raise _sin_permiso("Solo un administrador del sindicato puede hacer esto.")
        return
    if not db.tiene_permiso(uid, seccion):
        raise _sin_permiso("No tenés permiso para esta sección del panel.")


def exigir_sindicato(request: Request) -> int:
    """Devuelve el sindicato_id de la sesión, o lanza 403 si no hay sesión
    válida -- y, desde el sistema de Áreas, si el usuario no tiene el
    permiso que esta ruta exige (ver PERMISOS_RUTAS).

    Que el chequeo viva acá y no en cada ruta es a propósito: las 73 rutas
    del panel ya llamaban a esta función (algunas vía _exigir_dashboard),
    así que el gateo entró sin tocar ninguna, y una ruta nueva que se olvide
    de clasificar falla cerrada."""
    ses = sesion_actual(request, "sindicato")
    if not ses:
        raise HTTPException(403, "Necesitás iniciar sesión como administrador del sindicato.")
    _exigir_permiso_de_ruta(request, ses)
    return ses.get("sid", 0)


def exigir_plataforma(request: Request) -> None:
    """Lanza 403 si no hay sesión válida de plataforma. Mismo patrón que
    exigir_sindicato -- reemplaza el chequeo `if not ses or ses.get("rol")
    != "plataforma"` que estaba repetido literal en cada ruta de plataforma."""
    if not sesion_actual(request, "plataforma"):
        raise HTTPException(403, "Necesitás iniciar sesión como administrador de plataforma.")


def _contexto_convenio(sid: int, modulos: list) -> dict:
    """Datos del piloto de convenio para el panel, o vacío.

    El try/except cubre un caso concreto: que alguien prenda el módulo antes
    de que corra la migración. Sin él, esas consultas tumban TODO /admin con
    un 500 -- no solo la pestaña del convenio. Degradar a "no hay convenios"
    es mucho mejor que dejar al admin sin panel."""
    if "convenio" not in modulos:
        return {"convenios": [], "documentos_convenio": {}}
    try:
        convenios = db.convenios_del_sindicato(sid)
        return {"convenios": convenios,
                "documentos_convenio": {c["id"]: db.documentos_del_convenio(c["id"])
                                        for c in convenios}}
    except Exception as e:
        print(f"[convenio] no se pudieron leer los convenios ({type(e).__name__}). "
              f"¿Corrió `alembic upgrade head`?")
        return {"convenios": [], "documentos_convenio": {}}


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    ses = sesion_actual(request, "sindicato")
    if not ses:
        return templates.TemplateResponse("admin_login.html", {
            "request": request, "marca_plataforma": db.marca_plataforma()})

    sid = ses.get("sid", 0)
    uid = ses.get("uid", 0)
    # El panel es UNA página con todos los paneles adentro: esconder pestañas
    # en el cliente NO es ningún control, porque los datos viajarían igual en
    # el HTML y se leen con Ver Código Fuente. Por eso cada consulta se
    # saltea si el usuario no tiene la sección -- queda la lista vacía y la
    # plantilla directamente no la renderiza.
    permisos = db.permisos_efectivos(uid)
    es_super_admin = db.es_super_admin(uid)
    # Los dos administradores entran a Áreas y Usuarios; lo que cambia es
    # cuánto ven ahí adentro (ver `alcance` más abajo).
    administra = db.administra_areas_y_usuarios(uid)

    def puede(*secciones) -> bool:
        return any(x in permisos for x in secciones)

    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        # Los conceptos alimentan además los <select> de Fórmulas y el panel
        # de Aprendizaje, así que hacen falta para cualquiera de las tres.
        conceptos = s.exec(select(Concepto).where(Concepto.sindicato_id == sid)
                           .order_by(Concepto.codigo)).all() \
            if puede("conceptos", "formulas", "aprendizaje") else []
        formulas = s.exec(select(Formula).where(Formula.sindicato_id == sid)).all() \
            if puede("formulas") else []
        reportes = s.exec(select(Reporte).where(Reporte.sindicato_id == sid)
                          .order_by(Reporte.id.desc())).all() \
            if puede("reportes") else []
        # El padrón se usa también para resolver nombres por CUIL en Reportes
        # y en Cotizantes, que solo guardan el CUIL.
        trabajadores = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid)
                              .order_by(Trabajador.activo.desc(), Trabajador.nombre)).all() \
            if puede("trabajadores", "reportes", "cotizantes") else []
        envios = s.exec(select(EnvioSindicato).where(EnvioSindicato.sindicato_id == sid)
                        .order_by(EnvioSindicato.periodo.desc(), EnvioSindicato.id.desc())).all() \
            if puede("cotizantes") else []
        empleadores = s.exec(select(Empleador).where(Empleador.sindicato_id == sid)
                             .order_by(Empleador.activo.desc(), Empleador.razon_social)).all() \
            if puede("emp_empresas") else []
    # Nombre por CUIL, para poder filtrar Reportes y Afiliados cotizantes por
    # nombre (esas tablas solo guardan el CUIL, no el nombre).
    nombres_por_cuil = {t.cuil: t.nombre for t in trabajadores}
    # Conceptos con código provisorio (la IA no pudo leer el código del recibo):
    # nunca matchean por código, así que hay que revisarlos.
    provisorios = detectar_provisorios([
        {"id": c.id, "codigo": c.codigo, "nombre": c.nombre, "alias": c.alias or []}
        for c in conceptos
    ])
    # Conceptos genéricos (sin CUIT de empleador): son los únicos que una
    # Formula puede targetear directamente. Un concepto específico de un
    # empleador aporta su importe bajo su codigo_generico (ver validador.py,
    # codigo_efectivo), así que ESE código cuenta como "válido" para la
    # fórmula aunque ningún concepto lo tenga como codigo propio.
    genericos = [c for c in conceptos if not c.cuit_empleador]
    codigos_efectivos = {c.codigo_generico or c.codigo for c in conceptos}
    # Las seccionales aparecen en su propio CRUD y además como <select> de
    # destino en el alta de trabajador, Noticias, Beneficios y
    # Notificaciones: hace falta para cualquiera de esas.
    seccionales = db.seccionales_del_sindicato(sid) \
        if puede("seccionales", "trabajadores", "noticias", "beneficios",
                 "notificaciones", "tramites_formularios") or administra else []
    seccional_por_id = {sec["id"]: sec["nombre"] for sec in seccionales}
    modulos = _modulos_de(sid)
    # Áreas y Usuarios: la pantalla es de los dos administradores, así que
    # ni la lista de usuarios ni la de áreas se consultan para los demás.
    # Y para el admin de seccional se recortan a su alcance EN LA CONSULTA,
    # no en la plantilla: si el recorte viviera en el HTML, las áreas y los
    # CUIT de las otras delegaciones viajarían igual en la página.
    alcance = db.alcance_seccional(uid) if administra else set()
    # Las áreas las necesita además el constructor de Trámites, para elegir
    # el destino: quien arma formularios tiene que poder ver a qué áreas
    # rutear, aunque no administre usuarios. Su alcance sale igual de
    # alcance_seccional, así que un admin local no ve áreas de otras.
    arma_formularios = puede("tramites_formularios")
    alcance_areas = alcance if administra else (
        db.alcance_seccional(uid) if arma_formularios else set())
    areas = db.areas_del_sindicato(sid, alcance_areas) \
        if (administra or arma_formularios) else []
    usuarios_sindicato = db.usuarios_del_sindicato(sid, alcance) if administra else []
    # Las seccionales sobre las que puede crear áreas y asignar gente.
    seccionales_alcance = [x for x in seccionales
                           if alcance_areas is None or x["id"] in (alcance_areas or set())] \
        if (administra or arma_formularios) else []
    # El catálogo que se le ofrece al armar un perfil: solo las secciones que
    # los módulos contratados habilitan, agrupadas para la pantalla. Se
    # recorta además a lo que el que asigna tiene -- nadie da lo que no
    # tiene, y ofrecérselo en pantalla para después descartarlo en el POST
    # sería mentirle.
    catalogo_permisos = permisos_mod.agrupar_para_ui(
        [x for x in permisos_mod.secciones_de_modulos(modulos) if x in permisos]
    ) if administra else []
    return templates.TemplateResponse("admin.html", {
        "request": request, "sindicato": sind.nombre if sind else "",
        "marca": db.marca_sindicato(sid), "marca_plataforma": db.marca_plataforma(),
        "iniciales": _iniciales_sindicato(sind.nombre if sind else ""),
        "conceptos": conceptos, "genericos": genericos, "codigos_efectivos": codigos_efectivos,
        "formulas": formulas, "reportes": reportes,
        "trabajadores": trabajadores, "provincias": db.PROVINCIAS_AR, "envios": envios,
        "usuarios_sindicato": usuarios_sindicato,
        "permisos": permisos, "es_super_admin": es_super_admin,
        "administra_areas": administra,
        "seccionales_alcance": seccionales_alcance,
        "areas": areas, "catalogo_permisos": catalogo_permisos,
        "etiquetas_secciones": {k: v[0] for k, v in permisos_mod.SECCIONES.items()},
        "nombres_por_cuil": nombres_por_cuil, "provisorios": provisorios,
        "debe_cambiar": ses.get("cambiar", False),
        "noticias": db.noticias_del_sindicato(sid) if puede("noticias") else [],
        "beneficios": db.beneficios_del_sindicato(sid) if puede("beneficios") else [],
        "notificaciones": db.notificaciones_del_sindicato(sid, usuario_id=uid)
                          if puede("notificaciones") else [],
        # Encuestas: la lista se recorta por alcance de seccional EN LA
        # CONSULTA (N18) -- si el recorte viviera en la plantilla, las
        # encuestas de las otras delegaciones viajarían igual en el HTML.
        "encuestas": db.encuestas_del_sindicato(sid, alcance=db.alcance_seccional(uid))
                     if puede("encuestas", "encuestas_resultados") else [],
        "encuestas_modos": encuestas.MODOS,
        "encuestas_cortes": {c: etiqueta for c, (etiqueta, _) in encuestas.CORTES.items()},
        "encuestas_tipos": {t: etiqueta for t, (etiqueta, _) in encuestas.TIPOS_PREGUNTA.items()},
        "encuestas_tipos_anonima": [t for t, _ in encuestas.tipos_para(encuestas.ANONIMA)],
        "encuestas_ayuda": encuestas.AYUDA_POR_TIPO,
        "encuestas_umbral": db.umbral_encuestas(),
        "tipos_tramite": db.tipos_tramite_del_sindicato(sid)
                         if puede("tramites_formularios", "tramites_recibidos") else [],
        "tramites": db.tramites_del_sindicato(sid, usuario_id=uid)
                    if puede("tramites_recibidos") else [],
        "tramites_nuevos": db.contar_tramites_nuevos(sid, uid)
                           if "tramites" in modulos and puede("tramites_recibidos") else 0,
        "estados_tramite": db.ESTADOS_TRAMITE, "estados_tramite_label": db.ESTADOS_TRAMITE_LABEL,
        "seccionales": seccionales, "seccional_por_id": seccional_por_id,
        "empleadores": empleadores,
        "notificaciones_empresa": db.notificaciones_empleador_del_sindicato(sid)
                                  if puede("emp_notificaciones") else [],
        "tipos_tramite_empresa": db.tipos_tramite_empleador_del_sindicato(sid)
                                 if puede("emp_tramites_formularios", "emp_tramites_recibidos") else [],
        "tramites_empresa": db.tramites_empleador_del_sindicato(sid)
                            if puede("emp_tramites_recibidos") else [],
        "tramites_empresa_nuevos": db.contar_tramites_empleador_nuevos(sid)
                                   if "empleadores" in modulos and puede("emp_tramites_recibidos") else 0,
        "modulos": modulos,
        # Piloto de RAG: solo si el sindicato tiene el módulo habilitado.
        **(_contexto_convenio(sid, modulos) if puede("convenio")
           else {"convenios": [], "documentos_convenio": {}}),
        "version": VERSION_ADMIN, "fecha_version": FECHA_VERSION,
    })


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard_pagina(request: Request):
    """Página del Panel Sindical (docs/DASHBOARD.md, Fase 2). Los datos NO
    viajan acá: los pide static/dashboard.js a los endpoints de agregados.
    Sin sesión -> login; sin módulo -> de vuelta al panel."""
    ses = sesion_actual(request, "sindicato")
    if not ses:
        return templates.TemplateResponse("admin_login.html", {
            "request": request, "marca_plataforma": db.marca_plataforma()})
    sid = ses.get("sid", 0)
    # Módulo Y sección: el módulo dice qué contrató el sindicato, la sección
    # quién de adentro puede entrar. Redirige en vez de tirar 403 porque es
    # una pantalla, no un endpoint -- mismo criterio que la falta de módulo.
    if not db.modulo_habilitado(sid, "dashboard") \
            or not db.tiene_permiso(ses.get("uid", 0), "dashboard"):
        return RedirectResponse("/admin", status_code=303)
    marca = db.marca_sindicato(sid)
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "sindicato": marca.get("nombre", ""),
        "marca": marca, "marca_plataforma": db.marca_plataforma(),
        "iniciales": _iniciales_sindicato(marca.get("nombre", "")),
        # El carril de consultas se decide en el SERVIDOR: con el flag
        # apagado, ni el KPI ni el panel ni la pestaña llegan al HTML.
        "consultas_bot": db.config_dashboard()["consultas_bot_habilitado"],
        # Asistente del Panel (docs/ASISTENTE_PANEL.md): sin API key en el
        # entorno, ni el botón ni el cajón llegan al HTML.
        "asistente": asistente.disponible(),
        "version": VERSION_ADMIN, "fecha_version": FECHA_VERSION,
    })


@app.get("/admin/inicio", response_class=HTMLResponse)
def admin_inicio(request: Request):
    ses = sesion_actual(request, "sindicato")
    if not ses:
        return templates.TemplateResponse("admin_login.html", {
            "request": request, "marca_plataforma": db.marca_plataforma()})

    sid = ses.get("sid", 0)
    marca = db.marca_sindicato(sid)
    with db.get_session() as s:
        usuario = s.get(UsuarioSindicato, ses.get("uid", 0))
    nombre_admin = (usuario.nombre if usuario else "") or ""
    modulos = _modulos_de(sid)
    # La portada es una pantalla exenta del gateo (si no, un usuario de área
    # no podría ni entrar), pero sus tarjetas sí se recortan: mostrar un
    # acceso que al tocarlo rebota con 403 es peor que no mostrarlo.
    permisos = db.permisos_efectivos(ses.get("uid", 0))
    es_super_admin = db.es_super_admin(ses.get("uid", 0))
    tramites_nuevos = db.contar_tramites_nuevos(sid, ses.get("uid", 0)) \
        if "tramites" in modulos and "tramites_recibidos" in permisos else 0
    tramites_empresa_nuevos = db.contar_tramites_empleador_nuevos(sid) \
        if "empleadores" in modulos and "emp_tramites_recibidos" in permisos else 0
    return templates.TemplateResponse("admin_portada.html", {
        "permisos": permisos, "es_super_admin": es_super_admin,
        "request": request, "sindicato": marca.get("nombre", ""),
        "marca": marca, "marca_plataforma": db.marca_plataforma(),
        "iniciales": _iniciales_sindicato(marca.get("nombre", "")),
        "primer_nombre": nombre_admin.split(" ")[0] or "Admin",
        "tramites_nuevos": tramites_nuevos,
        "tramites_empresa_nuevos": tramites_empresa_nuevos,
        "modulos": modulos,
        "version": VERSION_ADMIN, "fecha_version": FECHA_VERSION,
    })


@app.post("/admin/login")
def admin_login(usuario: str = Form(...), clave: str = Form(...)):
    cuit = _norm_cuil(usuario)   # todos los usuarios se identifican con CUIT/CUIL
    with db.get_session() as s:
        user = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.usuario == cuit, UsuarioSindicato.activo == True)).first()
        if not user or not auth.verificar_clave(clave, user.clave_hash):
            return RedirectResponse("/admin?error=1", status_code=303)
        token = auth.crear_sesion("sindicato", id_usuario=user.id, sindicato_id=user.sindicato_id)
        db.registrar_acceso("admin", sindicato_id=user.sindicato_id)
    resp = RedirectResponse("/admin/inicio", status_code=303)
    resp.set_cookie(COOKIE_SINDICATO, token, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.get("/admin/salir")
def admin_salir():
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie(COOKIE_SINDICATO)
    return resp


@app.post("/admin/trabajador")
def admin_trabajador_alta(
    request: Request,
    id: str = Form(""), cuil: str = Form(...), nombre: str = Form(...),
    calle: str = Form(""), numero: str = Form(""), piso: str = Form(""),
    ciudad: str = Form(""), provincia: str = Form(""),
    telefono: str = Form(""), mail: str = Form(""),
    vigencia_credencial: str = Form(""), seccional_id: str = Form(""),
    cuit_empleador: str = Form(""),
):
    """Alta o modificación manual de un trabajador. Obligatorios: cuil y nombre."""
    sid = exigir_sindicato(request)
    cuil_norm = _norm_cuil(cuil)
    if len(cuil_norm) != 11 or not nombre.strip():
        return RedirectResponse("/admin?err=datos#trabajadores", status_code=303)
    sec_id = int(seccional_id) if seccional_id else None
    with db.get_session() as s:
        if sec_id and not s.exec(select(Seccional).where(
                Seccional.id == sec_id, Seccional.sindicato_id == sid)).first():
            sec_id = None  # seccional ajena o inexistente: se ignora, no se rechaza el alta
        if id:  # modificación (solo si es de este sindicato)
            t = s.get(Trabajador, int(id))
            if t and t.sindicato_id == sid:
                t.cuil, t.nombre = cuil_norm, nombre.strip()
                t.calle, t.numero, t.piso = calle, numero, piso
                t.ciudad, t.provincia = ciudad, provincia
                t.telefono, t.mail = telefono, mail
                t.vigencia_credencial = vigencia_credencial or None
                t.seccional_id = sec_id
                t.cuit_empleador = cuit_empleador.strip() or None
                s.add(t)
        else:    # alta — evitar duplicado de CUIL en el mismo sindicato
            existe = s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sid, Trabajador.cuil == cuil_norm)).first()
            if not existe:
                s.add(Trabajador(
                    sindicato_id=sid, cuil=cuil_norm, nombre=nombre.strip(),
                    calle=calle, numero=numero, piso=piso, ciudad=ciudad,
                    provincia=provincia, telefono=telefono, mail=mail,
                    vigencia_credencial=vigencia_credencial or None, seccional_id=sec_id,
                    cuit_empleador=cuit_empleador.strip() or None))
        s.commit()
    # Las dos altas pueden venir en cualquier orden: si a este CUIL ya se le
    # había dado usuario del panel, acá se arma el vínculo y se prende la
    # marca de empleado. Sin esto quedaría en el padrón sin marca, en
    # silencio.
    db.sincronizar_por_cuil(sid, cuil_norm)
    return RedirectResponse("/admin#trabajadores", status_code=303)


@app.post("/admin/trabajador/generar-credencial")
def admin_generar_credencial(request: Request, id: int = Form(...)):
    """El admin genera (o regenera) el código de credencial de un trabajador.
    Nunca es automático — siempre lo dispara este botón."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        t = s.get(Trabajador, id)
        if not t or t.sindicato_id != sid:
            raise HTTPException(403, "No autorizado")
        sind = s.get(Sindicato, sid)
    db.generar_codigo_credencial(id, sid, sind.nombre if sind else "")
    return RedirectResponse("/admin#trabajadores", status_code=303)


@app.post("/admin/trabajador/masivo")
def admin_trabajador_masivo(request: Request, lista: str = Form(...)):
    """Alta masiva: una línea por trabajador, campos separados por coma.
    Orden: cuil, nombre, calle, numero, piso, ciudad, provincia, telefono, mail.
    Obligatorios los dos primeros (cuil y nombre)."""
    sid = exigir_sindicato(request)
    altas = 0
    with db.get_session() as s:
        existentes = {t.cuil for t in s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sid)).all()}
        for linea in lista.strip().splitlines():
            if not linea.strip():
                continue
            campos = [c.strip() for c in linea.split(",")]
            cuil = _norm_cuil(campos[0]) if campos else ""
            nombre = campos[1] if len(campos) > 1 else ""
            if len(cuil) != 11 or not nombre or cuil in existentes:
                continue
            def campo(i): return campos[i] if len(campos) > i else ""
            s.add(Trabajador(
                sindicato_id=sid, cuil=cuil, nombre=nombre,
                calle=campo(2), numero=campo(3), piso=campo(4),
                ciudad=campo(5), provincia=campo(6),
                telefono=campo(7), mail=campo(8)))
            existentes.add(cuil); altas += 1
        s.commit()
    return RedirectResponse("/admin#trabajadores", status_code=303)


@app.post("/admin/trabajador/baja")
def admin_trabajador_baja(request: Request, id: int = Form(...)):
    """Baja lógica: marca inactivo sin borrar (recuperable)."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        t = s.get(Trabajador, id)
        if t and t.sindicato_id == sid:
            t.activo = False
            s.add(t); s.commit()
    return RedirectResponse("/admin#trabajadores", status_code=303)


@app.post("/admin/trabajador/alta-logica")
def admin_trabajador_reactivar(request: Request, id: int = Form(...)):
    """Reactiva un trabajador dado de baja."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        t = s.get(Trabajador, id)
        if t and t.sindicato_id == sid:
            t.activo = True
            s.add(t); s.commit()
    return RedirectResponse("/admin#trabajadores", status_code=303)


# ---------- ABM de administradores del propio sindicato ----------
# Antes solo plataforma podía dar de alta/ver los UsuarioSindicato de un
# sindicato (POST /plataforma/usuario, GET /plataforma/admins/{id}) -- un
# sindicato no tenía forma de listar ni sumar administradores propios sin
# pedírselo a plataforma. Alcance elegido a propósito (ver CLAUDE.md): alta
# con clave inicial, editar nombre, activar/desactivar -- cambiarle la
# clave a un admin YA EXISTENTE sigue siendo solo vía plataforma (mismo
# criterio que el resto de la app: no ampliar ese flujo transitorio).

@app.post("/admin/usuario")
def admin_usuario_alta(request: Request, usuario: str = Form(...), nombre: str = Form(""),
                        clave_inicial: str = Form(...), rol: str = Form("area"),
                        area_id: str = Form(""), seccional_id: str = Form(""),
                        agregar: list[str] = Form(default=[]),
                        bloquear: list[str] = Form(default=[])):
    """sindicato_id sale de la sesión, nunca de un campo del form -- un
    admin no puede darse de alta a sí mismo en otro sindicato.

    `rol` se pide EXPLÍCITO y su default es "area", no "super": si el campo
    llegara a faltar, el usuario nace SIN poder en vez de con todo. Antes
    de las Áreas todo usuario nacía omnipotente, que es lo que este default
    corrige."""
    sid = exigir_sindicato(request)
    cuit = _norm_cuil(usuario)
    if len(cuit) != 11 or not clave_inicial:
        return RedirectResponse("/admin?err=datos#administradores", status_code=303)
    es_super = (rol == "super")
    es_admin_local = (rol == "seccional")
    # Otorgar Super Admin es del administrador general y de nadie más: si un
    # admin local pudiera, se fabricaría un usuario sin techo y el alcance
    # local dejaría de significar algo.
    if es_super:
        _exigir_super_admin(request)
    with db.get_session() as s:
        area = _id_propio(s, Area, area_id, sid)
        seccional = _id_propio(s, Seccional, seccional_id, sid)
        area_seccional = s.get(Area, area).seccional_id if area else None
    # Un usuario de área SIN área no puede hacer nada: se crearía mudo y sin
    # que nada lo explique. Se rechaza con un aviso en vez de dejarlo pasar.
    # Un id de otro sindicato cae acá también: _id_propio lo devuelve None.
    if not es_super and not es_admin_local and not area:
        return RedirectResponse("/admin?err=sinarea#administradores", status_code=303)
    # Un administrador de seccional SIN seccional sería un admin sin
    # alcance: no administra nada y nadie entiende por qué.
    if es_admin_local and not seccional:
        return RedirectResponse("/admin?err=sinseccional#administradores", status_code=303)
    # El área y el usuario tienen que ser de la MISMA seccional. "Legales de
    # Rosario" con alcance Córdoba es un usuario que nadie sabe qué ve.
    if area and seccional and area_seccional != seccional:
        return RedirectResponse("/admin?err=areaajena#administradores", status_code=303)
    if area and not seccional:
        seccional = area_seccional      # la seccional la fija el área
    # Nadie crea usuarios fuera de su alcance.
    if not es_super:
        _exigir_alcance_seccional(request, seccional)
    with db.get_session() as s:
        if s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.usuario == cuit)).first():
            return RedirectResponse("/admin?err=usuarioexiste#administradores", status_code=303)
        u = UsuarioSindicato(
            sindicato_id=sid, usuario=cuit, nombre=nombre,
            # Hoy el login ES el CUIL, pero se guardan por separado: si
            # mañana se habilita entrar con mail, `usuario` cambia y la
            # identidad de la persona sigue en pie.
            cuil=cuit,
            clave_hash=auth.hashear_clave(clave_inicial), debe_cambiar_clave=True,
            es_super_admin=es_super,
            es_admin_seccional=es_admin_local,
            # Ni un Super Admin ni un admin de seccional cuelgan de un área:
            # los dos tienen todo lo contratado, así que un área lo único
            # que haría es mentir en la pantalla.
            area_id=None if (es_super or es_admin_local) else area,
            seccional_id=seccional,
        )
        s.add(u); s.commit(); s.refresh(u)
        nuevo_id = u.id
    # El vínculo con el padrón se resuelve POR CUIL, no con un buscador: el
    # padrón puede tener miles de filas y un <select> con todas sería
    # impracticable. Si ese CUIL está empadronado en este sindicato, el
    # usuario queda vinculado y la fila del padrón marcada como empleado;
    # si no está, se crea igual -- trabajar en el gremio sin estar afiliado
    # a él es un caso real.
    db.sincronizar_empleado(nuevo_id)
    if not es_super and not es_admin_local:
        db.set_permisos_usuario(nuevo_id, _secciones_que_puede_dar(request, agregar),
                                _secciones_que_puede_dar(request, bloquear), sid)
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/usuario/editar")
def admin_usuario_editar(request: Request, id: int = Form(...), nombre: str = Form(""),
                          rol: str = Form("area"), area_id: str = Form(""),
                          seccional_id: str = Form(""),
                          agregar: list[str] = Form(default=[]),
                          bloquear: list[str] = Form(default=[])):
    """Edita nombre, rol, área, seccional y los ajustes individuales.

    No se puede degradar al último Super Admin activo, por el mismo motivo
    que no se lo puede desactivar: el sindicato quedaría sin nadie que pueda
    administrarlo y solo plataforma podría arreglarlo a mano.

    Un admin de seccional solo edita gente de SU seccional, y nunca a un
    Super Admin: si pudiera, le cambiaría el rol al de arriba y se quedaría
    con el sindicato."""
    sid = exigir_sindicato(request)
    quiere_super = (rol == "super")
    quiere_admin_local = (rol == "seccional")
    if quiere_super:
        _exigir_super_admin(request)
    with db.get_session() as s:
        u = s.get(UsuarioSindicato, id)
        if not u or u.sindicato_id != sid:
            return RedirectResponse("/admin#administradores", status_code=303)
        # A un Super Admin solo lo toca otro Super Admin.
        if u.es_super_admin:
            _exigir_super_admin(request)
        else:
            _exigir_alcance_seccional(request, u.seccional_id)
        if u.es_super_admin and not quiere_super and db.contar_super_admins(sid, excluyendo=id) == 0:
            return RedirectResponse("/admin?err=ultimoadmin#administradores", status_code=303)
        # Los ids viajan en el form (son <select>), así que se valida que
        # sean de ESTE sindicato: uno ajeno mandado a mano no entra.
        area = _id_propio(s, Area, area_id, sid)
        seccional = _id_propio(s, Seccional, seccional_id, sid)
        area_seccional = s.get(Area, area).seccional_id if area else None
        if not quiere_super and not quiere_admin_local and not area:
            return RedirectResponse("/admin?err=sinarea#administradores", status_code=303)
        if quiere_admin_local and not seccional:
            return RedirectResponse("/admin?err=sinseccional#administradores", status_code=303)
        if area and seccional and area_seccional != seccional:
            return RedirectResponse("/admin?err=areaajena#administradores", status_code=303)
        if area and not seccional:
            seccional = area_seccional
        # Tampoco se puede mandar a alguien a una seccional que no alcanzo:
        # sería sacárselo de encima al de al lado.
        if not quiere_super:
            _exigir_alcance_seccional(request, seccional)
        u.nombre = nombre
        u.es_super_admin = quiere_super
        u.es_admin_seccional = quiere_admin_local
        u.area_id = None if (quiere_super or quiere_admin_local) else area
        u.seccional_id = seccional
        s.add(u); s.commit()
    db.sincronizar_empleado(id)
    # Un administrador (general o local) no lleva ajustes individuales: los
    # suyos se borran para que no reaparezcan si mañana lo degradan a
    # usuario de área.
    sin_ajustes = quiere_super or quiere_admin_local
    db.set_permisos_usuario(
        id,
        [] if sin_ajustes else _secciones_que_puede_dar(request, agregar),
        [] if sin_ajustes else _secciones_que_puede_dar(request, bloquear), sid)
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/usuario/baja")
def admin_usuario_baja(request: Request, id: int = Form(...)):
    """Baja lógica -- bloqueada si es el último SUPER ADMIN activo del
    sindicato (si no, un sindicato podría quedarse sin nadie que pueda
    entrar a administrar, y solo plataforma podría reactivarlo a mano).

    Contar usuarios activos a secas ya no alcanza: un sindicato puede tener
    diez usuarios de área y un solo Super Admin, y "queda más de uno
    activo" habría dejado desactivar justamente al único que administra."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        u = s.get(UsuarioSindicato, id)
        if not u or u.sindicato_id != sid:
            return RedirectResponse("/admin#administradores", status_code=303)
        if u.es_super_admin:
            _exigir_super_admin(request)
        else:
            _exigir_alcance_seccional(request, u.seccional_id)
        if u.activo and u.es_super_admin and db.contar_super_admins(sid, excluyendo=id) == 0:
            return RedirectResponse("/admin?err=ultimoadmin#administradores", status_code=303)
        u.activo = False
        s.add(u); s.commit()
    # Dar de baja al empleado le saca la marca a su fila del padrón, pero
    # solo si no queda otro usuario activo apuntando a la misma persona.
    db.sincronizar_empleado(id)
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/usuario/alta-logica")
def admin_usuario_reactivar(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        u = s.get(UsuarioSindicato, id)
        if u and u.sindicato_id == sid:
            if u.es_super_admin:
                _exigir_super_admin(request)
            else:
                _exigir_alcance_seccional(request, u.seccional_id)
            u.activo = True
            s.add(u); s.commit()
    db.sincronizar_empleado(id)
    return RedirectResponse("/admin#administradores", status_code=303)


# ---------- Áreas del sindicato (Super Admin) ----------

def _ids_int(valores) -> list:
    """Lista de ids enteros, descartando lo que no lo sea. Los <select> y los
    checkbox viajan como texto y se pueden escribir a mano; quien recibe
    esta lista ya filtra por sindicato, así que acá alcanza con sanear el
    tipo."""
    salida = []
    for v in (valores or []):
        try:
            salida.append(int(v))
        except (TypeError, ValueError):
            continue
    return salida


def _exigir_responder_tramite(request: Request, tramite_id: int, sid: int) -> None:
    """403 si este usuario puede VER el trámite pero no responderlo.

    Pasa con el área que lo derivó: conserva lectura y pierde la escritura.
    Son dos permisos distintos desde que existe el pase, y confundirlos
    dejaría a dos áreas contestándole lo mismo al trabajador."""
    if not db.puede_responder_tramite(tramite_id, _uid_sesion(request), sid):
        raise HTTPException(403, "Este trámite lo tiene otra área. Vos podés verlo, no responderlo.")


def _exigir_alcance_tramite(request: Request, tramite_id: int, sid: int) -> None:
    """403 si el trámite es de otra área o de otra seccional.

    Filtrar el listado no alcanza: acá el id llega por la URL (el detalle) o
    por el form (la nota, el estado) y se puede escribir a mano. Esconder
    una fila de una tabla nunca fue un control de acceso."""
    if not db.puede_ver_tramite(tramite_id, _uid_sesion(request), sid):
        raise HTTPException(403, "Este trámite es de otra área.")


def _alcance_de(request: Request):
    """El alcance de seccionales de quien está en la sesión (ver
    db.alcance_seccional): None = todas, un set = esas, set() = ninguna."""
    return db.alcance_seccional(_uid_sesion(request))


def _uid_sesion(request: Request) -> int:
    return (sesion_actual(request, "sindicato") or {}).get("uid", 0)


def _en_alcance(alcance, seccional_id) -> bool:
    """None alcanza todo; un set alcanza solo lo que contiene. Una fila sin
    seccional NO la alcanza nadie salvo quien tiene alcance total -- es el
    lado seguro: un dato incompleto no puede terminar en más permisos."""
    if alcance is None:
        return True
    return bool(seccional_id) and seccional_id in alcance


def _exigir_alcance_seccional(request: Request, seccional_id) -> None:
    """403 si esa seccional está fuera del alcance de quien pide.

    Es el chequeo que convierte al Admin de Seccional en local: sin él
    tendría las mismas secciones que el Super Admin (que es a propósito) y
    además podría usarlas sobre cualquier delegación."""
    if not _en_alcance(_alcance_de(request), seccional_id):
        raise HTTPException(403, "Esto es de otra seccional.")


def _exigir_super_admin(request: Request) -> None:
    """Para lo que es del administrador general y de nadie más: crear o
    borrar seccionales, tildar `ve_todas`, y otorgar el rol de Super Admin.
    Los tres son escalada de privilegio si los pudiera hacer un admin local
    -- con `ve_todas` sobre su propia seccional se daría alcance total."""
    if not db.es_super_admin(_uid_sesion(request)):
        raise HTTPException(403, "Solo el administrador general del sindicato puede hacer esto.")


def _secciones_que_puede_dar(request: Request, secciones: list) -> list:
    """Recorta una lista de secciones a las que el que asigna YA tiene.

    Anti-escalada: nadie puede dar lo que no tiene. Hoy los dos
    administradores tienen todas las secciones contratadas, así que no
    recorta nada -- existe para que el día que un administrador quede
    acotado, el recorte ya esté puesto y no haya que acordarse."""
    propias = db.permisos_efectivos(_uid_sesion(request))
    return [x for x in (secciones or []) if x in propias]


def _id_propio(s, modelo, valor: str, sid: int):
    """int(valor) solo si esa fila existe y es de ESTE sindicato; si no, None.

    Los <select> de área y seccional viajan como campos del form, así que un
    id de otro sindicato se puede mandar a mano. Devolver None en vez de
    fallar es a propósito: el usuario queda sin área/seccional, que es el
    estado más restrictivo (ver db.alcance_seccional, que sin seccional no
    alcanza a nadie)."""
    if not valor:
        return None
    try:
        fila = s.get(modelo, int(valor))
    except (TypeError, ValueError):
        return None
    return fila.id if fila and fila.sindicato_id == sid else None


@app.post("/admin/area")
def admin_area_abm(request: Request, id: str = Form(""), nombre: str = Form(...),
                    seccional_id: str = Form(""), secciones: list[str] = Form(default=[])):
    """Alta/edición de un área con sus permisos en la misma operación: la
    pantalla los muestra juntos y separarlos obligaría a guardar dos veces.

    El área pertenece a UNA seccional (decisión N2), así que el alta la pide
    y la edición no la deja cambiar: mover un área de seccional le
    cambiaría el alcance a todos sus usuarios de golpe y en silencio. Para
    eso se desactiva y se crea la nueva donde corresponde.

    Las secciones se sanean dos veces y las dos hacen falta: acá se recortan
    a las que el que asigna YA TIENE (nadie da lo que no tiene), y en
    db.set_permisos_area se descarta lo inventado o lo de un módulo no
    contratado."""
    sid = exigir_sindicato(request)
    nombre = (nombre or "").strip()
    if not nombre:
        return RedirectResponse("/admin?err=datosarea#administradores", status_code=303)
    secciones = _secciones_que_puede_dar(request, secciones)
    with db.get_session() as s:
        if id:
            area = s.get(Area, int(id))
            # El chequeo de sindicato no es decorativo: el id viaja en el
            # form y se puede escribir a mano.
            if not area or area.sindicato_id != sid:
                return RedirectResponse("/admin#administradores", status_code=303)
            # Y el de alcance tampoco: sin él un admin local podría
            # renombrar y repermisar las áreas de otra delegación.
            _exigir_alcance_seccional(request, area.seccional_id)
            area.nombre = nombre
            s.add(area); s.commit()
            area_id = area.id
        else:
            destino = _id_propio(s, Seccional, seccional_id, sid)
            if not destino:
                return RedirectResponse("/admin?err=datosarea#administradores", status_code=303)
            _exigir_alcance_seccional(request, destino)
            area = Area(sindicato_id=sid, seccional_id=destino, nombre=nombre)
            s.add(area); s.commit(); s.refresh(area)
            area_id = area.id
    db.set_permisos_area(area_id, secciones, sid)
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/area/estado")
def admin_area_estado(request: Request, id: int = Form(...), activo: str = Form("")):
    """Un área NO se borra, se desactiva: sus usuarios seguirían apuntando a
    un área inexistente. Desactivarla es además la forma de cortarle el
    acceso a todo un equipo de una, sin tocar usuario por usuario.

    El valor se compara contra una lista de afirmativos y NO con bool(): un
    string cualquiera es truthy en Python, así que `activo="no"` habría
    activado el área. Cualquier cosa que no sea un sí explícito desactiva,
    que es el lado seguro."""
    sid = exigir_sindicato(request)
    queda_activa = (activo or "").strip().lower() in ("1", "true", "on", "si", "sí")
    with db.get_session() as s:
        area = s.get(Area, id)
        if area and area.sindicato_id == sid:
            _exigir_alcance_seccional(request, area.seccional_id)
            area.activo = queda_activa
            s.add(area); s.commit()
    return RedirectResponse("/admin#administradores", status_code=303)


# ---------- ABM de conceptos ----------
CATEGORIAS_SINDICALES = ("", "convenio", "afiliacion")


@app.post("/admin/concepto")
def abm_concepto(
    request: Request,
    id: str = Form(""), codigo: str = Form(...), nombre: str = Form(...),
    tipo: str = Form(...), remunerativo: str = Form("no"),
    alias: str = Form(""), categoria_sindical: str = Form(""),
    cuit_empleador: str = Form(""), codigo_generico: str = Form(""),
):
    sid = exigir_sindicato(request)
    aliases = [a.strip() for a in alias.split(",") if a.strip()]
    if nombre not in aliases:
        aliases.append(nombre)
    es_remun = remunerativo == "si"
    categoria = categoria_sindical if categoria_sindical in CATEGORIAS_SINDICALES else ""
    cuit_empleador = _norm_cuil(cuit_empleador) or None
    codigo_gen = codigo_generico.strip() or None
    with db.get_session() as s:
        if id:  # edición — solo si el concepto es de este sindicato
            c = s.get(Concepto, int(id))
            if c and c.sindicato_id == sid:
                c.codigo, c.nombre, c.tipo = codigo, nombre, tipo
                c.remunerativo, c.alias = es_remun, aliases
                c.categoria_sindical = categoria
                c.cuit_empleador, c.codigo_generico = cuit_empleador, codigo_gen
                c.pendiente_revision = False
                s.add(c)
        else:   # alta
            s.add(Concepto(sindicato_id=sid, codigo=codigo, nombre=nombre, tipo=tipo,
                           remunerativo=es_remun, alias=aliases,
                           categoria_sindical=categoria,
                           cuit_empleador=cuit_empleador, codigo_generico=codigo_gen,
                           pendiente_revision=False))
        s.commit()
    return RedirectResponse("/admin#conceptos", status_code=303)


@app.post("/admin/concepto/borrar")
def borrar_concepto(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        c = s.get(Concepto, id)
        if c and c.sindicato_id == sid:
            s.delete(c)
            s.commit()
    return RedirectResponse("/admin#conceptos", status_code=303)


@app.post("/admin/concepto/confirmar")
def confirmar_concepto(request: Request, id: int = Form(...)):
    """Saca la marca "por revisar" de un concepto sin abrir el formulario de
    edición -- antes solo se podía limpiar como efecto secundario de editar
    y guardar (ver abm_concepto), lo cual no era evidente en la UI."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        c = s.get(Concepto, id)
        if c and c.sindicato_id == sid:
            c.pendiente_revision = False
            s.add(c)
            s.commit()
    return RedirectResponse("/admin#conceptos", status_code=303)


@app.post("/admin/concepto/fusionar")
def fusionar_concepto(request: Request, id: int = Form(...), destino_id: int = Form(...)):
    """Un concepto provisorio resultó ser el mismo que uno ya existente: se
    pasa su descripción como alias del original y se borra el provisorio.
    Así el próximo recibo que traiga esa variante matchea con el original."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        origen = s.get(Concepto, id)
        destino = s.get(Concepto, destino_id)
        if not (origen and destino and origen.sindicato_id == sid
                and destino.sindicato_id == sid and origen.id != destino.id):
            return RedirectResponse("/admin#conceptos", status_code=303)

        # El nombre y los alias del provisorio pasan a ser alias del original.
        alias = list(destino.alias or [])
        for texto in [origen.nombre] + list(origen.alias or []):
            if texto and texto not in alias:
                alias.append(texto)
        destino.alias = alias
        s.add(destino)

        # Si alguna fórmula apuntaba al código provisorio, repuntarla al real:
        # si no, quedaría huérfana y no matchearía nunca (el mismo problema que
        # el target de texto libre).
        for f in s.exec(select(Formula).where(
                Formula.sindicato_id == sid, Formula.target == origen.codigo)).all():
            f.target = destino.codigo
            s.add(f)

        s.delete(origen)
        s.commit()
    return RedirectResponse("/admin#conceptos", status_code=303)


# ---------- Aportes de ley (jubilación, PAMI, obra social) ----------
@app.post("/admin/conceptos-universales")
def admin_conceptos_universales(request: Request):
    """Botón manual: carga los conceptos/fórmulas de jubilación, PAMI y obra
    social. Pensado para sindicatos dados de alta ANTES de que esto se
    autocargara solo — es idempotente, no duplica lo que ya esté."""
    sid = exigir_sindicato(request)
    agregados = db.crear_conceptos_universales(sid)
    estado = "ok" if agregados else "nada"
    return RedirectResponse(f"/admin?universales={estado}#formulas", status_code=303)


# ---------- ABM de fórmulas ----------
@app.post("/admin/formula")
def abm_formula(
    request: Request,
    id: str = Form(""), target: str = Form(...), descripcion: str = Form(...),
    expr: str = Form(...), tolerancia: float = Form(1.0),
    fecha_desde: str = Form(""), fecha_hasta: str = Form(""),
    sujeto_a_tope: bool = Form(False),
):
    sid = exigir_sindicato(request)
    fecha_desde = fecha_desde or None
    fecha_hasta = fecha_hasta or None
    # La expresión se prueba ACÁ, con valores de juguete. Antes se guardaba sin
    # mirarla: una fórmula mal escrita (coma decimal, un signo %, una variable
    # inventada) no fallaba al cargarla sino meses después, en la pantalla del
    # trabajador, la primera vez que llegaba un recibo con ese concepto -- y
    # ahí reventaba la verificación entera del recibo. Ver error_de_expresion.
    motivo = error_de_expresion(expr)
    if motivo:
        return RedirectResponse(
            f"/admin?error=formulaexpr&motivo={quote(motivo)}#formulas", status_code=303)
    with db.get_session() as s:
        # Ninguna fórmula del mismo target puede tener una vigencia que se
        # pise con otra (si no, un mismo período tendría dos fórmulas
        # candidatas y no habría forma determinística de elegir cuál aplica).
        otras = s.exec(select(Formula).where(
            Formula.sindicato_id == sid, Formula.target == target,
            Formula.id != (int(id) if id else -1))).all()
        for otra in otras:
            if rangos_se_superponen(fecha_desde, fecha_hasta, otra.fecha_desde, otra.fecha_hasta):
                return RedirectResponse(
                    f"/admin?error=superposicion&target={target}#formulas", status_code=303)
        if id:
            f = s.get(Formula, int(id))
            if f and f.sindicato_id == sid:
                f.target, f.descripcion, f.expr, f.tolerancia = target, descripcion, expr, tolerancia
                f.fecha_desde, f.fecha_hasta = fecha_desde, fecha_hasta
                f.sujeto_a_tope = sujeto_a_tope
                s.add(f)
        else:
            s.add(Formula(sindicato_id=sid, target=target, descripcion=descripcion,
                          expr=expr, tolerancia=tolerancia,
                          fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                          sujeto_a_tope=sujeto_a_tope))
        s.commit()
    return RedirectResponse("/admin#formulas", status_code=303)


@app.post("/admin/formula/borrar")
def borrar_formula(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        f = s.get(Formula, id)
        if f and f.sindicato_id == sid:
            s.delete(f)
            s.commit()
    return RedirectResponse("/admin#formulas", status_code=303)


@app.post("/admin/noticia")
async def abm_noticia(
    request: Request,
    id: str = Form(""), titulo: str = Form(...), bajada: str = Form(""),
    texto_completo: str = Form(""), fecha_desde: str = Form(...), fecha_hasta: str = Form(...),
    imagen1: UploadFile = File(None), imagen2: UploadFile = File(None),
    destino_seccionales: list[str] = Form(default=[]),
    formulario_id: str = Form(""),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "noticias")
    formulario = _formulario_para_chat(sid, formulario_id, "trabajador")
    with db.get_session() as s:
        destinos = _destinos_de_publicacion(request, s, destino_seccionales, sid)
        if id:
            n = s.get(Noticia, int(id))
            if n and n.sindicato_id == sid:
                n.titulo, n.bajada, n.texto_completo = titulo, bajada, texto_completo
                n.fecha_desde, n.fecha_hasta = fecha_desde, fecha_hasta
                n.destino_seccionales = destinos
                n.formulario_id = formulario
                if imagen1 and imagen1.filename:
                    datos, mime, _ = _leer_logo(imagen1)
                    if datos:
                        n.imagen1_datos, n.imagen1_mime = datos, mime
                if imagen2 and imagen2.filename:
                    datos, mime, _ = _leer_logo(imagen2)
                    if datos:
                        n.imagen2_datos, n.imagen2_mime = datos, mime
                s.add(n)
        else:
            imagen1_datos, imagen1_mime = None, ""
            if imagen1 and imagen1.filename:
                imagen1_datos, imagen1_mime, _ = _leer_logo(imagen1)
            imagen2_datos, imagen2_mime = None, ""
            if imagen2 and imagen2.filename:
                imagen2_datos, imagen2_mime, _ = _leer_logo(imagen2)
            s.add(Noticia(
                sindicato_id=sid, titulo=titulo, bajada=bajada, texto_completo=texto_completo,
                fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                creada=fechas.ahora_texto(),
                imagen1_datos=imagen1_datos, imagen1_mime=imagen1_mime,
                imagen2_datos=imagen2_datos, imagen2_mime=imagen2_mime,
                destino_seccionales=destinos, formulario_id=formulario,
            ))
        s.commit()
    return RedirectResponse("/admin#noticias", status_code=303)


@app.post("/admin/noticia/borrar")
def borrar_noticia(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "noticias")
    with db.get_session() as s:
        n = s.get(Noticia, id)
        if n and n.sindicato_id == sid:
            s.delete(n)
            s.commit()
    return RedirectResponse("/admin#noticias", status_code=303)


@app.post("/admin/beneficio")
async def abm_beneficio(
    request: Request,
    id: str = Form(""), rubro: str = Form(...), descripcion: str = Form(""),
    link: str = Form(""), fecha_desde: str = Form(...), fecha_hasta: str = Form(...),
    imagen: UploadFile = File(None), destino_seccionales: list[str] = Form(default=[]),
    formulario_id: str = Form(""),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "beneficios")
    formulario = _formulario_para_chat(sid, formulario_id, "trabajador")
    with db.get_session() as s:
        destinos = _destinos_de_publicacion(request, s, destino_seccionales, sid)
        if id:
            b = s.get(Beneficio, int(id))
            if b and b.sindicato_id == sid:
                b.rubro, b.descripcion, b.link = rubro, descripcion, link
                b.fecha_desde, b.fecha_hasta = fecha_desde, fecha_hasta
                b.destino_seccionales = destinos
                b.formulario_id = formulario
                if imagen and imagen.filename:
                    datos, mime, _ = _leer_logo(imagen)
                    if datos:
                        b.imagen_datos, b.imagen_mime = datos, mime
                s.add(b)
        else:
            imagen_datos, imagen_mime = None, ""
            if imagen and imagen.filename:
                imagen_datos, imagen_mime, _ = _leer_logo(imagen)
            s.add(Beneficio(
                sindicato_id=sid, rubro=rubro, descripcion=descripcion, link=link,
                fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                creada=fechas.ahora_texto(),
                imagen_datos=imagen_datos, imagen_mime=imagen_mime,
                destino_seccionales=destinos, formulario_id=formulario,
            ))
        s.commit()
    return RedirectResponse("/admin#beneficios", status_code=303)


@app.post("/admin/beneficio/borrar")
def borrar_beneficio(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "beneficios")
    with db.get_session() as s:
        b = s.get(Beneficio, id)
        if b and b.sindicato_id == sid:
            s.delete(b)
            s.commit()
    return RedirectResponse("/admin#beneficios", status_code=303)


@app.post("/admin/seccional")
def abm_seccional(
    request: Request,
    id: str = Form(""), nombre: str = Form(...), direccion: str = Form(""),
    ve_todas: str = Form(""),
):
    """`ve_todas` define el ALCANCE de los usuarios de esta seccional: con el
    check puesto, alcanzan a los trabajadores de todas las seccionales del
    sindicato (es lo que hace que Sede Central sea "central"). Llega como
    checkbox, así que su ausencia es False.

    CREAR una seccional es del administrador general y de nadie más -- el
    mapa de delegaciones del sindicato no lo dibuja una delegación. Y tocar
    `ve_todas` también: un admin local que pudiera tildarlo sobre su propia
    seccional se daría alcance sobre todo el sindicato de un clic, que es
    exactamente la escalada que el rol tiene que impedir. Editar nombre y
    dirección de una seccional del propio alcance, en cambio, sí puede."""
    sid = exigir_sindicato(request)
    todas = bool(ve_todas)
    if not id:
        _exigir_super_admin(request)
    with db.get_session() as s:
        if id:
            sec = s.get(Seccional, int(id))
            if sec and sec.sindicato_id == sid:
                _exigir_alcance_seccional(request, sec.id)
                if todas != sec.ve_todas:
                    _exigir_super_admin(request)
                sec.nombre, sec.direccion, sec.ve_todas = nombre, direccion, todas
                s.add(sec)
        else:
            s.add(Seccional(sindicato_id=sid, nombre=nombre, direccion=direccion,
                            ve_todas=todas))
        s.commit()
    return RedirectResponse("/admin#seccionales", status_code=303)


@app.post("/admin/seccional/borrar")
def borrar_seccional(request: Request, id: int = Form(...)):
    """Al borrar una seccional, los trabajadores que la tenían asignada
    quedan sin seccional (es un dato opcional, no se bloquea el borrado).

    Solo el administrador general: borrar la seccional propia sería, para un
    admin local, borrarse el alcance a sí mismo y dejar a sus trabajadores
    sin seccional -- que desde el sistema de Áreas significa que ningún
    usuario de área los alcanza."""
    sid = exigir_sindicato(request)
    _exigir_super_admin(request)
    with db.get_session() as s:
        sec = s.get(Seccional, id)
        if sec and sec.sindicato_id == sid:
            trabajadores = s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sid, Trabajador.seccional_id == id)).all()
            for t in trabajadores:
                t.seccional_id = None
                s.add(t)
            s.delete(sec)
            s.commit()
    return RedirectResponse("/admin#seccionales", status_code=303)


# ---------- Empleadores (CRUD de empresas del sindicato) ----------

@app.post("/admin/empleador")
def admin_empleador_alta(
    request: Request,
    id: str = Form(""), cuit: str = Form(...), razon_social: str = Form(""),
    domicilio: str = Form(""), telefono: str = Form(""),
    provincia: str = Form(""), mail: str = Form(""),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    cuit_norm = _norm_cuil(cuit)
    if len(cuit_norm) != 11:
        return RedirectResponse("/admin?error=cuit#empleadores", status_code=303)
    with db.get_session() as s:
        if id:
            e = s.get(Empleador, int(id))
            if e and e.sindicato_id == sid:
                e.cuit, e.razon_social = cuit_norm, razon_social.strip()
                e.domicilio, e.telefono = domicilio, telefono
                e.provincia, e.mail = provincia, mail
                s.add(e)
        else:
            existe = s.exec(select(Empleador).where(
                Empleador.sindicato_id == sid, Empleador.cuit == cuit_norm)).first()
            if not existe:
                s.add(Empleador(sindicato_id=sid, cuit=cuit_norm,
                                 razon_social=razon_social.strip(), domicilio=domicilio,
                                 telefono=telefono, provincia=provincia, mail=mail))
        s.commit()
    return RedirectResponse("/admin#empleadores", status_code=303)


@app.post("/admin/empleador/baja")
def admin_empleador_baja(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    with db.get_session() as s:
        e = s.get(Empleador, id)
        if e and e.sindicato_id == sid:
            e.activo = False
            s.add(e); s.commit()
    return RedirectResponse("/admin#empleadores", status_code=303)


@app.post("/admin/empleador/alta-logica")
def admin_empleador_reactivar(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    with db.get_session() as s:
        e = s.get(Empleador, id)
        if e and e.sindicato_id == sid:
            e.activo = True
            s.add(e); s.commit()
    return RedirectResponse("/admin#empleadores", status_code=303)


@app.post("/admin/empleador/importar-cuits")
def admin_empleador_importar(request: Request):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    agregados = db.importar_cuits_de_conceptos(sid)
    return RedirectResponse(f"/admin?importados={agregados}#empleadores", status_code=303)


# ---------- Notificaciones (Fase 2 de Módulos + Notificaciones + Trámites) ----------
MAX_ADJUNTO_NOTIFICACION = 5 * 1024 * 1024  # 5 MB, pedido explícito del plan


def _leer_adjunto_notificacion(archivo: UploadFile):
    """Lee el adjunto de una notificación (imagen, PDF o Word) y devuelve
    (datos, mime, nombre_original). None/"" si el tipo no es válido, si está
    vacío, o si supera MAX_ADJUNTO_NOTIFICACION."""
    import os
    ext = os.path.splitext(archivo.filename)[1].lower()
    mimes = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
        ".pdf": "application/pdf", ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if ext not in mimes:
        return None, "", ""
    datos = archivo.file.read()
    if not datos or len(datos) > MAX_ADJUNTO_NOTIFICACION:
        return None, "", ""
    return datos, mimes[ext], archivo.filename


@app.post("/admin/notificacion/preview")
def notificacion_preview(request: Request, criterio: str = Form(...), valores: list[str] = Form(default=[])):
    """Solo cuenta cuántos trabajadores matchean -- no persiste nada. El
    admin lo usa para confirmar antes de mandar de verdad."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "notificaciones")
    # Con el usuario: el preview tiene que contar EXACTAMENTE lo que va a
    # salir. Si contara de más, el admin confirmaría un número y saldría
    # otro, y el error sería silencioso porque nadie los compara.
    cuils = db.resolver_destinatarios(sid, criterio, valores,
                                      usuario_id=_uid_sesion(request))
    return {"cantidad": len(cuils)}


@app.post("/admin/notificacion")
async def crear_notificacion(
    request: Request,
    remitente: str = Form(""), texto: str = Form(...),
    criterio: str = Form(...), valores: list[str] = Form(default=[]),
    adjunto: UploadFile = File(None), formulario_id: str = Form(""),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "notificaciones")
    ses = sesion_actual(request, "sindicato")
    adjunto_datos, adjunto_mime, adjunto_nombre = None, "", ""
    if adjunto and adjunto.filename:
        adjunto_datos, adjunto_mime, adjunto_nombre = _leer_adjunto_notificacion(adjunto)
        if not adjunto_datos:
            return RedirectResponse("/admin?error=adjunto#notificaciones", status_code=303)
    db.crear_notificacion(
        sid, ses.get("uid") or None, remitente, texto, criterio, valores,
        adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime, adjunto_nombre=adjunto_nombre,
        formulario_id=_formulario_para_chat(sid, formulario_id, "trabajador"),
    )
    return RedirectResponse("/admin#notificaciones", status_code=303)


@app.get("/admin/notificacion/{notificacion_id}/destinatarios")
def notificacion_ver_destinatarios(notificacion_id: int, request: Request):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        n = s.get(Notificacion, notificacion_id)
        if not n or n.sindicato_id != sid:
            raise HTTPException(403, "No autorizado")
    return {"destinatarios": db.notificacion_destinatarios(
        notificacion_id, usuario_id=_uid_sesion(request))}


@app.get("/notificacion-adjunto/{notificacion_id}")
def servir_adjunto_notificacion(notificacion_id: int, request: Request):
    """El adjunto lo puede ver el admin del sindicato que la mandó, o un
    trabajador que sea destinatario real -- no es público como el logo."""
    with db.get_session() as s:
        n = s.get(Notificacion, notificacion_id)
        if not n or not n.adjunto_datos:
            raise HTTPException(404, "Sin adjunto")
        ses_sind = sesion_actual(request, "sindicato")
        ses_trab = sesion_actual(request, "trabajador")
        autorizado = False
        if ses_sind and ses_sind.get("sid") == n.sindicato_id:
            autorizado = True
        elif ses_trab:
            cuil = request.cookies.get("cuil_trab", "")
            if cuil and s.exec(select(NotificacionDestinatario).where(
                    NotificacionDestinatario.notificacion_id == notificacion_id,
                    NotificacionDestinatario.cuil == cuil)).first():
                autorizado = True
        if not autorizado:
            raise HTTPException(403, "No autorizado")
        return BinResponse(
            content=n.adjunto_datos, media_type=n.adjunto_mime or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{n.adjunto_nombre or "adjunto"}"'},
        )


@app.get("/api/mis-notificaciones")
def api_mis_notificaciones(request: Request):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        return {"notificaciones": [], "no_leidas": 0}
    notifs = db.notificaciones_de_trabajador(cuil, sid)
    for n in notifs:
        n["texto_html"] = _texto_con_links(n["texto"])
    return {"notificaciones": notifs, "no_leidas": sum(1 for n in notifs if not n["leida_en"])}


@app.post("/api/notificacion/{notificacion_id}/leer")
def api_marcar_notificacion_leida(notificacion_id: int, request: Request):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    ok = db.marcar_notificacion_leida(notificacion_id, cuil)
    if not ok:
        raise HTTPException(404, "No sos destinatario de esta notificación")
    sid = sindicato_activo_trabajador(request)
    no_leidas = db.contar_notificaciones_no_leidas(cuil, sid) if sid else 0
    return {"ok": True, "no_leidas": no_leidas}


@app.post("/api/notificaciones/leer-todas")
def api_marcar_todas_notificaciones_leidas(request: Request):
    """Bandeja "Hilo" (2026-09-03): un solo toque deja todo leído."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        return {"ok": True, "marcadas": 0, "no_leidas": 0}
    marcadas = db.marcar_todas_notificaciones_leidas(cuil, sid)
    return {"ok": True, "marcadas": marcadas, "no_leidas": db.contar_notificaciones_no_leidas(cuil, sid)}


# ---------- Notificaciones a empleadores (Fase 4 del plan de Empleadores) ----------
# Mismo patrón que las rutas de notificaciones al trabajador (arriba), sobre
# las tablas propias NotificacionEmpleador/NotificacionEmpleadorDestinatario.

@app.post("/admin/notificacion-empresa/preview")
def notificacion_empresa_preview(request: Request, criterio: str = Form(...), valores: list[str] = Form(default=[])):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    cuits = db.resolver_destinatarios_empleador(sid, criterio, valores)
    return {"cantidad": len(cuits)}


@app.post("/admin/notificacion-empresa")
async def crear_notificacion_empresa(
    request: Request,
    remitente: str = Form(""), texto: str = Form(...),
    criterio: str = Form(...), valores: list[str] = Form(default=[]),
    adjunto: UploadFile = File(None), formulario_id: str = Form(""),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    ses = sesion_actual(request, "sindicato")
    adjunto_datos, adjunto_mime, adjunto_nombre = None, "", ""
    if adjunto and adjunto.filename:
        adjunto_datos, adjunto_mime, adjunto_nombre = _leer_adjunto_notificacion(adjunto)
        if not adjunto_datos:
            return RedirectResponse("/admin?error=adjunto#empleadores", status_code=303)
    db.crear_notificacion_empleador(
        sid, ses.get("uid") or None, remitente, texto, criterio, valores,
        adjunto_datos=adjunto_datos, adjunto_mime=adjunto_mime, adjunto_nombre=adjunto_nombre,
        formulario_id=_formulario_para_chat(sid, formulario_id, "empresa"),
    )
    return RedirectResponse("/admin#empleadores", status_code=303)


@app.get("/admin/notificacion-empresa/{notificacion_empleador_id}/destinatarios")
def notificacion_empresa_ver_destinatarios(notificacion_empleador_id: int, request: Request):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        n = s.get(NotificacionEmpleador, notificacion_empleador_id)
        if not n or n.sindicato_id != sid:
            raise HTTPException(403, "No autorizado")
    return {"destinatarios": db.notificacion_empleador_destinatarios(notificacion_empleador_id)}


@app.get("/notificacion-empresa-adjunto/{notificacion_empleador_id}")
def servir_adjunto_notificacion_empresa(notificacion_empleador_id: int, request: Request):
    """El adjunto lo puede ver el admin del sindicato que la mandó, o un
    empleador que sea destinatario real -- no es público como el logo."""
    with db.get_session() as s:
        n = s.get(NotificacionEmpleador, notificacion_empleador_id)
        if not n or not n.adjunto_datos:
            raise HTTPException(404, "Sin adjunto")
        ses_sind = sesion_actual(request, "sindicato")
        ses_emp = sesion_actual(request, "empleador")
        autorizado = False
        if ses_sind and ses_sind.get("sid") == n.sindicato_id:
            autorizado = True
        elif ses_emp:
            cuit = request.cookies.get("cuit_emp", "")
            if cuit and s.exec(select(NotificacionEmpleadorDestinatario).where(
                    NotificacionEmpleadorDestinatario.notificacion_empleador_id == notificacion_empleador_id,
                    NotificacionEmpleadorDestinatario.cuit == cuit)).first():
                autorizado = True
        if not autorizado:
            raise HTTPException(403, "No autorizado")
        return BinResponse(
            content=n.adjunto_datos, media_type=n.adjunto_mime or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{n.adjunto_nombre or "adjunto"}"'},
        )


@app.get("/api/empresa/notificaciones")
def api_mis_notificaciones_empresa(request: Request):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_empleador(request)
    if not sid:
        return {"notificaciones": [], "no_leidas": 0}
    notifs = db.notificaciones_de_empleador(cuit, sid)
    for n in notifs:
        n["texto_html"] = _texto_con_links(n["texto"])
    return {"notificaciones": notifs, "no_leidas": sum(1 for n in notifs if not n["leida_en"])}


@app.post("/api/empresa/notificacion/{notificacion_empleador_id}/leer")
def api_marcar_notificacion_leida_empresa(notificacion_empleador_id: int, request: Request):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    ok = db.marcar_notificacion_leida_empleador(notificacion_empleador_id, cuit)
    if not ok:
        raise HTTPException(404, "No sos destinatario de esta notificación")
    sid = sindicato_activo_empleador(request)
    no_leidas = db.contar_notificaciones_no_leidas_empleador(cuit, sid) if sid else 0
    return {"ok": True, "no_leidas": no_leidas}


# ---------- Perfil del empleador (mirror del perfil de trabajador) ----------
@app.post("/api/empresa/perfil")
async def api_actualizar_perfil_empleador(request: Request, razon_social: str = Form(...),
                                           domicilio: str = Form(""), telefono: str = Form(""),
                                           provincia: str = Form(""), mail: str = Form("")):
    """La empresa edita su propio perfil -- todo menos el CUIT. Actualiza el
    alta del sindicato ACTIVO (Empleador es por sindicato, mismo criterio
    que actualizar_perfil_trabajador)."""
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    if not razon_social.strip():
        raise HTTPException(400, "La razón social no puede estar vacía.")
    sid = sindicato_activo_empleador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    if not db.actualizar_perfil_empleador(cuit, sid, razon_social, domicilio, telefono, provincia, mail):
        raise HTTPException(404, "No se encontró tu alta en este sindicato.")
    perfil = db.perfil_empleador(cuit, sid)
    return {"ok": True, "razon_social": perfil["razon_social"] if perfil else razon_social}


@app.post("/api/empresa/perfil/foto")
async def api_subir_foto_perfil_empresa(request: Request, foto: UploadFile = File(...)):
    """Foto de perfil, una por CUIT (no por sindicato). Mismo criterio que
    api_subir_foto_perfil: el achicado a baja resolución lo hace el cliente
    antes de subir, acá solo se valida tipo/tamaño."""
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    if (foto.content_type or "") not in MIMES_FOTO_PERFIL:
        raise HTTPException(400, "La foto tiene que ser JPEG, PNG o WEBP.")
    datos = await foto.read()
    if not datos or len(datos) > MAX_FOTO_PERFIL:
        raise HTTPException(400, "Foto vacía o demasiado pesada.")
    if not db.guardar_foto_empleador(cuit, datos, foto.content_type):
        raise HTTPException(404, "No se encontró tu cuenta.")
    return {"ok": True}


@app.get("/perfil-empleador-foto/{cuit}")
def servir_foto_perfil_empleador(cuit: str, request: Request):
    """La ve la propia empresa dueña, o el admin de un sindicato donde ese
    CUIT esté dado de alta como Empleador (para el avatar en el chat de
    Trámites externos) -- no es pública como el logo del sindicato."""
    ses_emp = sesion_actual(request, "empleador")
    if ses_emp and request.cookies.get("cuit_emp", "") == cuit:
        pass
    else:
        ses_sind = sesion_actual(request, "sindicato")
        with db.get_session() as s:
            propio = ses_sind and s.exec(select(Empleador).where(
                Empleador.cuit == cuit, Empleador.sindicato_id == ses_sind.get("sid"))).first()
        if not propio:
            raise HTTPException(403, "No autorizado")
    foto = db.foto_empleador(cuit)
    if not foto:
        raise HTTPException(404, "Sin foto")
    return BinResponse(content=foto["datos"], media_type=foto["mime"],
                        headers={"Cache-Control": "no-cache"})


# ---------- Trámites (Fase 3 de Módulos + Notificaciones + Trámites) ----------
ARCHIVO_MIMES_TRAMITE = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
    ".pdf": "application/pdf", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_ARCHIVO_TRAMITE = 10 * 1024 * 1024  # 10 MB


def _leer_archivo_tramite(archivo: UploadFile):
    """Adjunto de una nota o de un campo tipo "archivo" -- mismo criterio de
    tipos/tamaño que _leer_adjunto_notificacion, tope más generoso porque
    acá puede ir un recibo escaneado o un comprobante."""
    import os
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in ARCHIVO_MIMES_TRAMITE:
        return None, "", ""
    datos = archivo.file.read()
    if not datos or len(datos) > MAX_ARCHIVO_TRAMITE:
        return None, "", ""
    return datos, ARCHIVO_MIMES_TRAMITE[ext], archivo.filename


def _notificar_cambio_tramite(sid: int, cuil: str, numero: str, texto: str) -> None:
    """Las novedades de un trámite NO generan Notificacion (decisión de Sd
    2026-09-02): el aviso in-app viaja por el globo de Trámites (visto vs
    NULL). Este gancho quedó para el canal PUSH: si las claves VAPID están
    configuradas, el teléfono recibe la novedad; si no, no hace nada."""
    push.notificar_tramite(cuil, numero, texto)


TIPOS_DATO_TRAMITE = ("texto", "numero", "fecha", "archivo", "seleccion",
                       "opcion_unica", "multiple", "booleano", "separador")
ANCHOS_CAMPO_TRAMITE = ("completo", "mitad", "tercio")


def _campos_tramite_validos(campos_crudos: list) -> list:
    """Normaliza y descarta campos mal formados que pudieran llegar de un
    request armado a mano -- misma lógica de saneo defensivo que ya usan
    _destinos_validos/_modulos_de para otros datos que vienen del cliente.
    "separador" es el único tipo_dato sin etiqueta obligatoria (es una raya
    visual, no junta respuesta)."""
    validos = []
    for c in campos_crudos:
        if not isinstance(c, dict):
            continue
        if c.get("tipo_dato") not in TIPOS_DATO_TRAMITE:
            continue
        if c.get("tipo_dato") != "separador" and not str(c.get("etiqueta") or "").strip():
            continue

        def _entero(v):
            try:
                return int(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None

        validos.append({
            # id presente = campo que ya existe y se actualiza en el lugar
            # (db.editar_tipo_tramite sincroniza por id; borrar y recrear
            # rompía el FK de RespuestaTramite). Un id inventado no matchea
            # ningún campo del tipo y termina creando uno nuevo, inocuo.
            "id": _entero(c.get("id")),
            "etiqueta": str(c.get("etiqueta") or "").strip()[:200],
            "tipo_dato": c["tipo_dato"],
            "longitud_maxima": _entero(c.get("longitud_maxima")),
            "longitud_exacta": _entero(c.get("longitud_exacta")),
            "decimales": _entero(c.get("decimales")),
            "tipos_archivo_permitidos": str(c.get("tipos_archivo_permitidos") or "").strip()[:200],
            "opciones": str(c.get("opciones") or "").strip()[:500],
            "ancho": c.get("ancho") if c.get("ancho") in ANCHOS_CAMPO_TRAMITE else "completo",
            "obligatorio": bool(c.get("obligatorio", True)),
            # Una validación mal formada no se guarda (se descarta acá, no
            # explota después en la pantalla del trabajador).
            "validaciones": validaciones_tramite.validaciones_saneadas(
                c.get("validaciones"), c["tipo_dato"]),
        })
    return validos


@app.post("/admin/tramite-tipo")
async def abm_tramite_tipo(
    request: Request,
    id: str = Form(""), titulo: str = Form(...), codigo: str = Form(...),
    activo: str = Form("si"), campos_json: str = Form(...),
    reglas_json: str = Form("[]"),
    area_destino_default_id: str = Form(""), seccional_id: str = Form(""),
    destinos_json: str = Form("{}"),
    permite_pase: str = Form(""), areas_pase: list[str] = Form(default=[]),
):
    """El formulario declara su RUTEO además de sus campos (decisiones N6 y
    N7): a qué área cae por defecto, el mapa seccional -> área, y si es
    global o de una seccional."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    import json
    try:
        campos_crudos = json.loads(campos_json)
        assert isinstance(campos_crudos, list)
        reglas_crudas = json.loads(reglas_json or "[]")
        assert isinstance(reglas_crudas, list)
        destinos_crudos = json.loads(destinos_json or "{}")
        assert isinstance(destinos_crudos, dict)
    except Exception:
        return RedirectResponse("/admin?error=campos#tramites", status_code=303)
    campos = _campos_tramite_validos(campos_crudos)
    if not campos:
        return RedirectResponse("/admin?error=campos#tramites", status_code=303)
    reglas = validaciones_tramite.reglas_saneadas(reglas_crudas, campos)
    with db.get_session() as s:
        destino_default = _id_propio(s, Area, area_destino_default_id, sid)
        del_seccional = _id_propio(s, Seccional, seccional_id, sid)
    # El destino por defecto es OBLIGATORIO: sin él, una seccional que nadie
    # mapeó dejaría trámites sin dueño y nadie los vería en ninguna bandeja.
    if not destino_default:
        return RedirectResponse("/admin?error=sindestino#tramites", status_code=303)
    # Un admin local solo arma formularios DE su seccional, y su destino y
    # su mapa tienen que caer dentro de su alcance.
    if del_seccional:
        _exigir_alcance_seccional(request, del_seccional)
    mapa = {}
    for k, v in destinos_crudos.items():
        try:
            mapa[int(k)] = int(v)
        except (TypeError, ValueError):
            continue    # "sin área": esa seccional cae al default
    if id:
        tipo = db.tipo_tramite_por_id(int(id))
        if not tipo or tipo["sindicato_id"] != sid:
            return RedirectResponse("/admin#tramites", status_code=303)
        # La seccional de un formulario no se edita (ver editar_tipo_tramite).
        if tipo.get("seccional_id"):
            _exigir_alcance_seccional(request, tipo["seccional_id"])
        db.editar_tipo_tramite(int(id), sid, titulo, codigo, activo == "si", campos, reglas,
                               area_destino_default_id=destino_default,
                               permite_pase=bool(permite_pase))
        db.set_destinos_tipo_tramite(int(id), mapa, sid)
        db.set_areas_de_pase(int(id), _ids_int(areas_pase), sid)
    else:
        nuevo_id = db.crear_tipo_tramite(sid, titulo, codigo, campos, reglas,
                                         area_destino_default_id=destino_default,
                                         seccional_id=del_seccional,
                                         permite_pase=bool(permite_pase))
        db.set_destinos_tipo_tramite(nuevo_id, mapa, sid)
        db.set_areas_de_pase(nuevo_id, _ids_int(areas_pase), sid)
    return RedirectResponse("/admin#tramites", status_code=303)


@app.post("/admin/tramite-tipo/probar")
async def probar_tramite_tipo(request: Request):
    """Banco de pruebas del constructor: evalúa datos de prueba contra las
    validaciones del formulario TAL CUAL está en pantalla (aunque no esté
    guardado). Ejecuta validaciones_tramite.evaluar_envio, la MISMA función
    del envío real -- si acá diera distinto que al recibir un trámite, el
    error sería silencioso porque nadie los compara (el criterio de
    resolver_destinatarios en Notificaciones). Sirve para los dos
    constructores (trabajador y empresa): la lógica es pura, no toca tablas,
    por eso alcanza con tener habilitado cualquiera de los dos módulos."""
    sid = exigir_sindicato(request)
    if "tramites" not in _modulos_de(sid):
        _exigir_modulo(sid, "empleadores")
    cuerpo = await request.json()
    campos = _campos_tramite_validos(cuerpo.get("campos") or [])
    reglas = validaciones_tramite.reglas_saneadas(cuerpo.get("reglas") or [], campos)
    # Los campos todavía no tienen id (no están guardados): se usa el índice
    # como id, y el cliente referencia sus inputs de prueba igual.
    for i, c in enumerate(campos):
        c["id"] = i
    crudos = cuerpo.get("valores") or {}
    valores = {}
    for clave, valor in crudos.items() if isinstance(crudos, dict) else []:
        try:
            valores[int(clave)] = str(valor)
        except (TypeError, ValueError):
            continue
    return validaciones_tramite.evaluar_envio(campos, reglas, valores)


@app.post("/admin/tramite-tipo/borrar")
def borrar_tramite_tipo(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    ok = db.borrar_tipo_tramite(id, sid)
    if not ok:
        return RedirectResponse("/admin?error=tramitesenviados#tramites", status_code=303)
    return RedirectResponse("/admin#tramites", status_code=303)


# ==================== Encuestas (SPRINT_ENCUESTAS.md, Fase 1) ====================
# El constructor. Crear y editar borradores: publicar, comunicar y leer los
# resultados son actos distintos y viven en fases posteriores.
def _preguntas_del_formulario(preguntas_json: str, modo: str):
    """(preguntas saneadas, mensaje de error). El saneo vive en encuestas.py,
    sin base ni request, así que es el MISMO para el alta, la edición y los
    tests -- mismo criterio que validaciones_tramite."""
    import json
    try:
        crudas = json.loads(preguntas_json or "[]")
        assert isinstance(crudas, list)
    except Exception:
        return [], "No se pudieron leer las preguntas."
    limpias, errores = encuestas.preguntas_saneadas(modo, crudas)
    return limpias, (errores[0] if errores else "")


@app.post("/admin/encuesta")
def abm_encuesta(
    request: Request,
    id: str = Form(""), titulo: str = Form(...), descripcion: str = Form(""),
    modo: str = Form("nominal"), cortes: list[str] = Form(default=[]),
    fecha_desde: str = Form(""), fecha_hasta: str = Form(""),
    mostrar_resultados: str = Form(""), preguntas_json: str = Form("[]"),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    uid = _uid_sesion(request)
    if modo not in encuestas.MODOS:
        modo = encuestas.NOMINAL
    preguntas, error = _preguntas_del_formulario(preguntas_json, modo)
    if error:
        return RedirectResponse(f"/admin?error=encuesta&motivo={quote(error)}#encuestas",
                                status_code=303)
    if fecha_desde and fecha_hasta and fecha_hasta < fecha_desde:
        return RedirectResponse(
            "/admin?error=encuesta&motivo=" + quote("La fecha de cierre no puede ser "
                                                    "anterior a la de apertura.") + "#encuestas",
            status_code=303)
    datos = {"titulo": titulo, "descripcion": descripcion, "modo": modo,
             "cortes": cortes, "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
             "mostrar_resultados": bool(mostrar_resultados)}
    if id:
        r = db.editar_encuesta(int(id), sid, datos, preguntas, usuario_id=uid)
        if not r["ok"]:
            return RedirectResponse(
                f"/admin?error=encuesta&motivo={quote(r['error'])}#encuestas", status_code=303)
    else:
        # La seccional de quien la crea viaja con la encuesta: es lo que
        # después deja que cada seccional vea las suyas (N18).
        db.crear_encuesta(sid, uid, db.seccional_de_usuario(uid), datos, preguntas)
    return RedirectResponse("/admin#encuestas", status_code=303)


def _valores_sueltos(valores) -> list:
    """["a, b", "c"] -> ["a", "b", "c"]. Sin vacíos ni repetidos."""
    salida, vistos = [], set()
    for bruto in (valores or []):
        for parte in str(bruto).split(","):
            v = parte.strip()
            if v and v not in vistos:
                vistos.add(v)
                salida.append(v)
    return salida


@app.post("/admin/encuesta/publicar")
def publicar_encuesta(request: Request, id: int = Form(...), criterio: str = Form(...),
                      valores: list[str] = Form(default=[])):
    """Fija el padrón y abre la encuesta. Es irreversible: a partir de acá
    hay gente invitada y la lista no se recalcula (N10)."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    # Los valores llegan como varios campos (una seccional por check) o como
    # un texto con comas (CUILs, CUITs): se aplana acá, así la pantalla usa
    # la forma que le quede mejor para cada criterio.
    r = db.publicar_encuesta(id, sid, criterio, _valores_sueltos(valores),
                             usuario_id=_uid_sesion(request))
    if not r["ok"]:
        return RedirectResponse(f"/admin?error=encuesta&motivo={quote(r['error'])}#encuestas",
                                status_code=303)
    return RedirectResponse("/admin#encuestas", status_code=303)


@app.post("/admin/encuesta/cerrar")
def cerrar_encuesta(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    r = db.cerrar_encuesta(id, sid, usuario_id=_uid_sesion(request))
    if not r["ok"]:
        return RedirectResponse(f"/admin?error=encuesta&motivo={quote(r['error'])}#encuestas",
                                status_code=303)
    return RedirectResponse("/admin#encuestas", status_code=303)


@app.get("/admin/encuesta/destinatarios")
def encuesta_contar_destinatarios(request: Request, criterio: str = "todos",
                                  valores: list[str] = Query(default=[])):
    """Cuántos afiliados alcanza un criterio, para que el admin vea el
    número ANTES de publicar. Usa la misma función que el envío real, así
    que el número que confirmó es el que sale (mismo criterio que el
    preview de Notificaciones)."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    cuils = db.resolver_destinatarios(sid, criterio, _valores_sueltos(valores),
                                      usuario_id=_uid_sesion(request))
    return {"cantidad": len(cuils)}


@app.get("/admin/encuesta/disclaimer")
def encuesta_disclaimer(request: Request, modo: str = "nominal",
                        cortes: list[str] = Query(default=[])):
    """El texto que verá el afiliado, para la vista previa del constructor.

    La pantalla NO arma este texto: se lo pide al servidor, que lo genera
    con la misma función que usará el trabajador (encuestas.disclaimer).
    Es el mismo criterio que evaluar_envio() en Trámites -- una sola
    implementación --, y acá pesa más: el disclaimer es una promesa sobre
    qué se guarda, y una copia en JS que se desincronice haría que la
    pantalla prometa algo distinto de lo que el sistema cumple.
    """
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    if modo not in encuestas.MODOS:
        modo = encuestas.NOMINAL
    return {"lineas": encuestas.disclaimer(modo, cortes, db.umbral_encuestas())}


@app.post("/admin/encuesta/borrar")
def borrar_encuesta(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    r = db.borrar_encuesta(id, sid)
    if not r["ok"]:
        return RedirectResponse(f"/admin?error=encuesta&motivo={quote(r['error'])}#encuestas",
                                status_code=303)
    return RedirectResponse("/admin#encuestas", status_code=303)


@app.post("/admin/encuesta/duplicar")
def duplicar_encuesta(request: Request, id: int = Form(...)):
    """Copia la estructura en un borrador nuevo (N23). Es la salida cuando
    una encuesta con respuestas quedó mal, y la forma de repetir la misma
    encuesta cada trimestre para comparar."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "encuestas")
    uid = _uid_sesion(request)
    nueva = db.duplicar_encuesta(id, sid, usuario_id=uid,
                                 seccional_id=db.seccional_de_usuario(uid))
    if not nueva:
        return RedirectResponse("/admin?error=encuesta&motivo=" +
                                quote("La encuesta no existe.") + "#encuestas", status_code=303)
    return RedirectResponse("/admin#encuestas", status_code=303)


@app.get("/admin/tramite/{tramite_id}")
def admin_ver_tramite(tramite_id: int, request: Request):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    # Con el usuario: el detalle informa si puede responder y a qué áreas
    # puede derivar. La pantalla los necesita a la vez -- sin saber si puede
    # escribir, el chat no sabe si mostrar el cajón de respuesta.
    detalle = db.tramite_detalle(tramite_id, usuario_id=_uid_sesion(request))
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    _exigir_alcance_tramite(request, tramite_id, sid)
    return detalle


@app.get("/admin/tramites-nuevos-cantidad")
def admin_tramites_nuevos_cantidad(request: Request):
    """Para el polling del globo de "Ver trámites" en admin.html -- si el
    panel queda abierto y llega un trámite nuevo, el globo no se actualizaba
    hasta recargar (se calculaba solo al renderizar la página). Payload
    mínimo (un número), pensado para pedirse cada 30s sin peso real."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    # Con el usuario: el globo en vivo tiene que contar lo MISMO que la
    # bandeja, o mostraría un número que al abrir la pestaña no baja.
    return {"cantidad": db.contar_tramites_nuevos(sid, _uid_sesion(request))}


def _formulario_para_chat(sid: int, formulario_id: str, familia: str):
    """Sanea el formulario que el admin adjunta en un mensaje del chat: tiene
    que ser un tipo ACTIVO de SU sindicato (de la familia correcta), si no se
    descarta en silencio -- mismo criterio defensivo que _destinos_validos."""
    try:
        fid = int(formulario_id or 0)
    except (TypeError, ValueError):
        return None
    if not fid:
        return None
    tipo = (db.tipo_tramite_empleador_por_id(fid) if familia == "empresa"
            else db.tipo_tramite_por_id(fid))
    if not tipo or tipo["sindicato_id"] != sid or not tipo["activo"]:
        return None
    return fid


@app.post("/admin/tramite/{tramite_id}/pase")
def admin_pasar_tramite(tramite_id: int, request: Request,
                         area_destino_id: int = Form(...), motivo: str = Form("")):
    """Deriva el trámite a otra área de las que el formulario declara.

    Solo puede derivar quien puede RESPONDER: el área que lo tiene. La que
    ya lo derivó conserva lectura pero no vuelve a moverlo -- si no, dos
    áreas se lo pasarían de vuelta entre sí sin que nadie lo resuelva."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    detalle = db.tramite_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    _exigir_alcance_tramite(request, tramite_id, sid)
    _exigir_responder_tramite(request, tramite_id, sid)
    if not db.pasar_tramite(tramite_id, area_destino_id, _uid_sesion(request), sid,
                            (motivo or "").strip()):
        raise HTTPException(400, "No se puede derivar este trámite a esa área.")
    return {"ok": True}


@app.post("/admin/tramite/{tramite_id}/nota")
async def admin_nota_tramite(tramite_id: int, request: Request, texto: str = Form(""),
                              adjunto: UploadFile = File(None),
                              formulario_id: str = Form(""), estado: str = Form("")):
    """Responder y cambiar el estado son UN SOLO ACTO (decisión N9).

    La ruta /admin/tramite/{id}/estado dejó de existir: no hay forma de
    mover el estado sin decirle algo al trabajador. Antes eran dos rutas y
    cada una escribía su línea en el chat, así que una sola respuesta del
    sindicato aparecía dos veces del lado del afiliado."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    detalle = db.tramite_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    _exigir_alcance_tramite(request, tramite_id, sid)
    _exigir_responder_tramite(request, tramite_id, sid)
    if detalle["estado"] == "terminado":
        raise HTTPException(400, "Este trámite está terminado y no se puede modificar.")
    adjunto_datos, adjunto_mime, adjunto_nombre = None, "", ""
    if adjunto and adjunto.filename:
        adjunto_datos, adjunto_mime, adjunto_nombre = _leer_archivo_tramite(adjunto)
        if not adjunto_datos:
            raise HTTPException(400, "Adjunto inválido o supera el tamaño máximo (10 MB).")
    formulario = _formulario_para_chat(sid, formulario_id, "trabajador")
    if not texto.strip() and not adjunto_datos and not formulario:
        raise HTTPException(400, "La nota necesita texto, un adjunto o un formulario.")
    db.agregar_nota_tramite(tramite_id, "admin", texto, adjunto_datos, adjunto_mime,
                            adjunto_nombre, formulario_id=formulario,
                            estado_nuevo=estado)
    # El aviso también es UNO: si el estado se movió, se lo cuenta en el
    # mismo mensaje en vez de mandarle dos notificaciones por un solo acto.
    if formulario:
        aviso = 'Tu sindicato te mandó un formulario para iniciar.'
    elif estado and estado != detalle["estado"]:
        etiqueta = db.ESTADOS_TRAMITE_LABEL.get(estado, estado)
        aviso = f'Tu sindicato te respondió. Estado: {etiqueta}.'
    else:
        aviso = 'Tu sindicato te escribió en el chat.'
    _notificar_cambio_tramite(sid, detalle["cuil"], detalle["numero_expediente"], aviso)
    return {"ok": True}


@app.get("/tramite-respuesta-archivo/{respuesta_id}")
def servir_archivo_respuesta_tramite(respuesta_id: int, request: Request):
    with db.get_session() as s:
        r = s.get(RespuestaTramite, respuesta_id)
        if not r or not r.archivo_datos:
            raise HTTPException(404, "Sin archivo")
        tr = s.get(Tramite, r.tramite_id)
        if not _autorizado_para_tramite(request, tr):
            raise HTTPException(403, "No autorizado")
        return BinResponse(
            content=r.archivo_datos, media_type=r.archivo_mime or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{r.archivo_nombre or "archivo"}"'},
        )


@app.get("/tramite-nota-adjunto/{nota_id}")
def servir_adjunto_nota_tramite(nota_id: int, request: Request):
    with db.get_session() as s:
        n = s.get(NotaTramite, nota_id)
        if not n or not n.adjunto_datos:
            raise HTTPException(404, "Sin adjunto")
        tr = s.get(Tramite, n.tramite_id)
        if not _autorizado_para_tramite(request, tr):
            raise HTTPException(403, "No autorizado")
        return BinResponse(
            content=n.adjunto_datos, media_type=n.adjunto_mime or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{n.adjunto_nombre or "adjunto"}"'},
        )


def _autorizado_para_tramite(request: Request, tr) -> bool:
    if not tr:
        return False
    ses_sind = sesion_actual(request, "sindicato")
    if ses_sind and ses_sind.get("sid") == tr.sindicato_id:
        return True
    ses_trab = sesion_actual(request, "trabajador")
    if ses_trab:
        cuil = request.cookies.get("cuil_trab", "")
        if cuil and cuil == tr.cuil:
            return True
    return False


@app.get("/api/tramites/tipos")
def api_tipos_tramite(request: Request):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        return {"tipos": []}
    # Los formularios GLOBALES más los de SU seccional (decisión N7). El
    # recorte va en la consulta: si se hiciera en el cliente, los
    # formularios de otras delegaciones viajarían igual en el JSON.
    return {"tipos": db.tipos_tramite_del_sindicato(
        sid, solo_activos=True, seccional_id=db.seccional_de_trabajador(cuil, sid))}


@app.get("/api/tramites/mios")
def api_mis_tramites(request: Request):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    return {"tramites": db.tramites_de_trabajador(cuil, sid) if sid else []}


@app.get("/api/tramite/{numero_expediente}")
def api_consultar_tramite(numero_expediente: str, request: Request):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    detalle = db.tramite_por_numero_expediente(numero_expediente.strip().upper())
    if not detalle or detalle["cuil"] != cuil:
        raise HTTPException(404, "No encontramos un trámite tuyo con ese número.")
    # abrir el detalle apaga la novedad de ESTE trámite en el globo
    db.marcar_tramite_visto(detalle["id"], cuil)
    return detalle


@app.get("/app/notificaciones", response_class=HTMLResponse)
def pantalla_notificaciones(request: Request):
    """Bandeja de notificaciones del trabajador (2026-09-02): reemplaza al
    modal de la portada por una página completa estilo casilla de correo --
    agrupadas por día, leídas/no leídas y filtros. Los datos los trae el
    mismo /api/mis-notificaciones de siempre."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        return RedirectResponse("/ingresar", status_code=303)
    sid = sindicato_activo_trabajador(request)
    if not sid:
        return RedirectResponse("/ingresar", status_code=303)
    _exigir_modulo(sid, "notificaciones")
    marca = db.marca_sindicato(sid)
    return templates.TemplateResponse("notificaciones.html", {
        "request": request,
        "sindicato": marca["nombre"],
        "marca": marca,
        "marca_plataforma": db.marca_plataforma(),
    })


# ---------- Web Push del trabajador (ver push.py) ----------
# La ruta /sw.js y el registro del service worker ya existían (PWA,
# main.service_worker + static/pwa.js): acá solo van la suscripción y la
# clave pública.

@app.get("/api/push/clave-publica")
def api_push_clave_publica():
    """Clave pública VAPID para suscribirse. Vacía = push apagado (sin
    claves configuradas): el cliente no ofrece nada."""
    return {"clave": push.VAPID_PUBLIC_KEY if push.habilitado() else ""}


@app.post("/api/push/suscribir")
async def api_push_suscribir(request: Request):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    cuerpo = await request.json()
    endpoint = str(cuerpo.get("endpoint") or "")[:1000]
    claves = cuerpo.get("keys") or {}
    if not endpoint or not claves.get("p256dh") or not claves.get("auth"):
        raise HTTPException(400, "Suscripción incompleta")
    db.guardar_suscripcion_push(cuil, endpoint,
                                str(claves["p256dh"])[:300], str(claves["auth"])[:300])
    return {"ok": True}


@app.post("/api/push/desuscribir")
async def api_push_desuscribir(request: Request):
    ses = sesion_actual(request, "trabajador")
    if not ses:
        raise HTTPException(403, "No autorizado")
    cuerpo = await request.json()
    db.borrar_suscripcion_push(str(cuerpo.get("endpoint") or ""))
    return {"ok": True}


@app.get("/api/tramites/novedades")
def api_novedades_tramites(request: Request):
    """Cantidad de trámites del trabajador con movimientos sin ver, para el
    globo de Trámites (reemplaza a las notificaciones de sistema)."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        return {"cantidad": 0}
    return {"cantidad": db.contar_tramites_con_novedades(cuil, sid)}


@app.get("/api/empresa/tramites/novedades")
def api_novedades_tramites_empresa(request: Request):
    """Mirror para la empresa."""
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_empleador(request)
    if not sid:
        return {"cantidad": 0}
    return {"cantidad": db.contar_tramites_empleador_con_novedades(cuit, sid)}


# ---------- Consultas del trabajador sobre el convenio (bloque 3) ----------

@app.get("/app/convenio", response_class=HTMLResponse)
def pantalla_convenio(request: Request):
    """Consultas sobre el convenio. NO figura en el menú del trabajador: se
    llega solo con la URL directa (decisión de producto del piloto).

    Que no esté listada NO es control de acceso -- exige sesión de trabajador
    y el módulo, igual que cualquier otra pantalla. Lo no listado es para no
    ensuciar la navegación mientras el piloto se prueba, no para esconderla
    de nadie."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        return RedirectResponse("/ingresar", status_code=303)
    sid = sindicato_activo_trabajador(request)
    if not sid:
        return RedirectResponse("/ingresar", status_code=303)
    _exigir_modulo(sid, "convenio")
    sind = None
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
    return templates.TemplateResponse("convenio.html", {
        "request": request,
        "sindicato": sind.nombre if sind else "",
        "marca": db.marca_sindicato(sid),
        "convenios": [c for c in db.convenios_del_sindicato(sid, solo_activos=True)
                      if c["fragmentos_vigentes"] > 0],
    })


@app.get("/api/convenio/convenios")
def api_convenios_del_trabajador(request: Request):
    """Los convenios que el trabajador puede consultar en su sindicato activo.

    El trabajador ELIGE cuál: no se infiere de su empleador ni su categoría,
    porque inferirlo mal y contestarle con el convenio equivocado es peor que
    no contestarle."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid or "convenio" not in _modulos_de(sid):
        return {"convenios": []}
    return {"convenios": [
        {"id": c["id"], "nombre": c["nombre"], "codigo": c["codigo"]}
        for c in db.convenios_del_sindicato(sid, solo_activos=True)
        if c["fragmentos_vigentes"] > 0]}


@app.post("/api/convenio/consultar")
async def api_consultar_convenio(request: Request):
    """Recibe la pregunta, busca y responde citando la fuente.

    Tarda unos segundos: la búsqueda vectorial son ~90 ms pero después hay
    una llamada al modelo. Es un request normal, a diferencia de la
    indexación."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    _exigir_modulo(sid, "convenio")

    cuerpo = await request.json()
    pregunta = (cuerpo.get("pregunta") or "").strip()
    convenio_id = cuerpo.get("convenio_id")
    if not pregunta:
        raise HTTPException(400, "Escribí una pregunta.")
    if len(pregunta) > 500:
        raise HTTPException(400, "La pregunta es demasiado larga.")
    if not convenio_id:
        raise HTTPException(400, "Elegí un convenio.")

    # El convenio tiene que ser DE SU SINDICATO: el id viaja en el body y se
    # puede escribir a mano.
    with db.get_session() as s:
        c = s.get(Convenio, int(convenio_id))
        if not c or c.sindicato_id != sid or not c.activo:
            raise HTTPException(404, "Convenio no encontrado")

    return rag.responder(pregunta, sid, int(convenio_id), cuil=cuil)


@app.get("/api/encuestas")
def api_encuestas_del_trabajador(request: Request):
    """Las encuestas a las que este CUIL fue invitado. Una encuesta a la que
    no fue invitado no aparece ni existe para él."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    _exigir_modulo(sid, "encuestas")
    return {"encuestas": db.encuestas_de_trabajador(cuil, sid)}


@app.post("/api/encuesta/{encuesta_id}")
async def api_responder_encuesta(encuesta_id: int, request: Request):
    """Responder. El cuerpo es {"respuestas": {pregunta_id: valor}}.

    Acá no se valida casi nada: TODO lo decide
    db.registrar_respuesta_encuesta, que chequea el padrón antes que las
    respuestas (es control de acceso, no validación), sanea contra las
    preguntas guardadas y escribe la urna y el padrón en una sola
    transacción. La ruta solo resuelve quién está pidiendo.
    """
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    _exigir_modulo(sid, "encuestas")
    try:
        cuerpo = await request.json()
    except Exception:
        raise HTTPException(400, "Cuerpo inválido")
    r = db.registrar_respuesta_encuesta(encuesta_id, cuil, sid,
                                        (cuerpo or {}).get("respuestas") or {})
    if not r["ok"]:
        raise ErrorApp("E-ENCUESTA-01", r["error"])
    return {"ok": True}


@app.post("/api/tramite")
async def api_enviar_tramite(request: Request):
    """Los campos vienen con nombre dinámico (campo_{id} / archivo_{id}) según
    el formulario de CADA tipo de trámite, así que se lee el form crudo en
    vez de declarar parámetros fijos. Valida obligatorios/longitud/tipo de
    archivo server-side -- el formulario del cliente ya valida lo mismo,
    pero esto es lo que realmente decide qué se persiste."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    _exigir_modulo(sid, "tramites")
    form = await request.form()
    try:
        tipo_tramite_id = int(form.get("tipo_tramite_id") or 0)
    except ValueError:
        raise HTTPException(400, "Tipo de trámite inválido")
    tipo = db.tipo_tramite_por_id(tipo_tramite_id)
    if not tipo or tipo["sindicato_id"] != sid or not tipo["activo"]:
        raise HTTPException(404, "Tipo de trámite inválido")
    # Un formulario DE OTRA SECCIONAL no se puede usar aunque se mande el id
    # a mano: que la lista no lo ofrezca no es un control, es una comodidad.
    if tipo.get("seccional_id") and \
            tipo["seccional_id"] != db.seccional_de_trabajador(cuil, sid):
        raise HTTPException(404, "Tipo de trámite inválido")

    errores = []
    respuestas = []
    for campo in tipo["campos"]:
        if campo["tipo_dato"] == "separador":
            continue  # raya visual, no junta respuesta
        if campo["tipo_dato"] == "booleano":
            # Un checkbox desmarcado ni siquiera viaja en el form -- "No" es
            # una respuesta válida en sí misma, no aplica el chequeo de
            # obligatorio genérico (una raya sin marcar no es "falta esto").
            marcado = bool(form.get(f'campo_{campo["id"]}'))
            respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": "Sí" if marcado else "No"})
            continue
        if campo["tipo_dato"] == "multiple":
            valores = [v.strip() for v in form.getlist(f'campo_{campo["id"]}') if str(v).strip()]
            if not valores:
                if campo["obligatorio"]:
                    errores.append(f'"{campo["etiqueta"]}" es obligatorio.')
                continue
            opciones = [o.strip() for o in (campo.get("opciones") or "").split(",") if o.strip()]
            if opciones and any(v not in opciones for v in valores):
                errores.append(f'"{campo["etiqueta"]}": elegí solo entre las opciones permitidas.')
                continue
            respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": ", ".join(valores)})
            continue
        if campo["tipo_dato"] == "archivo":
            archivo = form.get(f'archivo_{campo["id"]}')
            if archivo is None or not getattr(archivo, "filename", ""):
                if campo["obligatorio"]:
                    errores.append(f'"{campo["etiqueta"]}" es obligatorio.')
                continue
            import os
            ext = os.path.splitext(archivo.filename)[1].lower().lstrip(".")
            permitidos = [e.strip().lower() for e in (campo["tipos_archivo_permitidos"] or "").split(",") if e.strip()]
            if permitidos and ext not in permitidos:
                errores.append(f'"{campo["etiqueta"]}": el archivo tiene que ser {", ".join(permitidos)}.')
                continue
            datos = await archivo.read()
            if not datos or len(datos) > MAX_ARCHIVO_TRAMITE:
                errores.append(f'"{campo["etiqueta"]}": archivo vacío o supera los 10 MB.')
                continue
            mime = ARCHIVO_MIMES_TRAMITE.get(f".{ext}", archivo.content_type or "application/octet-stream")
            respuestas.append({"campo_tramite_id": campo["id"], "archivo_datos": datos,
                                "archivo_mime": mime, "archivo_nombre": archivo.filename})
            continue

        valor = str(form.get(f'campo_{campo["id"]}') or "").strip()
        if not valor:
            if campo["obligatorio"]:
                errores.append(f'"{campo["etiqueta"]}" es obligatorio.')
            continue
        if campo["tipo_dato"] in ("seleccion", "opcion_unica"):
            opciones = [o.strip() for o in (campo.get("opciones") or "").split(",") if o.strip()]
            if opciones and valor not in opciones:
                errores.append(f'"{campo["etiqueta"]}": elegí una de las opciones permitidas.')
                continue
            respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": valor})
            continue
        if campo["tipo_dato"] == "numero":
            try:
                float(valor.replace(",", "."))
            except ValueError:
                errores.append(f'"{campo["etiqueta"]}" tiene que ser un número.')
                continue
        if campo["longitud_exacta"] and len(valor) != campo["longitud_exacta"]:
            errores.append(f'"{campo["etiqueta"]}" tiene que tener exactamente {campo["longitud_exacta"]} caracteres.')
            continue
        if campo["longitud_maxima"] and len(valor) > campo["longitud_maxima"]:
            errores.append(f'"{campo["etiqueta"]}" supera el máximo de {campo["longitud_maxima"]} caracteres.')
            continue
        respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": valor})

    # Capa de validaciones del formulario (fija + consistencia): corre
    # SIEMPRE en el servidor aunque el cliente valide lo mismo en vivo --
    # esto es lo que decide qué se persiste. "avisa" no frena: queda como
    # advertencia para el operador en el detalle del trámite.
    valores = {r["campo_tramite_id"]: r.get("valor_texto", "")
               for r in respuestas if "valor_texto" in r}
    veredicto = validaciones_tramite.evaluar_envio(
        tipo["campos"], tipo.get("reglas_consistencia"), valores)
    errores += veredicto["errores"]

    if errores:
        return JSONResponse(status_code=422, content={
            "errores": errores, "errores_campos": veredicto["errores_campos"]})

    # Trámite encadenado: si el formulario se abrió desde el CHAT de otro
    # trámite, el nuevo queda vinculado. Solo vale un trámite DEL MISMO
    # trabajador en el mismo sindicato; cualquier otra cosa se ignora.
    origen_id = None
    try:
        candidato = int(form.get("origen_tramite_id") or 0)
    except ValueError:
        candidato = 0
    if candidato:
        origen = db.tramite_detalle(candidato)
        if origen and origen["sindicato_id"] == sid and origen["cuil"] == cuil:
            origen_id = candidato

    resultado = db.crear_tramite(sid, tipo_tramite_id, cuil, respuestas,
                                 advertencias=veredicto["advertencias"],
                                 origen_tramite_id=origen_id)
    if not resultado:
        raise HTTPException(400, "No se pudo crear el trámite.")
    return resultado


@app.post("/api/tramite/{tramite_id}/nota")
async def api_nota_tramite_trabajador(tramite_id: int, request: Request, texto: str = Form(""),
                                       adjunto: UploadFile = File(None)):
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    detalle = db.tramite_detalle(tramite_id)
    if not detalle or detalle["cuil"] != cuil:
        raise HTTPException(404, "Trámite no encontrado")
    if detalle["estado"] == "terminado":
        raise HTTPException(400, "Este trámite está terminado y no se puede modificar.")
    adjunto_datos, adjunto_mime, adjunto_nombre = None, "", ""
    if adjunto and adjunto.filename:
        adjunto_datos, adjunto_mime, adjunto_nombre = _leer_archivo_tramite(adjunto)
        if not adjunto_datos:
            raise HTTPException(400, "Adjunto inválido o supera el tamaño máximo (10 MB).")
    if not texto.strip() and not adjunto_datos:
        raise HTTPException(400, "La nota necesita texto o un adjunto.")
    db.agregar_nota_tramite(tramite_id, "trabajador", texto, adjunto_datos, adjunto_mime, adjunto_nombre)
    return {"ok": True}


# ---------- Trámites externos a empleadores (Fase 5 del plan de Empleadores) ----------
# Mirror de la sección de Trámites de arriba (cuil -> cuit, "trabajador" ->
# "empresa") sobre las tablas propias Tipo/Campo/Tramite/Respuesta/Nota/Log
# "...Empleador". Reusa las constantes y helpers sin estado de la sección de
# trabajador (ARCHIVO_MIMES_TRAMITE, MAX_ARCHIVO_TRAMITE, _leer_archivo_tramite,
# _campos_tramite_validos, TIPOS_DATO_TRAMITE, ANCHOS_CAMPO_TRAMITE) -- son
# puramente de datos, no dependen de qué rol las llama.

def _notificar_cambio_tramite_empleador(sid: int, cuit: str, texto: str) -> None:
    """Mirror de _notificar_cambio_tramite: DESACTIVADA (el aviso viaja por
    el globo de Trámites de la empresa, ver visto_empresa_en)."""
    return None


def _autorizado_para_tramite_empleador(request: Request, tr) -> bool:
    if not tr:
        return False
    ses_sind = sesion_actual(request, "sindicato")
    if ses_sind and ses_sind.get("sid") == tr.sindicato_id:
        return True
    ses_emp = sesion_actual(request, "empleador")
    if ses_emp:
        cuit = request.cookies.get("cuit_emp", "")
        if cuit and cuit == tr.cuit:
            return True
    return False


@app.post("/admin/tramite-tipo-empresa")
async def abm_tramite_tipo_empresa(
    request: Request,
    id: str = Form(""), titulo: str = Form(...), codigo: str = Form(...),
    activo: str = Form("si"), campos_json: str = Form(...),
    reglas_json: str = Form("[]"),
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    import json
    try:
        campos_crudos = json.loads(campos_json)
        assert isinstance(campos_crudos, list)
        reglas_crudas = json.loads(reglas_json or "[]")
        assert isinstance(reglas_crudas, list)
    except Exception:
        return RedirectResponse("/admin?error=campos#empleadores", status_code=303)
    campos = _campos_tramite_validos(campos_crudos)
    if not campos:
        return RedirectResponse("/admin?error=campos#empleadores", status_code=303)
    reglas = validaciones_tramite.reglas_saneadas(reglas_crudas, campos)
    if id:
        db.editar_tipo_tramite_empleador(int(id), sid, titulo, codigo, activo == "si", campos, reglas)
    else:
        db.crear_tipo_tramite_empleador(sid, titulo, codigo, campos, reglas)
    return RedirectResponse("/admin#empleadores", status_code=303)


@app.post("/admin/tramite-tipo-empresa/borrar")
def borrar_tramite_tipo_empresa(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    ok = db.borrar_tipo_tramite_empleador(id, sid)
    if not ok:
        return RedirectResponse("/admin?error=tramitesenviados#empleadores", status_code=303)
    return RedirectResponse("/admin#empleadores", status_code=303)


@app.get("/admin/tramite-empresa/{tramite_id}")
def admin_ver_tramite_empresa(tramite_id: int, request: Request):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    detalle = db.tramite_empleador_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    return detalle


@app.get("/admin/tramites-empresa-nuevos-cantidad")
def admin_tramites_empresa_nuevos_cantidad(request: Request):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    return {"cantidad": db.contar_tramites_empleador_nuevos(sid)}


@app.post("/admin/tramite-empresa/{tramite_id}/estado")
def admin_cambiar_estado_tramite_empresa(tramite_id: int, request: Request, estado: str = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    detalle = db.tramite_empleador_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    if detalle["estado"] == "terminado":
        raise HTTPException(400, "Este trámite está terminado y no se puede modificar.")
    if not db.cambiar_estado_tramite_empleador(tramite_id, sid, estado):
        raise HTTPException(400, "Estado inválido")
    nuevo_label = db.ESTADOS_TRAMITE_LABEL.get(estado, estado)
    _notificar_cambio_tramite_empleador(sid, detalle["cuit"],
        f'Tu trámite {detalle["numero_expediente"]} cambió de estado: {nuevo_label}.')
    return {"ok": True}


@app.post("/admin/tramite-empresa/{tramite_id}/nota")
async def admin_nota_tramite_empresa(tramite_id: int, request: Request, texto: str = Form(""),
                                      adjunto: UploadFile = File(None),
                                      formulario_id: str = Form("")):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "empleadores")
    detalle = db.tramite_empleador_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    if detalle["estado"] == "terminado":
        raise HTTPException(400, "Este trámite está terminado y no se puede modificar.")
    adjunto_datos, adjunto_mime, adjunto_nombre = None, "", ""
    if adjunto and adjunto.filename:
        adjunto_datos, adjunto_mime, adjunto_nombre = _leer_archivo_tramite(adjunto)
        if not adjunto_datos:
            raise HTTPException(400, "Adjunto inválido o supera el tamaño máximo (10 MB).")
    formulario = _formulario_para_chat(sid, formulario_id, "empresa")
    if not texto.strip() and not adjunto_datos and not formulario:
        raise HTTPException(400, "La nota necesita texto, un adjunto o un formulario.")
    db.agregar_nota_tramite_empleador(tramite_id, "admin", texto, adjunto_datos, adjunto_mime,
                                      adjunto_nombre, formulario_id=formulario)
    aviso = (f'Tu sindicato te mandó un formulario en tu trámite {detalle["numero_expediente"]}.'
             if formulario else
             f'Tu sindicato agregó una nota a tu trámite {detalle["numero_expediente"]}.')
    _notificar_cambio_tramite_empleador(sid, detalle["cuit"], aviso)
    return {"ok": True}


@app.get("/tramite-empresa-respuesta-archivo/{respuesta_id}")
def servir_archivo_respuesta_tramite_empresa(respuesta_id: int, request: Request):
    with db.get_session() as s:
        r = s.get(RespuestaTramiteEmpleador, respuesta_id)
        if not r or not r.archivo_datos:
            raise HTTPException(404, "Sin archivo")
        tr = s.get(TramiteEmpleador, r.tramite_id)
        if not _autorizado_para_tramite_empleador(request, tr):
            raise HTTPException(403, "No autorizado")
        return BinResponse(
            content=r.archivo_datos, media_type=r.archivo_mime or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{r.archivo_nombre or "archivo"}"'},
        )


@app.get("/tramite-empresa-nota-adjunto/{nota_id}")
def servir_adjunto_nota_tramite_empresa(nota_id: int, request: Request):
    with db.get_session() as s:
        n = s.get(NotaTramiteEmpleador, nota_id)
        if not n or not n.adjunto_datos:
            raise HTTPException(404, "Sin adjunto")
        tr = s.get(TramiteEmpleador, n.tramite_id)
        if not _autorizado_para_tramite_empleador(request, tr):
            raise HTTPException(403, "No autorizado")
        return BinResponse(
            content=n.adjunto_datos, media_type=n.adjunto_mime or "application/octet-stream",
            headers={"Content-Disposition": f'inline; filename="{n.adjunto_nombre or "adjunto"}"'},
        )


@app.get("/api/empresa/tramites/tipos")
def api_tipos_tramite_empresa(request: Request):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_empleador(request)
    return {"tipos": db.tipos_tramite_empleador_del_sindicato(sid, solo_activos=True) if sid else []}


@app.get("/api/empresa/tramites/mios")
def api_mis_tramites_empresa(request: Request):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_empleador(request)
    return {"tramites": db.tramites_de_empresa(cuit, sid) if sid else []}


@app.get("/api/empresa/tramite/{numero_expediente}")
def api_consultar_tramite_empresa(numero_expediente: str, request: Request):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    detalle = db.tramite_empleador_por_numero_expediente(numero_expediente.strip().upper())
    if not detalle or detalle["cuit"] != cuit:
        raise HTTPException(404, "No encontramos un trámite tuyo con ese número.")
    db.marcar_tramite_empleador_visto(detalle["id"], cuit)
    return detalle


@app.post("/api/empresa/tramite")
async def api_enviar_tramite_empresa(request: Request):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    sid = sindicato_activo_empleador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    _exigir_modulo(sid, "empleadores")
    form = await request.form()
    try:
        tipo_tramite_id = int(form.get("tipo_tramite_id") or 0)
    except ValueError:
        raise HTTPException(400, "Tipo de trámite inválido")
    tipo = db.tipo_tramite_empleador_por_id(tipo_tramite_id)
    if not tipo or tipo["sindicato_id"] != sid or not tipo["activo"]:
        raise HTTPException(404, "Tipo de trámite inválido")

    errores = []
    respuestas = []
    for campo in tipo["campos"]:
        if campo["tipo_dato"] == "separador":
            continue
        if campo["tipo_dato"] == "booleano":
            marcado = bool(form.get(f'campo_{campo["id"]}'))
            respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": "Sí" if marcado else "No"})
            continue
        if campo["tipo_dato"] == "multiple":
            valores = [v.strip() for v in form.getlist(f'campo_{campo["id"]}') if str(v).strip()]
            if not valores:
                if campo["obligatorio"]:
                    errores.append(f'"{campo["etiqueta"]}" es obligatorio.')
                continue
            opciones = [o.strip() for o in (campo.get("opciones") or "").split(",") if o.strip()]
            if opciones and any(v not in opciones for v in valores):
                errores.append(f'"{campo["etiqueta"]}": elegí solo entre las opciones permitidas.')
                continue
            respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": ", ".join(valores)})
            continue
        if campo["tipo_dato"] == "archivo":
            archivo = form.get(f'archivo_{campo["id"]}')
            if archivo is None or not getattr(archivo, "filename", ""):
                if campo["obligatorio"]:
                    errores.append(f'"{campo["etiqueta"]}" es obligatorio.')
                continue
            import os
            ext = os.path.splitext(archivo.filename)[1].lower().lstrip(".")
            permitidos = [e.strip().lower() for e in (campo["tipos_archivo_permitidos"] or "").split(",") if e.strip()]
            if permitidos and ext not in permitidos:
                errores.append(f'"{campo["etiqueta"]}": el archivo tiene que ser {", ".join(permitidos)}.')
                continue
            datos = await archivo.read()
            if not datos or len(datos) > MAX_ARCHIVO_TRAMITE:
                errores.append(f'"{campo["etiqueta"]}": archivo vacío o supera los 10 MB.')
                continue
            mime = ARCHIVO_MIMES_TRAMITE.get(f".{ext}", archivo.content_type or "application/octet-stream")
            respuestas.append({"campo_tramite_id": campo["id"], "archivo_datos": datos,
                                "archivo_mime": mime, "archivo_nombre": archivo.filename})
            continue

        valor = str(form.get(f'campo_{campo["id"]}') or "").strip()
        if not valor:
            if campo["obligatorio"]:
                errores.append(f'"{campo["etiqueta"]}" es obligatorio.')
            continue
        if campo["tipo_dato"] in ("seleccion", "opcion_unica"):
            opciones = [o.strip() for o in (campo.get("opciones") or "").split(",") if o.strip()]
            if opciones and valor not in opciones:
                errores.append(f'"{campo["etiqueta"]}": elegí una de las opciones permitidas.')
                continue
            respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": valor})
            continue
        if campo["tipo_dato"] == "numero":
            try:
                float(valor.replace(",", "."))
            except ValueError:
                errores.append(f'"{campo["etiqueta"]}" tiene que ser un número.')
                continue
        if campo["longitud_exacta"] and len(valor) != campo["longitud_exacta"]:
            errores.append(f'"{campo["etiqueta"]}" tiene que tener exactamente {campo["longitud_exacta"]} caracteres.')
            continue
        if campo["longitud_maxima"] and len(valor) > campo["longitud_maxima"]:
            errores.append(f'"{campo["etiqueta"]}" supera el máximo de {campo["longitud_maxima"]} caracteres.')
            continue
        respuestas.append({"campo_tramite_id": campo["id"], "valor_texto": valor})

    # Misma capa de validaciones que api_enviar_tramite (mirror completo).
    valores = {r["campo_tramite_id"]: r.get("valor_texto", "")
               for r in respuestas if "valor_texto" in r}
    veredicto = validaciones_tramite.evaluar_envio(
        tipo["campos"], tipo.get("reglas_consistencia"), valores)
    errores += veredicto["errores"]

    if errores:
        return JSONResponse(status_code=422, content={
            "errores": errores, "errores_campos": veredicto["errores_campos"]})

    # Trámite encadenado (mirror de api_enviar_tramite).
    origen_id = None
    try:
        candidato = int(form.get("origen_tramite_id") or 0)
    except ValueError:
        candidato = 0
    if candidato:
        origen = db.tramite_empleador_detalle(candidato)
        if origen and origen["sindicato_id"] == sid and origen["cuit"] == cuit:
            origen_id = candidato

    resultado = db.crear_tramite_empleador(sid, tipo_tramite_id, cuit, respuestas,
                                           advertencias=veredicto["advertencias"],
                                           origen_tramite_id=origen_id)
    if not resultado:
        raise HTTPException(400, "No se pudo crear el trámite.")
    return resultado


@app.post("/api/empresa/tramite/{tramite_id}/nota")
async def api_nota_tramite_empresa(tramite_id: int, request: Request, texto: str = Form(""),
                                    adjunto: UploadFile = File(None)):
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        raise HTTPException(403, "No autorizado")
    detalle = db.tramite_empleador_detalle(tramite_id)
    if not detalle or detalle["cuit"] != cuit:
        raise HTTPException(404, "Trámite no encontrado")
    if detalle["estado"] == "terminado":
        raise HTTPException(400, "Este trámite está terminado y no se puede modificar.")
    adjunto_datos, adjunto_mime, adjunto_nombre = None, "", ""
    if adjunto and adjunto.filename:
        adjunto_datos, adjunto_mime, adjunto_nombre = _leer_archivo_tramite(adjunto)
        if not adjunto_datos:
            raise HTTPException(400, "Adjunto inválido o supera el tamaño máximo (10 MB).")
    if not texto.strip() and not adjunto_datos:
        raise HTTPException(400, "La nota necesita texto o un adjunto.")
    db.agregar_nota_tramite_empleador(tramite_id, "empresa", texto, adjunto_datos, adjunto_mime, adjunto_nombre)
    return {"ok": True}


# ---------- Aprendizaje: subir N recibos y proponer conceptos nuevos ----------
# ---------- Convenio: carga e indexación (bloque 2 de PLAN_RAG_CONVENIO.md) ----------
# Todo gateado por el módulo "convenio", opt-in por sindicato.

MAX_PDF_CONVENIO = 30 * 1024 * 1024   # 30 MB


@app.post("/admin/convenio")
def abm_convenio(request: Request, id: str = Form(""), nombre: str = Form(...),
                  codigo: str = Form(""), activo: str = Form("si")):
    """Alta o edición de un convenio. `nombre` es lo único que va a guiar al
    trabajador en el selector, así que conviene que sea entendible."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    if not nombre.strip():
        return RedirectResponse("/admin?error=datos#convenio", status_code=303)
    if id:
        db.editar_convenio(int(id), sid, nombre, codigo, activo == "si")
    else:
        db.crear_convenio(sid, nombre, codigo)
    return RedirectResponse("/admin#convenio", status_code=303)


@app.post("/admin/convenio/documento")
async def subir_documento_convenio(
    request: Request,
    convenio_id: int = Form(...), tipo: str = Form("convenio"),
    titulo: str = Form(""), fecha_documento: str = Form(""),
    observaciones: str = Form(""), observaciones_fecha: str = Form(""),
    vigencia_desde: str = Form(""), vigencia_hasta: str = Form(""),
    confirmar_ocr: str = Form(""), archivo: UploadFile = File(...),
):
    """Guarda el PDF y dispara la indexación EN SEGUNDO PLANO.

    No indexa acá: tarda ~9 minutos (medido) y ningún request sobrevive eso.
    Devuelve enseguida con el id del documento; el panel consulta el progreso.

    Si el PDF resulta ser un escaneo y el admin no confirmó el OCR, el
    documento queda en "error" con el motivo -- OCRear cuesta plata y tiene
    que poder enterarse antes, no después."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    if not archivo or not archivo.filename:
        return RedirectResponse("/admin?error=archivo#convenio", status_code=303)
    contenido = await archivo.read()
    if len(contenido) > MAX_PDF_CONVENIO:
        return RedirectResponse("/admin?error=tamano#convenio", status_code=303)
    if not archivo.filename.lower().endswith(".pdf"):
        return RedirectResponse("/admin?error=formato#convenio", status_code=303)

    doc_id = db.crear_documento_convenio(
        convenio_id=convenio_id, sindicato_id=sid, tipo=tipo, titulo=titulo,
        fecha_documento=fecha_documento, archivo_datos=contenido,
        archivo_mime="application/pdf", archivo_nombre=archivo.filename,
        observaciones=observaciones, observaciones_fecha=observaciones_fecha,
        vigencia_desde=vigencia_desde, vigencia_hasta=vigencia_hasta)
    if not doc_id:
        return RedirectResponse("/admin?error=convenioajeno#convenio", status_code=303)

    rag.indexar_en_segundo_plano(doc_id, permitir_ocr=(confirmar_ocr == "si"))
    return RedirectResponse(f"/admin?indexando={doc_id}#convenio", status_code=303)


@app.get("/admin/convenio/documento/{documento_id}/estado")
def estado_documento_convenio(documento_id: int, request: Request):
    """Progreso de la indexación, para que el panel lo consulte cada pocos
    segundos. Payload mínimo, pensado para pedirse seguido."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    with db.get_session() as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d or d.sindicato_id != sid:
            raise HTTPException(404, "Documento no encontrado")
        return {"estado": d.estado, "fragmentos": d.fragmentos_generados,
                "error": d.error_detalle, "origen_texto": d.origen_texto,
                "paginas": d.paginas}


@app.get("/admin/convenio/documento/{documento_id}/fragmentos")
def fragmentos_documento_convenio(documento_id: int, request: Request):
    """Vista previa: devuelve TEXTO, no solo el conteo. Un troceo malo pasa
    el "se detectaron N fragmentos" sin problema y arruina todo lo de abajo;
    el admin tiene que poder leer los primeros y darse cuenta."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    with db.get_session() as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d or d.sindicato_id != sid:
            raise HTTPException(404, "Documento no encontrado")
    return {"fragmentos": db.fragmentos_de_documento(documento_id, limite=8),
            "total": d.fragmentos_generados}


@app.post("/admin/convenio/documento/{documento_id}/vigencia")
def vigencia_documento_convenio(documento_id: int, request: Request,
                                 vigente: str = Form(...)):
    """Marca un documento como vigente o no. Es lo que se usa cuando un texto
    ordenado nuevo ya incorpora actas viejas: quedan guardadas pero salen de
    la búsqueda."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    db.set_vigencia_documento(documento_id, sid, vigente == "si")
    return RedirectResponse("/admin#convenio", status_code=303)


@app.post("/admin/convenio/documento/{documento_id}/borrar")
def borrar_documento_convenio_ruta(documento_id: int, request: Request):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    db.borrar_documento_convenio(documento_id, sid)
    return RedirectResponse("/admin#convenio", status_code=303)


@app.post("/admin/convenio/documento/{documento_id}/reindexar")
def reindexar_documento_convenio(documento_id: int, request: Request,
                                  confirmar_ocr: str = Form("")):
    """Rehace el troceo y los embeddings. Se usa al iterar la estrategia de
    troceo -- cuesta ~9 minutos pero no cuesta plata, que es justamente el
    motivo por el que se eligieron embeddings locales."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    with db.get_session() as s:
        d = s.get(DocumentoConvenio, documento_id)
        if not d or d.sindicato_id != sid:
            raise HTTPException(404, "Documento no encontrado")
    rag.indexar_en_segundo_plano(documento_id, permitir_ocr=(confirmar_ocr == "si"))
    return RedirectResponse(f"/admin?indexando={documento_id}#convenio", status_code=303)


@app.get("/admin/convenio/{convenio_id}/anteriores")
def documentos_anteriores(convenio_id: int, request: Request, fecha: str = ""):
    """Documentos vigentes anteriores a esa fecha. El panel lo consulta al
    elegir la fecha de un documento nuevo, para avisar en el momento -- que
    es cuando la persona tiene el contexto fresco."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "convenio")
    with db.get_session() as s:
        c = s.get(Convenio, convenio_id)
        if not c or c.sindicato_id != sid:
            raise HTTPException(404, "Convenio no encontrado")
    return {"anteriores": db.documentos_anteriores_a(convenio_id, fecha)}


@app.post("/admin/aprender")
async def aprender(request: Request, archivos: list[UploadFile] = File(...)):
    """Lee varios recibos (de uno o varios empleadores) y junta los conceptos
    nuevos, deduplicados por (código, CUIT del empleador) — el mismo código
    crudo de dos empleadores distintos puede significar cosas distintas."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "recibos")
    conceptos_actuales = db.conceptos_como_dicts(sid)
    genericos_actuales = [c for c in conceptos_actuales if not c.get("cuit_empleador")]
    acumulados = {}
    leidos, fallidos = 0, 0

    for archivo in archivos:
        contenido = await archivo.read()
        try:
            recibo, uso = await run_in_threadpool(extraer, contenido, archivo.content_type)
        except Exception:
            fallidos += 1
            continue
        leidos += 1
        db.registrar_uso_ia(sid, "", "aprendizaje",
                             uso["modelo"], uso["tokens_entrada"], uso["tokens_salida"])
        cuit_empleador = _norm_cuil((recibo.get("empleador") or {}).get("cuit")) or None
        for n in detectar_nuevos(conceptos_actuales, recibo["lineas"], cuit_empleador):
            clave = (n["codigo"], cuit_empleador or "")
            if clave in acumulados:
                acumulados[clave]["veces"] += 1
            else:
                acumulados[clave] = {**n, "remunerativo": n["tipo"] == "ingreso", "veces": 1,
                                      "cuit_empleador": cuit_empleador}

    # Antes de que el admin apruebe el lote, avisar si alguna propuesta se
    # parece a un concepto que YA está en el catálogo: darla de alta crearía
    # un duplicado que después hay que ir a limpiar a mano.
    for p in acumulados.values():
        similar = buscar_similar(p["descripcion"], conceptos_actuales)
        p["similar"] = {
            "codigo": similar["concepto"]["codigo"],
            "nombre": similar["concepto"]["nombre"],
            "ratio": similar["ratio"],
        } if similar else None
        # Si la propuesta es específica de un empleador, además sugerir a qué
        # concepto GENÉRICO parece corresponder — así la fórmula de siempre la
        # controla sin que el admin tenga que ir a buscarlo a mano. Si la IA
        # identificó un aporte de ley (jubilación/PAMI/obra social/cuota
        # sindical) es una señal más fuerte que la similitud de texto: se usa
        # primero, y solo se cae a la búsqueda por parecido si no aplica.
        p["generico_sugerido"] = None
        if p["cuit_empleador"]:
            codigo_universal = CATEGORIAS_UNIVERSALES.get(p.get("categoria_universal"))
            generico_universal = next(
                (c for c in genericos_actuales if c["codigo"] == codigo_universal), None
            ) if codigo_universal else None
            if generico_universal:
                p["generico_sugerido"] = {
                    "codigo": generico_universal["codigo"], "nombre": generico_universal["nombre"],
                }
            else:
                similar_generico = buscar_similar(p["descripcion"], genericos_actuales)
                if similar_generico:
                    p["generico_sugerido"] = {
                        "codigo": similar_generico["concepto"]["codigo"],
                        "nombre": similar_generico["concepto"]["nombre"],
                    }

    return {
        "leidos": leidos, "fallidos": fallidos,
        "propuestas": sorted(acumulados.values(), key=lambda x: -x["veces"]),
    }


@app.post("/admin/aprender/aplicar")
def aprender_aplicar(request: Request, payload: dict):
    """Da de alta en lote los conceptos aprobados por el admin. Cada uno puede
    venir con cuit_empleador (propuesto en /admin/aprender) y codigo_generico
    (que el admin haya confirmado o cambiado en la revisión del lote)."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "recibos")
    aprobados = payload.get("aprobados", [])
    altas = 0
    with db.get_session() as s:
        existentes = {(c.codigo, c.cuit_empleador or "") for c in s.exec(select(Concepto).where(
            Concepto.sindicato_id == sid)).all()}
        for c in aprobados:
            cuit_empleador = _norm_cuil(c.get("cuit_empleador", "")) or None
            clave = (c["codigo"], cuit_empleador or "")
            if clave not in existentes:
                s.add(Concepto(
                    sindicato_id=sid,
                    codigo=c["codigo"], nombre=c["descripcion"], tipo=c["tipo"],
                    remunerativo=c.get("remunerativo", True),
                    alias=[c["descripcion"]], pendiente_revision=False,
                    cuit_empleador=cuit_empleador,
                    codigo_generico=(c.get("codigo_generico") or "").strip() or None,
                ))
                existentes.add(clave)
                altas += 1
        s.commit()
    return {"ok": True, "altas": altas}


# ================= Admin de plataforma =================
# Una cookie POR ROL (antes había una sola, "sesion_mitrabajo", compartida
# entre los tres) -- con una sola cookie, loguearse como trabajador en OTRA
# pestaña del mismo navegador pisaba en silencio la sesión de admin/
# plataforma que la primera pestaña necesitaba (bug real, 2026-08-16: "abro
# la app del trabajador en otra pestaña, vuelvo a la de admin a los 2
# minutos y me pide loguearme"). Con una cookie por rol, un mismo navegador
# puede tener las tres sesiones activas a la vez, cada una en su pestaña,
# sin pisarse.
COOKIE_SINDICATO = "sesion_sindicato"
COOKIE_PLATAFORMA = "sesion_plataforma"
COOKIE_TRABAJADOR = "sesion_trabajador"
COOKIE_EMPLEADOR = "sesion_empleador"
COOKIES_POR_ROL = {
    "sindicato": COOKIE_SINDICATO,
    "plataforma": COOKIE_PLATAFORMA,
    "trabajador": COOKIE_TRABAJADOR,
    "empleador": COOKIE_EMPLEADOR,
}


def sindicato_activo_empleador(request: Request) -> int:
    """Resuelve en qué sindicato está parado el empleador ahora -- mismo
    patrón que sindicato_activo_trabajador, con cuit_emp/sind_elegido_emp
    en vez de cuil_trab/sind_elegido (cookies propias, para que las dos
    sesiones convivan sin pisarse en el mismo navegador)."""
    cuit = request.cookies.get("cuit_emp", "")
    if not cuit:
        return 0
    sinds = db.sindicatos_de_cuit_empleador(cuit)
    if len(sinds) == 1:
        return sinds[0]["id"]
    elegido = request.cookies.get("sind_elegido_emp", "")
    if elegido:
        for sd in sinds:
            if str(sd["id"]) == elegido:
                return sd["id"]
    return 0


def sindicato_activo_trabajador(request: Request) -> int:
    """Resuelve en qué sindicato está parado el trabajador ahora.
    Si tiene uno solo, ese; si tiene varios, el que eligió (cookie sind_elegido).
    Devuelve 0 si no se puede determinar."""
    cuil = request.cookies.get("cuil_trab", "")
    if not cuil:
        return 0
    sinds = db.sindicatos_de_cuil(cuil)
    if len(sinds) == 1:
        return sinds[0]["id"]
    elegido = request.cookies.get("sind_elegido", "")
    if elegido:
        for sd in sinds:
            if str(sd["id"]) == elegido:
                return sd["id"]
    return 0


def sesion_actual(request: Request, rol: str) -> dict | None:
    """Sesión vigente para ESE rol puntual -- cada rol tiene su propia
    cookie (ver COOKIES_POR_ROL), así que hace falta pedir cuál se
    necesita; no hay más una sesión "genérica" del navegador."""
    payload = auth.leer_sesion(request.cookies.get(COOKIES_POR_ROL[rol], ""))
    if payload and payload.get("rol") == rol:
        return payload
    return None


def slugify(nombre: str) -> str:
    import re
    s = nombre.lower().strip()
    s = re.sub(r"[áàä]", "a", s); s = re.sub(r"[éèë]", "e", s)
    s = re.sub(r"[íìï]", "i", s); s = re.sub(r"[óòö]", "o", s)
    s = re.sub(r"[úùü]", "u", s); s = re.sub(r"ñ", "n", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "sindicato"


@app.get("/plataforma", response_class=HTMLResponse)
def plataforma(request: Request):
    if not sesion_actual(request, "plataforma"):
        return templates.TemplateResponse("plataforma_login.html", {
            "request": request, "marca_plataforma": db.marca_plataforma()})
    with db.get_session() as s:
        sindicatos = s.exec(select(Sindicato).order_by(Sindicato.id)).all()
        # contar usuarios por sindicato
        info = []
        for sind in sindicatos:
            n_users = len(s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sind.id)).all())
            n_trab = len(s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sind.id)).all())
            info.append({"s": sind, "usuarios": n_users, "trabajadores": n_trab})
    uso_ia = db.uso_ia_listado()
    topes = db.topes_listado()
    topes_json = [{"id": t.id, "vigencia_desde": t.vigencia_desde,
                   "tope_maximo": t.tope_maximo, "base_minima": t.base_minima} for t in topes]
    return templates.TemplateResponse("plataforma.html", {
        "request": request, "sindicatos": info,
        "tope_sindical_pct": db.obtener_tope_sindical(),
        "config_dashboard": db.config_dashboard(),
        "marca_plataforma": db.marca_plataforma(),
        "uso_ia": uso_ia,
        "sindicatos_uso_ia": sorted({u["sindicato"] for u in uso_ia}),
        "modelos_uso_ia": sorted({u["modelo"] for u in uso_ia}),
        "recibos_sospechosos": db.recibos_sospechosos_listado(),
        "catalogo_modulos": MODULOS, "modulos_iniciales": MODULOS_INICIALES,
        "topes": topes, "topes_json": topes_json,
        "version": VERSION_PLATAFORMA, "fecha_version": FECHA_VERSION,
    })


@app.get("/plataforma/inicio", response_class=HTMLResponse)
def plataforma_inicio(request: Request):
    if not sesion_actual(request, "plataforma"):
        return templates.TemplateResponse("plataforma_login.html", {
            "request": request, "marca_plataforma": db.marca_plataforma()})
    return templates.TemplateResponse("plataforma_portada.html", {
        "request": request, "marca_plataforma": db.marca_plataforma(),
        "version": VERSION_PLATAFORMA, "fecha_version": FECHA_VERSION,
    })


@app.get("/plataforma/recibos-sospechosos/{recibo_id}/archivo")
def servir_recibo_sospechoso(recibo_id: int, request: Request):
    """Archivo original (imagen o PDF) de un recibo marcado con posible
    adulteración -- solo lo puede ver el admin de plataforma."""
    exigir_plataforma(request)
    with db.get_session() as s:
        r = s.get(ReciboSospechoso, recibo_id)
        if not r:
            raise HTTPException(404, "No encontrado")
        return BinResponse(
            content=r.archivo_datos, media_type=r.archivo_mime or "application/octet-stream",
            headers={"Cache-Control": "private, no-cache"},
        )


@app.post("/plataforma/login")
def plataforma_login(response: Response, cuit: str = Form(...), clave: str = Form(...)):
    if not auth.verificar_plataforma(clave, cuit):
        return RedirectResponse("/plataforma?error=1", status_code=303)
    token = auth.crear_sesion("plataforma")
    db.registrar_acceso("plataforma")
    resp = RedirectResponse("/plataforma/inicio", status_code=303)
    resp.set_cookie(COOKIE_PLATAFORMA, token, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.post("/plataforma/config")
def plataforma_config(request: Request, tope_sindical_pct: float = Form(...)):
    exigir_plataforma(request)
    db.set_tope_sindical(tope_sindical_pct)
    return RedirectResponse("/plataforma?config=ok", status_code=303)


@app.post("/plataforma/config-dashboard")
def plataforma_config_dashboard(
    request: Request,
    semaforo_verde_hasta_dias: int = Form(...),
    semaforo_amarillo_hasta_dias: int = Form(...),
    dashboard_consultas_bot_habilitado: bool = Form(False),
):
    """Parámetros del Panel Sindical (docs/DASHBOARD.md §2.3), mismos para
    todos los sindicatos. set_config_dashboard ignora umbrales incoherentes
    (verde tiene que ser menor que amarillo)."""
    exigir_plataforma(request)
    db.set_config_dashboard(semaforo_verde_hasta_dias, semaforo_amarillo_hasta_dias,
                             dashboard_consultas_bot_habilitado)
    return RedirectResponse("/plataforma?config=ok#config", status_code=303)


ESTADOS_TOPE = ("verificado", "derivado", "por_verificar", "SOSPECHOSO")


def _parse_numero_tope(texto: str) -> float:
    """Los montos de esta pantalla se escriben SIN separador de miles y con
    coma para los decimales (ej. 4594798,23) -- convención argentina, para
    que no choque con el separador de miles que usa Python al mostrarlos.
    Un punto en el texto es un error de formato, no un separador válido acá
    (evita el caso ambiguo de no saber si es de miles o decimal)."""
    texto = (texto or "").strip()
    if "." in texto:
        raise ValueError("punto no permitido")
    return float(texto.replace(",", "."))


@app.post("/plataforma/tope")
def plataforma_tope(
    request: Request,
    id: str = Form(""), vigencia_desde: str = Form(...),
    tope_maximo: str = Form(...), base_minima: str = Form(...),
    estado: str = Form("por_verificar"), fuente: str = Form(""),
    confirmado: str = Form(""),
):
    """Alta/edición de un tope de base imponible (un solo endpoint, mismo
    patrón que /admin/formula). El JS del panel ya avisa con un confirm()
    si el valor es menor al del período anterior -- acá se vuelve a
    chequear igual del lado del servidor (esconder/advertir en el cliente
    no alcanza, mismo criterio que el resto de la app)."""
    exigir_plataforma(request)
    if estado not in ESTADOS_TOPE:
        estado = "por_verificar"
    try:
        tope_maximo_val = _parse_numero_tope(tope_maximo)
        base_minima_val = _parse_numero_tope(base_minima)
    except ValueError:
        return RedirectResponse("/plataforma?error=topeformato#topes", status_code=303)
    tope_id = int(id) if id else None
    anterior = db.tope_anterior_a(vigencia_desde, excluir_id=tope_id)
    if anterior and confirmado != "1" and (
        tope_maximo_val < anterior["tope_maximo"] or base_minima_val < anterior["base_minima"]
    ):
        return RedirectResponse("/plataforma?error=topebajo#topes", status_code=303)
    if tope_id:
        if not db.editar_tope(tope_id, tope_maximo_val, base_minima_val, estado, fuente):
            return RedirectResponse("/plataforma?error=topenoexiste#topes", status_code=303)
    else:
        if not db.crear_tope(vigencia_desde, tope_maximo_val, base_minima_val, estado, fuente):
            return RedirectResponse("/plataforma?error=topeduplicado#topes", status_code=303)
    return RedirectResponse("/plataforma#topes", status_code=303)


@app.post("/plataforma/tope/borrar")
def plataforma_tope_borrar(request: Request, id: int = Form(...)):
    exigir_plataforma(request)
    db.borrar_tope(id)
    return RedirectResponse("/plataforma#topes", status_code=303)


@app.post("/plataforma/marca")
async def plataforma_marca(
    request: Request,
    color_primario: str = Form("#152238"), color_secundario: str = Form("#1a7a6b"),
    color_acento: str = Form("#b23a2e"), logo: UploadFile = File(None),
    logo_oscuro: UploadFile = File(None),
    portada_clara: bool = Form(False),
):
    """Marca de 'Mi Trabajo' (logins y panel de plataforma) — mismo patrón que
    la marca de un sindicato, pero para la plataforma misma. Dos logos: uno
    para fondo claro (logins) y uno para fondo oscuro (encabezados)."""
    exigir_plataforma(request)
    logo_datos, logo_mime, logo_flag = (None, "", "")
    if logo and logo.filename:
        logo_datos, logo_mime, logo_flag = _leer_logo(logo)
    logo_datos_osc, logo_mime_osc, logo_flag_osc = (None, "", "")
    if logo_oscuro and logo_oscuro.filename:
        logo_datos_osc, logo_mime_osc, logo_flag_osc = _leer_logo(logo_oscuro)
    db.set_marca_plataforma(color_primario, color_secundario, color_acento,
                             logo_datos, logo_mime, logo_flag, portada_clara,
                             logo_datos_osc, logo_mime_osc, logo_flag_osc)
    return RedirectResponse("/plataforma?marca=ok", status_code=303)


@app.get("/plataforma/salir")
def plataforma_salir():
    resp = RedirectResponse("/plataforma", status_code=303)
    resp.delete_cookie(COOKIE_PLATAFORMA)
    return resp


@app.post("/plataforma/sindicato")
async def plataforma_alta_sindicato(
    request: Request,
    nombre: str = Form(...), descripcion: str = Form(""),
    cuit: str = Form(""), direccion: str = Form(""), mail: str = Form(""),
    telefonos: str = Form(""), autoridad: str = Form(""), cargo_autoridad: str = Form(""),
    color_primario: str = Form("#152238"),
    color_secundario: str = Form("#1a7a6b"),
    color_acento: str = Form("#b23a2e"),
    color_base: str = Form("#0f1b2d"),
    color_destacado: str = Form("#E5188F"),
    logo: UploadFile = File(None), firma: UploadFile = File(None),
    modulos_habilitados: list[str] = Form(default=[]),
    portada_clara: bool = Form(False),
    admin_portada_clara: bool = Form(False),
):
    exigir_plataforma(request)
    color_base = color_base or "#0f1b2d"
    if not _es_oscuro(color_base):
        return RedirectResponse("/plataforma?error=colorbase#sindicatos", status_code=303)
    modulos_validos = [m for m in modulos_habilitados if m in MODULOS]
    slug = slugify(nombre)
    logo_datos, logo_mime, logo_flag = (None, "", "")
    if logo and logo.filename:
        logo_datos, logo_mime, logo_flag = _leer_logo(logo)
    firma_datos, firma_mime, firma_flag = (None, "", "")
    if firma and firma.filename:
        firma_datos, firma_mime, firma_flag = _leer_logo(firma)
    with db.get_session() as s:
        sind = Sindicato(
            nombre=nombre, descripcion=descripcion, slug=slug,
            cuit=cuit, direccion=direccion, mail=mail, telefonos=telefonos,
            autoridad=autoridad, cargo_autoridad=cargo_autoridad,
            logo=logo_flag, logo_datos=logo_datos, logo_mime=logo_mime,
            firma=firma_flag, firma_datos=firma_datos, firma_mime=firma_mime,
            color_primario=color_primario or "#152238",
            color_secundario=color_secundario or "#1a7a6b",
            color_acento=color_acento or "#b23a2e",
            color_base=color_base,
            color_destacado=color_destacado or "#E5188F",
            modulos_habilitados=modulos_validos,
            portada_clara=portada_clara,
            admin_portada_clara=admin_portada_clara,
        )
        s.add(sind); s.commit(); s.refresh(sind)
        sind_id = sind.id
    # Aportes de ley (jubilación, PAMI, obra social): mismo % en cualquier
    # recibo argentino en blanco, se autocargan para que el chequeo funcione
    # desde el primer recibo aunque todavía no haya ningún empleador cargado.
    db.crear_conceptos_universales(sind_id)
    return RedirectResponse("/plataforma", status_code=303)


def _es_oscuro(color_hex: str) -> bool:
    """La portada del trabajador pinta texto claro sobre --marca-base: si el
    sindicato carga un color de base que no es oscuro, el texto deja de
    contrastar. Luminancia percibida (0.299R+0.587G+0.114B); < 140/255 se
    considera oscuro -- umbral con margen, no el punto medio exacto."""
    h = (color_hex or "").lstrip("#")
    if len(h) != 6:
        return False
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return False
    luminancia = 0.299 * r + 0.587 * g + 0.114 * b
    return luminancia < 140


def _destinos_validos(s, destino_seccionales: list[str], sid: int,
                      alcance=None) -> list[int]:
    """Convierte los ids de seccional tildados en el form a int, descartando
    los que no sean de ESTE sindicato (ajenos o inventados) -- mismo criterio
    defensivo que el seccional_id del alta de trabajador.

    `alcance` (ver db.alcance_seccional) descarta además las que estén fuera
    del alcance de quien publica: Prensa de Córdoba no le publica a todo el
    país (decisión N10). None = sin recorte.

    Una lista VACÍA significa "a todas las seccionales", así que para alguien
    acotado hay que traducirla a su alcance explícito en vez de dejarla
    vacía: si no, un admin local publicaría a todo el sindicato sin tildar
    nada. Eso lo hace _destinos_de_publicacion."""
    ids_del_sindicato = {sec.id for sec in s.exec(
        select(Seccional).where(Seccional.sindicato_id == sid)).all()}
    resultado = []
    for valor in destino_seccionales:
        try:
            sec_id = int(valor)
        except (TypeError, ValueError):
            continue
        if sec_id in ids_del_sindicato and (alcance is None or sec_id in alcance):
            resultado.append(sec_id)
    return resultado


def _destinos_de_publicacion(request: Request, s, destino_seccionales: list[str],
                             sid: int) -> list[int]:
    """Los destinos de una Noticia o un Beneficio, ya recortados al alcance
    de quien publica.

    El caso que hay que atajar es el de la lista VACÍA, que en este modelo
    significa "a todas las seccionales": dejarla vacía para un admin local
    sería darle exactamente lo que el alcance le niega. Se la reemplaza por
    su alcance explícito."""
    alcance = _alcance_de(request)
    destinos = _destinos_validos(s, destino_seccionales, sid, alcance)
    if not destinos and alcance is not None:
        return sorted(alcance)
    return destinos


def _modulos_de(sid: int) -> set:
    """Módulos habilitados de un sindicato, para el contexto de portada/
    trabajador/admin (ver modulos.py). Set vacío si sid es 0/None."""
    if not sid:
        return set()
    return set(db.modulos_habilitados(sid))


def _exigir_modulo(sid: int, modulo: str) -> None:
    """403 si el sindicato no tiene ESE módulo habilitado. Esconder el botón
    en la UI no alcanza: la ruta tiene que rechazar igual (mismo criterio
    defensivo que _destinos_validos para seccionales ajenas)."""
    if not db.modulo_habilitado(sid, modulo):
        raise HTTPException(403, "Este módulo no está habilitado para tu sindicato.")


# ---------- Panel Sindical (docs/DASHBOARD.md) ----------
# Todos los endpoints: sesión de admin de sindicato + módulo "dashboard". El
# sindicato_id sale SIEMPRE de la cookie (exigir_sindicato) -- ninguna ruta
# acepta un sindicato_id por parámetro, ese es el aislamiento de tenant.

def _exigir_dashboard(request: Request) -> int:
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "dashboard")
    return sid


def _exigir_dashboard_detalle(request: Request) -> int:
    """Gate del explorador de datos (el detalle caso por caso). Hoy exige lo
    mismo que el resto del dashboard; cuando exista la diferenciación
    STD/PRO (excluyentes), el módulo PRO se chequea SOLO acá -- por eso el
    explorador no llama a _exigir_dashboard directo."""
    return _exigir_dashboard(request)


def _filtros_dashboard(request: Request) -> dict:
    try:
        return dashboard.parsear_filtros(request.query_params)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/admin/dashboard/asistente")
def dashboard_asistente(request: Request, cuerpo: dict = Body(default={})):
    """Asistente del Panel Sindical (docs/ASISTENTE_PANEL.md): una pregunta
    en lenguaje natural -> los filtros del panel + un resumen con los
    números reales. Mismo gate que el explorador (_exigir_dashboard_detalle):
    es una función PRO del Panel, no un módulo aparte. El modelo no ve filas
    ni genera SQL -- ver asistente.py."""
    sid = _exigir_dashboard_detalle(request)
    if not asistente.disponible():
        raise HTTPException(503, "El asistente no está configurado en este entorno.")
    if not isinstance(cuerpo, dict):
        cuerpo = {}
    pregunta = str(cuerpo.get("pregunta") or "").strip()
    if not pregunta:
        raise HTTPException(422, "Escribí una pregunta.")
    if len(pregunta) > asistente.MAX_PREGUNTA:
        raise HTTPException(422, f"La pregunta es demasiado larga (máximo "
                                 f"{asistente.MAX_PREGUNTA} caracteres).")
    filtros = cuerpo.get("filtros") if isinstance(cuerpo.get("filtros"), dict) else {}
    historial = cuerpo.get("historial") if isinstance(cuerpo.get("historial"), list) else []
    # Tope diario por sindicato: red de seguridad de costo, no de negocio.
    if db.consultas_asistente_hoy(sid) >= asistente.TOPE_DIARIO:
        raise HTTPException(429, f"El asistente llegó al tope de {asistente.TOPE_DIARIO} preguntas "
                                 f"por día de tu sindicato. Mañana vuelve a estar disponible; los "
                                 f"filtros del panel siguen funcionando a mano.")
    try:
        salida = asistente.responder(sid, pregunta, filtros, historial)
    except asistente.ErrorModelo as e:
        print(f"[asistente] sindicato {sid}: {e}")
        raise ErrorApp("E-ASISTENTE-01")
    # Se registra todo lo que el modelo contestó, aplique o no (una
    # repregunta también cuenta para el tope y para el set de frases).
    uid = (sesion_actual(request, "sindicato") or {}).get("uid") or None
    db.registrar_consulta_asistente(sid, uid, pregunta, salida["respuesta"], salida["filtros"],
                                    salida["aplicar"], salida["uso"])
    return {"respuesta": salida["respuesta"], "filtros": salida["filtros"],
            "aplicar": salida["aplicar"], "afiliado": salida["afiliado"],
            "candidatos": salida["candidatos"], "filtros_pendientes": salida["filtros_pendientes"]}


@app.get("/admin/dashboard/kpis")
def dashboard_kpis(request: Request):
    sid = _exigir_dashboard(request)
    return dashboard.kpis(sid, _filtros_dashboard(request))


@app.get("/admin/dashboard/serie-recibos")
def dashboard_serie_recibos(request: Request):
    sid = _exigir_dashboard(request)
    return {"serie": dashboard.serie_recibos(sid, _filtros_dashboard(request))}


@app.get("/admin/dashboard/validacion")
def dashboard_validacion(request: Request):
    sid = _exigir_dashboard(request)
    return dashboard.validacion(sid, _filtros_dashboard(request))


@app.get("/admin/dashboard/diferencias-empresa")
def dashboard_diferencias_empresa(request: Request):
    sid = _exigir_dashboard(request)
    return {"empresas": dashboard.diferencias_empresa(sid, _filtros_dashboard(request))}


@app.get("/admin/dashboard/tramites-seccional")
def dashboard_tramites_seccional(request: Request):
    sid = _exigir_dashboard(request)
    return dashboard.tramites_seccional(sid, _filtros_dashboard(request))


@app.get("/admin/dashboard/notificaciones")
def dashboard_notificaciones(request: Request):
    sid = _exigir_dashboard(request)
    return dashboard.notificaciones(sid, _filtros_dashboard(request))


@app.get("/admin/dashboard/formato-semana")
def dashboard_formato_semana(request: Request):
    sid = _exigir_dashboard(request)
    return {"semanas": dashboard.formato_semana(sid, _filtros_dashboard(request))}


@app.get("/admin/dashboard/semaforo")
def dashboard_semaforo(request: Request):
    sid = _exigir_dashboard(request)
    return dashboard.semaforo(sid, _filtros_dashboard(request))


@app.get("/admin/dashboard/consultas")
def dashboard_consultas(request: Request):
    sid = _exigir_dashboard(request)
    # Feature flag de plataforma: mientras el bot no clasifique por tema, el
    # carril entero no existe para afuera (404, no 403: no se revela nada).
    if not db.config_dashboard()["consultas_bot_habilitado"]:
        raise HTTPException(404, "No disponible.")
    return {"temas": dashboard.consultas_por_tema(sid, _filtros_dashboard(request))}


@app.get("/admin/dashboard/explorador/{fuente}")
def dashboard_explorador(request: Request, fuente: str):
    sid = _exigir_dashboard_detalle(request)
    fuentes = {
        "recibos": dashboard.explorador_recibos,
        "tramites": dashboard.explorador_tramites,
        "consultas": dashboard.explorador_consultas,
        "notificaciones": dashboard.explorador_notificaciones,
    }
    if fuente not in fuentes:
        raise HTTPException(404, "Fuente desconocida.")
    if fuente == "consultas" and not db.config_dashboard()["consultas_bot_habilitado"]:
        raise HTTPException(404, "No disponible.")
    filtros = _filtros_dashboard(request)
    try:
        page, page_size = dashboard._paginacion(request.query_params)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return fuentes[fuente](sid, filtros, page, page_size)


@app.get("/admin/dashboard/detalle/recibo/{recibo_id}")
def dashboard_detalle_recibo(request: Request, recibo_id: int):
    """Modal "Ver" del explorador. La anonimización de un recibo NO enviado
    la hace dashboard.detalle_recibo en el servidor, no el frontend."""
    sid = _exigir_dashboard_detalle(request)
    d = dashboard.detalle_recibo(sid, recibo_id)
    if not d:
        raise HTTPException(404, "Recibo inexistente.")
    return d


@app.get("/admin/dashboard/detalle/tramite/{tramite_id}")
def dashboard_detalle_tramite(request: Request, tramite_id: int):
    sid = _exigir_dashboard_detalle(request)
    d = dashboard.detalle_tramite(sid, tramite_id)
    if not d:
        raise HTTPException(404, "Trámite inexistente.")
    return d


@app.get("/admin/dashboard/detalle/notificaciones")
def dashboard_detalle_notificaciones(request: Request, dia: str, tipo: str,
                                      seccional_id: int = 0):
    sid = _exigir_dashboard_detalle(request)
    try:
        date.fromisoformat(dia)
    except ValueError:
        raise HTTPException(422, "'dia' tiene que ser una fecha AAAA-MM-DD.")
    if tipo not in dashboard.TIPOS_NOTIF:
        raise HTTPException(422, "'tipo' admite 'manual' o 'sistema'.")
    return {"notificaciones": dashboard.detalle_notificaciones_grupo(
        sid, dia, seccional_id or None, tipo)}


@app.get("/admin/dashboard/detalle/notificacion/{notificacion_id}/destinatarios")
def dashboard_detalle_notif_destinatarios(request: Request, notificacion_id: int):
    """Último nivel del modal de notificaciones: quién la recibió y cuándo
    la leyó, persona por persona."""
    sid = _exigir_dashboard_detalle(request)
    d = dashboard.destinatarios_notificacion(sid, notificacion_id)
    if d is None:
        raise HTTPException(404, "Notificación inexistente.")
    return d


@app.get("/admin/dashboard/detalle/consulta/{consulta_id}")
def dashboard_detalle_consulta(request: Request, consulta_id: int):
    sid = _exigir_dashboard_detalle(request)
    if not db.config_dashboard()["consultas_bot_habilitado"]:
        raise HTTPException(404, "No disponible.")
    d = dashboard.detalle_consulta(sid, consulta_id)
    if not d:
        raise HTTPException(404, "Consulta inexistente.")
    return d


@app.get("/admin/dashboard/afiliados")
def dashboard_buscar_afiliados(request: Request, q: str = "", id: int = 0):
    """Buscador del filtro por afiliado (docs/ASISTENTE_PANEL.md §9): por
    nombre o CUIL, hasta 10 del padrón del PROPIO sindicato. Con `id`
    devuelve ese afiliado solo (para etiquetar el chip de un link con
    ?afiliado=). Gate del explorador: mirar a una persona es detalle."""
    sid = _exigir_dashboard_detalle(request)
    if id:
        uno = dashboard.afiliado_por_id(sid, id)
        return {"items": [uno] if uno else []}
    return {"items": dashboard.buscar_afiliados(sid, q[:80])}


@app.get("/admin/dashboard/filtros")
def dashboard_catalogo_filtros(request: Request):
    """Catálogos para poblar los filtros: seccionales y empresas del tenant,
    categorías vistas en los recibos, y límites del slider de bruto
    (percentiles 1 y 99 del tenant, §4.3 -- se calculan en Fase 2 si hace
    falta afinar; por ahora min/max reales)."""
    sid = _exigir_dashboard(request)
    with db.get_session() as s:
        secc = db.seccionales_del_sindicato(sid)
        from sqlalchemy import text as _text
        categorias = [f[0] for f in s.execute(_text(
            "SELECT DISTINCT categoria FROM reciboverificado "
            "WHERE sindicato_id = :sid AND categoria != '' ORDER BY categoria"
        ), {"sid": sid}).all()]
    bruto_min, bruto_max = dashboard.limites_bruto(sid)
    return {
        "seccionales": secc,
        "empresas": [{"id": e["id"], "nombre": e["nombre"]}
                     for e in dashboard.catalogo_empresas(sid)],
        "categorias": categorias,
        "bruto_min": bruto_min, "bruto_max": bruto_max,
        "consultas_bot_habilitado": db.config_dashboard()["consultas_bot_habilitado"],
    }


def _leer_logo(archivo: UploadFile):
    """Lee el logo subido y devuelve (datos, mime, nombre_flag).
    Guarda el binario en la base (Opción B), no en el disco efímero.
    Acepta PNG y formatos de imagen compatibles."""
    import os
    ext = os.path.splitext(archivo.filename)[1].lower()
    mimes = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
    }
    if ext not in mimes:
        return None, "", ""
    datos = archivo.file.read()
    if not datos:
        return None, "", ""
    return datos, mimes[ext], f"logo{ext}"


@app.post("/plataforma/usuario")
def plataforma_alta_usuario(
    request: Request,
    sindicato_id: int = Form(...), usuario: str = Form(...),
    nombre: str = Form(""), clave_inicial: str = Form(...),
):
    exigir_plataforma(request)
    with db.get_session() as s:
        s.add(UsuarioSindicato(
            sindicato_id=sindicato_id, usuario=_norm_cuil(usuario), nombre=nombre,
            cuil=_norm_cuil(usuario),
            clave_hash=auth.hashear_clave(clave_inicial),
            debe_cambiar_clave=True,
            # Es el PRIMER usuario del sindicato: si no naciera Super Admin,
            # nadie podría entrar a crear las áreas ni los demás usuarios.
            es_super_admin=True,
        ))
        s.commit()
    db.sincronizar_por_cuil(sindicato_id, _norm_cuil(usuario))
    return RedirectResponse("/plataforma", status_code=303)


@app.post("/plataforma/sindicato/editar")
async def plataforma_editar_sindicato(
    request: Request,
    id: int = Form(...), nombre: str = Form(...), descripcion: str = Form(""),
    cuit: str = Form(""), direccion: str = Form(""), mail: str = Form(""),
    telefonos: str = Form(""), autoridad: str = Form(""), cargo_autoridad: str = Form(""),
    color_primario: str = Form("#152238"), color_secundario: str = Form("#1a7a6b"),
    color_acento: str = Form("#b23a2e"), color_base: str = Form("#0f1b2d"),
    color_destacado: str = Form("#E5188F"),
    logo: UploadFile = File(None),
    firma: UploadFile = File(None),
    modulos_habilitados: list[str] = Form(default=[]),
    portada_clara: bool = Form(False),
    admin_portada_clara: bool = Form(False),
):
    exigir_plataforma(request)
    color_base = color_base or "#0f1b2d"
    if not _es_oscuro(color_base):
        return RedirectResponse("/plataforma?error=colorbase#sindicatos", status_code=303)
    modulos_validos = [m for m in modulos_habilitados if m in MODULOS]
    with db.get_session() as s:
        sind = s.get(Sindicato, id)
        if sind:
            sind.nombre, sind.descripcion = nombre, descripcion
            sind.cuit, sind.direccion, sind.mail = cuit, direccion, mail
            sind.telefonos, sind.autoridad, sind.cargo_autoridad = telefonos, autoridad, cargo_autoridad
            sind.color_primario = color_primario or "#152238"
            sind.color_secundario = color_secundario or "#1a7a6b"
            sind.color_acento = color_acento or "#b23a2e"
            sind.color_base = color_base
            sind.color_destacado = color_destacado or "#E5188F"
            sind.modulos_habilitados = modulos_validos
            sind.portada_clara = portada_clara
            sind.admin_portada_clara = admin_portada_clara
            if logo and logo.filename:
                datos, mime, flag = _leer_logo(logo)
                if datos:
                    sind.logo_datos, sind.logo_mime, sind.logo = datos, mime, flag
            if firma and firma.filename:
                datos, mime, flag = _leer_logo(firma)
                if datos:
                    sind.firma_datos, sind.firma_mime, sind.firma = datos, mime, flag
            s.add(sind); s.commit()
    return RedirectResponse("/plataforma", status_code=303)


@app.post("/plataforma/sindicato/borrar")
def plataforma_borrar_sindicato(request: Request, id: int = Form(...)):
    """Borra un sindicato y TODOS sus datos asociados (conceptos, fórmulas,
    reportes, trabajadores, admins). Operación destructiva."""
    exigir_plataforma(request)
    with db.get_session() as s:
        for c in s.exec(select(Concepto).where(Concepto.sindicato_id == id)).all(): s.delete(c)
        for f in s.exec(select(Formula).where(Formula.sindicato_id == id)).all(): s.delete(f)
        for r in s.exec(select(Reporte).where(Reporte.sindicato_id == id)).all(): s.delete(r)
        for t in s.exec(select(Trabajador).where(Trabajador.sindicato_id == id)).all(): s.delete(t)
        for u in s.exec(select(UsuarioSindicato).where(UsuarioSindicato.sindicato_id == id)).all(): s.delete(u)
        sind = s.get(Sindicato, id)
        if sind: s.delete(sind)
        s.commit()
    return RedirectResponse("/plataforma", status_code=303)


@app.get("/plataforma/admins/{sindicato_id}")
def plataforma_ver_admins(sindicato_id: int, request: Request):
    """Devuelve la lista de admins de un sindicato (para mostrar al clickear el número)."""
    exigir_plataforma(request)
    with db.get_session() as s:
        admins = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sindicato_id)).all()
        return {"admins": [
            {"usuario": a.usuario, "nombre": a.nombre, "activo": a.activo}
            for a in admins]}


@app.get("/plataforma/trabajadores/{sindicato_id}")
def plataforma_ver_trabajadores(sindicato_id: int, request: Request):
    """Devuelve la lista de trabajadores empadronados en un sindicato (para
    mostrar al clickear el número, mismo patrón que plataforma_ver_admins)."""
    exigir_plataforma(request)
    with db.get_session() as s:
        trabajadores = s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sindicato_id).order_by(
            Trabajador.activo.desc(), Trabajador.nombre)).all()
        return {"trabajadores": [
            {"cuil": t.cuil, "nombre": t.nombre, "activo": t.activo, "registrado": t.registrado}
            for t in trabajadores]}


@app.post("/plataforma/reset-clave")
def plataforma_reset_clave(
    request: Request, tipo: str = Form(...), identificador: str = Form(...),
    clave_nueva: str = Form(...),
):
    """TRANSITORIO (para pruebas): el admin de plataforma cambia la clave de
    cualquier usuario. tipo = 'sindicato' (admin) o 'trabajador' (cuenta).
    ⚠️ Sacar o reemplazar por recuperación segura antes de producción."""
    exigir_plataforma(request)
    ident = _norm_cuil(identificador)
    hasheada = auth.hashear_clave(clave_nueva)
    with db.get_session() as s:
        if tipo == "sindicato":
            u = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == ident)).first()
            if u:
                u.clave_hash = hasheada; u.debe_cambiar_clave = False; s.add(u); s.commit()
                return RedirectResponse("/plataforma?reset=ok", status_code=303)
        elif tipo == "trabajador":
            c = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == ident)).first()
            if c:
                c.clave_hash = hasheada; s.add(c); s.commit()
                return RedirectResponse("/plataforma?reset=ok", status_code=303)
    return RedirectResponse("/plataforma?reset=nohay", status_code=303)


def _norm_cuil(cuil: str) -> str:
    import re
    return re.sub(r"[^0-9]", "", cuil or "")


def _fmt_fecha_ar(iso: str) -> str:
    """'AAAA-MM-DD' (lo que manda <input type=date>) -> 'DD/MM/AAAA'. None o
    formato inesperado -> lo devuelve tal cual (o vacío)."""
    if not iso:
        return ""
    partes = iso.split("-")
    if len(partes) == 3 and all(p.isdigit() for p in partes):
        a, m, d = partes
        return f"{d}/{m}/{a}"
    return iso


def _dni_de_cuil(cuil: str) -> str:
    """El DNI son los 8 dígitos del medio del CUIL (20-20279041-1 -> 20279041).
    Cadena vacía si el CUIL no tiene el largo esperado."""
    digitos = _norm_cuil(cuil)
    return digitos[2:10] if len(digitos) == 11 else ""


def _iniciales_sindicato(nombre: str) -> str:
    """Iniciales para el logo de respaldo cuando el sindicato no cargó uno
    (ej. "Unión Obrera Metalúrgica" -> "UOM"), hasta 3 letras."""
    letras = [p[0].upper() for p in (nombre or "").split() if p]
    return "".join(letras[:3]) or "?"


def _parsear_creada(creada: str):
    """Noticia.creada puede venir como "AAAA-MM-DD HH:MM" (formato actual) o
    "AAAA-MM-DD" (noticias cargadas antes de este cambio) -- probar los dos."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(creada, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _antiguedad(creada: str) -> str:
    """"Hace 2 días" a partir de Noticia.creada. Sin dramatizar: si no se
    puede parsear, devuelve el valor tal cual."""
    dt = _parsear_creada(creada)
    if not dt:
        return creada or ""
    dias = (fechas.hoy() - dt.date()).days
    if dias <= 0:
        return "Hoy"
    if dias == 1:
        return "Ayer"
    if dias < 30:
        return f"Hace {dias} días"
    meses = dias // 30
    return f"Hace {meses} mes{'es' if meses != 1 else ''}"


def _fmt_fecha_hora_corta(creada: str) -> str:
    """"12/08 14:30" para la esquina de la tarjeta de noticia en el feed."""
    dt = _parsear_creada(creada)
    return dt.strftime("%d/%m %H:%M") if dt else (creada or "")


def _con_antiguedad(noticias: list) -> list:
    return [{**n, "antiguedad": _antiguedad(n["creada"]),
              "fecha_hora": _fmt_fecha_hora_corta(n["creada"])} for n in noticias]


def _texto_con_links(texto: str) -> str:
    """Escapa HTML y convierte URLs sueltas en links + saltos de línea en
    <br>, para el texto completo de una noticia (lo carga el admin, pero
    puede incluir URLs que sí queremos clickeables)."""
    import html
    import re
    escapado = html.escape(texto or "")
    con_links = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        escapado,
    )
    return con_links.replace("\n", "<br>")


@app.get("/ingresar", response_class=HTMLResponse)
def ingresar(request: Request):
    """Pantalla de login/registro del trabajador."""
    return templates.TemplateResponse("trabajador_login.html", {
        "request": request, "marca_plataforma": db.marca_plataforma()})


@app.post("/trabajador/login")
def trabajador_login(request: Request, cuil: str = Form(...), clave: str = Form(...)):
    cuil = _norm_cuil(cuil)
    with db.get_session() as s:
        cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if not cuenta or not auth.verificar_clave(clave, cuenta.clave_hash):
            return RedirectResponse("/ingresar?error=login", status_code=303)
        cuenta_id = cuenta.id   # capturar el id ANTES de cerrar la sesión
    sinds = db.sindicatos_de_cuil(cuil)
    if not sinds:
        return RedirectResponse("/ingresar?error=sinsind", status_code=303)
    token = auth.crear_sesion("trabajador", id_usuario=cuenta_id, sindicato_id=0)
    db.registrar_acceso("trabajador", sindicato_id=sinds[0]["id"] if len(sinds) == 1 else None)
    # sindicato_id 0 = todavía no eligió; se define en /elegir o directo si hay uno solo
    resp = RedirectResponse("/app/inicio", status_code=303)
    resp.set_cookie(COOKIE_TRABAJADOR, token, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    resp.set_cookie("cuil_trab", cuil, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.post("/trabajador/registro")
def trabajador_registro(request: Request, cuil: str = Form(...), clave: str = Form(...)):
    cuil = _norm_cuil(cuil)
    # Validar que el CUIL esté empadronado en al menos un sindicato
    sinds = db.sindicatos_de_cuil(cuil)
    if not sinds:
        return RedirectResponse("/ingresar?error=nohabilitado", status_code=303)
    with db.get_session() as s:
        existe = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
        if existe:
            return RedirectResponse("/ingresar?error=yaexiste", status_code=303)
        s.add(CuentaTrabajador(cuil=cuil, clave_hash=auth.hashear_clave(clave)))
        # marcar los empadronamientos como registrados
        for t in s.exec(select(Trabajador).where(Trabajador.cuil == cuil)).all():
            t.registrado = True
            s.add(t)
        s.commit()
    token = auth.crear_sesion("trabajador", sindicato_id=0)
    resp = RedirectResponse("/app/inicio", status_code=303)
    resp.set_cookie(COOKIE_TRABAJADOR, token, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    resp.set_cookie("cuil_trab", cuil, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.get("/app", response_class=HTMLResponse)
def app_trabajador(request: Request):
    """La app del trabajador. Si está en varios sindicatos y no eligió, muestra el selector."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        return RedirectResponse("/ingresar", status_code=303)

    sinds = db.sindicatos_de_cuil(cuil)
    elegido = request.cookies.get("sind_elegido", "")

    # Determinar el sindicato activo
    sid_activo = None
    if len(sinds) == 1:
        sid_activo = sinds[0]["id"]
    elif elegido:
        for sd in sinds:
            if str(sd["id"]) == elegido:
                sid_activo = sd["id"]

    if sid_activo:
        marca = db.marca_sindicato(sid_activo)
        credencial = db.credencial_de(cuil, sid_activo) or {}
        codigo_cred = credencial.get("codigo")
        contexto = {
            "request": request, "sindicato": marca["nombre"], "marca": marca,
            "marca_plataforma": db.marca_plataforma(),
            "iniciales": _iniciales_sindicato(marca["nombre"]),
            "cuil": cuil, "nombre_trab": db.nombre_trabajador(cuil, sid_activo),
            "documento": _dni_de_cuil(cuil),
            "codigo_credencial": codigo_cred,
            "vigencia_credencial": _fmt_fecha_ar(credencial.get("vigencia")),
            "filigrana": filigrana_svg(marca["nombre"], marca["color_secundario"], marca["color_acento"]),
            "semaforo_guardado": db.semaforo_guardado(cuil, sid_activo),
            "noticias": _con_antiguedad(db.noticias_vigentes(
                sid_activo, seccional_id=db.seccional_de_trabajador(cuil, sid_activo))),
            "modulos": _modulos_de(sid_activo),
            "encuestas_ayuda": encuestas.AYUDA_POR_TIPO,
            "tiene_foto_perfil": bool(db.foto_trabajador(cuil)),
            "tramites_novedades": db.contar_tramites_con_novedades(cuil, sid_activo),
        }
        # El QR (y la verificación pública que hay detrás) solo tiene sentido
        # una vez que el sindicato generó el código real de la credencial.
        if codigo_cred:
            svg, vence_en = _qr_credencial(request, cuil, sid_activo, codigo_cred)
            contexto["qr_credencial"] = svg
            contexto["qr_vence_en"] = vence_en
        return templates.TemplateResponse("trabajador.html", contexto)
    # Varios y no eligió → selector
    return templates.TemplateResponse("elegir_sindicato.html", {
        "request": request, "sindicatos": sinds, "marca_plataforma": db.marca_plataforma(),
    })


@app.get("/app/inicio", response_class=HTMLResponse)
def app_portada(request: Request):
    """Portada del trabajador: pantalla de bienvenida con accesos rápidos.
    No reemplaza /app (Tu Recibo, sigue intacta) -- misma resolución de
    sindicato activo, landing previa a la que apuntan login/registro/elegir."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        return RedirectResponse("/ingresar", status_code=303)

    sinds = db.sindicatos_de_cuil(cuil)
    elegido = request.cookies.get("sind_elegido", "")

    sid_activo = None
    if len(sinds) == 1:
        sid_activo = sinds[0]["id"]
    elif elegido:
        for sd in sinds:
            if str(sd["id"]) == elegido:
                sid_activo = sd["id"]

    if sid_activo:
        marca = db.marca_sindicato(sid_activo)
        credencial = db.credencial_de(cuil, sid_activo) or {}
        nombre_trab = db.nombre_trabajador(cuil, sid_activo)
        seccional_id = db.seccional_de_trabajador(cuil, sid_activo)
        return templates.TemplateResponse("portada.html", {
            "request": request, "sindicato": marca["nombre"], "marca": marca,
            "marca_plataforma": db.marca_plataforma(),
            "cuil": cuil, "nombre_trab": nombre_trab,
            "primer_nombre": (nombre_trab or "").split(" ")[0] or "Trabajador",
            "iniciales": _iniciales_sindicato(marca["nombre"]),
            "credencial_generada": bool(credencial.get("codigo")),
            "documento": _dni_de_cuil(cuil),
            "perfil": db.perfil_trabajador(cuil, sid_activo),
            "provincias": db.PROVINCIAS_AR,
            "tiene_foto_perfil": bool(db.foto_trabajador(cuil)),
            "noticias": _con_antiguedad(db.noticias_vigentes(sid_activo, seccional_id=seccional_id, limite=3)),
            "beneficios": db.beneficios_vigentes(sid_activo, seccional_id=seccional_id),
            "notificaciones_no_leidas": db.contar_notificaciones_no_leidas(cuil, sid_activo),
            "tramites_novedades": db.contar_tramites_con_novedades(cuil, sid_activo),
            "encuestas_pendientes": db.contar_encuestas_pendientes(cuil, sid_activo)
                                    if "encuestas" in _modulos_de(sid_activo) else 0,
            "modulos": _modulos_de(sid_activo),
            "version": VERSION_TRABAJADOR, "fecha_version": FECHA_VERSION,
        })
    # Varios y no eligió → selector (mismo criterio que /app)
    return templates.TemplateResponse("elegir_sindicato.html", {
        "request": request, "sindicatos": sinds, "marca_plataforma": db.marca_plataforma(),
    })


@app.post("/api/perfil")
async def api_actualizar_perfil(request: Request, nombre: str = Form(...), calle: str = Form(""),
                                 numero: str = Form(""), piso: str = Form(""), ciudad: str = Form(""),
                                 provincia: str = Form(""), telefono: str = Form(""), mail: str = Form("")):
    """El trabajador edita su propio perfil -- todo menos el CUIL. Actualiza
    el empadronamiento del sindicato ACTIVO (ver actualizar_perfil_trabajador:
    Trabajador es por sindicato, no hay un domicilio único de la persona)."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    if not nombre.strip():
        raise HTTPException(400, "El nombre no puede estar vacío.")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(403, "No autorizado")
    if not db.actualizar_perfil_trabajador(cuil, sid, nombre, calle, numero, piso, ciudad, provincia, telefono, mail):
        raise HTTPException(404, "No se encontró tu empadronamiento en este sindicato.")
    nombre_guardado = db.nombre_trabajador(cuil, sid)
    return {"ok": True, "nombre": nombre_guardado, "primer_nombre": nombre_guardado.split(" ")[0] or "Trabajador"}


MAX_FOTO_PERFIL = 1 * 1024 * 1024  # 1 MB -- de sobra: el cliente ya la redimensiona a un JPEG chico antes de subirla
MIMES_FOTO_PERFIL = {"image/jpeg", "image/png", "image/webp"}


@app.post("/api/perfil/foto")
async def api_subir_foto_perfil(request: Request, foto: UploadFile = File(...)):
    """Foto de perfil, una por CUIL (no por sindicato). El achicado a muy
    baja resolución lo hace el cliente (canvas -> JPEG chico) antes de subir
    -- acá solo se valida tipo/tamaño, no se reprocesa la imagen de nuevo."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(403, "No autorizado")
    if (foto.content_type or "") not in MIMES_FOTO_PERFIL:
        raise HTTPException(400, "La foto tiene que ser JPEG, PNG o WEBP.")
    datos = await foto.read()
    if not datos or len(datos) > MAX_FOTO_PERFIL:
        raise HTTPException(400, "Foto vacía o demasiado pesada.")
    if not db.guardar_foto_trabajador(cuil, datos, foto.content_type):
        raise HTTPException(404, "No se encontró tu cuenta.")
    return {"ok": True}


@app.get("/perfil-foto/{cuil}")
def servir_foto_perfil(cuil: str, request: Request):
    """La ve el propio trabajador dueño, o el admin de un sindicato donde
    ese CUIL esté empadronado (para el avatar en el chat de Trámites) --
    no es pública como el logo del sindicato."""
    ses_trab = sesion_actual(request, "trabajador")
    if ses_trab and request.cookies.get("cuil_trab", "") == cuil:
        pass
    else:
        ses_sind = sesion_actual(request, "sindicato")
        with db.get_session() as s:
            propio = ses_sind and s.exec(select(Trabajador).where(
                Trabajador.cuil == cuil, Trabajador.sindicato_id == ses_sind.get("sid"))).first()
        if not propio:
            raise HTTPException(403, "No autorizado")
    foto = db.foto_trabajador(cuil)
    if not foto:
        raise HTTPException(404, "Sin foto")
    return BinResponse(content=foto["datos"], media_type=foto["mime"],
                        headers={"Cache-Control": "no-cache"})


@app.get("/app/elegir/{sindicato_id}")
def app_elegir(sindicato_id: int, request: Request):
    resp = RedirectResponse("/app/inicio", status_code=303)
    resp.set_cookie("sind_elegido", str(sindicato_id), httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.get("/app/cambiar")
def app_cambiar():
    """Volver al selector de sindicato."""
    resp = RedirectResponse("/app/inicio", status_code=303)
    resp.delete_cookie("sind_elegido")
    return resp


def _qr_credencial(request: Request, cuil: str, sindicato_id: int, codigo_cred: str):
    """(svg, segundos_de_vida) del QR efímero de una credencial ya emitida.

    Un solo lugar arma la URL para que la primera pintada del servidor y las
    renovaciones de /api/credencial/qr no puedan divergir."""
    token = db.token_credencial(cuil, sindicato_id)
    codigo, vence_en = codigo_efimero(token)
    url = url_verificacion(str(request.base_url), token,
                            db.nombre_trabajador(cuil, sindicato_id), cuil,
                            codigo_cred, codigo)
    return qr_svg(url), vence_en


@app.get("/api/credencial/qr")
def api_qr_credencial(request: Request):
    """Emite un QR nuevo para la credencial del trabajador logueado.

    La app lo pide al abrir la pestaña Credencial y antes de cada vencimiento,
    así el código que se ve en pantalla siempre está vigente y una captura
    vieja no verifica."""
    ses = sesion_actual(request, "trabajador")
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or not cuil:
        raise HTTPException(401, "Sesión vencida")
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(404, "Sin sindicato activo")
    codigo_cred = (db.credencial_de(cuil, sid) or {}).get("codigo")
    if not codigo_cred:
        raise HTTPException(404, "La credencial todavía no está emitida")
    svg, vence_en = _qr_credencial(request, cuil, sid, codigo_cred)
    return {"svg": svg, "vence_en": vence_en}


@app.get("/v/{token}", response_class=HTMLResponse)
def verificar_credencial(token: str, request: Request, k: str = ""):
    """Página pública de verificación de una credencial (detrás del QR). No
    requiere login: es lo que ve quien escanea. A propósito NO muestra el DNI.

    `k` es el código efímero que emitió la app al mostrar el QR. Sin un código
    válido y vigente no se muestra NINGÚN dato: es lo que hace que la captura
    de pantalla de un QR ajeno no sirva para hacerse pasar por el afiliado."""
    if not verificar_codigo_efimero(token, k):
        return templates.TemplateResponse("verificar_credencial.html", {
            "request": request, "datos": None, "marca": None,
            "motivo": "vencido", "minutos": TTL_QR_SEGUNDOS // 60,
        })
    datos = db.credencial_por_token(token)
    if datos:
        datos["vigencia_credencial"] = _fmt_fecha_ar(datos.get("vigencia_credencial"))
    return templates.TemplateResponse("verificar_credencial.html", {
        "request": request, "datos": datos, "motivo": "",
        "marca": db.marca_sindicato(datos["sindicato_id"]) if datos else None,
    })


@app.get("/trabajador/salir")
def trabajador_salir():
    resp = RedirectResponse("/ingresar", status_code=303)
    resp.delete_cookie(COOKIE_TRABAJADOR)
    resp.delete_cookie("cuil_trab")
    resp.delete_cookie("sind_elegido")
    return resp


# ================= Empleadores: sesión, login y app =================
# Mismo patrón que el trabajador (CuentaEmpleador/Empleador, cuit_emp/
# sind_elegido_emp en vez de cuil_trab/sind_elegido) -- ver Fase 3 del
# plan de Empleadores.

@app.get("/ingresar-empresa", response_class=HTMLResponse)
def ingresar_empresa(request: Request):
    """Pantalla de login/registro del empleador."""
    return templates.TemplateResponse("empresa_login.html", {
        "request": request, "marca_plataforma": db.marca_plataforma()})


@app.post("/empresa/login")
def empresa_login(request: Request, cuit: str = Form(...), clave: str = Form(...)):
    cuit = _norm_cuil(cuit)
    with db.get_session() as s:
        cuenta = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
        if not cuenta or not auth.verificar_clave(clave, cuenta.clave_hash):
            return RedirectResponse("/ingresar-empresa?error=login", status_code=303)
        cuenta_id = cuenta.id   # capturar el id ANTES de cerrar la sesión
    sinds = db.sindicatos_de_cuit_empleador(cuit)
    if not sinds:
        return RedirectResponse("/ingresar-empresa?error=sinsind", status_code=303)
    token = auth.crear_sesion("empleador", id_usuario=cuenta_id, sindicato_id=0)
    db.registrar_acceso("empresa", sindicato_id=sinds[0]["id"] if len(sinds) == 1 else None)
    resp = RedirectResponse("/empresa/inicio", status_code=303)
    resp.set_cookie(COOKIE_EMPLEADOR, token, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    resp.set_cookie("cuit_emp", cuit, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.post("/empresa/registro")
def empresa_registro(request: Request, cuit: str = Form(...), clave: str = Form(...)):
    cuit = _norm_cuil(cuit)
    # Validar que el CUIT esté dado de alta como Empleador activo en al menos un sindicato
    sinds = db.sindicatos_de_cuit_empleador(cuit)
    if not sinds:
        return RedirectResponse("/ingresar-empresa?error=nohabilitado", status_code=303)
    with db.get_session() as s:
        existe = s.exec(select(CuentaEmpleador).where(CuentaEmpleador.cuit == cuit)).first()
        if existe:
            return RedirectResponse("/ingresar-empresa?error=yaexiste", status_code=303)
        s.add(CuentaEmpleador(cuit=cuit, clave_hash=auth.hashear_clave(clave)))
        # marcar las altas de este CUIT como registradas
        for e in s.exec(select(Empleador).where(Empleador.cuit == cuit)).all():
            e.registrado = True
            s.add(e)
        s.commit()
    token = auth.crear_sesion("empleador", sindicato_id=0)
    resp = RedirectResponse("/empresa/inicio", status_code=303)
    resp.set_cookie(COOKIE_EMPLEADOR, token, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    resp.set_cookie("cuit_emp", cuit, httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.get("/empresa/inicio", response_class=HTMLResponse)
def empresa_inicio(request: Request):
    """Portada del empleador (mirror de admin_portada.html/portada.html):
    tarjetas para lo que tenga habilitado + círculo de perfil editable con
    foto. Sin capa de módulos propia -- Notificaciones y Trámites externos
    siempre están, gatean juntos con el módulo "empleadores" del sindicato
    (ya verificado para que exista la fila Empleador en primer lugar)."""
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        return RedirectResponse("/ingresar-empresa", status_code=303)

    sinds = db.sindicatos_de_cuit_empleador(cuit)
    elegido = request.cookies.get("sind_elegido_emp", "")
    sid_activo = None
    if len(sinds) == 1:
        sid_activo = sinds[0]["id"]
    elif elegido:
        for sd in sinds:
            if str(sd["id"]) == elegido:
                sid_activo = sd["id"]
    if not sid_activo:
        return templates.TemplateResponse("elegir_sindicato_empresa.html", {
            "request": request, "sindicatos": sinds, "marca_plataforma": db.marca_plataforma(),
        })

    marca = db.marca_sindicato(sid_activo)
    perfil = db.perfil_empleador(cuit, sid_activo)
    return templates.TemplateResponse("empresa_portada.html", {
        "request": request, "sindicato": marca["nombre"], "marca": marca,
        "marca_plataforma": db.marca_plataforma(),
        "cuit": cuit, "razon_social": perfil["razon_social"] if perfil else "",
        "iniciales": _iniciales_sindicato(marca["nombre"]),
        "perfil": perfil, "provincias": db.PROVINCIAS_AR,
        "tiene_foto_perfil": bool(db.foto_empleador(cuit)),
        "notificaciones_no_leidas": db.contar_notificaciones_no_leidas_empleador(cuit, sid_activo),
        "tramites_novedades": db.contar_tramites_empleador_con_novedades(cuit, sid_activo),
    })


@app.get("/empresa", response_class=HTMLResponse)
def app_empresa(request: Request):
    """La app del empleador -- una sola pantalla con tabbar (Notificaciones/
    Trámites), sin una portada separada como tiene el trabajador (con solo
    2 funcionalidades no hace falta esa capa extra). Si el CUIT está en
    varios sindicatos y no eligió, muestra el selector."""
    ses = sesion_actual(request, "empleador")
    cuit = request.cookies.get("cuit_emp", "")
    if not ses or not cuit:
        return RedirectResponse("/ingresar-empresa", status_code=303)

    sinds = db.sindicatos_de_cuit_empleador(cuit)
    elegido = request.cookies.get("sind_elegido_emp", "")

    sid_activo = None
    if len(sinds) == 1:
        sid_activo = sinds[0]["id"]
    elif elegido:
        for sd in sinds:
            if str(sd["id"]) == elegido:
                sid_activo = sd["id"]

    if sid_activo:
        marca = db.marca_sindicato(sid_activo)
        with db.get_session() as s:
            empleador = s.exec(select(Empleador).where(
                Empleador.sindicato_id == sid_activo, Empleador.cuit == cuit)).first()
        return templates.TemplateResponse("empresa.html", {
            "request": request, "sindicato": marca["nombre"], "marca": marca,
            "marca_plataforma": db.marca_plataforma(),
            "iniciales": _iniciales_sindicato(marca["nombre"]),
            "cuit": cuit, "razon_social": empleador.razon_social if empleador else "",
            "modulos": _modulos_de(sid_activo),
            "tiene_foto_perfil": bool(db.foto_empleador(cuit)),
        })
    # Varios y no eligió → selector
    return templates.TemplateResponse("elegir_sindicato_empresa.html", {
        "request": request, "sindicatos": sinds, "marca_plataforma": db.marca_plataforma(),
    })


@app.get("/empresa/elegir/{sindicato_id}")
def empresa_elegir(sindicato_id: int, request: Request):
    resp = RedirectResponse("/empresa/inicio", status_code=303)
    resp.set_cookie("sind_elegido_emp", str(sindicato_id), httponly=True, max_age=auth.IDLE_TIMEOUT_SEGUNDOS)
    return resp


@app.get("/empresa/cambiar")
def empresa_cambiar():
    """Volver al selector de sindicato."""
    resp = RedirectResponse("/empresa/inicio", status_code=303)
    resp.delete_cookie("sind_elegido_emp")
    return resp


@app.get("/empresa/salir")
def empresa_salir():
    resp = RedirectResponse("/ingresar-empresa", status_code=303)
    resp.delete_cookie(COOKIE_EMPLEADOR)
    resp.delete_cookie("cuit_emp")
    resp.delete_cookie("sind_elegido_emp")
    return resp


# ================= Entornos: landing interna y versión =================
# Pedido de Sd (2026-09-07): con Pruebas y Demo iguales a la vista es fácil
# entrar al login equivocado. /entornos junta los 8 accesos (4 logins x
# Pruebas/Demo), cada entorno con su color, y la versión que corre en cada
# uno. Detalle en HISTORIAL.md, "Landing de entornos".

ROLES_LOGIN = [
    {"clave": "trabajador", "nombre": "Trabajador", "ruta": "/ingresar"},
    {"clave": "admin", "nombre": "Sindicato", "ruta": "/admin"},
    {"clave": "empresa", "nombre": "Empresa", "ruta": "/ingresar-empresa"},
    {"clave": "plataforma", "nombre": "Plataforma", "ruta": "/plataforma"},
]


def _versiones():
    """Las tres apps con versión propia en version.py. Empresa no lleva
    una, y la landing lo dice en vez de inventarle un número."""
    return {"trabajador": VERSION_TRABAJADOR, "admin": VERSION_ADMIN,
            "plataforma": VERSION_PLATAFORMA, "fecha": FECHA_VERSION}


@app.get("/api/version")
def api_version():
    """Versión de cada app y entorno de ESTE servicio, en JSON. Público y
    con CORS abierto a propósito: la landing /entornos de Pruebas le
    pregunta a la demo (otro origen) qué versión corre, sin entrar a ningún
    "Acerca de". No cuenta nada que el distintivo o el "Acerca de" no
    muestren ya."""
    return JSONResponse({"entorno": entorno.ENTORNO, **_versiones()},
                        headers={"Access-Control-Allow-Origin": "*",
                                 "Cache-Control": "no-store"})


# ---- Actividad: dashboard de monitoreo en /entornos (2026-09-09) ----
# Mismo criterio que /api/version: público y con CORS abierto a propósito,
# porque las cookies de sesión NO viajan entre orígenes distintos (Pruebas
# y Demo son hosts .onrender.com separados) -- sin esto, la pestaña
# Actividad de un entorno no podría mostrar los números del otro. Son
# agregados (cantidades, tokens totales), no el contenido de ningún recibo
# ni trámite puntual. "Cada servicio expone SU propio resumen" (decisión
# de Sd, 2026-09-09): esta ruta nunca consulta la base del otro entorno.
_CACHE_ACTIVIDAD = {"hasta": 0.0, "datos": None}
CACHE_ACTIVIDAD_SEGUNDOS = 120


@app.get("/api/entornos/actividad")
def api_entornos_actividad():
    """Trámites, notificaciones, recibos, tokens de IA y accesos de ESTE
    entorno, por sindicato y totales -- con un caché corto en memoria del
    proceso para que el polling del navegador (cada ~10 min, ver
    entornos.html) y las visitas cruzadas de otro entorno no recalculen en
    cada pedido. CPU/RAM del propio servidor vía render_admin (mismos datos
    que la pestaña Tests)."""
    import time
    ahora = time.monotonic()
    if not _CACHE_ACTIVIDAD["datos"] or ahora > _CACHE_ACTIVIDAD["hasta"]:
        datos = db.actividad_resumen()
        datos["servidor"] = render_admin.estado_servidor()
        datos["entorno"] = entorno.ENTORNO
        _CACHE_ACTIVIDAD["datos"] = datos
        _CACHE_ACTIVIDAD["hasta"] = ahora + CACHE_ACTIVIDAD_SEGUNDOS
    return JSONResponse(_CACHE_ACTIVIDAD["datos"],
                        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})


@app.get("/entornos", response_class=HTMLResponse)
def entornos(request: Request):
    """Landing interna de accesos. Existe SOLO donde se muestra el
    distintivo (local/pruebas, entorno.py): en la demo responde 404 aunque
    el código llegue promovido, porque es una herramienta del equipo y no
    algo para mostrarle a un sindicato. MUESTRA_DISTINTIVO se lee por
    request (no al importar) para que un test pueda simular la demo."""
    if not entorno.MUESTRA_DISTINTIVO:
        raise HTTPException(404, "No existe en este entorno")
    aviso = request.query_params.get("aviso", "")
    # Sin pase no se ve nada: ni accesos ni recursos. Solo la pantalla del
    # PIN (entorno.PIN_LANDING), que deja el pase de 30 días en la cookie.
    if not _pase_landing(request):
        return templates.TemplateResponse("entornos_pin.html", {
            "request": request, "marca_plataforma": db.marca_plataforma(), "aviso": aviso,
            # A dónde ir después del PIN: el recurso que se pidió por enlace
            # directo (_exigir_pase lo manda acá con ?siguiente=).
            "siguiente": _siguiente_seguro(request.query_params.get("siguiente", "")),
        })
    # Prellenar solo las versiones de este mismo servicio (las de Pruebas
    # cuando se sirve desde Pruebas); las del otro entorno las trae el JS.
    versiones = {entorno.ENTORNO: _versiones()} if entorno.ENTORNO in entorno.URLS else {}
    return templates.TemplateResponse("entornos.html", {
        "request": request, "marca_plataforma": db.marca_plataforma(),
        "urls": entorno.URLS, "roles": ROLES_LOGIN, "versiones": versiones,
        # Recursos (recursos.py): el catálogo completo y el aviso de la
        # última acción.
        "recursos": recursos.catalogo(), "aviso": aviso, "hoy": fechas.hoy().isoformat(),
        "tamanio_max_mb": recursos.TAMANIO_MAX // (1024 * 1024),
        # Tests: el detalle de servidor y la lista se piden también por JS
        # (polling), pero se prellenan acá para que la pestaña no arranque
        # vacía si alguien entra directo con #tests.
        "entorno_actual": entorno.ENTORNO,
        "tests_recientes": db.tests_carga_recientes(20) if entorno.ENTORNO == "pruebas" else [],
        # CPU/RAM: funciona en cualquier entorno que tenga sus propias
        # RENDER_API_KEY/RENDER_WEB_SERVICE_ID/RENDER_DB_ID -- hoy solo
        # Pruebas las tiene, así que en Demo queda "configurado": false
        # (render_admin.py lo maneja solo, sin romper la página).
        "render_estado": render_admin.estado_servidor(),
        # Actividad: a diferencia de Tests (solo Pruebas), tiene sentido en
        # los dos entornos -- Demo también se monitorea. La del OTRO
        # entorno la trae el JS (api_entornos_actividad es público con CORS
        # abierto, mismo motivo que /api/version).
        "actividad_local": db.actividad_resumen(),
        "escalones_default_lecturas": ",".join(map(str, ESCALONES_DEFAULT_LECTURAS)),
        "escalones_default_recibos": ",".join(map(str, ESCALONES_DEFAULT_RECIBOS)),
    })


# ---- PIN de la landing ----
# Intentos fallidos por IP, en memoria del proceso: cinco seguidos y ese
# origen espera un minuto. No es un cerrojo serio (se reinicia con cada
# deploy y hay un solo proceso), pero vuelve inútil el tanteo a mano y le
# da sentido a un PIN de ocho dígitos. Detalle en HISTORIAL.md.
PIN_MAX_FALLOS = 5
PIN_ESPERA_SEGUNDOS = 60
_intentos_pin: dict[str, list] = {}     # ip -> [fallos, bloqueado_hasta]


def _ip_de(request: Request) -> str:
    """Render pone la IP real en X-Forwarded-For; sin proxy, la del socket."""
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _pin_bloqueado(ip: str) -> bool:
    import time
    estado = _intentos_pin.get(ip)
    return bool(estado) and estado[1] > time.time()


def _pin_fallo(ip: str) -> None:
    import time
    estado = _intentos_pin.setdefault(ip, [0, 0.0])
    estado[0] += 1
    if estado[0] >= PIN_MAX_FALLOS:
        estado[0] = 0
        estado[1] = time.time() + PIN_ESPERA_SEGUNDOS
    # Que la tabla no crezca sin límite si alguien tantea desde muchas IPs.
    if len(_intentos_pin) > 5000:
        _intentos_pin.clear()


@app.post("/entornos/pin")
def entornos_pin(request: Request, pin: str = Form(""), siguiente: str = Form("")):
    """El PIN de ocho dígitos, una vez por dispositivo: deja el pase de 30
    días (recursos.crear_pase) en una cookie Lax, así un POST desde otro
    sitio no la manda y el pase no sirve para subir o quitar desde afuera.
    `siguiente`: el recurso pedido por enlace directo antes del PIN; con el
    pase puesto se abre ese documento en vez de la landing, así un enlace
    a /recursos/.../archivo se puede compartir con solo el PIN."""
    _exigir_landing()
    ip = _ip_de(request)
    siguiente = _siguiente_seguro(siguiente)
    cola = f"&siguiente={quote(siguiente, safe='')}" if siguiente else ""
    if _pin_bloqueado(ip):
        return RedirectResponse(f"/entornos?aviso=espera{cola}", status_code=303)
    if not entorno.verificar_pin(pin):
        _pin_fallo(ip)
        return RedirectResponse(f"/entornos?aviso=pin{cola}", status_code=303)
    _intentos_pin.pop(ip, None)
    resp = RedirectResponse(siguiente or "/entornos", status_code=303)
    resp.set_cookie(recursos.COOKIE_PASE, recursos.crear_pase(), httponly=True,
                    samesite="lax", max_age=recursos.PASE_SEGUNDOS)
    return resp


# ================= Tests: pestaña de test de estrés en /entornos =================
# Pedido de Sd (2026-09-09): correr el test de estrés (carga/, ver
# carga/README.md) desde un botón en vez de la terminal, y ver ahí mismo
# cómo está configurado el servidor. El botón NO corre el generador en este
# mismo proceso -- competiría por su propia CPU/red con el servidor que
# está midiendo y los números saldrían falsos -- sino que crea un Job de
# Render (contenedor aparte, mismo código y variables de entorno) que corre
# carga/correr_job.py. Ese Job y esta página no comparten proceso ni
# filesystem: se comunican solo a través de la tabla TestCarga (db.py).
# Mismo gate que el resto de /entornos (PIN o sesión de plataforma) -- sin
# login propio por ahora, a reforzar después (ver BACKLOG.md).
ESCALONES_DEFAULT_LECTURAS = [50, 100, 200, 400, 800]
ESCALONES_DEFAULT_RECIBOS = [2, 5, 10, 20]
# El informe completo (gráfico, glosario, diagnóstico) se sirve DESDE ACÁ
# mismo (/entornos/informe, templates/informe_completo.html) -- pedido
# explícito de Sd (2026-09-10): "lo quiero todo en el sitio". Antes vivía
# como Artifact externo de claude.ai, pero ese link exigía iniciar sesión
# (vía GitHub) para verlo -- el mismo problema que ya se había resuelto
# una vez sacando los links directos a GitHub. Ruta relativa: funciona
# igual en Pruebas y Demo, sin hardcodear el dominio.
URL_INFORME_COMPLETO = "/entornos/informe"


def _parsear_escalones(texto: str, default: list) -> list:
    try:
        vals = [int(x.strip()) for x in texto.split(",") if x.strip()]
        vals = [v for v in vals if 0 < v <= 1000]
        return vals or default
    except ValueError:
        return default


@app.post("/entornos/tests/correr")
def entornos_tests_correr(request: Request, tipo: str = Form("lecturas"),
                          escalones: str = Form(""), duracion_seg: int = Form(120)):
    _exigir_landing()
    if not _pase_landing(request):
        raise HTTPException(403, "Ingresá el PIN de la landing.")
    if entorno.ENTORNO != "pruebas":
        raise HTTPException(400, "El test de carga solo corre en Pruebas.")
    if tipo not in ("lecturas", "recibos"):
        raise HTTPException(400, "Tipo de test inválido.")
    default = ESCALONES_DEFAULT_LECTURAS if tipo == "lecturas" else ESCALONES_DEFAULT_RECIBOS
    escalones_ok = _parsear_escalones(escalones, default)
    duracion_seg = max(30, min(duracion_seg, 600))  # entre 30s y 10 min por escalón, cordura
    # Snapshot de la config AL MOMENTO de lanzar (workers, plan, pool): sin
    # esto, la página de detalle de un test viejo mostraría la config de
    # HOY, no la que tenía cuando corrió -- justo lo que hace falta para
    # comparar corridas con distinta cantidad de workers.
    config_al_correr = render_admin.estado_servidor()
    test_id = db.crear_test_carga(tipo, {
        "escalones": escalones_ok, "duracion_seg": duracion_seg,
        "config": {k: config_al_correr.get(k) for k in
                   ("workers_uvicorn", "plan_web", "plan_db", "pool_size", "max_overflow")},
    })
    resultado = render_admin.crear_job(f"python carga/correr_job.py {test_id}")
    if "error" in resultado:
        db.actualizar_test_carga(test_id, estado="error", error_detalle=resultado["error"])
    else:
        db.fijar_job_test_carga(test_id, resultado.get("id", ""))
    return RedirectResponse("/entornos?aviso=test_lanzado#tests", status_code=303)


@app.post("/entornos/tests/publicar")
def entornos_tests_publicar(request: Request, payload: dict = Body(...),
                             x_pin_entornos: str = Header(default="")):
    """Publica en la lista de Tests un test ya corrido AFUERA de la app
    (por ejemplo `carga/correr.sh` con k6, corrido a mano para un
    experimento de infraestructura) -- sin esto, esos resultados solo
    quedan en `carga/log/` y en el informe, y no aparecen en
    /entornos#tests-pruebas junto a los disparados con el botón. Pedido
    explícito de Sd (2026-09-10): "que terminado el test, todos sean
    publicados", sea cual sea la herramienta que lo corrió.
    Acepta el mismo pase de cookie que el resto de /entornos (para
    publicar a mano desde el navegador/curl con sesión) O el PIN en el
    header X-Pin-Entornos (para que `correr.sh` lo llame de punta a punta
    sin login interactivo)."""
    _exigir_landing()
    if not (_pase_landing(request) or entorno.verificar_pin(x_pin_entornos)):
        raise HTTPException(403, "Ingresá el PIN de la landing (cookie o header X-Pin-Entornos).")
    if entorno.ENTORNO != "pruebas":
        raise HTTPException(400, "El test de carga solo corre en Pruebas.")
    tipo = payload.get("tipo")
    if tipo not in ("lecturas", "recibos", "experimento"):
        raise HTTPException(400, "Tipo de test inválido.")
    resumen = payload.get("resumen") or []
    if not resumen:
        raise HTTPException(400, "Falta el resumen del test.")
    if tipo == "experimento":
        # Un experimento completo: varias fases (lecturas, recibos, lectores
        # en paralelo), cada una con sus escalones y la carga medida de web
        # y de Postgres. Lo arma carga/consolidar.py desde los datos crudos.
        if not all(isinstance(f, dict) and "filas" in f for f in resumen):
            raise HTTPException(400, "Un experimento espera fases con 'filas'.")
        parametros = {k: payload.get(k) for k in
                      ("numero", "nombre", "subtitulo", "objetivo", "config",
                       "advertencias", "veredicto", "conclusion", "inicio_ba", "fin_ba")}
    else:
        parametros = {
            "escalones": payload.get("escalones") or [f.get("escalon") for f in resumen],
            "duracion_seg": payload.get("duracion_seg"),
            "config": payload.get("config") or {},
        }
    test_id = db.crear_test_carga(tipo, parametros)
    db.actualizar_test_carga(
        test_id, estado="listo", resumen=resumen,
        terminado_en=payload.get("terminado_en") or fechas.ahora_con_segundos())
    return {"id": test_id}


@app.post("/entornos/tests/borrar-todo")
def entornos_tests_borrar_todo(request: Request, x_pin_entornos: str = Header(default="")):
    """Vacía la lista de tests y reinicia la numeración en 1. Se usa para
    republicar la serie completa desde carga/experimentos.json cuando el
    contenido cambió de forma (ver db.borrar_todos_los_tests_carga)."""
    _exigir_landing()
    if not (_pase_landing(request) or entorno.verificar_pin(x_pin_entornos)):
        raise HTTPException(403, "Ingresá el PIN de la landing (cookie o header X-Pin-Entornos).")
    if entorno.ENTORNO != "pruebas":
        raise HTTPException(400, "Solo en Pruebas.")
    return {"borrados": db.borrar_todos_los_tests_carga()}


# ==================== Solapa "Planes": subir y bajar de plan ====================
# Cambiar de plan corta el servicio: el web se reinicia y la base queda un
# minuto devolviendo error. Por eso todo esto vive SOLO en Pruebas, igual que
# los tests -- en Demo la solapa aparece deshabilitada con el motivo a la
# vista, y estas rutas rechazan cualquier intento aunque alguien las llame a
# mano.


def _exigir_planes(request: Request):
    _exigir_landing()
    if not _pase_landing(request):
        raise HTTPException(403, "Ingresá el PIN de la landing.")
    if entorno.ENTORNO != "pruebas":
        raise HTTPException(
            400, "Los planes se administran solo desde Pruebas: cambiar de plan "
                 "reinicia el servicio y Demo la ven sindicatos e inversor.")


@app.get("/api/entornos/planes")
def api_entornos_planes(request: Request):
    """Lo que la solapa pide al abrirse y cada vez que se aplica algo: plan
    actual de cada servicio, si están activos, el catálogo con precios y las
    reglas programadas. Todo en una sola llamada para que la pantalla no
    muestre mitad vieja y mitad nueva."""
    _exigir_planes(request)
    return {
        "estado": render_admin.estado_planes(),
        "catalogo": render_planes.catalogo(),
        "programados": db.planes_programados(),
        "historial": db.cambios_de_plan(15),
    }


@app.post("/entornos/planes/aplicar")
def entornos_planes_aplicar(request: Request, payload: dict = Body(...)):
    """El botón "Aplicar ahora". `destino` es "web" o "db"."""
    _exigir_planes(request)
    destino = payload.get("destino")
    plan = (payload.get("plan") or "").strip()
    if destino not in ("web", "db"):
        raise HTTPException(400, "Destino inválido.")
    if not render_planes.buscar(destino, plan):
        raise HTTPException(400, f"El plan '{plan}' no está en el catálogo de Render.")

    estado = render_admin.estado_planes()
    anterior = ((estado.get(destino) or {}).get("plan")) or ""
    cambio_id = db.registrar_cambio_plan(
        destino=destino, plan_anterior=anterior, plan_nuevo=plan,
        detalle="aplicado a mano desde /entornos", ok=False, error="en curso")

    if destino == "db":
        res = render_admin.aplicar_plan_db(plan)
    else:
        # Los workers acompañan al plan salvo que se pida lo contrario: la
        # combinación "muchos workers, poca CPU" es la peor medida de todo
        # el informe de carga, y quedó puesta por olvido dos veces durante
        # las pruebas del 2026-09-10.
        workers = (render_planes.workers_para(plan)
                   if payload.get("ajustar_workers", True) else None)
        instancias = payload.get("instancias")
        res = render_admin.aplicar_plan_web(
            plan, instancias=int(instancias) if instancias else None, workers=workers)

    hechos = ", ".join(res.get("hechos") or []) or "sin cambios (ya estaba así)"
    db.actualizar_cambio_plan(cambio_id, ok=not res.get("error"),
                              detalle=f"a mano desde /entornos: {hechos}",
                              error=res.get("error", ""))
    if res.get("error"):
        raise HTTPException(502, res["error"])
    return {"ok": True, "hechos": res.get("hechos") or [], "cambio_id": cambio_id}


@app.post("/entornos/planes/programados")
def entornos_planes_programar(request: Request, payload: dict = Body(...)):
    """Alta de una regla semanal. Los días son ISO: 1 = lunes, 7 = domingo."""
    _exigir_planes(request)
    destino = payload.get("destino")
    plan = (payload.get("plan") or "").strip()
    hora = (payload.get("hora") or "").strip()
    dias = payload.get("dias") or []
    if destino not in ("web", "db"):
        raise HTTPException(400, "Destino inválido.")
    if not render_planes.buscar(destino, plan):
        raise HTTPException(400, f"El plan '{plan}' no está en el catálogo de Render.")
    import re
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora):
        raise HTTPException(400, "La hora tiene que ser HH:MM, de 00:00 a 23:59.")
    dias = [int(d) for d in dias if str(d).isdigit() and 1 <= int(d) <= 7]
    if not dias:
        raise HTTPException(400, "Elegí al menos un día.")
    regla_id = db.crear_plan_programado(
        destino=destino, dias=dias, hora=hora, plan=plan,
        instancias=int(payload["instancias"]) if payload.get("instancias") else None,
        ajustar_workers=bool(payload.get("ajustar_workers", True)),
        nota=(payload.get("nota") or "").strip()[:200])
    return {"id": regla_id}


@app.post("/entornos/planes/programados/{regla_id}/activo")
def entornos_planes_alternar(request: Request, regla_id: int, payload: dict = Body(...)):
    _exigir_planes(request)
    if not db.alternar_plan_programado(regla_id, bool(payload.get("activo"))):
        raise HTTPException(404, "No existe esa regla.")
    return {"ok": True}


@app.delete("/entornos/planes/programados/{regla_id}")
def entornos_planes_borrar(request: Request, regla_id: int):
    _exigir_planes(request)
    if not db.borrar_plan_programado(regla_id):
        raise HTTPException(404, "No existe esa regla.")
    return {"ok": True}


@app.get("/api/entornos/tests")
def api_entornos_tests(request: Request):
    """Lista para el polling de la sección Tests -- se refresca sola cada
    pocos segundos mientras haya alguno corriendo."""
    if not _pase_landing(request):
        raise HTTPException(403, "Ingresá el PIN de la landing.")
    return {"tests": db.tests_carga_recientes(20), "servidor": render_admin.estado_servidor()}


@app.get("/api/entornos/tests/{test_id}")
def api_entornos_test_detalle(request: Request, test_id: int):
    if not _pase_landing(request):
        raise HTTPException(403, "Ingresá el PIN de la landing.")
    fila = db.test_carga_por_id(test_id)
    if not fila:
        raise HTTPException(404, "No existe ese test.")
    return fila


def _analisis_resumen(resumen: list) -> dict:
    """Marca cada escalón contra el objetivo (p95 < 1000ms y errores <1%,
    el mismo criterio de carga/INFORME.md) y busca el último que lo
    cumple -- para que la página de detalle diga la baranda de ESE test
    en una frase, no solo la tabla cruda."""
    filas = []
    ultimo_sano = None
    for f in resumen or []:
        p95 = f.get("p95")
        err = f.get("errores_pct") or 0
        cumple = p95 is not None and p95 < 1000 and err < 1
        if cumple:
            ultimo_sano = f.get("escalon")
        filas.append({**f, "cumple": cumple})
    return {"filas": filas, "ultimo_sano": ultimo_sano}


def _vista_test(fila: dict) -> dict:
    """Normaliza para la plantilla las DOS formas que puede tener un test:

    - Experimento publicado desde carga/experimentos.json: el resumen ya
      viene como fases (lecturas, recibos, lectores en paralelo), cada una
      con sus escalones y la carga medida de web y de Postgres, más el
      veredicto y la conclusión ya redactados desde esos mismos números.
    - Test rápido disparado con el botón (carga/correr_job.py): el resumen
      es una lista plana de escalones de un solo tipo, sin métricas de
      servidor. Se envuelve en una fase única para que la página sea una
      sola, sin dos plantillas que puedan divergir."""
    resumen = fila.get("resumen") or []
    params = fila.get("parametros") or {}
    es_experimento = bool(resumen) and isinstance(resumen[0], dict) and "filas" in resumen[0]
    if es_experimento:
        return {
            "es_experimento": True,
            "fases": resumen,
            "config": params.get("config") or {},
            "veredicto": params.get("veredicto") or "",
            "conclusion": params.get("conclusion") or "",
            "objetivo": params.get("objetivo") or "",
            "advertencias": params.get("advertencias") or [],
            "titulo": params.get("nombre") or f"Test #{fila.get('id')}",
            "subtitulo": params.get("subtitulo") or "",
            "inicio_ba": params.get("inicio_ba") or "",
            "fin_ba": params.get("fin_ba") or "",
        }
    analisis = _analisis_resumen(resumen)
    unidad = "recibos simultáneos" if fila.get("tipo") == "recibos" else "usuarios concurrentes"
    fase = {
        "clave": fila.get("tipo") or "lecturas",
        "titulo": "Recibos" if fila.get("tipo") == "recibos" else "Lecturas",
        "detalle": "", "unidad": unidad, "filas": analisis["filas"],
        "carga": None, "carga_medida": False, "muestras_bajas": False,
        "inicio_ba": "", "fin_ba": "", "duracion_min": None,
    }
    if analisis["ultimo_sano"]:
        veredicto = (f"Cumple el objetivo (p95 por debajo de 1 s y menos de 1% de "
                     f"errores) hasta {analisis['ultimo_sano']} {unidad}.")
    else:
        veredicto = ("Ningún escalón cumplió el objetivo (p95 por debajo de 1 s y "
                     "menos de 1% de errores).")
    return {
        "es_experimento": False,
        "fases": [fase] if analisis["filas"] else [],
        "config": params.get("config") or {},
        "veredicto": veredicto if analisis["filas"] else "",
        "conclusion": "", "objetivo": "", "advertencias": [],
        "titulo": f"Test #{fila.get('id')}", "subtitulo": "",
        "inicio_ba": fila.get("creado_en") or "", "fin_ba": "",
    }


@app.get("/entornos/tests/{test_id}", response_class=HTMLResponse)
def entornos_test_detalle(request: Request, test_id: int):
    """Página de detalle de UN test corrido: config real que tenía el
    servidor en ese momento, parámetros, resultados y si cumplió el
    objetivo -- lo que carga/INFORME.md explica para la corrida de
    referencia, pero por cada corrida rápida disparada desde acá."""
    _exigir_landing()
    if not _pase_landing(request):
        # _siguiente_seguro solo reconoce /recursos/... -- sin pase, vuelve
        # a la landing general (con el PIN puesto, la lista de tests queda
        # ahí mismo para volver a entrar).
        return RedirectResponse("/entornos#tests-pruebas", status_code=303)
    fila = db.test_carga_por_id(test_id)
    if not fila:
        raise HTTPException(404, "No existe ese test.")
    return templates.TemplateResponse("test_detalle.html", {
        "request": request, "marca_plataforma": db.marca_plataforma(),
        "t": fila, "v": _vista_test(fila), "url_informe": URL_INFORME_COMPLETO,
    })


@app.get("/entornos/informe", response_class=HTMLResponse)
def entornos_informe(request: Request):
    """Los cuatro tests comparados: tablas, gráfico, diagnóstico y
    recomendaciones. TODO se genera desde carga/experimentos.json (ver
    carga/informe.py), los mismos datos que muestran las páginas de cada
    test -- antes era HTML escrito a mano que se parchaba después de cada
    corrida y terminó contradiciéndose entre secciones."""
    _exigir_landing()
    if not _pase_landing(request):
        return RedirectResponse("/entornos#tests-pruebas", status_code=303)
    from carga import informe as informe_carga
    return templates.TemplateResponse("informe_completo.html", {
        "request": request, "inf": informe_carga.construir(),
    })


# ================= Recursos: la documentación del proyecto en la landing =================
# Pedido de Sd (2026-09-07): los documentos del proyecto (planes, guías,
# videos) estaban repartidos entre el celular, la nube y la PC. La landing
# los junta bajo "Recursos", cada uno con miniatura, descripción de una
# línea y fecha, y permite subir uno nuevo desde ahí mismo. Qué es un
# recurso, de dónde salen y por qué la landing pide un PIN está en
# recursos.py y entorno.py; el detalle en HISTORIAL.md, "Recursos en la
# landing" y "PIN de la landing".

def _exigir_landing() -> None:
    """Las rutas de recursos existen donde existe la landing (local/
    pruebas) y en ningún otro lado, igual que /entornos."""
    if not entorno.MUESTRA_DISTINTIVO:
        raise HTTPException(404, "No existe en este entorno")


def _pase_landing(request: Request) -> bool:
    """Puede ver la landing y abrir, subir y quitar recursos: pase de 30
    días (el PIN ingresado una vez en este navegador) o sesión de
    plataforma vigente."""
    return (recursos.pase_valido(request.cookies.get(recursos.COOKIE_PASE, ""))
            or bool(sesion_actual(request, "plataforma")))


def _exigir_pase(request: Request):
    """Sin pase: un <form> o un clic vuelven a la landing, que muestra la
    pantalla del PIN; una llamada fetch recibe el 403 de siempre. Si lo que
    se pidió fue abrir un recurso (GET), la puerta se acuerda del destino y
    después del PIN abre ese documento: un enlace directo a
    /recursos/.../archivo funciona con solo el PIN."""
    if _pase_landing(request):
        return None
    if _es_navegacion_de_pagina(request):
        destino = _siguiente_seguro(request.url.path) if request.method == "GET" else ""
        cola = f"?siguiente={quote(destino, safe='')}" if destino else ""
        return RedirectResponse(f"/entornos{cola}", status_code=303)
    raise HTTPException(403, "Ingresá el PIN de la landing para abrir los recursos.")


def _siguiente_seguro(destino: str) -> str:
    """Solo se vuelve a un recurso de esta misma app: un path que empiece
    con /recursos/ (sin esquema ni host, para que nadie use la puerta del
    PIN como redirección abierta hacia otro sitio). Cualquier otra cosa
    equivale a "sin destino" y se va a la landing."""
    return destino if destino.startswith("/recursos/") and not destino.startswith("/recursos//") else ""


def _error_recurso(request: Request, codigo: str, mensaje: str):
    """Errores de validación del alta: el <form> sin JS vuelve a la landing
    con el aviso; el fetch del JS lee el JSON y lo muestra al lado del botón."""
    if _es_navegacion_de_pagina(request):
        return RedirectResponse(f"/entornos?aviso={codigo}#alta", status_code=303)
    return JSONResponse(status_code=400, content={"detail": mensaje, "codigo": codigo})


def _bytes_con_rango(request: Request, datos: bytes, mime: str, nombre: str,
                     cache: str = "private, max-age=86400") -> BinResponse:
    """Sirve bytes de la base respetando `Range` (un solo rango), que es lo
    que el reproductor del navegador manda para adelantar un video o un
    audio: sin 206 se puede reproducir pero no saltar. Los archivos del
    repositorio no pasan por acá (FileResponse ya lo hace solo)."""
    total = len(datos)
    cabeceras = {"Cache-Control": cache, "Accept-Ranges": "bytes",
                 "Content-Disposition": f"inline; filename*=UTF-8''{quote(nombre or 'recurso')}"}
    rango = request.headers.get("range", "")
    if rango.startswith("bytes=") and "," not in rango:
        desde, _, hasta = rango[6:].partition("-")
        try:
            inicio = int(desde) if desde else max(0, total - int(hasta))
            fin = min(int(hasta), total - 1) if (hasta and desde) else total - 1
        except ValueError:
            inicio, fin = 0, total - 1
        if 0 <= inicio <= fin < total:
            cabeceras["Content-Range"] = f"bytes {inicio}-{fin}/{total}"
            return BinResponse(content=datos[inicio:fin + 1], media_type=mime,
                               status_code=206, headers=cabeceras)
        return BinResponse(status_code=416, headers={"Content-Range": f"bytes */{total}"})
    return BinResponse(content=datos, media_type=mime, headers=cabeceras)


@app.post("/recursos")
async def recursos_subir(
    request: Request,
    titulo: str = Form(""), descripcion: str = Form(""), fecha: str = Form(""),
    fragmento: str = Form(""), url: str = Form(""),
    archivo: UploadFile = File(None), miniatura: UploadFile = File(None),
):
    """Alta desde la landing: un archivo (hasta recursos.TAMANIO_MAX) o un
    enlace, con título, descripción de una línea, fecha del documento,
    ancla opcional y miniatura opcional. La miniatura la arma el JS de la
    landing para imágenes y videos; para el resto la elige quien sube, o
    la landing dibuja una portada con el título."""
    _exigir_landing()
    if (sin_pase := _exigir_pase(request)):
        return sin_pase
    titulo = (titulo or "").strip()
    url = (url or "").strip()
    if not titulo:
        return _error_recurso(request, "titulo", "Falta el título.")
    if url and not (url.startswith("http://") or url.startswith("https://")):
        return _error_recurso(request, "enlace", "El enlace tiene que empezar con http:// o https://.")
    datos, nombre, mime = None, "", ""
    if archivo and archivo.filename:
        # El tamaño se mira antes de leer: un archivo enorme no tiene que
        # pasar entero por memoria para ser rechazado.
        if (archivo.size or 0) > recursos.TAMANIO_MAX:
            return _error_recurso(request, "tamanio",
                                  f"El archivo supera los {recursos.TAMANIO_MAX // (1024 * 1024)} MB.")
        datos = await archivo.read()
        if len(datos) > recursos.TAMANIO_MAX:
            return _error_recurso(request, "tamanio",
                                  f"El archivo supera los {recursos.TAMANIO_MAX // (1024 * 1024)} MB.")
        if not datos:
            return _error_recurso(request, "vacio", "El archivo está vacío.")
        nombre = Path(archivo.filename).name
        mime = recursos.mime_de(archivo.content_type, nombre)
    if not datos and not url:
        return _error_recurso(request, "archivo", "Elegí un archivo o pegá un enlace.")
    mini_datos, mini_mime = None, ""
    if miniatura and miniatura.filename:
        mini_datos = await miniatura.read()
        mini_mime = (miniatura.content_type or "").lower()
        if not mini_datos or not mini_mime.startswith("image/") or len(mini_datos) > 2 * 1024 * 1024:
            return _error_recurso(request, "miniatura", "La miniatura tiene que ser una imagen de hasta 2 MB.")
    recurso_id = db.guardar_recurso(
        titulo=titulo[:200], descripcion=(descripcion or "").strip()[:200],
        fecha=recursos.leer_fecha(fecha),
        tipo=recursos.tipo_de(mime, nombre, url) if datos else "enlace",
        url=url if not datos else "", nombre_archivo=nombre, mime=mime, archivo_datos=datos,
        miniatura_datos=mini_datos, miniatura_mime=mini_mime,
        fragmento=recursos.normalizar_fragmento(fragmento),
    )
    # `n=` hace única la URL de cada alta: si la landing ya estaba en
    # "?aviso=agregado", cambiar solo el #ancla no recargaría la página.
    destino = f"/entornos?aviso=agregado&n={recurso_id}#recurso-{recurso_id}"
    if _es_navegacion_de_pagina(request):
        return RedirectResponse(destino, status_code=303)
    return JSONResponse({"ok": True, "id": recurso_id, "ir": destino})


@app.post("/recursos/{recurso_id}/quitar")
def recursos_quitar(recurso_id: int, request: Request):
    """Solo los subidos: los del repositorio se quitan con un commit."""
    _exigir_landing()
    if (sin_pase := _exigir_pase(request)):
        return sin_pase
    if not db.borrar_recurso(recurso_id):
        raise HTTPException(404, "No existe ese recurso")
    return RedirectResponse("/entornos?aviso=quitado#recursos", status_code=303)


@app.get("/recursos/{ref}/archivo")
def recursos_archivo(ref: str, request: Request):
    """Abre el recurso: `ref` es la clave de uno del repositorio
    (recursos.SEMILLA) o el id de uno subido. Un enlace redirige a su URL.
    Pide el pase: son documentos internos."""
    _exigir_landing()
    if (sin_pase := _exigir_pase(request)):
        return sin_pase
    if ref.isdigit():
        r = db.recurso(int(ref))
        if not r:
            raise HTTPException(404, "No existe ese recurso")
        if not r.archivo_datos:
            if r.url:
                return RedirectResponse(r.url, status_code=303)
            raise HTTPException(404, "Ese recurso no tiene archivo")
        return _bytes_con_rango(request, r.archivo_datos, r.mime or "application/octet-stream",
                                r.nombre_archivo)
    item = recursos.del_repositorio_por_clave(ref)
    if not item or not item["ruta"].exists():
        raise HTTPException(404, "No existe ese recurso")
    return FileResponse(item["ruta"], media_type=item["mime"], filename=item["nombre_archivo"],
                        content_disposition_type="inline",
                        headers={"Cache-Control": "private, no-cache"})


@app.get("/recursos/{ref}/miniatura")
def recursos_miniatura(ref: str, request: Request):
    """Detrás del mismo pase que la landing que la muestra."""
    _exigir_landing()
    if (sin_pase := _exigir_pase(request)):
        return sin_pase
    if ref.isdigit():
        r = db.recurso(int(ref))
        if not r or not r.miniatura_datos:
            raise HTTPException(404, "Sin miniatura")
        return BinResponse(content=r.miniatura_datos, media_type=r.miniatura_mime or "image/jpeg",
                           headers={"Cache-Control": "private, max-age=86400"})
    item = recursos.del_repositorio_por_clave(ref)
    if not item or not item["miniatura"] or not item["miniatura"].exists():
        raise HTTPException(404, "Sin miniatura")
    # La URL lleva ?v= (recursos._sello), así que se puede cachear una hora
    # como /static/ (CLAUDE.md, "Todo lo que sale de /static/ va con sello").
    return FileResponse(item["miniatura"], headers={"Cache-Control": "public, max-age=3600"})

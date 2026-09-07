"""Servidor del validador de recibos — Mi Trabajo.

Datos en SQLite (ver db.py). Conceptos, fórmulas y reportes viven en la base;
seed_aefip.json es histórico y NO se siembra solo (ver db.init_db).

Rutas del trabajador:
  GET  /                    pantalla del trabajador
  POST /api/leer            lee un recibo con IA y devuelve preview
  POST /api/validar         valida el recibo confirmado, da de alta conceptos nuevos
  POST /api/reportar        guarda un reporte
  POST /api/enviar-sindicato  envío voluntario para acreditar afiliado cotizante
  GET  /api/mis-recibos     historial de recibos verificados por el trabajador

Rutas del sindicato (admin):
  GET  /admin               panel
  POST /admin/concepto      alta/edición de concepto (ABM)
  POST /admin/concepto/borrar
  POST /admin/formula       alta/edición de fórmula (ABM)
  POST /admin/formula/borrar
  POST /admin/aprender      sube N recibos y devuelve conceptos nuevos propuestos
  POST /admin/aprender/aplicar   da de alta en lote los conceptos aprobados

Rutas de plataforma:
  POST /plataforma/config   edita el tope sindical del 2% (Ley 27.802 art. 133)

Arrancar con:  uvicorn main:app --reload
"""
import traceback
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Form, Cookie, Response, Body
from fastapi.responses import HTMLResponse, RedirectResponse, Response as BinResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select

import db
import auth
import validaciones_tramite
import push
import errores
from errores import ErrorApp
from db import (Concepto, Formula, Reporte, Sindicato, UsuarioSindicato, Trabajador,
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
import recursos
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
    mostrar el JSON. Un 403 con sesión VÁLIDA del rol correcto (ej. módulo
    no habilitado, CUIL ajeno) sigue devolviendo JSON como siempre -- no es
    este caso."""
    if exc.status_code in (401, 403) and _es_navegacion_de_pagina(request):
        rol = _rol_de(request.url.path)
        destino = _panel_de(request.url.path)
        if destino and (not rol or not sesion_actual(request, rol)):
            return RedirectResponse(destino, status_code=303)
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
        recibo, uso = extraer(contenido, archivo.content_type)
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
            fecha=datetime.now().strftime("%d/%m/%Y %H:%M"),
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
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
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
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
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
        datos, uso = extraer_aportes(contenido, archivo.content_type)
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
def exigir_sindicato(request: Request) -> int:
    """Devuelve el sindicato_id de la sesión, o lanza 403 si no hay sesión válida."""
    ses = sesion_actual(request, "sindicato")
    if not ses:
        raise HTTPException(403, "Necesitás iniciar sesión como administrador del sindicato.")
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
    with db.get_session() as s:
        sind = s.get(Sindicato, sid)
        conceptos = s.exec(select(Concepto).where(Concepto.sindicato_id == sid)
                           .order_by(Concepto.codigo)).all()
        formulas = s.exec(select(Formula).where(Formula.sindicato_id == sid)).all()
        reportes = s.exec(select(Reporte).where(Reporte.sindicato_id == sid)
                          .order_by(Reporte.id.desc())).all()
        trabajadores = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid)
                              .order_by(Trabajador.activo.desc(), Trabajador.nombre)).all()
        envios = s.exec(select(EnvioSindicato).where(EnvioSindicato.sindicato_id == sid)
                        .order_by(EnvioSindicato.periodo.desc(), EnvioSindicato.id.desc())).all()
        usuarios_sindicato = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.sindicato_id == sid)
                                    .order_by(UsuarioSindicato.activo.desc(), UsuarioSindicato.nombre)).all()
        empleadores = s.exec(select(Empleador).where(Empleador.sindicato_id == sid)
                             .order_by(Empleador.activo.desc(), Empleador.razon_social)).all()
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
    seccionales = db.seccionales_del_sindicato(sid)
    seccional_por_id = {sec["id"]: sec["nombre"] for sec in seccionales}
    modulos = _modulos_de(sid)
    return templates.TemplateResponse("admin.html", {
        "request": request, "sindicato": sind.nombre if sind else "",
        "marca": db.marca_sindicato(sid), "marca_plataforma": db.marca_plataforma(),
        "iniciales": _iniciales_sindicato(sind.nombre if sind else ""),
        "conceptos": conceptos, "genericos": genericos, "codigos_efectivos": codigos_efectivos,
        "formulas": formulas, "reportes": reportes,
        "trabajadores": trabajadores, "provincias": db.PROVINCIAS_AR, "envios": envios,
        "usuarios_sindicato": usuarios_sindicato,
        "nombres_por_cuil": nombres_por_cuil, "provisorios": provisorios,
        "debe_cambiar": ses.get("cambiar", False),
        "noticias": db.noticias_del_sindicato(sid),
        "beneficios": db.beneficios_del_sindicato(sid),
        "notificaciones": db.notificaciones_del_sindicato(sid),
        "tipos_tramite": db.tipos_tramite_del_sindicato(sid),
        "tramites": db.tramites_del_sindicato(sid),
        "tramites_nuevos": db.contar_tramites_nuevos(sid) if "tramites" in modulos else 0,
        "estados_tramite": db.ESTADOS_TRAMITE, "estados_tramite_label": db.ESTADOS_TRAMITE_LABEL,
        "seccionales": seccionales, "seccional_por_id": seccional_por_id,
        "empleadores": empleadores,
        "notificaciones_empresa": db.notificaciones_empleador_del_sindicato(sid),
        "tipos_tramite_empresa": db.tipos_tramite_empleador_del_sindicato(sid),
        "tramites_empresa": db.tramites_empleador_del_sindicato(sid),
        "tramites_empresa_nuevos": db.contar_tramites_empleador_nuevos(sid) if "empleadores" in modulos else 0,
        "modulos": modulos,
        # Piloto de RAG: solo si el sindicato tiene el módulo habilitado.
        **_contexto_convenio(sid, modulos),
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
    if not db.modulo_habilitado(sid, "dashboard"):
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
    tramites_nuevos = db.contar_tramites_nuevos(sid) if "tramites" in modulos else 0
    tramites_empresa_nuevos = db.contar_tramites_empleador_nuevos(sid) if "empleadores" in modulos else 0
    return templates.TemplateResponse("admin_portada.html", {
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
                        clave_inicial: str = Form(...)):
    """sindicato_id sale de la sesión, nunca de un campo del form -- un
    admin no puede darse de alta a sí mismo en otro sindicato."""
    sid = exigir_sindicato(request)
    cuit = _norm_cuil(usuario)
    if len(cuit) != 11 or not clave_inicial:
        return RedirectResponse("/admin?err=datos#administradores", status_code=303)
    with db.get_session() as s:
        if s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.usuario == cuit)).first():
            return RedirectResponse("/admin?err=usuarioexiste#administradores", status_code=303)
        s.add(UsuarioSindicato(
            sindicato_id=sid, usuario=cuit, nombre=nombre,
            clave_hash=auth.hashear_clave(clave_inicial), debe_cambiar_clave=True,
        ))
        s.commit()
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/usuario/editar")
def admin_usuario_editar(request: Request, id: int = Form(...), nombre: str = Form("")):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        u = s.get(UsuarioSindicato, id)
        if u and u.sindicato_id == sid:
            u.nombre = nombre
            s.add(u); s.commit()
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/usuario/baja")
def admin_usuario_baja(request: Request, id: int = Form(...)):
    """Baja lógica -- bloqueada si es el último administrador activo del
    sindicato (si no, un sindicato podría quedarse sin nadie que pueda
    entrar a /admin, y solo plataforma podría reactivarlo a mano)."""
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        u = s.get(UsuarioSindicato, id)
        if not u or u.sindicato_id != sid:
            return RedirectResponse("/admin#administradores", status_code=303)
        if u.activo:
            activos = s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.activo == True)).all()
            if len(activos) <= 1:
                return RedirectResponse("/admin?err=ultimoadmin#administradores", status_code=303)
        u.activo = False
        s.add(u); s.commit()
    return RedirectResponse("/admin#administradores", status_code=303)


@app.post("/admin/usuario/alta-logica")
def admin_usuario_reactivar(request: Request, id: int = Form(...)):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        u = s.get(UsuarioSindicato, id)
        if u and u.sindicato_id == sid:
            u.activo = True
            s.add(u); s.commit()
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
        destinos = _destinos_validos(s, destino_seccionales, sid)
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
                creada=datetime.now().strftime("%Y-%m-%d %H:%M"),
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
        destinos = _destinos_validos(s, destino_seccionales, sid)
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
                creada=datetime.now().strftime("%Y-%m-%d %H:%M"),
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
):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        if id:
            sec = s.get(Seccional, int(id))
            if sec and sec.sindicato_id == sid:
                sec.nombre, sec.direccion = nombre, direccion
                s.add(sec)
        else:
            s.add(Seccional(sindicato_id=sid, nombre=nombre, direccion=direccion))
        s.commit()
    return RedirectResponse("/admin#seccionales", status_code=303)


@app.post("/admin/seccional/borrar")
def borrar_seccional(request: Request, id: int = Form(...)):
    """Al borrar una seccional, los trabajadores que la tenían asignada
    quedan sin seccional (es un dato opcional, no se bloquea el borrado)."""
    sid = exigir_sindicato(request)
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
    cuils = db.resolver_destinatarios(sid, criterio, valores)
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
    return {"destinatarios": db.notificacion_destinatarios(notificacion_id)}


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
):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    import json
    try:
        campos_crudos = json.loads(campos_json)
        assert isinstance(campos_crudos, list)
        reglas_crudas = json.loads(reglas_json or "[]")
        assert isinstance(reglas_crudas, list)
    except Exception:
        return RedirectResponse("/admin?error=campos#tramites", status_code=303)
    campos = _campos_tramite_validos(campos_crudos)
    if not campos:
        return RedirectResponse("/admin?error=campos#tramites", status_code=303)
    reglas = validaciones_tramite.reglas_saneadas(reglas_crudas, campos)
    if id:
        db.editar_tipo_tramite(int(id), sid, titulo, codigo, activo == "si", campos, reglas)
    else:
        db.crear_tipo_tramite(sid, titulo, codigo, campos, reglas)
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


@app.get("/admin/tramite/{tramite_id}")
def admin_ver_tramite(tramite_id: int, request: Request):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    detalle = db.tramite_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    return detalle


@app.get("/admin/tramites-nuevos-cantidad")
def admin_tramites_nuevos_cantidad(request: Request):
    """Para el polling del globo de "Ver trámites" en admin.html -- si el
    panel queda abierto y llega un trámite nuevo, el globo no se actualizaba
    hasta recargar (se calculaba solo al renderizar la página). Payload
    mínimo (un número), pensado para pedirse cada 30s sin peso real."""
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    return {"cantidad": db.contar_tramites_nuevos(sid)}


@app.post("/admin/tramite/{tramite_id}/estado")
def admin_cambiar_estado_tramite(tramite_id: int, request: Request, estado: str = Form(...)):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    detalle = db.tramite_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
    if detalle["estado"] == "terminado":
        raise HTTPException(400, "Este trámite está terminado y no se puede modificar.")
    if not db.cambiar_estado_tramite(tramite_id, sid, estado):
        raise HTTPException(400, "Estado inválido")
    nuevo_label = db.ESTADOS_TRAMITE_LABEL.get(estado, estado)
    _notificar_cambio_tramite(sid, detalle["cuil"], detalle["numero_expediente"],
        f'Tu sindicato actualizó el estado: {nuevo_label}.')
    return {"ok": True}


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


@app.post("/admin/tramite/{tramite_id}/nota")
async def admin_nota_tramite(tramite_id: int, request: Request, texto: str = Form(""),
                              adjunto: UploadFile = File(None),
                              formulario_id: str = Form("")):
    sid = exigir_sindicato(request)
    _exigir_modulo(sid, "tramites")
    detalle = db.tramite_detalle(tramite_id)
    if not detalle or detalle["sindicato_id"] != sid:
        raise HTTPException(404, "Trámite no encontrado")
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
                            adjunto_nombre, formulario_id=formulario)
    aviso = ('Tu sindicato te mandó un formulario para iniciar.' if formulario
             else 'Tu sindicato te escribió en el chat.')
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
    return {"tipos": db.tipos_tramite_del_sindicato(sid, solo_activos=True) if sid else []}


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
            recibo, uso = extraer(contenido, archivo.content_type)
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


def _destinos_validos(s, destino_seccionales: list[str], sid: int) -> list[int]:
    """Convierte los ids de seccional tildados en el form a int, descartando
    los que no sean de ESTE sindicato (ajenos o inventados) -- mismo criterio
    defensivo que el seccional_id del alta de trabajador."""
    ids_del_sindicato = {sec.id for sec in s.exec(
        select(Seccional).where(Seccional.sindicato_id == sid)).all()}
    resultado = []
    for valor in destino_seccionales:
        try:
            sec_id = int(valor)
        except (TypeError, ValueError):
            continue
        if sec_id in ids_del_sindicato:
            resultado.append(sec_id)
    return resultado


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
            clave_hash=auth.hashear_clave(clave_inicial),
            debe_cambiar_clave=True,
        ))
        s.commit()
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
    dias = (datetime.now().date() - dt.date()).days
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
        })
    # Prellenar solo las versiones de este mismo servicio (las de Pruebas
    # cuando se sirve desde Pruebas); las del otro entorno las trae el JS.
    versiones = {entorno.ENTORNO: _versiones()} if entorno.ENTORNO in entorno.URLS else {}
    return templates.TemplateResponse("entornos.html", {
        "request": request, "marca_plataforma": db.marca_plataforma(),
        "urls": entorno.URLS, "roles": ROLES_LOGIN, "versiones": versiones,
        # Recursos (recursos.py): el catálogo completo y el aviso de la
        # última acción.
        "recursos": recursos.catalogo(), "aviso": aviso, "hoy": date.today().isoformat(),
        "tamanio_max_mb": recursos.TAMANIO_MAX // (1024 * 1024),
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
def entornos_pin(request: Request, pin: str = Form("")):
    """El PIN de ocho dígitos, una vez por dispositivo: deja el pase de 30
    días (recursos.crear_pase) en una cookie Lax, así un POST desde otro
    sitio no la manda y el pase no sirve para subir o quitar desde afuera."""
    _exigir_landing()
    ip = _ip_de(request)
    if _pin_bloqueado(ip):
        return RedirectResponse("/entornos?aviso=espera", status_code=303)
    if not entorno.verificar_pin(pin):
        _pin_fallo(ip)
        return RedirectResponse("/entornos?aviso=pin", status_code=303)
    _intentos_pin.pop(ip, None)
    resp = RedirectResponse("/entornos", status_code=303)
    resp.set_cookie(recursos.COOKIE_PASE, recursos.crear_pase(), httponly=True,
                    samesite="lax", max_age=recursos.PASE_SEGUNDOS)
    return resp


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
    pantalla del PIN; una llamada fetch recibe el 403 de siempre."""
    if _pase_landing(request):
        return None
    if _es_navegacion_de_pagina(request):
        return RedirectResponse("/entornos", status_code=303)
    raise HTTPException(403, "Ingresá el PIN de la landing para abrir los recursos.")


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

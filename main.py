"""Servidor del validador de recibos — Mi Trabajo.

Datos en SQLite (ver db.py). Conceptos, fórmulas y reportes viven en la base;
seed_aefip.json solo siembra la base la primera vez.

Rutas del trabajador:
  GET  /                    pantalla del trabajador
  POST /api/leer            lee un recibo con IA y devuelve preview
  POST /api/validar         valida el recibo confirmado, da de alta conceptos nuevos
  POST /api/reportar        guarda un reporte

Rutas del sindicato (admin):
  GET  /admin               panel
  POST /admin/concepto      alta/edición de concepto (ABM)
  POST /admin/concepto/borrar
  POST /admin/formula       alta/edición de fórmula (ABM)
  POST /admin/formula/borrar
  POST /admin/aprender      sube N recibos y devuelve conceptos nuevos propuestos
  POST /admin/aprender/aplicar   da de alta en lote los conceptos aprobados

Arrancar con:  uvicorn main:app --reload
"""
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Form, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select

import db
import auth
from db import Concepto, Formula, Reporte, Sindicato, UsuarioSindicato, Trabajador, CuentaTrabajador
from extractor import extraer, extraer_aportes
from validador import validar, detectar_nuevos
from semaforo import calcular_semaforo

app = FastAPI(title="Mi Trabajo — validador de recibos")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def _startup():
    db.init_db()


# ================= App del trabajador =================
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("trabajador.html", {
        "request": request, "sindicato": db.nombre_sindicato(),
    })


@app.post("/api/leer")
async def api_leer(request: Request, archivo: UploadFile = File(...)):
    contenido = await archivo.read()
    try:
        recibo = extraer(contenido, archivo.content_type)
    except Exception:
        raise HTTPException(422, "No pudimos leer el recibo. Probá con una foto más nítida.")
    if recibo.get("confianza") == "baja":
        raise HTTPException(422, "La imagen no es clara. Sacá la foto de nuevo con buena luz.")
    sid = sindicato_activo_trabajador(request)
    nuevos = detectar_nuevos(db.conceptos_como_dicts(sid), recibo["lineas"])
    return {"recibo": recibo, "conceptos_nuevos": nuevos}


@app.post("/api/validar")
def api_validar(request: Request, payload: dict):
    recibo = payload["recibo"]
    nuevos = payload.get("conceptos_nuevos", [])
    sid = sindicato_activo_trabajador(request)
    if not sid:
        raise HTTPException(400, "No pudimos determinar tu sindicato. Volvé a ingresar.")

    # Alta de conceptos nuevos como pendientes, EN EL SINDICATO del trabajador
    if nuevos and sid:
        with db.get_session() as s:
            existentes = {c.codigo for c in s.exec(select(Concepto).where(
                Concepto.sindicato_id == sid)).all()}
            for n in nuevos:
                if n["codigo"] not in existentes:
                    s.add(Concepto(
                        sindicato_id=sid,
                        codigo=n["codigo"], nombre=n["descripcion"], tipo=n["tipo"],
                        remunerativo=n.get("remunerativo", True),
                        alias=[n["descripcion"]], pendiente_revision=True,
                    ))
                    existentes.add(n["codigo"])
            s.commit()

    # Validar SOLO con conceptos y fórmulas de ESE sindicato
    return validar(db.conceptos_como_dicts(sid), db.formulas_como_dicts(sid), recibo)


@app.post("/api/reportar")
def api_reportar(payload: dict):
    with db.get_session() as s:
        s.add(Reporte(
            fecha=datetime.now().strftime("%d/%m/%Y %H:%M"),
            cuil=payload.get("cuil", ""), periodo=payload.get("periodo", ""),
            estado="nuevo", detalle=payload,
        ))
        s.commit()
    return {"ok": True}


@app.post("/api/aportes")
async def api_aportes(archivo: UploadFile = File(...)):
    """Lee el comprobante de aportes de ARCA que sube el trabajador y arma el semáforo."""
    contenido = await archivo.read()
    try:
        datos = extraer_aportes(contenido, archivo.content_type)
    except Exception:
        raise HTTPException(422, "No pudimos leer el comprobante. Probá con una captura más nítida.")
    if datos.get("confianza") == "baja" or not datos.get("meses"):
        raise HTTPException(422, "No parece un comprobante de aportes de ARCA. Revisá la captura.")
    return calcular_semaforo(datos)


# ================= Panel del sindicato =================
def exigir_sindicato(request: Request) -> int:
    """Devuelve el sindicato_id de la sesión, o lanza 403 si no hay sesión válida."""
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "sindicato":
        raise HTTPException(403, "Necesitás iniciar sesión como administrador del sindicato.")
    return ses.get("sid", 0)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "sindicato":
        return templates.TemplateResponse("admin_login.html", {"request": request})

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
    return templates.TemplateResponse("admin.html", {
        "request": request, "sindicato": sind.nombre if sind else "",
        "marca": db.marca_sindicato(sid),
        "conceptos": conceptos, "formulas": formulas, "reportes": reportes,
        "trabajadores": trabajadores, "provincias": db.PROVINCIAS_AR,
        "debe_cambiar": ses.get("cambiar", False),
        "marca": db.marca_sindicato(sid),
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
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, max_age=8*3600)
    return resp


@app.get("/admin/salir")
def admin_salir():
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


@app.post("/admin/trabajador")
def admin_trabajador_alta(
    request: Request,
    id: str = Form(""), cuil: str = Form(...), nombre: str = Form(...),
    calle: str = Form(""), numero: str = Form(""), piso: str = Form(""),
    ciudad: str = Form(""), provincia: str = Form(""),
    telefono: str = Form(""), mail: str = Form(""),
):
    """Alta o modificación manual de un trabajador. Obligatorios: cuil y nombre."""
    sid = exigir_sindicato(request)
    cuil_norm = _norm_cuil(cuil)
    if len(cuil_norm) != 11 or not nombre.strip():
        return RedirectResponse("/admin?err=datos#trabajadores", status_code=303)
    with db.get_session() as s:
        if id:  # modificación (solo si es de este sindicato)
            t = s.get(Trabajador, int(id))
            if t and t.sindicato_id == sid:
                t.cuil, t.nombre = cuil_norm, nombre.strip()
                t.calle, t.numero, t.piso = calle, numero, piso
                t.ciudad, t.provincia = ciudad, provincia
                t.telefono, t.mail = telefono, mail
                s.add(t)
        else:    # alta — evitar duplicado de CUIL en el mismo sindicato
            existe = s.exec(select(Trabajador).where(
                Trabajador.sindicato_id == sid, Trabajador.cuil == cuil_norm)).first()
            if not existe:
                s.add(Trabajador(
                    sindicato_id=sid, cuil=cuil_norm, nombre=nombre.strip(),
                    calle=calle, numero=numero, piso=piso, ciudad=ciudad,
                    provincia=provincia, telefono=telefono, mail=mail))
        s.commit()
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


# ---------- ABM de conceptos ----------
@app.post("/admin/concepto")
def abm_concepto(
    request: Request,
    id: str = Form(""), codigo: str = Form(...), nombre: str = Form(...),
    tipo: str = Form(...), remunerativo: str = Form("no"),
    alias: str = Form(""),
):
    sid = exigir_sindicato(request)
    aliases = [a.strip() for a in alias.split(",") if a.strip()]
    if nombre not in aliases:
        aliases.append(nombre)
    es_remun = remunerativo == "si"
    with db.get_session() as s:
        if id:  # edición — solo si el concepto es de este sindicato
            c = s.get(Concepto, int(id))
            if c and c.sindicato_id == sid:
                c.codigo, c.nombre, c.tipo = codigo, nombre, tipo
                c.remunerativo, c.alias = es_remun, aliases
                c.pendiente_revision = False
                s.add(c)
        else:   # alta
            s.add(Concepto(sindicato_id=sid, codigo=codigo, nombre=nombre, tipo=tipo,
                           remunerativo=es_remun, alias=aliases,
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


# ---------- ABM de fórmulas ----------
@app.post("/admin/formula")
def abm_formula(
    request: Request,
    id: str = Form(""), target: str = Form(...), descripcion: str = Form(...),
    expr: str = Form(...), tolerancia: float = Form(1.0),
):
    sid = exigir_sindicato(request)
    with db.get_session() as s:
        if id:
            f = s.get(Formula, int(id))
            if f and f.sindicato_id == sid:
                f.target, f.descripcion, f.expr, f.tolerancia = target, descripcion, expr, tolerancia
                s.add(f)
        else:
            s.add(Formula(sindicato_id=sid, target=target, descripcion=descripcion,
                          expr=expr, tolerancia=tolerancia))
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


# ---------- Aprendizaje: subir N recibos y proponer conceptos nuevos ----------
@app.post("/admin/aprender")
async def aprender(request: Request, archivos: list[UploadFile] = File(...)):
    """Lee varios recibos y junta los conceptos nuevos, deduplicados."""
    sid = exigir_sindicato(request)
    conceptos_actuales = db.conceptos_como_dicts(sid)
    acumulados = {}
    leidos, fallidos = 0, 0

    for archivo in archivos:
        contenido = await archivo.read()
        try:
            recibo = extraer(contenido, archivo.content_type)
        except Exception:
            fallidos += 1
            continue
        leidos += 1
        for n in detectar_nuevos(conceptos_actuales, recibo["lineas"]):
            clave = n["codigo"]
            if clave in acumulados:
                acumulados[clave]["veces"] += 1
            else:
                acumulados[clave] = {**n, "remunerativo": n["tipo"] == "ingreso", "veces": 1}

    return {
        "leidos": leidos, "fallidos": fallidos,
        "propuestas": sorted(acumulados.values(), key=lambda x: -x["veces"]),
    }


@app.post("/admin/aprender/aplicar")
def aprender_aplicar(request: Request, payload: dict):
    """Da de alta en lote los conceptos aprobados por el admin."""
    sid = exigir_sindicato(request)
    aprobados = payload.get("aprobados", [])
    altas = 0
    with db.get_session() as s:
        existentes = {c.codigo for c in s.exec(select(Concepto).where(
            Concepto.sindicato_id == sid)).all()}
        for c in aprobados:
            if c["codigo"] not in existentes:
                s.add(Concepto(
                    sindicato_id=sid,
                    codigo=c["codigo"], nombre=c["descripcion"], tipo=c["tipo"],
                    remunerativo=c.get("remunerativo", True),
                    alias=[c["descripcion"]], pendiente_revision=False,
                ))
                existentes.add(c["codigo"])
                altas += 1
        s.commit()
    return {"ok": True, "altas": altas}


# ================= Admin de plataforma =================
COOKIE = "sesion_mitrabajo"


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


def sesion_actual(request: Request) -> dict | None:
    return auth.leer_sesion(request.cookies.get(COOKIE, ""))


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
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        return templates.TemplateResponse("plataforma_login.html", {"request": request})
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
    return templates.TemplateResponse("plataforma.html", {
        "request": request, "sindicatos": info,
    })


@app.post("/plataforma/login")
def plataforma_login(response: Response, cuit: str = Form(...), clave: str = Form(...)):
    if not auth.verificar_plataforma(clave, cuit):
        return RedirectResponse("/plataforma?error=1", status_code=303)
    token = auth.crear_sesion("plataforma")
    resp = RedirectResponse("/plataforma", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, max_age=8*3600)
    return resp


@app.get("/plataforma/salir")
def plataforma_salir():
    resp = RedirectResponse("/plataforma", status_code=303)
    resp.delete_cookie(COOKIE)
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
    logo: UploadFile = File(None),
):
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        raise HTTPException(403, "No autorizado")
    slug = slugify(nombre)
    logo_nombre = ""
    if logo and logo.filename:
        logo_nombre = _guardar_logo(logo, slug)
    with db.get_session() as s:
        sind = Sindicato(
            nombre=nombre, descripcion=descripcion, slug=slug,
            cuit=cuit, direccion=direccion, mail=mail, telefonos=telefonos,
            autoridad=autoridad, cargo_autoridad=cargo_autoridad, logo=logo_nombre,
            color_primario=color_primario or "#152238",
            color_secundario=color_secundario or "#1a7a6b",
            color_acento=color_acento or "#b23a2e",
        )
        s.add(sind); s.commit()
    return RedirectResponse("/plataforma", status_code=303)


def _guardar_logo(archivo: UploadFile, slug: str) -> str:
    """Guarda el logo en static/logos/ y devuelve el nombre del archivo.
    Acepta PNG y formatos de imagen compatibles."""
    import os
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        return ""
    os.makedirs("static/logos", exist_ok=True)
    nombre = f"{slug}{ext}"
    ruta = os.path.join("static/logos", nombre)
    with open(ruta, "wb") as f:
        f.write(archivo.file.read())
    return nombre


@app.post("/plataforma/usuario")
def plataforma_alta_usuario(
    request: Request,
    sindicato_id: int = Form(...), usuario: str = Form(...),
    nombre: str = Form(""), clave_inicial: str = Form(...),
):
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        raise HTTPException(403, "No autorizado")
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
    color_acento: str = Form("#b23a2e"), logo: UploadFile = File(None),
):
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        raise HTTPException(403, "No autorizado")
    with db.get_session() as s:
        sind = s.get(Sindicato, id)
        if sind:
            sind.nombre, sind.descripcion = nombre, descripcion
            sind.cuit, sind.direccion, sind.mail = cuit, direccion, mail
            sind.telefonos, sind.autoridad, sind.cargo_autoridad = telefonos, autoridad, cargo_autoridad
            sind.color_primario = color_primario or "#152238"
            sind.color_secundario = color_secundario or "#1a7a6b"
            sind.color_acento = color_acento or "#b23a2e"
            if logo and logo.filename:
                sind.logo = _guardar_logo(logo, sind.slug)
            s.add(sind); s.commit()
    return RedirectResponse("/plataforma", status_code=303)


@app.post("/plataforma/sindicato/borrar")
def plataforma_borrar_sindicato(request: Request, id: int = Form(...)):
    """Borra un sindicato y TODOS sus datos asociados (conceptos, fórmulas,
    reportes, trabajadores, admins). Operación destructiva."""
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        raise HTTPException(403, "No autorizado")
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
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        raise HTTPException(403, "No autorizado")
    with db.get_session() as s:
        admins = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sindicato_id)).all()
        return {"admins": [
            {"usuario": a.usuario, "nombre": a.nombre, "activo": a.activo}
            for a in admins]}


@app.post("/plataforma/reset-clave")
def plataforma_reset_clave(
    request: Request, tipo: str = Form(...), identificador: str = Form(...),
    clave_nueva: str = Form(...),
):
    """TRANSITORIO (para pruebas): el admin de plataforma cambia la clave de
    cualquier usuario. tipo = 'sindicato' (admin) o 'trabajador' (cuenta).
    ⚠️ Sacar o reemplazar por recuperación segura antes de producción."""
    ses = sesion_actual(request)
    if not ses or ses.get("rol") != "plataforma":
        raise HTTPException(403, "No autorizado")
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


@app.get("/ingresar", response_class=HTMLResponse)
def ingresar(request: Request):
    """Pantalla de login/registro del trabajador."""
    return templates.TemplateResponse("trabajador_login.html", {"request": request})


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
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, max_age=8*3600)
    resp.set_cookie("cuil_trab", cuil, httponly=True, max_age=8*3600)
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
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, max_age=8*3600)
    resp.set_cookie("cuil_trab", cuil, httponly=True, max_age=8*3600)
    return resp


@app.get("/app", response_class=HTMLResponse)
def app_trabajador(request: Request):
    """La app del trabajador. Si está en varios sindicatos y no eligió, muestra el selector."""
    ses = sesion_actual(request)
    cuil = request.cookies.get("cuil_trab", "")
    if not ses or ses.get("rol") != "trabajador" or not cuil:
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
        return templates.TemplateResponse("trabajador.html", {
            "request": request, "sindicato": marca["nombre"], "marca": marca,
            "cuil": cuil, "nombre_trab": db.nombre_trabajador(cuil, sid_activo),
        })
    # Varios y no eligió → selector
    return templates.TemplateResponse("elegir_sindicato.html", {
        "request": request, "sindicatos": sinds,
    })


@app.get("/app/elegir/{sindicato_id}")
def app_elegir(sindicato_id: int, request: Request):
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie("sind_elegido", str(sindicato_id), httponly=True, max_age=8*3600)
    return resp


@app.get("/app/cambiar")
def app_cambiar():
    """Volver al selector de sindicato."""
    resp = RedirectResponse("/app", status_code=303)
    resp.delete_cookie("sind_elegido")
    return resp


@app.get("/trabajador/salir")
def trabajador_salir():
    resp = RedirectResponse("/ingresar", status_code=303)
    resp.delete_cookie(COOKIE)
    resp.delete_cookie("cuil_trab")
    resp.delete_cookie("sind_elegido")
    return resp

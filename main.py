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

from fastapi import FastAPI, UploadFile, File, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select

import db
from db import Concepto, Formula, Reporte, Sindicato
from extractor import extraer
from validador import validar, detectar_nuevos

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
async def api_leer(archivo: UploadFile = File(...)):
    contenido = await archivo.read()
    try:
        recibo = extraer(contenido, archivo.content_type)
    except Exception:
        raise HTTPException(422, "No pudimos leer el recibo. Probá con una foto más nítida.")
    if recibo.get("confianza") == "baja":
        raise HTTPException(422, "La imagen no es clara. Sacá la foto de nuevo con buena luz.")
    nuevos = detectar_nuevos(db.conceptos_como_dicts(), recibo["lineas"])
    return {"recibo": recibo, "conceptos_nuevos": nuevos}


@app.post("/api/validar")
def api_validar(payload: dict):
    recibo = payload["recibo"]
    nuevos = payload.get("conceptos_nuevos", [])

    # Alta de conceptos nuevos como pendientes (respetando remunerativo del trabajador)
    if nuevos:
        with db.get_session() as s:
            existentes = {c.codigo for c in s.exec(select(Concepto)).all()}
            for n in nuevos:
                if n["codigo"] not in existentes:
                    s.add(Concepto(
                        codigo=n["codigo"], nombre=n["descripcion"], tipo=n["tipo"],
                        remunerativo=n.get("remunerativo", True),
                        alias=[n["descripcion"]], pendiente_revision=True,
                    ))
                    existentes.add(n["codigo"])
            s.commit()

    return validar(db.conceptos_como_dicts(), db.formulas_como_dicts(), recibo)


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


# ================= Panel del sindicato =================
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    with db.get_session() as s:
        conceptos = s.exec(select(Concepto).order_by(Concepto.codigo)).all()
        formulas = s.exec(select(Formula)).all()
        reportes = s.exec(select(Reporte).order_by(Reporte.id.desc())).all()
    return templates.TemplateResponse("admin.html", {
        "request": request, "sindicato": db.nombre_sindicato(),
        "conceptos": conceptos, "formulas": formulas, "reportes": reportes,
    })


# ---------- ABM de conceptos ----------
@app.post("/admin/concepto")
def abm_concepto(
    id: str = Form(""), codigo: str = Form(...), nombre: str = Form(...),
    tipo: str = Form(...), remunerativo: str = Form("no"),
    alias: str = Form(""),
):
    aliases = [a.strip() for a in alias.split(",") if a.strip()]
    if nombre not in aliases:
        aliases.append(nombre)
    es_remun = remunerativo == "si"
    with db.get_session() as s:
        if id:  # edición
            c = s.get(Concepto, int(id))
            if c:
                c.codigo, c.nombre, c.tipo = codigo, nombre, tipo
                c.remunerativo, c.alias = es_remun, aliases
                c.pendiente_revision = False  # editado = revisado
                s.add(c)
        else:   # alta
            s.add(Concepto(codigo=codigo, nombre=nombre, tipo=tipo,
                           remunerativo=es_remun, alias=aliases,
                           pendiente_revision=False))
        s.commit()
    return RedirectResponse("/admin#conceptos", status_code=303)


@app.post("/admin/concepto/borrar")
def borrar_concepto(id: int = Form(...)):
    with db.get_session() as s:
        c = s.get(Concepto, id)
        if c:
            s.delete(c)
            s.commit()
    return RedirectResponse("/admin#conceptos", status_code=303)


# ---------- ABM de fórmulas ----------
@app.post("/admin/formula")
def abm_formula(
    id: str = Form(""), target: str = Form(...), descripcion: str = Form(...),
    expr: str = Form(...), tolerancia: float = Form(1.0),
):
    with db.get_session() as s:
        if id:
            f = s.get(Formula, int(id))
            if f:
                f.target, f.descripcion, f.expr, f.tolerancia = target, descripcion, expr, tolerancia
                s.add(f)
        else:
            s.add(Formula(target=target, descripcion=descripcion, expr=expr, tolerancia=tolerancia))
        s.commit()
    return RedirectResponse("/admin#formulas", status_code=303)


@app.post("/admin/formula/borrar")
def borrar_formula(id: int = Form(...)):
    with db.get_session() as s:
        f = s.get(Formula, id)
        if f:
            s.delete(f)
            s.commit()
    return RedirectResponse("/admin#formulas", status_code=303)


# ---------- Aprendizaje: subir N recibos y proponer conceptos nuevos ----------
@app.post("/admin/aprender")
async def aprender(archivos: list[UploadFile] = File(...)):
    """Lee varios recibos y junta los conceptos nuevos, deduplicados."""
    conceptos_actuales = db.conceptos_como_dicts()
    acumulados = {}   # clave -> propuesta
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
def aprender_aplicar(payload: dict):
    """Da de alta en lote los conceptos aprobados por el admin."""
    aprobados = payload.get("aprobados", [])
    altas = 0
    with db.get_session() as s:
        existentes = {c.codigo for c in s.exec(select(Concepto)).all()}
        for c in aprobados:
            if c["codigo"] not in existentes:
                s.add(Concepto(
                    codigo=c["codigo"], nombre=c["descripcion"], tipo=c["tipo"],
                    remunerativo=c.get("remunerativo", True),
                    alias=[c["descripcion"]], pendiente_revision=False,
                ))
                existentes.add(c["codigo"])
                altas += 1
        s.commit()
    return {"ok": True, "altas": altas}

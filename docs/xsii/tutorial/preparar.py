"""Prepara la base LOCAL para filmar el tutorial: limpia los restos de XSII,
crea el usuario «Sofía Demo» y el proyecto «UOM · Primera versión» con tres
tarjetas de la Mesa. Imprime un JSON con la cookie de sesión.
Uso: .venv/bin/python docs/xsii/tutorial/preparar.py   (base de desarrollo, nunca Pruebas)"""
import json
import os
import sys

os.environ.setdefault("ENTORNO", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from sqlalchemy import text  # noqa: E402
from sqlmodel import select  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402
import implementacion as im  # noqa: E402

USUARIO, NOMBRE = "sofia.demo", "Sofía Demo"
PROYECTO = "UOM · Primera versión"
NUEVAS_DEL_TUTORIAL = ["Seccional Bahía Blanca", "Seccional Resistencia", "Seccional San Luis", "Seccional Neuquén", "Seccional Río Gallegos"]
TARJETAS = [
    ("Lista de seccionales con domicilios", "Necesitamos la lista de seccionales con su domicilio y teléfono."),
    ("Planilla del padrón de afiliados", "Necesitamos la planilla del padrón en Excel o CSV."),
    ("Recibos de muestra", "Necesitamos tres recibos de muestra, de distintos puestos."),
]

with db.get_session() as s:
    # Restos de pruebas: XSII y los proyectos de QA (SQL directo: el registro es inmutable por ORM).
    for t in ("xsiimovimiento", "xsiiinsumo", "xsiidecision"):
        s.exec(text(f"DELETE FROM {t}"))
    viejos = [p.id for p in s.exec(select(db.ImplProyecto)).all() if p.nombre.startswith("QA XSII") or p.nombre == PROYECTO]
    if viejos:
        tablas = [r[0] for r in s.exec(text(
            "SELECT table_name FROM information_schema.columns WHERE column_name='proyecto_id' AND table_name LIKE 'impl%'"))]
        ids = ",".join(str(i) for i in viejos)
        for t in tablas:
            s.exec(text(f"DELETE FROM {t} WHERE proyecto_id IN ({ids})"))
        s.exec(text(f"DELETE FROM implproyecto WHERE id IN ({ids})"))
    s.commit()
    # Las seccionales que el tutorial carga desde la planilla se borran para poder filmarlo de nuevo.
    # (Solo si nadie las usa: una seccional con afiliados o usuarios no se toca.)
    uom0 = s.exec(select(db.Sindicato).where(db.Sindicato.nombre.contains("Metal"))).first()
    for nom in NUEVAS_DEL_TUTORIAL:
        sec = s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == uom0.id, db.Seccional.nombre == nom)).first()
        if sec:
            s.exec(text("DELETE FROM seccional WHERE id = :i AND NOT EXISTS (SELECT 1 FROM trabajador WHERE seccional_id = :i)"), params={"i": sec.id})
    s.commit()
    u = s.exec(select(db.UsuarioPlataforma).where(db.UsuarioPlataforma.usuario == USUARIO)).first()
    if not u:
        u = db.UsuarioPlataforma(usuario=USUARIO, nombre=NOMBRE, email="", clave_hash=auth.hashear_clave("xsii-tutorial-1"),
                                 activo=True, debe_cambiar_clave=False, debe_completar_datos=False)
        s.add(u)
        s.commit()
        s.refresh(u)
    uid = u.id
    uom = s.exec(select(db.Sindicato).where(db.Sindicato.nombre.contains("Metal"))).first()
    eq = im.Actor(im.EQUIPO, uid, NOMBRE)
    p = db.impl_crear_proyecto(s, PROYECTO, eq, sindicato_id=uom.id)
    pid = p.id
    cods = [db.impl_crear_tarjeta(s, pid, eq, "pedido", t, x).codigo for t, x in TARJETAS]
    s.commit()
cookie = auth.crear_sesion("plataforma", id_usuario=uid, ident=USUARIO)
print(json.dumps({"uid": uid, "pid": pid, "tarjetas": cods, "cookie": cookie, "cookie_name": "sesion_plataforma"}))

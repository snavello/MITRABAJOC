"""Carga dos sindicatos de demostración completos, para mostrar la plataforma.

Ejecutar UNA vez con el servidor apagado:  python cargar_demo.py
Crea: 2 sindicatos con marca, sus admins, conceptos, fórmulas y trabajadores.
"""
import db
from db import Sindicato, UsuarioSindicato, Concepto, Formula, Trabajador
from sqlmodel import select
import auth

db.init_db()

SINDICATOS = [
    {
        "nombre": "Unión Obrera Metalúrgica", "descripcion": "Trabajadores del metal",
        "cuit": "30-11111111-1", "mail": "info@uom.org.ar", "autoridad": "Ana Pérez",
        "cargo_autoridad": "Secretaria General",
        "color_primario": "#1a3d6b", "color_secundario": "#2fa88f", "color_acento": "#e8b84b",
        "admin": ("20111111110", "uom-demo"),   # CUIT del admin UOM
        "conceptos": [
            ("SUELDO", "Sueldo básico", "ingreso", True),
            ("PRESENT", "Presentismo", "ingreso", True),
            ("VIATICO", "Viáticos", "ingreso", False),
            ("JUB", "Aporte jubilatorio", "descuento", False),
            ("SINDMET", "Cuota sindical UOM", "descuento", False),
        ],
        "formulas": [
            ("JUB", "Jubilación = 11% del remunerativo", "0.11 * base_remunerativa", 1.0),
            ("SINDMET", "Cuota UOM = 2.5% del remunerativo", "0.025 * base_remunerativa", 1.0),
        ],
        "cuils": ["20111111119", "27222222224", "20333333336"],
    },
    {
        "nombre": "Federación Gastronómica", "descripcion": "Trabajadores gastronómicos",
        "cuit": "30-22222222-2", "mail": "info@fega.org.ar", "autoridad": "Luis Gómez",
        "cargo_autoridad": "Secretario General",
        "color_primario": "#7a1f2b", "color_secundario": "#c19a3e", "color_acento": "#3d6b4a",
        "admin": ("20222222220", "fega-demo"),  # CUIT del admin Gastronómica
        "conceptos": [
            ("BASICO", "Sueldo básico", "ingreso", True),
            ("ADIC", "Adicional por categoría", "ingreso", True),
            ("PROP", "Propinas (no remun.)", "ingreso", False),
            ("JUBG", "Aporte jubilatorio", "descuento", False),
            ("SINDGAS", "Cuota sindical gastronómica", "descuento", False),
        ],
        "formulas": [
            ("JUBG", "Jubilación = 11% del remunerativo", "0.11 * base_remunerativa", 1.0),
            ("SINDGAS", "Cuota gastronómica = 2% del remunerativo", "0.02 * base_remunerativa", 1.0),
        ],
        "cuils": ["27222222224", "20444444440"],  # el 222 también está en UOM (pluriempleo)
    },
]

with db.get_session() as s:
    # Limpiar sindicatos demo previos (por si se corre dos veces), dejando AEFIP
    for nom in [x["nombre"] for x in SINDICATOS]:
        for sind in s.exec(select(Sindicato).where(Sindicato.nombre == nom)).all():
            for c in s.exec(select(Concepto).where(Concepto.sindicato_id == sind.id)).all(): s.delete(c)
            for f in s.exec(select(Formula).where(Formula.sindicato_id == sind.id)).all(): s.delete(f)
            for t in s.exec(select(Trabajador).where(Trabajador.sindicato_id == sind.id)).all(): s.delete(t)
            for u in s.exec(select(UsuarioSindicato).where(UsuarioSindicato.sindicato_id == sind.id)).all(): s.delete(u)
            s.delete(sind)
    s.commit()

import re
def slug(n):
    x = n.lower()
    for a,b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]: x=x.replace(a,b)
    return re.sub(r"[^a-z0-9]+","-",x).strip("-")

with db.get_session() as s:
    for d in SINDICATOS:
        sind = Sindicato(
            nombre=d["nombre"], descripcion=d["descripcion"], slug=slug(d["nombre"]),
            cuit=d["cuit"], mail=d["mail"], autoridad=d["autoridad"],
            cargo_autoridad=d["cargo_autoridad"], color_primario=d["color_primario"],
            color_secundario=d["color_secundario"], color_acento=d["color_acento"],
        )
        s.add(sind); s.commit(); s.refresh(sind)
        u, cl = d["admin"]
        s.add(UsuarioSindicato(sindicato_id=sind.id, usuario=u, nombre="Administrador",
                               clave_hash=auth.hashear_clave(cl), debe_cambiar_clave=False))
        for cod, nom, tipo, rem in d["conceptos"]:
            s.add(Concepto(sindicato_id=sind.id, codigo=cod, nombre=nom, tipo=tipo,
                           remunerativo=rem, alias=[nom]))
        for tgt, desc, expr, tol in d["formulas"]:
            s.add(Formula(sindicato_id=sind.id, target=tgt, descripcion=desc, expr=expr, tolerancia=tol))
        for cuil in d["cuils"]:
            s.add(Trabajador(sindicato_id=sind.id, cuil=cuil, registrado=False))
        s.commit()
        print(f"✓ {d['nombre']}: admin {u}/{cl}, {len(d['conceptos'])} conceptos, {len(d['cuils'])} trabajadores")

print("\nDemo cargada. Accesos:")
print("  Plataforma:  /plataforma  (clave en variable PLATAFORMA_PASSWORD)")
print("  UOM:         /admin  →  CUIT 20111111110 / uom-demo")
print("  Gastronómica:/admin  →  CUIT 20222222220 / fega-demo")
print("  Trabajador:  /ingresar  →  registrarse con un CUIL habilitado")
print("  Pluriempleo: CUIL 27222222224 está en ambos sindicatos")

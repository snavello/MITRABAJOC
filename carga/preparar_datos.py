# -*- coding: utf-8 -*-
"""Siembra el sindicato y los 1.000 trabajadores sintéticos para el test de
carga (ver carga/README.md). Corre SOLO contra el Postgres que apunte
DATABASE_URL -- pensado para el servicio `mitrabajo-pruebas`, nunca para la
demo. Idempotente: correrlo de nuevo no duplica nada.

Uso (con la Internal o External Database URL de mitrabajo-pruebas-db):
    DATABASE_URL=postgresql://... python carga/preparar_datos.py
    DATABASE_URL=postgresql://... python carga/preparar_datos.py --limpiar

Crea:
- Un sindicato "Sindicato de Pruebas -- Carga" (slug `carga-estres`), con
  los módulos que la app del trabajador usa en el test de lecturas
  (recibos, aportes, credencial, notificaciones) y una marca mínima propia
  para no interferir con ningún sindicato real.
- 1.000 trabajadores (Trabajador, empadronados en ese sindicato) + su
  CuentaTrabajador (login), con clave "1234" para todos -- SOLO
  corresponde en un sindicato de prueba descartable como este.
- carga/usuarios.csv con cuil,clave para que los scripts de carga lean de
  ahí (no hardcodean nada).

Los CUIL son sintéticos con el prefijo 20/27 + un bloque reservado para
este sindicato (no calzan con ningún CUIL real ni con los de otros lotes
de demo -- mismo criterio de `cargar_lote_sindicato.contexto_lote`).
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

import auth
import db
from db import Sindicato, Trabajador, CuentaTrabajador

NOMBRE_SINDICATO = "Sindicato de Pruebas -- Carga"
SLUG_SINDICATO = "carga-estres"
CANTIDAD = 1000
CLAVE = "1234"
BASE_CUIL = 90000000  # bloque que no usa ningún lote de demo (ver cargar_lote_sindicato.py)
CSV_SALIDA = Path(__file__).resolve().parent / "usuarios.csv"


def _cuil(i: int) -> str:
    prefijo = "20" if i % 3 else "27"
    return f"{prefijo}{BASE_CUIL + i:08d}{i % 10}"


def obtener_o_crear_sindicato() -> int:
    with db.get_session() as s:
        existente = s.exec(select(Sindicato).where(Sindicato.slug == SLUG_SINDICATO)).first()
        if existente:
            return existente.id
        sind = Sindicato(
            nombre=NOMBRE_SINDICATO, slug=SLUG_SINDICATO,
            descripcion="Sindicato descartable para pruebas de carga -- no usar para demos.",
            modulos_habilitados=["recibos", "aportes", "credencial", "notificaciones"],
        )
        s.add(sind)
        s.commit()
        s.refresh(sind)
        print(f"Sindicato creado: id={sind.id} slug={sind.slug}")
        return sind.id


def sembrar_trabajadores(sindicato_id: int, nombre_sindicato: str):
    filas_csv = []
    creados = 0
    nuevos_ids = []
    with db.get_session() as s:
        existentes = {t.cuil for t in s.exec(
            select(Trabajador).where(Trabajador.sindicato_id == sindicato_id)).all()}
        for i in range(CANTIDAD):
            cuil = _cuil(i)
            filas_csv.append((cuil, CLAVE))
            if cuil in existentes:
                continue
            s.add(Trabajador(sindicato_id=sindicato_id, cuil=cuil))
            # Nombre y domicilio van en la PERSONA (ver CuentaTrabajador).
            db.guardar_datos_personales(
                s, cuil, nombre=f"Carga Sintetico {i:04d}",
                domicilio={"localidad": "Buenos Aires", "provincia": "Buenos Aires"})
            cuenta = db.asegurar_cuenta(s, cuil)
            if not cuenta.clave_hash:
                cuenta.clave_hash = auth.hashear_clave(CLAVE)
                s.add(cuenta)
            creados += 1
            if creados % 200 == 0:
                s.commit()
                print(f"  ... {creados}/{CANTIDAD}")
        s.commit()
        # Los ids recien commiteados: releer por cuil nuevo para generar su
        # credencial (necesaria para que el paso "credencial" del test de
        # lecturas -- GET /api/credencial/qr -- no devuelva 404 en masa).
        cuils_nuevos = {c for c, _ in filas_csv} - existentes
        if cuils_nuevos:
            nuevos_ids = [t.id for t in s.exec(
                select(Trabajador).where(
                    Trabajador.sindicato_id == sindicato_id,
                    Trabajador.cuil.in_(cuils_nuevos),
                )).all()]
    print(f"Trabajadores nuevos creados: {creados} (ya existian: {CANTIDAD - creados})")
    if nuevos_ids:
        for j, tid in enumerate(nuevos_ids, 1):
            db.generar_codigo_credencial(tid, sindicato_id, nombre_sindicato)
            if j % 200 == 0:
                print(f"  ... credenciales {j}/{len(nuevos_ids)}")
        print(f"Credenciales generadas: {len(nuevos_ids)}")
    with open(CSV_SALIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cuil", "clave"])
        w.writerows(filas_csv)
    print(f"Escrito {CSV_SALIDA} con {len(filas_csv)} filas")


def limpiar(sindicato_id: int):
    with db.get_session() as s:
        trabs = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sindicato_id)).all()
        cuils = [t.cuil for t in trabs]
        for t in trabs:
            s.delete(t)
        for cuil in cuils:
            cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
            if cuenta:
                s.delete(cuenta)
        s.commit()
    print(f"Borrados {len(cuils)} trabajadores y sus cuentas del sindicato de carga.")


if __name__ == "__main__":
    sid = obtener_o_crear_sindicato()
    if "--limpiar" in sys.argv:
        limpiar(sid)
    else:
        sembrar_trabajadores(sid, NOMBRE_SINDICATO)

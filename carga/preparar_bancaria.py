# -*- coding: utf-8 -*-
"""Empadrona en La Bancaria a los 50 empleados del lote de recibos bancarios
(PLAN_PRUEBAS_BANCARIA.md, §5.1) y escribe `carga/usuarios_bancaria.csv`
para k6 y para `probar_lote_bancaria.py`.

SIN `--si` NO ESCRIBE NADA: muestra qué haría. Corre contra la base que
apunte DATABASE_URL (pensado para Pruebas, como Job de Render o con la
External Database URL). Se niega con ENTORNO=demo o prod.

Uso:
    python carga/lote_bancaria.py extraer
    DATABASE_URL=... python carga/preparar_bancaria.py                # ensayo
    DATABASE_URL=... python carga/preparar_bancaria.py --si           # empadrona
    DATABASE_URL=... python carga/preparar_bancaria.py --limpiar      # ensayo del borrado
    DATABASE_URL=... python carga/preparar_bancaria.py --limpiar --si
Opciones: --sindicato "La Bancaria" (por nombre, sin distinguir mayúsculas),
          --sin-seccional (por defecto se reparten entre las seccionales que
          ya tenga el sindicato, siempre igual, para que el Panel tenga qué
          recortar al Admin de Seccional).

Qué hace con cada CUIL:
- Lo empadrona (Trabajador) con el CUIT del banco como empleador.
- Nombre y domicilio en la persona (db.guardar_datos_personales).
- Clave = los 6 primeros dígitos del CUIL (la mínima de la app), SOLO si
  la cuenta no tenía clave. Si ya tenía una, no se toca y el CSV la deja en
  blanco: ese CUIL no se usa en las pruebas (no pisamos la clave de nadie).

`--limpiar` borra de ESE sindicato lo que dejaron las pruebas para esos 50
CUIL (recibos verificados, envíos, reportes, recibos sospechosos) y su
empadronamiento; la cuenta, solo si no está empadronada en otro sindicato.
El consumo de IA (UsoIA) NO se borra: es el registro de lo que se gastó.
Los conceptos pendientes con el CUIT de los bancos del lote se cuentan y se
borran solo con `--con-conceptos`.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlmodel import func, select  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402
import lote_bancaria as L  # noqa: E402
from db import (Concepto, CuentaTrabajador, EnvioSindicato, Reporte, ReciboSospechoso,  # noqa: E402
                ReciboVerificado, Seccional, Sindicato, Trabajador)

CSV_SALIDA = Path(__file__).resolve().parent / "usuarios_bancaria.csv"


def clave_de(cuil: str) -> str:
    # 6: la clave mínima de la app (main.CLAVE_MINIMA). Igual que alta_por_panel.py.
    return L.solo_digitos(cuil)[:6]


def _sindicato(s, nombre: str) -> Sindicato:
    sind = s.exec(select(Sindicato).where(
        func.lower(Sindicato.nombre) == nombre.strip().lower())).first()
    if not sind:
        raise SystemExit(f"No hay un sindicato llamado {nombre!r} en esta base.")
    return sind


def empadronar(nombre_sindicato: str, escribir: bool, con_seccional: bool = True) -> list[dict]:
    """Devuelve las filas del CSV (cuil, clave, banco, seccional_id, estado)."""
    emps = L.empleados()
    filas = []
    with db.get_session() as s:
        sind = _sindicato(s, nombre_sindicato)
        secc = s.exec(select(Seccional).where(Seccional.sindicato_id == sind.id)
                      .order_by(Seccional.id)).all() if con_seccional else []
        ya = {t.cuil: t for t in s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == sind.id)).all()}
        print(f"Sindicato: {sind.nombre} (id {sind.id}), {len(secc)} seccionales")
        for i, e in enumerate(sorted(emps, key=lambda e: e["cuil"])):
            cuil = L.solo_digitos(e["cuil"])
            seccional_id = secc[i % len(secc)].id if secc else None
            cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first()
            tenia_clave = bool(cuenta and cuenta.clave_hash)
            estado = "ya_empadronado" if cuil in ya else "nuevo"
            if tenia_clave and cuil not in ya:
                estado = "cuenta_ajena"     # existe con clave propia: no se usa
            clave = "" if tenia_clave and estado == "cuenta_ajena" else clave_de(cuil)
            if escribir and estado != "cuenta_ajena":
                t = ya.get(cuil) or Trabajador(sindicato_id=sind.id, cuil=cuil)
                t.cuit_empleador = L.solo_digitos(e["cuit_banco"])
                t.seccional_id = seccional_id
                t.registrado = True
                t.activo = True
                s.add(t)
                db.guardar_datos_personales(
                    s, cuil, nombre=e["nombre"],
                    domicilio={"localidad": "Ciudad Autónoma de Buenos Aires",
                               "provincia": "Ciudad Autónoma de Buenos Aires"})
                cuenta = db.asegurar_cuenta(s, cuil)
                if not cuenta.clave_hash:
                    cuenta.clave_hash = auth.hashear_clave(clave)
                    s.add(cuenta)
            filas.append({"cuil": cuil, "clave": clave, "banco": e["banco"],
                          "seccional_id": seccional_id or "", "estado": estado})
        if escribir:
            s.commit()
    return filas


def limpiar(nombre_sindicato: str, escribir: bool, con_conceptos: bool = False) -> dict:
    cuils = {L.solo_digitos(e["cuil"]) for e in L.empleados()}
    cuits = {L.solo_digitos(e["cuit_banco"]) for e in L.empleados()}
    cuenta = {}
    with db.get_session() as s:
        sind = _sindicato(s, nombre_sindicato)
        # Los conceptos que /api/validar dio de alta como pendientes con el
        # CUIT de los bancos del lote. Solo con --con-conceptos: un recibo
        # real del mismo banco pudo haber creado los mismos.
        pend = s.exec(select(Concepto).where(
            Concepto.sindicato_id == sind.id, Concepto.pendiente_revision == True,  # noqa: E712
            Concepto.cuit_empleador.in_(cuits))).all()
        cuenta["Concepto pendiente (bancos del lote)"] = len(pend)
        if escribir and con_conceptos:
            for c in pend:
                s.delete(c)
        for modelo in (ReciboVerificado, EnvioSindicato, Reporte, ReciboSospechoso):
            filas = s.exec(select(modelo).where(modelo.sindicato_id == sind.id,
                                                modelo.cuil.in_(cuils))).all()
            cuenta[modelo.__name__] = len(filas)
            if escribir:
                for f in filas:
                    s.delete(f)
        trabs = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sind.id,
                                                Trabajador.cuil.in_(cuils))).all()
        cuenta["Trabajador"] = len(trabs)
        en_otro = set(s.exec(select(Trabajador.cuil).where(
            Trabajador.sindicato_id != sind.id, Trabajador.cuil.in_(cuils))).all())
        cuentas = s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.cuil.in_(cuils - en_otro))).all()
        cuenta["CuentaTrabajador"] = len(cuentas)
        if escribir:
            for t in trabs:
                s.delete(t)
            s.flush()
            for c in cuentas:
                s.delete(c)
            s.commit()
    return cuenta


def _guarda():
    if os.getenv("ENTORNO", "").strip().lower() in ("demo", "prod"):
        raise SystemExit("ENTORNO es demo o prod: este script es solo para Pruebas o local.")


def main(argv):
    _guarda()
    escribir = "--si" in argv
    nombre = "La Bancaria"
    if "--sindicato" in argv:
        nombre = argv[argv.index("--sindicato") + 1]
    if "--limpiar" in argv:
        r = limpiar(nombre, escribir, con_conceptos="--con-conceptos" in argv)
        print(("Borrado: " if escribir else "Se borraría (ensayo, falta --si): ") + str(r))
        return
    filas = empadronar(nombre, escribir, con_seccional="--sin-seccional" not in argv)
    from collections import Counter
    print("Estados:", dict(Counter(f["estado"] for f in filas)))
    if not escribir:
        print("Ensayo: no se escribió nada. Con --si empadrona y escribe el CSV.")
        return
    with open(CSV_SALIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cuil", "clave", "banco", "seccional_id", "estado"])
        w.writeheader()
        w.writerows(filas)
    print(f"Escrito {CSV_SALIDA} ({sum(1 for f in filas if f['clave'])} usables)")


if __name__ == "__main__":
    main(sys.argv[1:])

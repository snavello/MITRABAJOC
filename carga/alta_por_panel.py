# -*- coding: utf-8 -*-
"""Da de alta empleados del lote bancario en Pruebas POR LA APP, sin tocar la
base (PLAN_PRUEBAS_BANCARIA.md): el admin de La Bancaria los carga en el
padrón (`POST /admin/trabajador`) y cada uno se registra como lo haría desde
el teléfono (`/trabajador/registro/iniciar` + `/trabajador/registro`).

Es la alternativa a `preparar_bancaria.py` cuando no se tiene la URL de la
base de Pruebas: hace lo mismo para unos pocos CUIL y deja la misma
`carga/usuarios_bancaria.csv` (agrega, no pisa). Clave = los 6 primeros
dígitos del CUIL (la mínima de la app es 6).

Se registra con el canal de mail apagado (nivel 1). Si el registro pide un
código por mail, el CUIL se informa y se saltea: no se inventa el código.
Un CUIL que ya entra con su clave se deja como está.

Uso:
    python carga/alta_por_panel.py --base-url https://mitrabajo-pruebas.onrender.com \
        --admin-cuit 20333444551 --admin-clave ... --azar 10 --semilla 20261103      # ensayo
    ... --si
La selección (`--azar N --semilla S`) es la misma que usa
`probar_lote_bancaria.py`, así que se dan de alta exactamente los dueños de
los recibos que se van a subir.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import lote_bancaria as L  # noqa: E402

USUARIOS = Path(__file__).resolve().parent / "usuarios_bancaria.csv"
CAMPOS = ["cuil", "clave", "banco", "seccional_id", "estado"]
PROVINCIA = LOCALIDAD = "Ciudad Autónoma de Buenos Aires"


def clave_de(cuil: str) -> str:
    return L.solo_digitos(cuil)[:6]


def _entra(base, cuil, clave) -> bool:
    import httpx
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{base}/trabajador/login", data={"cuil": cuil, "clave": clave},
                   follow_redirects=True)
        return "/app" in str(r.url)


def alta_y_registro(base: str, admin_cuit: str, admin_clave: str, empleados: list[dict]) -> list[dict]:
    import httpx
    filas = []
    with httpx.Client(timeout=60) as admin:
        r = admin.post(f"{base}/admin/login", data={"usuario": admin_cuit, "clave": admin_clave},
                       follow_redirects=True)
        if not r.url.path.startswith("/admin/inicio"):
            raise SystemExit(f"El admin no pudo entrar al panel (terminó en {r.url}).")
        for e in empleados:
            cuil, clave = L.solo_digitos(e["cuil"]), clave_de(e["cuil"])
            fila = {"cuil": cuil, "clave": clave, "banco": e["banco"], "seccional_id": "", "estado": ""}
            if _entra(base, cuil, clave):
                fila["estado"] = "ya_entraba"
                filas.append(fila)
                continue
            ra = admin.post(f"{base}/admin/trabajador", data={
                "cuil": cuil, "nombre": e["nombre"], "provincia": PROVINCIA, "localidad": LOCALIDAD,
                "cuit_empleador": L.solo_digitos(e["cuit_banco"])}, follow_redirects=False)
            destino = ra.headers.get("location", "")
            if ra.status_code != 303 or "err=" in destino:
                fila.update(clave="", estado=f"alta_rechazada {ra.status_code} {destino}")
                filas.append(fila)
                continue
            with httpx.Client(timeout=60) as t:
                ri = t.post(f"{base}/trabajador/registro/iniciar", data={"cuil": cuil})
                datos = ri.json() if ri.headers.get("content-type", "").startswith("application/json") else {}
                if ri.status_code != 200 or datos.get("paso") != "datos":
                    fila.update(clave="", estado=f"registro_pide_{datos.get('paso') or ri.status_code}")
                    filas.append(fila)
                    continue
                rr = t.post(f"{base}/trabajador/registro", data={
                    "cuil": cuil, "clave": clave, "nombre": e["nombre"], "provincia": PROVINCIA,
                    "localidad": LOCALIDAD, "token": datos.get("token", "")}, follow_redirects=False)
            ok = rr.status_code == 303 and rr.headers.get("location", "").startswith("/app")
            fila["estado"] = "registrado" if ok else f"registro_fallo {rr.headers.get('location', rr.status_code)}"
            if not ok:
                fila["clave"] = ""
            filas.append(fila)
    return filas


def guardar(filas: list[dict], ruta: Path = USUARIOS) -> None:
    """Agrega o reemplaza por CUIL en el CSV, sin perder los que ya estaban."""
    previas = {}
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            previas = {r["cuil"]: r for r in csv.DictReader(f)}
    for f in filas:
        previas[f["cuil"]] = f
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        w.writeheader()
        w.writerows(previas.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--admin-cuit", default="20333444551")
    ap.add_argument("--admin-clave", required=True)
    ap.add_argument("--azar", type=int, required=True)
    ap.add_argument("--semilla", type=int, required=True)
    ap.add_argument("--si", action="store_true")
    a = ap.parse_args(argv)
    base = a.base_url.rstrip("/")
    if "mitrabajo.onrender.com" in base or "mitrabajo-demo" in base:
        raise SystemExit("Nunca contra la demo.")
    recibos = L.muestra_azar(L.manifiesto(), a.azar, a.semilla)
    cuils = {L.solo_digitos(r["cuil"]) for r in recibos}
    empleados = [e for e in L.empleados() if L.solo_digitos(e["cuil"]) in cuils]
    print(f"{len(recibos)} recibos al azar (semilla {a.semilla}) de {len(empleados)} personas:")
    for e in empleados:
        print(f"  {L.solo_digitos(e['cuil'])}  {e['banco']}")
    if not a.si:
        print("Ensayo: no se dio de alta nadie. Con --si los carga en el padrón y los registra.")
        return
    filas = alta_y_registro(base, a.admin_cuit, a.admin_clave, empleados)
    guardar(filas)
    for f in filas:
        print(f"  {f['cuil']}  {f['estado']}")
    print(f"{sum(1 for f in filas if f['clave'])} de {len(filas)} listos en {USUARIOS}")


if __name__ == "__main__":
    main()

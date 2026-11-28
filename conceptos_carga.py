"""Las reglas de «aprender conceptos de los recibos de muestra», en un solo lugar.

Las usan dos puertas: la pestaña Aprendizaje del panel (`POST /admin/aprender` y
`/admin/aprender/aplicar`) y la tarea asistida REC-04 de XSII (docs/xsii/API.md,
«Bloque 4b»). Así lo que cada una propone y lo que cada una escribe no pueden
diferir: las dos rutas del panel son adaptadores y dan EXACTAMENTE lo mismo que
antes de este módulo (lo fija `test_xsii_conceptos.py`).

No importa `main`. `proponer` es pura (no toca la base ni la red) y `aplicar` solo
escribe en la sesión que recibe, sin commit.
"""

from __future__ import annotations

from sqlmodel import select

import cuit
import validador
from db import Concepto


def _cuit_del_recibo(recibo: dict) -> str | None:
    return cuit.normalizar((recibo.get("empleador") or {}).get("cuit")) or None


def _cuit_mal(numero, opcional: bool = True) -> bool:
    """Lo mismo que `main._cuit_mal(numero, opcional=True)`: un CUIT vacío es
    opcional, pero un texto sin dígitos es un número mal escrito. True = frenarlo."""
    n = cuit.normalizar(numero)
    if not n:
        return (not opcional) or bool(str(numero or "").strip())
    return not cuit.es_valido(n)


def proponer(conceptos_actuales: list, recibos: list, detalle: bool = False) -> list:
    """Los conceptos nuevos que traen estos recibos (los dicts que devolvió el
    extractor, ya rearmados), deduplicados por `(código, CUIT del empleador)`:
    el mismo código crudo de dos empleadores puede significar cosas distintas.
    Cada propuesta lleva cuántas veces apareció (`veces`), a qué concepto que ya
    está se parece (`similar`) y, si es de un empleador, a qué genérico parece
    corresponder (`generico_sugerido`). Orden: las más vistas primero.

    `detalle=True` (solo la asistida de XSII) suma `seccion_leida` y `tipo_leido`,
    lo que la IA vio de la primera línea que la trajo; nada más cambia."""
    genericos_actuales = [c for c in conceptos_actuales if not c.get("cuit_empleador")]
    acumulados: dict = {}
    for recibo in recibos:
        cuit_empleador = _cuit_del_recibo(recibo)
        lineas = recibo["lineas"]
        for n in validador.detectar_nuevos(conceptos_actuales, lineas, cuit_empleador):
            clave = (n["codigo"], cuit_empleador or "")
            if clave in acumulados:
                acumulados[clave]["veces"] += 1
                continue
            acumulados[clave] = {**n, "veces": 1, "cuit_empleador": cuit_empleador}
            if detalle:
                acumulados[clave].update(_lo_leido(n["codigo"], lineas))

    # Antes de que se apruebe el lote, avisar si alguna propuesta se parece a un
    # concepto que YA está en el catálogo: darla de alta crearía un duplicado que
    # después hay que ir a limpiar a mano.
    for p in acumulados.values():
        similar = validador.buscar_similar(p["descripcion"], conceptos_actuales)
        p["similar"] = {
            "codigo": similar["concepto"]["codigo"],
            "nombre": similar["concepto"]["nombre"],
            "ratio": similar["ratio"],
        } if similar else None
        # Si la propuesta es específica de un empleador, además sugerir a qué
        # concepto GENÉRICO parece corresponder, así la fórmula de siempre la
        # controla sin ir a buscarlo a mano. Si la IA identificó un aporte de ley
        # (jubilación, PAMI, obra social, cuota sindical) es una señal más fuerte
        # que la similitud de texto: se usa primero.
        p["generico_sugerido"] = None
        if p["cuit_empleador"]:
            generico_universal = validador.generico_de_categoria(p.get("categoria_universal"),
                                                                 genericos_actuales)
            if generico_universal:
                p["generico_sugerido"] = {
                    "codigo": generico_universal["codigo"], "nombre": generico_universal["nombre"],
                }
            else:
                similar_generico = validador.buscar_similar(p["descripcion"], genericos_actuales)
                if similar_generico:
                    p["generico_sugerido"] = {
                        "codigo": similar_generico["concepto"]["codigo"],
                        "nombre": similar_generico["concepto"]["nombre"],
                    }
    return sorted(acumulados.values(), key=lambda x: -x["veces"])


def _lo_leido(codigo: str, lineas: list) -> dict:
    """La sección y el tipo que la IA leyó en la primera línea que dio ese código."""
    for ln in lineas:
        if not isinstance(ln, dict):
            continue
        clave = validador._clave(ln.get("codigo")) or validador.codigo_provisorio(ln.get("descripcion"))
        if clave == codigo:
            tipo = ln.get("tipo")
            return {"seccion_leida": validador.seccion_de(ln) or "",
                    "tipo_leido": tipo if isinstance(tipo, str) else ""}
    return {"seccion_leida": "", "tipo_leido": ""}


def aplicar(s, sid: int, aprobados: list) -> dict:
    """Da de alta en lote los conceptos aprobados, ya revisados
    (`pendiente_revision=False`). Cada uno puede traer `cuit_empleador` y
    `codigo_generico`, y `categoria_sindical` (solo para un descuento). SIN commit.

    El CUIT del empleador lo propuso la IA leyendo recibos y el concepto nace
    CONFIRMADO: es una puerta de alta (PLAN_CUIT_MOD11.md, D2). Uno que no cumple
    el módulo 11 (casi siempre un dígito mal leído) no entra: queda afuera y se
    informa. Un concepto que ya existe con esa clave no se toca y se cuenta.

    Devuelve `{altas, cuit_invalidos, repetidos}` (`repetidos` es una cantidad)."""
    altas, repetidos = 0, 0
    cuit_invalidos = []
    existentes = {(c.codigo, c.cuit_empleador or "") for c in s.exec(select(Concepto).where(
        Concepto.sindicato_id == sid)).all()}
    for c in aprobados:
        if _cuit_mal(c.get("cuit_empleador", ""), opcional=True):
            cuit_invalidos.append(c.get("codigo", ""))
            continue
        cuit_empleador = cuit.normalizar(c.get("cuit_empleador", "")) or None
        clave = (c["codigo"], cuit_empleador or "")
        if clave in existentes:
            repetidos += 1
            continue
        s.add(Concepto(
            sindicato_id=sid,
            codigo=c["codigo"], nombre=c["descripcion"], tipo=c["tipo"],
            remunerativo=c.get("remunerativo", True),
            alias=[c["descripcion"]], pendiente_revision=False,
            cuit_empleador=cuit_empleador,
            codigo_generico=(c.get("codigo_generico") or "").strip() or None,
            categoria_sindical=c.get("categoria_sindical") or "",
        ))
        existentes.add(clave)
        altas += 1
    return {"altas": altas, "cuit_invalidos": cuit_invalidos, "repetidos": repetidos}

"""Números en formato argentino para lo que lee una persona en el panel.

Auditoría de diseño 2026-10 (G4-35): el panel del sindicato mostraba los
números como los guarda la base -- «$1.0», «2.5%», «2026-09», el CUIL sin
guiones y «1583 recibos». La app del afiliado ya escribía en castellano
(`peso()` de trabajador.html); esto es lo mismo para las plantillas del panel,
registrado como filtros de Jinja en main.py. Su espejo en el navegador es
`static/numeros_ar.js`, con las mismas reglas.

Puro: no importa `db` y no cambia nada de lo que se guarda. Solo da forma al
mostrar. Un valor que no se entiende vuelve tal cual: es texto para una
pantalla y nunca vale romperla (mismo criterio que `fechas.dia_legible`).
"""
from typing import Optional

import cuit

MESES_CORTOS = ("ene.", "feb.", "mar.", "abr.", "may.", "jun.", "jul.", "ago.",
                "sep.", "oct.", "nov.", "dic.")


def _numero(valor) -> Optional[float]:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def miles(valor, decimales: int = 0) -> str:
    """1583 -> «1.583»; con decimales, 1234.5 -> «1.234,50»."""
    n = _numero(valor)
    if n is None:
        return "" if valor is None else str(valor)
    texto = f"{abs(n):,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("-" if n < 0 and texto.strip("0,.") else "") + texto


def pesos(valor) -> str:
    """1.0 -> «$ 1,00»; -1200 -> «-$ 1.200,00». Ilegible -> «—», nunca «$ 0,00»."""
    n = _numero(valor)
    if n is None:
        return "—"
    return ("-" if n < 0 else "") + "$ " + miles(abs(n), 2)


def porcentaje(valor, decimales: int = 1) -> str:
    """2.5 -> «2,5%»; 21.0 -> «21%» (sin el ",0" que no dice nada)."""
    n = _numero(valor)
    if n is None:
        return "" if valor is None else str(valor)
    texto = miles(n, decimales)
    if "," in texto:
        texto = texto.rstrip("0").rstrip(",")
    return texto + "%"


def periodo_corto(periodo) -> str:
    """«2026-09» -> «sep. 2026»: el período de un recibo en una tabla."""
    partes = str(periodo or "").strip().split("-")
    if len(partes) != 2 or not partes[0].isdigit() or not partes[1].isdigit():
        return periodo or ""
    mes = int(partes[1])
    if not 1 <= mes <= 12:
        return periodo
    return f"{MESES_CORTOS[mes - 1]} {partes[0]}"


def cuil(valor) -> str:
    """«20480000917» -> «20-48000091-7». Solo al mostrar: se guarda igual."""
    return cuit.formatear(valor) if valor else ""


def _dia(iso: str) -> str:
    partes = (iso or "").strip().split("-")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return iso or ""
    return f"{partes[2]}/{partes[1]}/{partes[0]}"


def vigencia(desde, hasta) -> str:
    """La vigencia de una regla en castellano de persona (G4-11), en vez de
    «(sin inicio) → vigente»: «Siempre», «Desde el 01/03/2026», «Hasta el
    31/12/2026» o «Del 01/03 al 31/12/2026» (el año una sola vez si es el
    mismo). Si ya venció lo dice la pantalla con una pastilla aparte."""
    desde, hasta = (desde or "").strip(), (hasta or "").strip()
    if not desde and not hasta:
        return "Siempre"
    if not hasta:
        return f"Desde el {_dia(desde)}"
    if not desde:
        return f"Hasta el {_dia(hasta)}"
    d, h = _dia(desde), _dia(hasta)
    if desde[:4] == hasta[:4] and len(d) == 10:
        d = d[:5]
    return f"Del {d} al {h}"


def contar(n: int, singular: str, plural: str) -> str:
    """«1 recibo», «1.583 recibos»: el número con su palabra."""
    return f"{miles(n)} {singular if n == 1 else plural}"

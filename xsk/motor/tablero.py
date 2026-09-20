"""Arma el resumen que la página de avance muestra, a partir del registro de
un proyecto. **Puro**: no importa nada de la app; devuelve un dict listo para
serializar a JSON. La página (en el proyecto evaluado) es solo un lector de
esto, así que cuando XSK se extraiga a su repo, la página se reescribe pero
esta función viaja igual.

No incluye el cuerpo de los hallazgos (que son un manual de ataque hasta que
se corrigen): solo el encabezado que hace falta para el ranking y los
conteos. El detalle de un hallazgo se lee del archivo, no de acá.
"""

from __future__ import annotations

from . import registro


def _hallazgo_publico(h: dict) -> dict:
    """Los campos de un hallazgo que la página muestra, sin el cuerpo."""
    return {
        "id": h["id"], "titulo": h["titulo"], "eje": h["eje"],
        "eje_nombre": registro.EJES.get(h["eje"], h["eje"]),
        "test": h["test"], "estado": h["estado"],
        "riesgo": h["riesgo"], "nivel": h["nivel"],
        "probabilidad": h["probabilidad"], "dano": h["dano"],
        "complejidad": h["complejidad"],
        "owasp": h.get("owasp", ""), "cwe": h.get("cwe", ""),
        "archivo": h["archivo"],
    }


def tablero(nombre: str) -> dict:
    """Todo lo que la página de `/entornos/xsanders` necesita, serializable."""
    est = registro.estado_proyecto(nombre)
    catalogo = est["catalogo"]
    ultimo = est["ultimo_por_test"]

    # Catálogo por eje, con el último resultado de cada test si lo hay.
    por_eje: dict[str, list] = {e: [] for e in registro.EJES}
    for t in catalogo:
        u = ultimo.get(t["id"])
        por_eje[t["eje"]].append({
            "id": t["id"], "titulo": t["titulo"], "tipo": t["tipo"],
            "destructivo": t.get("destructivo", "no"),
            "owasp": t.get("owasp", ""), "asvs": t.get("asvs", ""),
            "cwe": t.get("cwe", ""),
            "resultado": u["resultado"] if u else "sin_correr",
            "fecha": u["fecha"] if u else "",
        })

    corridas = [{
        "fecha": c["fecha"], "eje": c["eje"], "entorno": c["entorno"],
        "iteracion": c.get("iteracion", ""),
        "conteo": _conteo_resultados(c["resultados"]),
        "archivo": c["archivo"],
    } for c in est["corridas"]]

    return {
        "proyecto": nombre,
        "avance": {
            "iteracion": est["avance"]["iteracion"],
            "etapa_actual": est["avance"]["etapa_actual"],
            "etapas": est["avance"]["etapas"],
            "como_seguir": est["avance"]["cuerpo"].split("## Cómo seguir")[-1].strip(),
        },
        "resumen": est["resumen"],
        "ranking": [_hallazgo_publico(h) for h in est["ranking"]],
        "bloquean": [_hallazgo_publico(h) for h in est["bloquean"]],
        "catalogo_por_eje": por_eje,
        "ejes": registro.EJES,
        "corridas": corridas,
        "puede_salir": len(est["bloquean"]) == 0,
    }


def _conteo_resultados(resultados: list[dict]) -> dict:
    conteo = {r: 0 for r in registro.RESULTADOS}
    for x in resultados:
        conteo[x["resultado"]] = conteo.get(x["resultado"], 0) + 1
    return conteo

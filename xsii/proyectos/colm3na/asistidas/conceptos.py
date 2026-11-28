"""Tarea asistida REC-04: el catálogo de conceptos, leído de los recibos de muestra.
Contrato: docs/xsii/API.md, «Bloque 4b».

A diferencia de Seccionales y el Padrón, la entrada NO es una planilla sino
recibos (`entrada: "recibos"`): la pantalla manda de a uno, la IA lo lee y
propone; la persona revisa, corrige o descarta cada concepto y recién ahí se
cargan, ya revisados (`pendiente_revision = False`). Nada entra sin que alguien lo
haya mirado (X28).

Este módulo es PURO respecto de la IA y de la red: la lectura del recibo la hace
`main` (`_leer_recibo_de_muestra`, la misma que usa la pestaña Aprendizaje) y acá
solo se arma la propuesta de lo que volvió, se valida lo que la persona aprobó y se
escribe. Las reglas de qué es un concepto nuevo y de cómo se da de alta son las de
`conceptos_carga`, compartidas con el panel.

Nada del recibo se guarda ni se devuelve: ni nombre, ni CUIL, ni importes. Lo único
que sale de acá hacia el movimiento son cantidades.
"""

from __future__ import annotations

import os
import unicodedata

from sqlmodel import select

import conceptos_carga
import cuit
from db import Concepto

from . import base
from .base import ErrorAsistida

ENTRADA = "recibos"
TOPE_MB = 8
FORMATOS = ["pdf", "jpg", "png", "webp"]
TOPE_CONCEPTOS = 500
TOPE_RECIBOS_LEIDOS = 5000
LARGO_CODIGO = 40
LARGO_DESCRIPCION = 120
SIN_DESCRIPCION = "(sin descripción)"        # lo que pone `validador.detectar_nuevos`

RUBROS = (
    ("haber", "Haber remunerativo"),
    ("no_remunerativo", "Haber no remunerativo"),
    ("descuento", "Descuento"),
)
CLAVES_RUBRO = {c for c, _ in RUBROS}
CATEGORIAS = (
    ("", "Ninguna"),
    ("afiliacion", "Cuota de afiliación (no cuenta para el tope del 2 %)"),
    ("convenio", "Aporte de convenio (cuenta para el tope del 2 %)"),
)
CLAVES_CATEGORIA = {c for c, _ in CATEGORIAS}


def _disponibilidad() -> dict:
    """`{disponible, simulada, motivo}`: sin clave de la API no hay lectura; con
    `MOCK_EXTRACTOR=1` se lee un recibo de mentira y se avisa."""
    if os.getenv("MOCK_EXTRACTOR") == "1":
        return {"disponible": True, "simulada": True,
                "motivo": "La lectura es simulada: no se llama a la IA y los conceptos son de ejemplo."}
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return {"disponible": True, "simulada": False, "motivo": ""}
    return {"disponible": False, "simulada": False,
            "motivo": "No hay clave de la API configurada: no se pueden leer recibos."}


def describir() -> dict:
    return {
        "titulo": "Conceptos desde los recibos de muestra",
        "entrada": ENTRADA,
        "que_voy_a_hacer": [
            "Leo cada recibo que subas y propongo los conceptos que todavía no están en el catálogo del sindicato: "
            "en esta etapa no se guarda nada.",
            "Vos revisás, corregís o descartás cada uno. Recién cuando confirmás se cargan, ya revisados, "
            "y controlo el resultado.",
        ],
        "archivos": {"por_envio": 1, "tope_mb": TOPE_MB, "formatos": list(FORMATOS),
                     "sugeridos": "30 a 60, de varios empleadores"},
        "ia": _disponibilidad(),
        "rubros": [{"clave": c, "rotulo": r} for c, r in RUBROS],
        "categorias_sindicales": [{"clave": c, "rotulo": r} for c, r in CATEGORIAS],
        "genericos": [],
        "tope_conceptos": TOPE_CONCEPTOS,
    }


def _genericos(s, sid: int) -> list:
    """Los conceptos genéricos del sindicato, leídos con la sesión del request."""
    return s.exec(select(Concepto).where(Concepto.sindicato_id == sid, Concepto.cuit_empleador == None)  # noqa: E711
                  .order_by(Concepto.codigo)).all()


def contexto(s, sid: int) -> dict:
    """Lo de describir() que sale de la base: los conceptos genéricos del sindicato
    (los que no son de un empleador), para «Corresponde a»."""
    return {"genericos": [{"codigo": c.codigo, "nombre": c.nombre} for c in _genericos(s, sid)]}


# ------------------------------------------------------------------ propuesta

def _rubro(p: dict) -> str:
    if p.get("tipo") == "descuento":
        return "descuento"
    return "haber" if p.get("remunerativo") else "no_remunerativo"


def _categoria_sugerida(p: dict, conceptos_actuales: list) -> str:
    """Solo para un descuento, y solo si el genérico al que parece corresponder ya
    dice qué categoría es: la IA no distingue la cuota de afiliación del aporte
    de convenio, así que no se adivina."""
    gen = p.get("generico_sugerido")
    if not gen or p["rubro"] != "descuento":
        return ""
    for c in conceptos_actuales:
        if c.get("codigo") == gen["codigo"] and not c.get("cuit_empleador"):
            cat = c.get("categoria_sindical") or ""
            return cat if cat in CLAVES_CATEGORIA else ""
    return ""


def _no_coinciden(p: dict) -> bool:
    seccion, tipo = p.get("seccion_leida"), p.get("tipo_leido")
    if seccion in ("haberes", "no_remunerativos"):
        return tipo == "aporte_trabajador"
    if seccion == "descuentos":
        return tipo == "remuneracion"
    return False


def _propuesta(p: dict, conceptos_actuales: list) -> dict:
    avisos, errores = [], []
    codigo = str(p.get("codigo") or "")
    descripcion = "" if p.get("descripcion") in (None, SIN_DESCRIPCION) else base.limpiar(p["descripcion"])
    cuit_empleador = p.get("cuit_empleador") or ""
    rubro = _rubro(p)
    dudosa = False
    if not codigo:
        errores.append("El recibo no trae un código para este concepto.")
    elif len(codigo) > LARGO_CODIGO:
        errores.append(f"El código tiene más de {LARGO_CODIGO} caracteres: cargalo a mano en Conceptos.")
    if cuit_empleador and not cuit.es_valido(cuit_empleador):
        errores.append("El CUIT del empleador no cumple el dígito verificador: se leyó mal. "
                       "Cargá el concepto a mano en Conceptos con el CUIT correcto.")
    if not descripcion:
        avisos.append("La descripción vino vacía: escribila antes de cargar.")
        dudosa = True
    elif len(descripcion) > LARGO_DESCRIPCION:
        descripcion = descripcion[:LARGO_DESCRIPCION].rstrip()
        avisos.append(f"La descripción era más larga que {LARGO_DESCRIPCION} caracteres y se recortó.")
    if p.get("similar"):
        sim = p["similar"]
        avisos.append(f"Se parece a un concepto que ya está: {sim['codigo']} ({sim['nombre']}).")
        dudosa = True
    if _no_coinciden(p):
        avisos.append("La sección del recibo y el tipo que leyó la IA no coinciden: revisá el rubro.")
        dudosa = True
    if p.get("reintegro"):
        avisos.append("Parece un reintegro: está impreso entre los descuentos con el signo contrario.")
        dudosa = True
    salida = {
        "clave": f"{codigo}|{cuit_empleador}", "codigo": codigo, "descripcion": descripcion,
        "cuit_empleador": cuit_empleador, "empleador_nombre": p.get("empleador_nombre") or "",
        "rubro": rubro, "categoria_sindical": "", "veces": int(p.get("veces") or 1),
        "similar": p.get("similar"),
        "generico_sugerido": ({"codigo": p["generico_sugerido"]["codigo"],
                               "nombre": p["generico_sugerido"]["nombre"]}
                              if p.get("generico_sugerido") else None),
        "estado": "rechazada" if errores else ("dudosa" if dudosa else "valida"),
        "avisos": avisos, "errores": errores,
    }
    salida["categoria_sindical"] = _categoria_sugerida({**p, "rubro": rubro}, conceptos_actuales)
    return salida


def armar_ensayo(conceptos_actuales: list, recibo: dict | None, nombre: str, motivo: str = "") -> dict:
    """La respuesta del ensayo de UN recibo: lo que se leyó (sin identidad ni importes)
    y los conceptos nuevos que propone. `recibo` None = no se pudo leer."""
    simulado = os.getenv("MOCK_EXTRACTOR") == "1"
    nombre = base.limpiar(nombre)[:120]
    if recibo is None:
        return {"recibo": {"nombre": nombre, "leido": False, "motivo": motivo or "No pude leer el recibo.",
                           "empleador_cuit": "", "empleador_nombre": "", "lineas": 0, "simulado": simulado},
                "propuestas": []}
    emp = recibo.get("empleador") or {}
    cuit_empleador = cuit.normalizar(emp.get("cuit")) or ""
    nombre_empleador = base.limpiar(emp.get("nombre"))[:120]
    lineas = [ln for ln in (recibo.get("lineas") or []) if isinstance(ln, dict)]
    propuestas = []
    for p in conceptos_carga.proponer(conceptos_actuales, [recibo], detalle=True):
        propuestas.append(_propuesta({**p, "empleador_nombre": nombre_empleador}, conceptos_actuales))
    return {"recibo": {"nombre": nombre, "leido": True, "motivo": "", "empleador_cuit": cuit_empleador,
                       "empleador_nombre": nombre_empleador, "lineas": len(lineas), "simulado": simulado},
            "propuestas": propuestas}


# ------------------------------------------------------------------ validación de la carga

_CAMPOS = ("codigo", "descripcion", "cuit_empleador", "rubro", "categoria_sindical", "codigo_generico")


def _texto(valor, campo: str, rotulo: str, minimo: int, maximo: int, mensajes: list, indice: int) -> str:
    if valor is None:
        valor = ""
    if not isinstance(valor, str):
        mensajes.append({"indice": indice, "campo": campo, "mensaje": f"{rotulo} tiene que ser un texto."})
        return ""
    if "\x00" in valor or any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in valor):
        mensajes.append({"indice": indice, "campo": campo,
                         "mensaje": f"{rotulo} tiene caracteres que no se pueden guardar."})
        return ""
    v = valor.strip()
    if not (minimo <= len(v) <= maximo):
        faltante = "no puede estar vacío" if minimo and not v else f"tiene que tener de {minimo} a {maximo} caracteres"
        mensajes.append({"indice": indice, "campo": campo, "mensaje": f"{rotulo} {faltante}."})
    return v


def validar_carga(datos, codigos_genericos: set) -> tuple:
    """`(aprobados, recibos_leidos)`: lo que la persona revisó, validado ítem por ítem
    y todo o nada. Un error levanta `ErrorAsistida(400)` con `.detalle`, la lista de
    `{indice, campo, mensaje}` de lo que no pasó. `codigos_genericos` son los códigos
    de los conceptos genéricos del sindicato (para «Corresponde a»)."""
    if not isinstance(datos, dict):
        raise ErrorAsistida(400, "El cuerpo tiene que ser un objeto.")
    conceptos = datos.get("conceptos")
    if not isinstance(conceptos, list) or not conceptos:
        raise ErrorAsistida(400, "No hay conceptos para cargar.")
    if len(conceptos) > TOPE_CONCEPTOS:
        raise ErrorAsistida(400, f"Se pueden cargar hasta {base.miles(TOPE_CONCEPTOS)} conceptos por vez.")
    leidos = datos.get("recibos_leidos", 0)
    if isinstance(leidos, bool) or not isinstance(leidos, int) or not 0 <= leidos <= TOPE_RECIBOS_LEIDOS:
        raise ErrorAsistida(400, f"La cantidad de recibos leídos tiene que ser un número entero de 0 a "
                                 f"{base.miles(TOPE_RECIBOS_LEIDOS)}.")
    mensajes, aprobados, vistos = [], [], set()
    for i, c in enumerate(conceptos):
        antes = len(mensajes)
        if not isinstance(c, dict):
            mensajes.append({"indice": i, "campo": "", "mensaje": "El concepto tiene que ser un objeto."})
            continue
        codigo = _texto(c.get("codigo"), "codigo", "El código", 1, LARGO_CODIGO, mensajes, i)
        descripcion = _texto(c.get("descripcion"), "descripcion", "La descripción", 1, LARGO_DESCRIPCION, mensajes, i)
        cuit_crudo = c.get("cuit_empleador")
        cuit_texto = _texto(cuit_crudo, "cuit_empleador", "El CUIT del empleador", 0, 30, mensajes, i)
        cuit_norm = cuit.normalizar(cuit_texto)
        if cuit_texto and (not cuit_norm or not cuit.es_valido(cuit_norm)):
            mensajes.append({"indice": i, "campo": "cuit_empleador",
                             "mensaje": "El CUIT del empleador no cumple el dígito verificador."})
        rubro = c.get("rubro")
        if rubro not in CLAVES_RUBRO:
            mensajes.append({"indice": i, "campo": "rubro", "mensaje": "El rubro no es válido."})
        categoria = c.get("categoria_sindical") or ""
        if not isinstance(categoria, str) or categoria not in CLAVES_CATEGORIA:
            mensajes.append({"indice": i, "campo": "categoria_sindical", "mensaje": "La categoría sindical no es válida."})
        elif categoria and rubro != "descuento":
            mensajes.append({"indice": i, "campo": "categoria_sindical",
                             "mensaje": "La categoría sindical solo vale para un descuento."})
        generico = _texto(c.get("codigo_generico"), "codigo_generico", "El concepto al que corresponde", 0,
                          LARGO_CODIGO, mensajes, i)
        if generico:
            if not cuit_norm:
                mensajes.append({"indice": i, "campo": "codigo_generico",
                                 "mensaje": "«Corresponde a» solo vale para un concepto de un empleador."})
            elif generico not in codigos_genericos:
                mensajes.append({"indice": i, "campo": "codigo_generico",
                                 "mensaje": "El concepto genérico elegido no existe en este sindicato."})
        clave = (codigo, cuit_norm)
        if codigo and clave in vistos:
            mensajes.append({"indice": i, "campo": "codigo",
                             "mensaje": "Este concepto está repetido en la lista (mismo código y mismo empleador)."})
        vistos.add(clave)
        if len(mensajes) > antes:
            continue
        aprobados.append({
            "codigo": codigo, "descripcion": descripcion,
            "tipo": "descuento" if rubro == "descuento" else "ingreso",
            "remunerativo": rubro == "haber",
            "cuit_empleador": cuit_norm, "codigo_generico": generico,
            "categoria_sindical": categoria,
        })
    if mensajes:
        e = ErrorAsistida(400, f"Hay {base.plural(len({m['indice'] for m in mensajes}), 'concepto', 'conceptos')} "
                               f"con datos que no sirven: corregilos y volvé a cargar.")
        e.detalle = mensajes[:50]
        raise e
    return aprobados, leidos


def cargar(s, sid: int, datos) -> dict:
    """Valida todo y escribe en la sesión (sin commit). Devuelve
    `{cargados, repetidos, recibos_leidos}`. Si no se cargó ninguno (todos ya
    existían) el que llama decide qué hacer: acá no se escribió nada."""
    genericos = {c.codigo for c in _genericos(s, sid)}
    aprobados, leidos = validar_carga(datos, genericos)
    r = conceptos_carga.aplicar(s, sid, aprobados)
    return {"cargados": r["altas"], "repetidos": r["repetidos"], "recibos_leidos": leidos}


def movimiento(carga: dict) -> tuple:
    """`(texto, cantidades)` del movimiento `asistida_carga`: solo cantidades."""
    texto = (f"Cargó {base.plural(carga['cargados'], 'concepto', 'conceptos')} desde "
             f"{base.plural(carga['recibos_leidos'], 'recibo leído', 'recibos leídos')} "
             f"({carga['repetidos']} ya existían)")
    return texto, {k: carga[k] for k in ("cargados", "repetidos", "recibos_leidos")}

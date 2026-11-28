# -*- coding: utf-8 -*-
"""Bloque 5 de XSII: los hitos de la Mesa enlazados a tareas (`docs/xsii/API.md`).

Los hitos (`ImplHito`) son texto libre por proyecto. Acá se lee lo que hace falta
para vincularlos con las tareas del catálogo, se calcula cuáles se PROPONEN
marcar (todas sus tareas enlazadas resueltas) y se arma el JSON de la pantalla.
Quien tilda el hito en la Mesa es siempre una persona del equipo: XSII solo propone.

No importa `vista` (que importa este módulo): trabaja sobre el `Contexto` que
recibe, que ya trae `hitos_datos` leído con la sesión del request.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from sqlmodel import select

import db

from .catalogo import TAREAS

POR_CODIGO = {t.codigo: t for t in TAREAS}
ARCHIVO_SUGERIDOS = Path(__file__).resolve().parents[3] / "data" / "xsii" / "hitos_sugeridos.json"


def normalizar(texto) -> str:
    """Minúsculas y sin tildes, para comparar frases."""
    n = unicodedata.normalize("NFD", (texto or "").lower())
    return " ".join("".join(c for c in n if not unicodedata.combining(c)).split())


_cache: dict = {}


def sugerencias_definidas() -> list:
    """Las sugerencias del archivo, con las frases ya normalizadas. Una entrada mal
    formada se descarta (la pantalla no se cae por un JSON a medio editar)."""
    if "lista" not in _cache:
        try:
            crudo = json.loads(ARCHIVO_SUGERIDOS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            crudo = []
        lista = []
        for e in crudo if isinstance(crudo, list) else []:
            frases = e.get("texto_contiene") if isinstance(e, dict) else None
            tareas = e.get("tareas") if isinstance(e, dict) else None
            if (isinstance(frases, list) and frases and all(isinstance(f, str) and f.strip() for f in frases)
                    and isinstance(tareas, list) and tareas and all(isinstance(c, str) for c in tareas)):
                lista.append({"frases": [normalizar(f) for f in frases],
                              "tareas": [c for c in tareas if c in POR_CODIGO]})
        _cache["lista"] = lista
    return _cache["lista"]


def sugeridas_para(texto_hito: str) -> list:
    """Los códigos de tarea que las sugerencias proponen para un hito, sin repetir y en orden."""
    n = normalizar(texto_hito)
    salida: list = []
    for e in sugerencias_definidas():
        if all(f in n for f in e["frases"]):
            salida.extend(c for c in e["tareas"] if c not in salida)
    return salida


# ------------------------------------------------------------------ lectura (con la sesión)

def cargar(s, pid: int) -> dict:
    """Todo lo que hace falta de la Mesa y del registro para armar los hitos de UN
    proyecto, como datos simples (sin objetos de la sesión)."""
    etapas = [{"id": e.id, "nombre": e.nombre, "orden": e.orden} for e in db.impl_etapas(s, pid)]
    filas = s.exec(select(db.ImplHito.id, db.ImplHito.codigo, db.ImplHito.etapa_id, db.ImplHito.texto,
                          db.ImplHito.orden, db.ImplHito.hecho, db.ImplHito.hecho_por, db.ImplHito.hecho_en)
                   .where(db.ImplHito.proyecto_id == pid).order_by(db.ImplHito.orden, db.ImplHito.id)).all()
    hitos = [{"id": i, "codigo": c, "etapa_id": e, "texto": t, "hecho": bool(h), "hecho_por": hp, "hecho_en": he}
             for i, c, e, t, _o, h, hp, he in filas]
    enlaces: dict = {}
    for hid, codigo in db.xsii_hitos_activos(s, pid):
        enlaces.setdefault(hid, []).append(codigo)
    return {"etapas": etapas, "hitos": hitos, "enlaces": enlaces}


# ------------------------------------------------------------------ cálculo

def _estado_tarea(ctx, codigo: str) -> str:
    e = ctx.tb.get(codigo) if ctx.tb else None
    return e.estado if e is not None else ""


def _tarea_json(ctx, codigo: str) -> dict:
    estado = _estado_tarea(ctx, codigo)
    return {"codigo": codigo, "nombre": POR_CODIGO[codigo].nombre, "estado": estado,
            "resuelta": estado == "hecha"}


def _porque(tareas: list) -> str:
    activas = [t for t in tareas if t["estado"] != "no_aplica"]
    if len(activas) == 1:
        return f"{activas[0]['codigo']} ({activas[0]['nombre']}) está hecha."
    return f"Las {len(activas)} tareas enlazadas están hechas: " + ", ".join(t["codigo"] for t in activas) + "."


def _no_propuesto(h: dict, tareas: list) -> str:
    """Por qué un hito enlazado y todavía sin marcar no se propone (vacío si se propone)."""
    if h["hecho"]:
        return "El hito ya está marcado como hecho en la Mesa."
    if not tareas:
        return "El hito no tiene tareas enlazadas."
    activas = [t for t in tareas if t["estado"] != "no_aplica"]
    if not activas:
        return "Las tareas enlazadas no aplican a este sindicato: no hay nada que respalde el hito."
    faltan = [t["codigo"] for t in activas if not t["resuelta"]]
    if faltan:
        return "Todavía faltan tareas: " + ", ".join(faltan) + "."
    return ""


def _hito(ctx, h: dict, con_sugeridas: bool) -> dict:
    enlazadas = ctx.hitos_datos["enlaces"].get(h["id"], [])
    tareas = [_tarea_json(ctx, c) for c in enlazadas]
    motivo = _no_propuesto(h, tareas)
    propuesto = not h["hecho"] and bool(tareas) and not motivo
    salida = {"id": h["id"], "codigo": h["codigo"], "texto": h["texto"], "hecho": h["hecho"],
              "hecho_por": h["hecho_por"], "hecho_en": h["hecho_en"], "tareas": tareas,
              "propuesto": propuesto, "porque": _porque(tareas) if propuesto else ""}
    if con_sugeridas:
        salida["sugeridas"] = [{"codigo": c, "nombre": POR_CODIGO[c].nombre}
                               for c in sugeridas_para(h["texto"]) if c not in enlazadas]
    return salida


def todos(ctx) -> list:
    """Los hitos del proyecto como JSON, en el orden de la Mesa (se calcula una vez por contexto)."""
    if getattr(ctx, "_hitos_json", None) is None:
        ctx._hitos_json = [_hito(ctx, h, True) for h in ctx.hitos_datos["hitos"]]
    return ctx._hitos_json


def hito_json(ctx, hito_id: int) -> dict | None:
    return next((h for h in todos(ctx) if h["id"] == hito_id), None)


def hitos_json(ctx) -> dict:
    """`GET .../hitos`: por fase, con el resumen."""
    lista = todos(ctx)
    por_etapa: dict = {}
    for h, datos in zip(lista, ctx.hitos_datos["hitos"]):
        por_etapa.setdefault(datos["etapa_id"], []).append(h)
    fases = [{"etapa": e["nombre"], "hitos": por_etapa.get(e["id"], [])} for e in ctx.hitos_datos["etapas"]]
    return {"fases": fases, "resumen": resumen(ctx)}


def resumen(ctx) -> dict:
    lista = todos(ctx)
    return {"total": len(lista), "hechos": sum(1 for h in lista if h["hecho"]),
            "enlazados": sum(1 for h in lista if h["tareas"]),
            "propuestos": sum(1 for h in lista if h["propuesto"]),
            "sugerencias": sum(len(h["sugeridas"]) for h in lista)}


def resumen_tablero(ctx) -> dict:
    r = resumen(ctx)
    return {"propuestos": r["propuestos"], "sugerencias": r["sugerencias"]}


def de_la_tarea(ctx, codigo: str) -> list:
    """Los hitos enlazados a la tarea, sin las sugeridas (van en la ficha)."""
    return [{k: v for k, v in h.items() if k != "sugeridas"} for h in todos(ctx)
            if any(t["codigo"] == codigo for t in h["tareas"])]


def pares_a_aceptar(ctx, hitos=None) -> list:
    """[(hito_id, codigo, nombre)] de las sugeridas de esos hitos (todos si `hitos` es None)."""
    quiero = None if hitos is None else set(hitos)
    return [(h["id"], x["codigo"], x["nombre"]) for h in todos(ctx)
            if quiero is None or h["id"] in quiero for x in h["sugeridas"]]


def para_preguntame(ctx) -> dict:
    """Lo que lee «Preguntame»: código, estado y tareas, NUNCA el texto libre del hito."""
    salida = []
    for h in todos(ctx):
        estado = ("hecho" if h["hecho"] else "propuesto" if h["propuesto"]
                  else "pendiente" if h["tareas"] else "sin enlazar")
        salida.append({"codigo": h["codigo"], "estado": estado,
                       "tareas": [{"codigo": t["codigo"], "nombre": t["nombre"], "estado": t["estado"]}
                                  for t in h["tareas"]]})
    return {"hitos": salida, "cantidad": len(salida), "resumen": resumen(ctx)}


def revalidar(ctx, hito_id: int) -> tuple:
    """`(frase, codigos)` para marcar el hito con un contexto RECIÉN armado: la frase
    del conflicto (vacía si sigue propuesto) y los códigos de las tareas que lo respaldan."""
    h = hito_json(ctx, hito_id)
    if h is None:
        return "No existe ese hito en la Mesa de este proyecto.", []
    if not h["propuesto"]:
        return _no_propuesto(h, h["tareas"]) or "El hito ya no se propone.", []
    return "", [t["codigo"] for t in h["tareas"] if t["estado"] != "no_aplica"]

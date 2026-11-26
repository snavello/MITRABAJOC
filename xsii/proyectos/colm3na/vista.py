"""La vista del tablero de XSII (bloque 1): arma el JSON que lee la pantalla
(`docs/xsii/API.md`) y decide qué se puede hacer con cada tarea.

NO es puro: lee la base. Recibe la sesión del request (regla del proyecto: una
sesión por request, ningún helper abre la suya) y no escribe nada salvo en
`decidir`, `deshacer`, `registrar_insumo` y `retirar_insumo`, que llaman a las
funciones `xsii_*` de db.py. `main.py` solo enruta.

Las reglas de «se puede o no» de cada decisión viven en UNA función
(`regla_de_decision`) que usan tanto `acciones` como el POST.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import select

import db
import fechas
import implementacion
import modulos
from xsii.motor import consulta, estados
from xsii.motor.catalogo import MODOS

from . import tablero as tablero_mod
from .catalogo import GRUPOS, INSUMOS, TAREAS

POR_CODIGO = {t.codigo: t for t in TAREAS}

ROTULOS = {
    "estados": {"hecha": "Hecha", "lista": "Se puede hacer", "en_curso": "En curso",
                "esperando": "Esperando un dato", "bloqueada": "Bloqueada", "no_aplica": "No aplica"},
    "modos": {"asistida": "Asistida", "herramienta": "Con herramienta",
              "aplicacion": "Por la aplicación", "manual": "Manual", "automatica": "Automática"},
    "decisiones": dict(db.XSII_ROTULOS_DECISION),
}

# Lo que dice `como` según el modo: en el bloque 1 todavía no hay asistente.
COMO = {
    "asistida": "Se hace en la pantalla de siempre; acá controlo el resultado.",
    "herramienta": "Se hace con la herramienta indicada; acá controlo el resultado.",
    "aplicacion": "Se hace en la pantalla de siempre; acá controlo el resultado.",
    "manual": "La hace una persona fuera del sistema; acá queda registrada.",
    "automatica": "La hace el sistema sola; acá se controla el resultado.",
}

_SECCIONES_ADMIN = {
    "trabajadores": "Trabajadores", "seccionales": "Seccionales", "administradores": "Áreas y Usuarios",
    "aprendizaje": "Aprendizaje", "formulas": "Reglas", "conceptos": "Conceptos",
    "empleadores": "Empleadores", "listas": "Listas", "apariencia": "Apariencia",
    "noticias": "Noticias", "beneficios": "Beneficios", "notificaciones": "Notificaciones",
    "convenio": "Convenio", "encuestas": "Encuestas", "tramites": "Trámites", "reportes": "Reportes",
}
_HERRAMIENTAS = {"convenio-escalas": "Convenio y escalas", "asistente-tramites": "Asistente de trámites",
                 "calculadora-bancaria": "Calculadora bancaria"}


class NoDisponible(Exception):
    """El proyecto no tiene un sindicato de Colm3na al que mirar."""


# ------------------------------------------------------------------ pequeñas

def _cuando_a_dias(cuando: str) -> int | None:
    try:
        return max(0, (fechas.hoy() - date.fromisoformat((cuando or "")[:10])).days)
    except ValueError:
        return None


def _pedido_texto(dias: int | None) -> str:
    """«pedido hoy», «pedido ayer» o «pedido hace N días»."""
    if dias is None:
        return "pedido"
    if dias == 0:
        return "pedido hoy"
    if dias == 1:
        return "pedido ayer"
    return f"pedido hace {dias} días"


DIAS_DEMORADO = 2


def _lista_y(nombres: list) -> str:
    if len(nombres) <= 1:
        return "".join(nombres)
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def donde_de(url: str | None, pid: int) -> dict | None:
    """`{"url", "rotulo"}` de la pantalla de una tarea, o None si no tiene."""
    if not url:
        return None
    base, _, ancla = url.partition("#")
    if base == "/plataforma":
        rotulo = "Plataforma"
    elif base == "/admin":
        rotulo = "Panel del sindicato" + (f" · {_SECCIONES_ADMIN.get(ancla, ancla.capitalize())}" if ancla else "")
    elif base.startswith("/entornos/herramientas/"):
        nombre = base.rsplit("/", 1)[-1]
        rotulo = "Herramientas · " + _HERRAMIENTAS.get(nombre, nombre.replace("-", " ").capitalize())
    elif base == "/app":
        rotulo = "App del afiliado"
    elif base == "/implementacion":
        rotulo, url = "Mesa de implementación", f"/implementacion?p={pid}"
    else:
        rotulo = base
    return {"url": url, "rotulo": rotulo}


def _niveles() -> dict:
    nivel: dict = {}
    for t in TAREAS:           # el catálogo valida que no hay ciclos; se recorre con memo
        def n(c):
            if c not in nivel:
                dep = POR_CODIGO[c].necesita
                nivel[c] = 0 if not dep else 1 + max(n(d) for d in dep)
            return nivel[c]
        n(t.codigo)
    return nivel


NIVELES = _niveles()
NECESITADA_POR = {t.codigo: [x.codigo for x in TAREAS if t.codigo in x.necesita] for t in TAREAS}


# ------------------------------------------------------------------ contexto

class Contexto:
    """Todo lo que hace falta para armar la vista de UN proyecto: se carga una
    vez por request, con la sesión que ya tiene la ruta."""

    def __init__(self, s, pid: int):
        self.proyecto = db.impl_proyecto(s, pid)
        if self.proyecto is None:
            raise LookupError(pid)
        self.pid = self.proyecto.id
        self.sindicato = s.get(db.Sindicato, self.proyecto.sindicato_id) if self.proyecto.sindicato_id else None
        self.sindicato_nombre = self.sindicato.nombre if self.sindicato else None
        self.sindicato_id = self.proyecto.sindicato_id
        self.proyecto_nombre = self.proyecto.nombre
        self.tareas, self.tb = [], {}
        # Primero lo que lee la sesión, después los controles (un control que
        # falla hace rollback y expira lo que quedó cargado). Decisiones e
        # insumos se leen siempre: un insumo se puede pedir antes del alta.
        self.decisiones = db.xsii_decisiones_activas(s, self.pid)
        self.insumos = {k: _InsumoPlano(i) for k, i in db.xsii_insumos_activos(s, self.pid).items()}
        self.tarjetas = {i: _TarjetaPlana(t) for i, t in db.xsii_tarjetas(
            s, self.pid, [x.tarjeta_id for x in self.insumos.values()]).items()}
        if self.sindicato is None:
            return
        recibidos = {k: True for k, i in self.insumos.items() if i.estado == "recibido"}
        self.tareas, self.tb = tablero_mod.armar(
            s, self.sindicato.id, decisiones=self.decisiones, insumos=recibidos)

    @property
    def disponible(self) -> bool:
        return self.sindicato is not None

    @property
    def motivo_no_disponible(self) -> str:
        if self.proyecto.sindicato_id is None:
            return "Este proyecto todavía no tiene un sindicato asociado en Colm3na: no hay nada que controlar."
        return "El sindicato de este proyecto ya no existe en Colm3na: no hay nada que controlar."


class _InsumoPlano:
    """El registro de un insumo como datos simples (no objeto de la sesión)."""
    def __init__(self, i):
        self.clave, self.estado, self.tarjeta_id = i.clave, i.estado, i.tarjeta_id
        self.nota, self.quien, self.cuando = i.nota, i.quien_nombre, i.cuando


class _TarjetaPlana:
    def __init__(self, t):
        self.id, self.codigo, self.titulo, self.estado = t.id, t.codigo, t.titulo, t.estado


# ------------------------------------------------------------------ reglas

def _tipos_activos(ctx: Contexto, codigo: str) -> list:
    return [d["tipo"] for d in ctx.decisiones.get(codigo, [])]


def conflicto_entre_decisiones(tipo: str, activos) -> str:
    """La frase del conflicto entre `tipo` y las decisiones ya activas, o vacío.
    Lo que depende solo de las decisiones (no del estado calculado): se revalida
    adentro del candado de la tarea al escribir."""
    rot = db.XSII_ROTULOS_DECISION.get(tipo, tipo)
    if tipo in activos:
        return f"Ya hay una decisión «{rot}» activa en esta tarea."
    if tipo == "no_aplica" and "completada_a_mano" in activos:
        return "La tarea está completada a mano: deshacé eso antes de declararla no aplicable."
    if tipo == "completada_a_mano" and "no_aplica" in activos:
        return "Esta tarea no aplica: no hace falta completarla."
    return ""


def regla_de_decision(ctx: Contexto, codigo: str, tipo: str) -> tuple[bool, str]:
    """¿Se puede registrar la decisión `tipo` en la tarea ahora? `(True, "")` o
    `(False, frase)`. La única fuente de la tabla de reglas del contrato: la usan
    `acciones` (qué botones) y el POST (409 con esta misma frase)."""
    t, e = POR_CODIGO[codigo], ctx.tb[codigo]
    activos = _tipos_activos(ctx, codigo)
    if (frase := conflicto_entre_decisiones(tipo, activos)):
        return False, frase
    if tipo == "confirmada":
        if not t.confirmacion:
            return False, "Esta tarea no lleva confirmación."
        if e.estado == "no_aplica":
            return False, "Esta tarea no aplica: no hay nada que confirmar."
        if not (e.control and e.control.pasa):
            return False, "Todavía no se puede confirmar: el control de la tarea no pasa."
        if e.insumos_faltantes:
            return False, "Primero registrá que llegó el insumo."
    elif tipo == "completada_a_mano":
        if e.estado == "no_aplica":
            return False, "Esta tarea no aplica: no hace falta completarla."
        if e.estado == "hecha" and not e.a_mano:
            return False, "El control ya da esta tarea por hecha."
    elif tipo == "no_aplica":
        if e.no_aplica_por == "condicion":
            return False, "La tarea ya no aplica: " + _por_que_no_aplica(t)
    elif tipo == "pospuesta":
        if e.resuelta:
            return False, "La tarea ya está resuelta: no hace falta posponerla."
    else:
        return False, "El tipo de decisión no es válido."
    return True, ""


def _por_que_no_aplica(t) -> str:
    nombre = modulos.MODULOS.get(t.aplica_si, t.aplica_si)
    return f"el módulo «{nombre}» no está contratado."


def acciones_de(ctx: Contexto, codigo: str) -> dict:
    return {"confirmar": regla_de_decision(ctx, codigo, "confirmada")[0],
            "completar_a_mano": regla_de_decision(ctx, codigo, "completada_a_mano")[0],
            "no_aplica": regla_de_decision(ctx, codigo, "no_aplica")[0],
            "posponer": regla_de_decision(ctx, codigo, "pospuesta")[0],
            "deshacer": [x for x in db.XSII_DECISIONES if x in _tipos_activos(ctx, codigo)]}


# ------------------------------------------------------------------ JSON

def _tarjeta_json(ctx: Contexto, tarjeta_id) -> dict | None:
    t = ctx.tarjetas.get(tarjeta_id) if tarjeta_id else None
    if not t:
        return None
    return {"id": t.id, "codigo": t.codigo, "titulo": t.titulo, "estado": t.estado,
            "url": f"/implementacion?p={ctx.pid}"}


def insumo_json(ctx: Contexto, clave: str, sin_registrar: bool = False) -> dict:
    meta = INSUMOS[clave]
    reg = ctx.insumos.get(clave)
    dias = _cuando_a_dias(reg.cuando) if reg and reg.estado == "pedido" else None
    return {"clave": clave, "nombre": meta["nombre"], "descripcion": meta["descripcion"],
            "estado": reg.estado if reg else "falta",
            "sin_registrar": bool(sin_registrar and reg is None),
            "dias": dias, "nota": reg.nota if reg else "",
            "quien": reg.quien if reg else "", "cuando": reg.cuando if reg else "",
            "tarjeta": _tarjeta_json(ctx, reg.tarjeta_id) if reg else None}


def _cifras(c) -> list:
    return [{"clave": k, "nombre": (k.replace("_", " ").capitalize()), "valor": v}
            for k, v in (c.cifras or {}).items()]


def _detalle(ctx: Contexto, t, e) -> str:
    if e.estado == "no_aplica":
        if e.no_aplica_por == "condicion":
            return f"Módulo {modulos.MODULOS.get(t.aplica_si, t.aplica_si)} no contratado"
        motivo = (e.decision or {}).get("motivo") or ""
        return "Declarada no aplica" + (f": {motivo}" if motivo else "")
    if e.estado == "hecha" and e.a_mano:
        d = e.decision or {}
        return f"Completada a mano por {d.get('quien') or '?'}" + (f": {d['motivo']}" if d.get("motivo") else "")
    if e.estado == "bloqueada":
        return "Espera a " + _lista_y([POR_CODIGO[c].nombre for c in e.frenada_por])
    if e.estado == "esperando":
        partes = []
        for clave in e.insumos_faltantes:
            texto = INSUMOS[clave]["nombre"]
            reg = ctx.insumos.get(clave)
            if reg and reg.estado == "pedido":
                tj = ctx.tarjetas.get(reg.tarjeta_id)
                extra = _pedido_texto(_cuando_a_dias(reg.cuando))
                texto += f"; {extra}" + (f" ({tj.codigo})" if tj else "")
            partes.append(texto)
        return "Falta: " + " · ".join(partes)
    if e.falta_confirmar:
        return "Falta confirmar: " + (e.confirmacion or "")
    return e.control.resumen if e.control else ""


def tarea_json(ctx: Contexto, codigo: str) -> dict:
    t, e = POR_CODIGO[codigo], ctx.tb[codigo]
    c = e.control
    sin_registrar = e.estado != "no_aplica" and c is not None and estados.datos_cargados(t, c)
    return {
        "codigo": t.codigo, "nombre": t.nombre, "grupo": t.grupo, "modo": t.modo,
        "descripcion": t.descripcion, "aplica_si": t.aplica_si,
        "estado": e.estado, "con_observaciones": e.con_observaciones, "a_mano": e.a_mano,
        "pospuesta": e.pospuesta, "no_aplica_por": e.no_aplica_por,
        "falta_confirmar": e.falta_confirmar, "confirmacion": t.confirmacion,
        "detalle": _detalle(ctx, t, e),
        "necesita": list(t.necesita), "mejora_con": list(t.mejora_con),
        "frenada_por": [] if e.resuelta else list(e.frenada_por), "avisos": list(e.avisos),
        "camino": [] if e.resuelta else consulta.que_frena(ctx.tareas, ctx.tb, codigo),
        "necesitada_por": list(NECESITADA_POR[codigo]),
        "destraba": consulta.que_destraba(ctx.tareas, ctx.tb, codigo),
        "nivel": NIVELES[codigo],
        "donde": donde_de(t.donde, ctx.pid),
        "control": ({"estado": c.estado, "resumen": c.resumen, "cifras": _cifras(c),
                     "faltan": list(c.faltan), "en_curso": c.en_curso} if c else None),
        "decisiones": [dict(d) for d in ctx.decisiones.get(codigo, [])],
        "insumos": [insumo_json(ctx, k, sin_registrar) for k in t.insumos],
        "acciones": acciones_de(ctx, codigo),
    }


def _movimiento_json(m) -> dict:
    return {"id": m.id, "codigo": m.codigo, "tipo": m.tipo, "texto": m.texto,
            "cantidades": dict(m.cantidades or {}), "quien": m.quien_nombre, "cuando": m.cuando}


def _recomendada(ctx: Contexto) -> dict | None:
    codigo = consulta.recomendada(ctx.tareas, ctx.tb)
    if codigo is None:
        return None
    t, e = POR_CODIGO[codigo], ctx.tb[codigo]
    n = len(consulta.que_destraba(ctx.tareas, ctx.tb, codigo)["transitivo"])
    if e.falta_confirmar:
        por_que = "Solo falta que la confirmes."
    elif e.estado == "en_curso":
        por_que = "Ya está empezada: conviene terminarla."
    elif n >= 2:
        por_que = f"Es la que más destraba: {n} tareas dependen de esta."
    elif n == 1:
        por_que = "Destraba una tarea que depende de esta."
    else:
        por_que = "Se puede hacer ya y no frena a nadie."
    return {"codigo": codigo, "por_que": por_que, "destraba": n, "como": COMO[t.modo]}


def _demorados(ctx: Contexto) -> list:
    salida = []
    for clave, reg in ctx.insumos.items():
        if reg.estado != "pedido" or clave not in INSUMOS:
            continue
        tareas = [t for t in TAREAS if clave in t.insumos and not ctx.tb[t.codigo].resuelta]
        if not tareas:
            continue
        t = tareas[0]
        dias = _cuando_a_dias(reg.cuando)
        if dias is None or dias < DIAS_DEMORADO:
            continue
        frena = max(len(consulta.que_destraba(ctx.tareas, ctx.tb, x.codigo)["transitivo"]) for x in tareas) + 1
        salida.append({"clave": clave, "nombre": INSUMOS[clave]["nombre"], "codigo": t.codigo,
                       "dias": dias, "tarjeta": ({"codigo": tj["codigo"], "titulo": tj["titulo"]}
                                                       if (tj := _tarjeta_json(ctx, reg.tarjeta_id)) else None),
                       "frena": frena})
    salida.sort(key=lambda d: -d["dias"])
    return salida


def tablero_json(s, ctx: Contexto) -> dict:
    movs = [_movimiento_json(m) for m in db.xsii_movimientos(s, ctx.pid, limite=8)]
    salida = {
        "proyecto": {"id": ctx.pid, "nombre": ctx.proyecto_nombre, "sindicato_id": ctx.sindicato_id,
                     "sindicato_nombre": ctx.sindicato_nombre, "mesa_url": f"/implementacion?p={ctx.pid}"},
        "disponible": ctx.disponible, "motivo": "" if ctx.disponible else ctx.motivo_no_disponible,
        "grupos": list(GRUPOS), "rotulos": ROTULOS,
        "resumen": None, "recomendada": None, "alternativas": [], "demorados": [], "tareas": [],
        "movimientos": movs,
    }
    if ctx.disponible:
        salida.update({
            "resumen": consulta.resumen(ctx.tb), "recomendada": _recomendada(ctx),
            "alternativas": consulta.alternativas(ctx.tareas, ctx.tb), "demorados": _demorados(ctx),
            "tareas": [tarea_json(ctx, t.codigo) for t in TAREAS]})
    return salida


def ficha_json(s, ctx: Contexto, codigo: str) -> dict:
    t = POR_CODIGO[codigo]
    historial = db.xsii_movimientos(s, ctx.pid, codigo=codigo, claves_insumo=t.insumos, limite=50)
    return {"tarea": tarea_json(ctx, codigo), "historial": [_movimiento_json(m) for m in historial]}


def movimientos_json(s, ctx: Contexto, codigo: str = "", limite: int = 50) -> dict:
    t = POR_CODIGO.get(codigo)
    movs = db.xsii_movimientos(s, ctx.pid, codigo=codigo, claves_insumo=(t.insumos if t else ()), limite=limite)
    return {"movimientos": [_movimiento_json(m) for m in movs]}


def proyectos_json(s) -> dict:
    nombres = {i: n for i, n in s.exec(select(db.Sindicato.id, db.Sindicato.nombre)).all()}
    return {"proyectos": [{"id": p.id, "nombre": p.nombre, "activo": p.activo,
                           "sindicato_id": p.sindicato_id,
                           "sindicato_nombre": nombres.get(p.sindicato_id) if p.sindicato_id else None}
                          for p in db.impl_proyectos(s)]}


# ------------------------------------------------------------------ escrituras

def _exigir_disponible(ctx: Contexto) -> None:
    if not ctx.disponible:
        raise db.XsiiError(409, ctx.motivo_no_disponible)


def decidir(s, ctx: Contexto, actor, codigo: str, tipo: str, motivo) -> None:
    """Registra la decisión si las reglas lo permiten. Levanta `XsiiError`
    (400 dato inválido, 409 la regla no se cumple)."""
    if tipo not in db.XSII_DECISIONES:
        raise db.XsiiError(400, "El tipo de decisión no es válido.")
    _exigir_disponible(ctx)
    db.xsii_motivo(motivo, tipo in db.XSII_MOTIVO_OBLIGATORIO)
    puede, frase = regla_de_decision(ctx, codigo, tipo)
    if not puede:
        raise db.XsiiError(409, frase)
    db.xsii_decidir(s, ctx.pid, actor, codigo, POR_CODIGO[codigo].nombre, tipo, motivo,
                    revalidar=lambda activos: conflicto_entre_decisiones(tipo, activos))


def deshacer(s, ctx: Contexto, actor, codigo: str, tipo: str, motivo) -> None:
    if tipo not in db.XSII_DECISIONES:
        raise db.XsiiError(400, "El tipo de decisión no es válido.")
    _exigir_disponible(ctx)
    db.xsii_deshacer(s, ctx.pid, actor, codigo, POR_CODIGO[codigo].nombre, tipo, motivo)


def registrar_insumo(s, ctx: Contexto, actor, clave: str, estado: str, tarjeta, nota) -> None:
    """`tarjeta`: código o id de una tarjeta de la Mesa de ESTE proyecto, o vacío.
    No exige sindicato: un insumo se puede pedir antes del alta."""
    tarjeta_id = None
    if tarjeta not in (None, ""):
        t = db.impl_tarjeta_por_codigo_o_id(s, ctx.pid, tarjeta)
        if t is None:
            raise db.XsiiError(400, "No encontré esa tarjeta en la Mesa de este proyecto.")
        tarjeta_id = t.id
    db.xsii_registrar_insumo(s, ctx.pid, actor, clave, INSUMOS[clave]["nombre"], estado, tarjeta_id, nota)


def retirar_insumo(s, ctx: Contexto, actor, clave: str) -> None:
    db.xsii_retirar_insumo(s, ctx.pid, actor, clave, INSUMOS[clave]["nombre"])

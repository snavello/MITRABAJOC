"""De hechos a estado de cada tarea.

El estado NO se guarda: se calcula cada vez a partir de lo que dicen los
controles (la realidad), las condiciones (módulos contratados), los insumos
recibidos y las decisiones de las personas. Así el asistente no puede
equivocarse sobre el avance (principio 1 del plan).

Precedencia (X14, X15 y «Estados» del plan), en este orden:
no_aplica → hecha → bloqueada → esperando → en_curso → lista.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONTROLES = ("completa", "observaciones", "incompleta")
ESTADOS = ("no_aplica", "hecha", "bloqueada", "esperando", "en_curso", "lista")
DECISIONES = ("completada_a_mano", "no_aplica", "pospuesta", "confirmada")


@dataclass(frozen=True)
class Control:
    """Lo que devuelve el control de una tarea.

    `estado`: completa / observaciones (pasa, con avisos) / incompleta.
    `resumen`: una frase para la persona. `cifras`: nombre → número.
    `faltan`: textos de lo que falta. `en_curso`: hay avance parcial."""
    estado: str
    resumen: str = ""
    cifras: dict = field(default_factory=dict)
    faltan: list = field(default_factory=list)
    en_curso: bool = False

    def __post_init__(self):
        if self.estado not in CONTROLES:
            raise ValueError(f"Estado de control inválido: {self.estado!r}.")

    @property
    def pasa(self) -> bool:
        return self.estado in ("completa", "observaciones")


@dataclass(frozen=True)
class EstadoTarea:
    codigo: str
    estado: str
    con_observaciones: bool = False      # hecha, pero el control pasó con avisos
    a_mano: bool = False                 # hecha por decisión de una persona (X15)
    control: Control | None = None       # el control calculado, siempre expuesto
    frenada_por: list = field(default_factory=list)       # dependencias duras sin resolver
    insumos_faltantes: list = field(default_factory=list)
    avisos: list = field(default_factory=list)            # dependencias blandas sin resolver
    pospuesta: bool = False
    decision: dict | None = None
    # El control pasa pero falta que una persona confirme `confirmacion`.
    falta_confirmar: bool = False
    confirmacion: str | None = None
    # Por qué no aplica: "condicion" (módulo apagado) o "decision" (declarada
    # por una persona, con quién y motivo en `decision`). "" si aplica.
    no_aplica_por: str = ""

    @property
    def resuelta(self) -> bool:
        """Cumple una dependencia dura: está hecha o no aplica."""
        return self.estado in ("hecha", "no_aplica")


def _aplica(tarea, hechos) -> bool:
    clave = tarea.aplica_si
    if clave is None:
        return True
    condiciones = hechos.get("aplica") or {}
    if clave not in condiciones:
        # Si no se informa, no se adivina: ocultar una tarea por un olvido
        # sería un «no aplica» silencioso.
        raise ValueError(f"{tarea.codigo}: la condición {clave!r} no fue informada en hechos['aplica'].")
    return bool(condiciones[clave])


def resolver(tareas, hechos: dict) -> dict:
    """{codigo: EstadoTarea}, en el orden del catálogo.

    `hechos`: `controles` {codigo: Control}, `aplica` {condición: bool},
    `insumos` {clave: recibido}, `decisiones` {codigo: {tipo, quien, cuando,
    motivo}} y `ensayos_abiertos` (set de códigos).

    Dos pasadas. La primera fija lo que no depende de nadie (no aplica,
    hecha): el estado «hecha» se calcula de la realidad aunque alguna
    dependencia no esté hecha. La segunda, sobre el resto, mira qué las frena.
    """
    tareas = list(tareas)
    controles = hechos.get("controles") or {}
    insumos = hechos.get("insumos") or {}
    decisiones = hechos.get("decisiones") or {}
    ensayos = set(hechos.get("ensayos_abiertos") or ())

    def control_de(t) -> Control:
        c = controles.get(t.codigo)
        if c is None:
            return Control("incompleta", "Todavía no hay un control calculado.",
                           faltan=["Sin control calculado"])
        return c

    primera: dict[str, EstadoTarea] = {}
    for t in tareas:
        c = control_de(t)
        d = decisiones.get(t.codigo)
        d_tipo = (d or {}).get("tipo")
        if d is not None and d_tipo not in DECISIONES:
            raise ValueError(f"{t.codigo}: decisión inválida {d_tipo!r}.")
        if not _aplica(t, hechos):
            primera[t.codigo] = EstadoTarea(t.codigo, "no_aplica", control=c, decision=d,
                                            no_aplica_por="condicion")
        elif d_tipo == "no_aplica":
            primera[t.codigo] = EstadoTarea(t.codigo, "no_aplica", control=c, decision=d,
                                            no_aplica_por="decision")
        elif c.pasa and (not t.confirmacion or d_tipo == "confirmada"):
            primera[t.codigo] = EstadoTarea(
                t.codigo, "hecha", con_observaciones=(c.estado == "observaciones"),
                control=c, decision=d, confirmacion=t.confirmacion)
        elif d_tipo == "completada_a_mano":
            primera[t.codigo] = EstadoTarea(t.codigo, "hecha", a_mano=True, control=c, decision=d,
                                            confirmacion=t.confirmacion)

    salida: dict[str, EstadoTarea] = {}
    for t in tareas:
        if t.codigo in primera:
            salida[t.codigo] = primera[t.codigo]
            continue
        c = control_de(t)
        d = decisiones.get(t.codigo)
        pospuesta = (d or {}).get("tipo") == "pospuesta"
        frenada = [dep for dep in t.necesita if dep not in primera]
        avisos = [dep for dep in t.mejora_con if dep not in primera]
        faltan_insumos = [i for i in t.insumos if not insumos.get(i)]
        # Pasó el control pero nadie confirmó (si estuviera confirmada, ya
        # estaría hecha): no destraba a nadie hasta que se confirme.
        falta_confirmar = c.pasa and bool(t.confirmacion)
        con_avance = c.en_curso or t.codigo in ensayos or (falta_confirmar and not t.solo_confirmacion)
        if frenada:
            estado = "bloqueada"
        elif faltan_insumos:
            estado = "esperando"
        elif con_avance:
            estado = "en_curso"
        else:
            estado = "lista"
        salida[t.codigo] = EstadoTarea(
            t.codigo, estado, control=c,
            frenada_por=frenada if estado == "bloqueada" else [],
            insumos_faltantes=faltan_insumos if estado == "esperando" else [],
            avisos=avisos, pospuesta=pospuesta, decision=d,
            falta_confirmar=falta_confirmar,
            confirmacion=t.confirmacion if falta_confirmar else None)
    return salida

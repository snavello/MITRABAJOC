"""De hechos a estado de cada tarea.

El estado NO se guarda: se calcula cada vez a partir de lo que dicen los
controles (la realidad), las condiciones (módulos contratados), los insumos
recibidos y las decisiones de las personas. Así el asistente no puede
equivocarse sobre el avance (principio 1 del plan).

Precedencia (X14, X15 y «Estados» del plan), en este orden:
no_aplica → hecha → bloqueada → esperando → en_curso → lista.

Una tarea puede tener VARIAS decisiones activas a la vez (como mucho una por
tipo): `pospuesta` es una marca que no cambia el estado y convive con las
demás; las otras tres son las que pueden resolver la tarea.
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
    # La decisión que DETERMINA el estado (no_aplica, completada_a_mano o
    # confirmada), o None; `decisiones` es la lista de todas las activas.
    decision: dict | None = None
    decisiones: list = field(default_factory=list)
    # Insumos sin registrar que NO frenan la tarea porque el control ya muestra
    # datos cargados: la pantalla avisa «hay datos; el insumo no está registrado».
    insumos_sin_registrar: list = field(default_factory=list)
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


def _lista_de(d) -> list:
    """Las decisiones de una tarea como lista: acepta una lista, un dict suelto
    (una sola decisión) o nada."""
    if d is None:
        return []
    if isinstance(d, dict):
        return [d]
    return list(d)


def datos_cargados(tarea, control: Control) -> bool:
    """El control ya muestra datos que permiten calcular la tarea aunque un
    insumo no esté registrado: hay avance parcial o pasa. En una tarea
    `solo_confirmacion` el control no calcula nada, así que no cuenta."""
    return bool(control.en_curso or (control.pasa and not tarea.solo_confirmacion))


def resolver(tareas, hechos: dict) -> dict:
    """{codigo: EstadoTarea}, en el orden del catálogo.

    `hechos`: `controles` {codigo: Control}, `aplica` {condición: bool},
    `insumos` {clave: recibido}, `decisiones` {codigo: [{tipo, quien, cuando,
    motivo}, ...]} (las activas; también se acepta un dict suelto por código)
    y `ensayos_abiertos` (set de códigos).

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

    def decisiones_de(t) -> list:
        lista = _lista_de(decisiones.get(t.codigo))
        for d in lista:
            if d.get("tipo") not in DECISIONES:
                raise ValueError(f"{t.codigo}: decisión inválida {d.get('tipo')!r}.")
        return lista

    def de_tipo(lista, tipo):
        return next((d for d in lista if d.get("tipo") == tipo), None)

    primera: dict[str, EstadoTarea] = {}
    for t in tareas:
        c = control_de(t)
        ds = decisiones_de(t)
        pospuesta = de_tipo(ds, "pospuesta") is not None
        no_aplica = de_tipo(ds, "no_aplica")
        confirmada = de_tipo(ds, "confirmada")
        a_mano = de_tipo(ds, "completada_a_mano")
        if not _aplica(t, hechos):
            primera[t.codigo] = EstadoTarea(t.codigo, "no_aplica", control=c, decisiones=ds,
                                            pospuesta=pospuesta, no_aplica_por="condicion")
        elif no_aplica is not None:
            primera[t.codigo] = EstadoTarea(t.codigo, "no_aplica", control=c, decision=no_aplica,
                                            decisiones=ds, pospuesta=pospuesta, no_aplica_por="decision")
        elif c.pasa and (not t.confirmacion or confirmada is not None):
            primera[t.codigo] = EstadoTarea(
                t.codigo, "hecha", con_observaciones=(c.estado == "observaciones"),
                control=c, decision=confirmada, decisiones=ds, pospuesta=pospuesta,
                confirmacion=t.confirmacion)
        elif a_mano is not None:
            primera[t.codigo] = EstadoTarea(t.codigo, "hecha", a_mano=True, control=c, decision=a_mano,
                                            decisiones=ds, pospuesta=pospuesta,
                                            confirmacion=t.confirmacion)

    salida: dict[str, EstadoTarea] = {}
    for t in tareas:
        if t.codigo in primera:
            salida[t.codigo] = primera[t.codigo]
            continue
        c = control_de(t)
        ds = decisiones_de(t)
        pospuesta = de_tipo(ds, "pospuesta") is not None
        frenada = [dep for dep in t.necesita if dep not in primera]
        avisos = [dep for dep in t.mejora_con if dep not in primera]
        sin_insumo = [i for i in t.insumos if not insumos.get(i)]
        # Un insumo sin registrar no deja «esperando un dato» a una tarea cuyo
        # control ya muestra datos cargados: se calcula como si estuviera.
        sin_registrar = sin_insumo if datos_cargados(t, c) else []
        faltan_insumos = [i for i in sin_insumo if i not in sin_registrar]
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
            avisos=avisos, pospuesta=pospuesta, decision=None, decisiones=ds,
            insumos_sin_registrar=sin_registrar,
            falta_confirmar=falta_confirmar,
            confirmacion=t.confirmacion if falta_confirmar else None)
    return salida

"""Un control por tarea del catálogo de Colm3na (PLAN_XSII.md, principio 1:
el estado se calcula, no se declara).

Cada función recibe `(s, sindicato_id)`, donde `s` es una sesión SQLModel YA
ABIERTA: regla del proyecto, un request tiene UNA sesión y ningún helper abre
la suya. Las consultas son agregadas y nunca traen columnas de bytes (para
saber si hay logo o contrato se pregunta por `octet_length`).

Tres clases de control (plan):
- **calculado**: sale de contar en la base.
- **confirmado**: lo afirma una persona. Sin una confirmación registrada, el
  control dice `incompleta` con «Falta confirmar»; las confirmaciones llegan
  por `decisiones` en el bloque 1 (hoy no hay tabla donde guardarlas).
- **mixto**: lo calculado manda; lo que además hay que confirmar se lista
  como observación («pasa, con avisos») y no frena.

Un control nunca escribe y nunca falla por datos raros: si no puede saber,
dice que falta algo.
"""

from __future__ import annotations

from sqlalchemy import func, text
from sqlmodel import select

import correo
import cuit as cuit_mod
import fechas
import modulos
import temas
import validador
from db import (
    Area, Beneficio, CampoTramite, Concepto, CuentaPanel, DocumentoConvenio,
    Empleador, Encuesta, Formula, GrillaSalarial, ListaSindicato, Noticia,
    Notificacion, PermisoArea, ReciboVerificado, Seccional, Sindicato,
    TipoTramite, TopeBaseImponible, Tramite, Trabajador, UsuarioSindicato,
    DestinoTipoTramite, ImplProyecto, ImplTarjeta,
)
from xsii.motor.estados import Control

FALTA_CONFIRMAR = "Falta confirmar"

# Los tres aportes de ley que crea el alta del sindicato (`db.crear_conceptos_universales`).
CODIGOS_DE_LEY = tuple(c["codigo"] for c in validador.CONCEPTOS_UNIVERSALES)

# «Al menos N» formularios publicados (TRA-01): hoy, uno.
MINIMO_FORMULARIOS = 1


# ------------------------------------------------------------------ ayudas

def _n(s, consulta) -> int:
    """El entero de una consulta de conteo."""
    return int(s.exec(consulta).one() or 0)


def _completa(resumen, cifras=None) -> Control:
    return Control("completa", resumen, cifras or {})


def _con_avisos(resumen, avisos, cifras=None) -> Control:
    return Control("observaciones", resumen, cifras or {}, faltan=list(avisos))


def _incompleta(resumen, faltan, cifras=None, en_curso=False) -> Control:
    return Control("incompleta", resumen, cifras or {}, faltan=list(faltan), en_curso=en_curso)


def _por_confirmar(resumen, cifras=None) -> Control:
    """Un control puramente confirmado, sin confirmación registrada."""
    return Control("incompleta", resumen, cifras or {}, faltan=[FALTA_CONFIRMAR])


def _sindicato(s, sid):
    """Columnas livianas del sindicato (sin bytes); None si no existe."""
    return s.execute(select(
        Sindicato.nombre, Sindicato.cuit, Sindicato.modulos_habilitados,
        Sindicato.color_base, Sindicato.color_primario, Sindicato.color_acento,
        Sindicato.color_secundario, Sindicato.clausula_confidencialidad,
        Sindicato.convenio_grilla,
        func.coalesce(func.octet_length(Sindicato.logo_datos), 0),
        func.coalesce(func.octet_length(Sindicato.contrato_datos), 0),
    ).where(Sindicato.id == sid)).first()


def _plural(n, uno, varios) -> str:
    return f"{n} {uno if n == 1 else varios}"


# -------------------------------------------------------------------- Base

def bas_01(s, sid) -> Control:
    fila = _sindicato(s, sid)
    if not fila:
        return _incompleta("El sindicato no existe.", ["Dar de alta el sindicato"])
    faltan = []
    if not (fila[0] or "").strip():
        faltan.append("Falta el nombre del sindicato")
    if not (fila[1] or "").strip():
        faltan.append("Falta el CUIT del sindicato")
    elif not cuit_mod.es_valido(fila[1], cuit_mod.EMPRESA):
        faltan.append("El CUIT del sindicato no es válido")
    if faltan:
        return _incompleta("La ficha del sindicato está incompleta.", faltan)
    return _completa("El sindicato está dado de alta, con nombre y CUIT válido.")


def bas_02(s, sid) -> Control:
    fila = _sindicato(s, sid)
    if not fila:
        return _incompleta("El sindicato no existe.", ["Dar de alta el sindicato"])
    logo = int(fila[9] or 0)
    if not logo:
        return _incompleta("Falta cargar el logo.", ["Cargar el logo del sindicato"],
                           {"logo": 0})
    avisos = [a["aviso"] for a in temas.prueba_de_lectura(fila[3], fila[4], fila[5], fila[6])]
    if avisos:
        return _con_avisos("Logo cargado; algunos colores se leen mal.", avisos,
                           {"logo": 1, "avisos_de_lectura": len(avisos)})
    return _completa("Logo cargado y colores legibles.", {"logo": 1, "avisos_de_lectura": 0})


def bas_03(s, sid) -> Control:
    fila = _sindicato(s, sid)
    habilitados = [m for m in ((fila[2] if fila else None) or []) if m in modulos.MODULOS]
    return _por_confirmar(
        "Los módulos contratados los confirma el equipo.",
        {"modulos_habilitados": len(habilitados), "modulos_del_catalogo": len(modulos.MODULOS)})


def bas_04(s, sid) -> Control:
    # La bandera de clave transitoria vive en la CUENTA de la persona
    # (CuentaPanel), no en la fila del usuario: ver CLAUDE.md, «Alta de
    # administradores y clave inicial».
    filas = s.execute(
        select(CuentaPanel.debe_cambiar_clave)
        .select_from(UsuarioSindicato)
        .join(CuentaPanel, CuentaPanel.cuil == UsuarioSindicato.cuil)
        .where(UsuarioSindicato.sindicato_id == sid,
               UsuarioSindicato.activo == True,           # noqa: E712
               UsuarioSindicato.es_super_admin == True)   # noqa: E712
    ).all()
    activos = _n(s, select(func.count()).select_from(UsuarioSindicato).where(
        UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.activo == True,   # noqa: E712
        UsuarioSindicato.es_super_admin == True))                               # noqa: E712
    con_clave_propia = sum(1 for f in filas if not f[0])
    cifras = {"super_admins_activos": activos, "con_clave_propia": con_clave_propia}
    if con_clave_propia:
        return _completa("Hay un administrador que ya eligió su clave.", cifras)
    if activos:
        return _incompleta("El administrador todavía no eligió su clave.",
                           ["Entrar al panel y elegir la clave propia"], cifras, en_curso=True)
    return _incompleta("No hay ningún administrador.",
                       ["Crear el primer administrador del sindicato"], cifras)


def bas_05(s, sid) -> Control:
    canal = 1 if correo.habilitado() else 0
    resumen = "La política de registro la confirma el equipo."
    return Control("incompleta", resumen, {"canal_de_mail": canal},
                   faltan=[FALTA_CONFIRMAR] + ([] if canal else ["El canal de mail está apagado en este entorno"]))


def bas_06(s, sid) -> Control:
    fila = _sindicato(s, sid)
    if not fila:
        return _incompleta("El sindicato no existe.", ["Dar de alta el sindicato"])
    contrato, clausula = int(fila[10] or 0) > 0, bool(fila[7])
    cifras = {"contrato": int(contrato), "clausula": int(clausula)}
    if contrato and clausula:
        return _completa("Contrato cargado y cláusula marcada.", cifras)
    faltan = []
    if not contrato:
        faltan.append("Cargar el contrato firmado")
    if not clausula:
        faltan.append("Marcar la cláusula de confidencialidad")
    return _incompleta("Falta el contrato o la cláusula.", faltan, cifras, en_curso=contrato or clausula)


# ------------------------------------------------------------- Estructura

def est_01(s, sid) -> Control:
    total = _n(s, select(func.count()).select_from(Seccional).where(Seccional.sindicato_id == sid))
    sede = _n(s, select(func.count()).select_from(Seccional).where(
        Seccional.sindicato_id == sid, Seccional.ve_todas == True))   # noqa: E712
    cifras = {"seccionales": total, "con_alcance_total": sede}
    if not total:
        return _incompleta("Todavía no hay seccionales.", ["Cargar las seccionales (y Sede Central)"], cifras)
    # Mixto: lo calculado alcanza; que la lista coincida con la del sindicato
    # es una confirmación que todavía no se puede registrar.
    avisos = ["Falta confirmar la lista contra la del sindicato"]
    if not sede:
        avisos.append("Ninguna seccional ve todas las demás (Sede Central)")
    return _con_avisos(f"Hay {_plural(total, 'seccional', 'seccionales')}.", avisos, cifras)


def est_02(s, sid) -> Control:
    filas = s.execute(select(Seccional.precision_geo, Seccional.latitud).where(
        Seccional.sindicato_id == sid)).all()
    total = len(filas)
    if not total:
        return _incompleta("No hay seccionales para ubicar.", ["Cargar las seccionales primero"],
                           {"seccionales": 0, "ubicadas": 0})
    sin_ubicar = sum(1 for p, lat in filas if lat is None or p == "sin_geo")
    aproximadas = sum(1 for p, lat in filas if lat is not None and p == "aproximada")
    cifras = {"seccionales": total, "sin_ubicar": sin_ubicar, "aproximadas": aproximadas,
              "ubicadas": total - sin_ubicar}
    if sin_ubicar:
        return _incompleta(f"{sin_ubicar} de {total} seccionales sin ubicar.",
                           ["Ubicar las seccionales pendientes en el mapa"], cifras,
                           en_curso=sin_ubicar < total)
    if aproximadas:
        return _con_avisos("Todas ubicadas; algunas de forma aproximada.",
                           [f"{aproximadas} con ubicación aproximada (el globo no está en la puerta)"], cifras)
    return _completa("Todas las seccionales están ubicadas.", cifras)


def est_03(s, sid) -> Control:
    areas = s.execute(select(Area.id, Area.nombre).where(
        Area.sindicato_id == sid, Area.activo == True)).all()    # noqa: E712
    cifras = {"areas_activas": len(areas)}
    if not areas:
        return _incompleta("Todavía no hay áreas.", ["Crear las áreas con sus permisos"], cifras)
    con_permiso = {r[0] for r in s.execute(select(PermisoArea.area_id).where(
        PermisoArea.area_id.in_([a[0] for a in areas])).distinct()).all()}
    sin = [a[1] for a in areas if a[0] not in con_permiso]
    cifras["sin_permisos"] = len(sin)
    if sin:
        return _incompleta(f"{_plural(len(sin), 'área sin permisos', 'áreas sin permisos')}.",
                           [f"Dar permisos al área «{n}»" for n in sin[:10]], cifras,
                           en_curso=len(sin) < len(areas))
    return _completa("Todas las áreas activas tienen permisos.", cifras)


def est_04(s, sid) -> Control:
    areas = s.execute(select(Area.id, Area.nombre).where(
        Area.sindicato_id == sid, Area.activo == True)).all()    # noqa: E712
    if not areas:
        return _incompleta("No hay áreas con usuarios.", ["Crear las áreas primero"],
                           {"areas_activas": 0})
    # Las que RECIBEN trámites: destino por defecto o mapeadas por seccional.
    recibe = {r[0] for r in s.execute(
        select(TipoTramite.area_destino_default_id).where(
            TipoTramite.sindicato_id == sid, TipoTramite.area_destino_default_id.is_not(None))).all()}
    recibe |= {r[0] for r in s.execute(
        select(DestinoTipoTramite.area_id).select_from(DestinoTipoTramite).join(
            TipoTramite, TipoTramite.id == DestinoTipoTramite.tipo_tramite_id).where(
            TipoTramite.sindicato_id == sid)).all()}
    # Sin formularios todavía, se exige un usuario en cada área activa.
    exigidas = [a for a in areas if a[0] in recibe] if recibe else list(areas)
    con_usuario = {r[0] for r in s.execute(select(UsuarioSindicato.area_id).where(
        UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.activo == True,   # noqa: E712
        UsuarioSindicato.area_id.is_not(None)).distinct()).all()}
    sin = [a[1] for a in exigidas if a[0] not in con_usuario]
    transitorias = _n(s, select(func.count()).select_from(UsuarioSindicato).join(
        CuentaPanel, CuentaPanel.cuil == UsuarioSindicato.cuil).where(
        UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.activo == True,   # noqa: E712
        UsuarioSindicato.area_id.is_not(None), CuentaPanel.debe_cambiar_clave == True))  # noqa: E712
    cifras = {"areas_exigidas": len(exigidas), "areas_sin_usuario": len(sin),
              "usuarios_con_clave_transitoria": transitorias}
    if sin:
        return _incompleta(f"{_plural(len(sin), 'área sin usuario', 'áreas sin usuario')}.",
                           [f"Dar de alta un usuario en «{n}»" for n in sin[:10]], cifras,
                           en_curso=len(sin) < len(exigidas))
    if transitorias:
        return _con_avisos("Cada área tiene usuario; algunos no eligieron su clave.",
                           [f"{transitorias} usuarios todavía con la clave inicial"], cifras)
    return _completa("Cada área que recibe trámites tiene un usuario activo.", cifras)


# ---------------------------------------------------------------- Recibos

def rec_01(s, sid) -> Control:
    # Los recibos de muestra no entran al sistema (diferencia 1 del plan): se
    # reciben por la Mesa y lo confirma el equipo.
    return _por_confirmar("Que llegaron los recibos de muestra lo confirma el equipo.")


def rec_02(s, sid) -> Control:
    conceptos = {r[0] for r in s.execute(select(Concepto.codigo).where(
        Concepto.sindicato_id == sid, Concepto.cuit_empleador.is_(None),
        Concepto.codigo.in_(CODIGOS_DE_LEY))).all()}
    reglas = {r[0] for r in s.execute(select(Formula.target).where(
        Formula.sindicato_id == sid, Formula.activa == True,     # noqa: E712
        Formula.target.in_(CODIGOS_DE_LEY))).all()}
    cifras = {"conceptos_de_ley": len(conceptos), "reglas_de_ley": len(reglas),
              "esperados": len(CODIGOS_DE_LEY)}
    faltan = [f"{c}: " + ("falta el concepto" if c not in conceptos else "falta la regla")
              for c in CODIGOS_DE_LEY if c not in conceptos or c not in reglas]
    if faltan:
        return _incompleta("Faltan aportes de ley.", faltan, cifras,
                           en_curso=bool(conceptos or reglas))
    return _completa("Jubilación, PAMI y obra social están con sus reglas.", cifras)


def rec_03(s, sid) -> Control:
    cuotas = s.execute(select(Concepto.codigo).where(
        Concepto.sindicato_id == sid, Concepto.tipo == "descuento",
        Concepto.categoria_sindical == "afiliacion", Concepto.cuit_empleador.is_(None))).all()
    solidarios = _n(s, select(func.count()).select_from(Concepto).where(
        Concepto.sindicato_id == sid, Concepto.categoria_sindical == "convenio",
        Concepto.cuit_empleador.is_(None)))
    codigos = [c[0] for c in cuotas]
    con_regla = 0
    if codigos:
        con_regla = len({r[0] for r in s.execute(select(Formula.target).where(
            Formula.sindicato_id == sid, Formula.activa == True,     # noqa: E712
            Formula.target.in_(codigos))).all()})
    cifras = {"conceptos_de_afiliacion": len(codigos), "con_regla": con_regla,
              "conceptos_solidarios": solidarios}
    if not codigos:
        return _incompleta("No hay un concepto de cuota sindical.",
                           ["Crear el concepto de afiliación"], cifras)
    if not con_regla:
        return _incompleta("La cuota sindical no tiene regla.",
                           ["Cargar la regla de control de la cuota"], cifras, en_curso=True)
    return _completa("La cuota sindical tiene su concepto y su regla.", cifras)


def rec_04(s, sid) -> Control:
    propios = _n(s, select(func.count()).select_from(Concepto).where(
        Concepto.sindicato_id == sid, Concepto.codigo.not_in(CODIGOS_DE_LEY)))
    pendientes = _n(s, select(func.count()).select_from(Concepto).where(
        Concepto.sindicato_id == sid, Concepto.pendiente_revision == True))    # noqa: E712
    cifras = {"conceptos": propios, "pendientes_de_revision": pendientes}
    if not propios:
        return _incompleta("No hay conceptos de los recibos de muestra.",
                           ["Leer los recibos de muestra con Aprendizaje"], cifras)
    if pendientes:
        return _incompleta(f"{_plural(pendientes, 'concepto pendiente', 'conceptos pendientes')} de revisión.",
                           ["Revisar los conceptos pendientes"], cifras,
                           en_curso=pendientes < propios)
    return _completa("Ningún concepto está pendiente de revisión.", cifras)


def rec_05(s, sid) -> Control:
    reglas = s.execute(select(Formula.id, Formula.target, Formula.expr, Formula.tolerancia,
                              Formula.fecha_desde, Formula.fecha_hasta).where(
        Formula.sindicato_id == sid, Formula.activa == True)).all()    # noqa: E712
    propias = [r for r in reglas if r[1] not in CODIGOS_DE_LEY]
    cifras = {"reglas": len(reglas), "reglas_propias": len(propias)}
    if not propias:
        return _incompleta("Solo están las reglas de los aportes de ley.",
                           ["Cargar las reglas de control de los conceptos del sindicato"], cifras)
    rotas = [r for r in reglas if validador.error_de_expresion(r[2])]
    altas = [r for r in reglas if validador.texto_tolerancia_alta(r[3])]
    superpuestas = set()
    por_regla: dict = {}
    for r in reglas:
        por_regla.setdefault(r[1], []).append(r)
    for grupo in por_regla.values():
        for i, a in enumerate(grupo):
            for b in grupo[i + 1:]:
                if validador.rangos_se_superponen(a[4], a[5], b[4], b[5]):
                    superpuestas.add(a[1])
    cifras.update({"con_error": len(rotas), "tolerancia_alta": len(altas),
                   "con_vigencias_superpuestas": len(superpuestas)})
    faltan = ([f"La regla de {r[1]} no evalúa" for r in rotas]
              + [f"Vigencias superpuestas en {t}" for t in sorted(superpuestas)])
    if faltan:
        return _incompleta("Hay reglas con problemas.", faltan, cifras, en_curso=True)
    if altas:
        return _con_avisos("Las reglas evalúan; algunas tienen tolerancia alta.",
                           [f"Tolerancia alta en {r[1]} ($ {r[3]:,.0f})".replace(",", ".") for r in altas], cifras)
    return _completa("Todas las reglas evalúan y no se pisan.", cifras)


def rec_06(s, sid) -> Control:
    # Los topes son de plataforma, no del sindicato. Se controla que haya uno
    # vigente hoy y que cubra los períodos de los recibos ya verificados; los
    # de la muestra (REC-01) no están en el sistema todavía.
    topes = s.execute(select(TopeBaseImponible.vigencia_desde, TopeBaseImponible.estado)).all()
    cifras = {"topes_cargados": len(topes)}
    if not topes:
        return _incompleta("No hay topes de base imponible cargados.",
                           ["Cargar los topes en plataforma"], cifras)
    hoy = fechas.hoy().strftime("%Y-%m")
    vigente = max((t for t in topes if t[0] <= hoy), key=lambda t: t[0], default=None)
    if vigente is None:
        return _incompleta("No hay un tope vigente para el período actual.",
                           ["Cargar el tope vigente en plataforma"], cifras)
    primero = min(t[0] for t in topes)
    menor = s.exec(select(func.min(ReciboVerificado.periodo)).where(
        ReciboVerificado.sindicato_id == sid, ReciboVerificado.periodo != "")).one()
    if menor and menor[:7] < primero:
        return _incompleta("Hay recibos de períodos sin tope cargado.",
                           [f"Cargar topes desde {menor[:7]}"], cifras)
    if vigente[1] not in ("verificado", "derivado"):
        return _con_avisos("Hay tope vigente, pero no está verificado.",
                           [f"El tope vigente desde {vigente[0]} figura como «{vigente[1]}»"], cifras)
    return _completa("Hay tope de base imponible vigente.", cifras)


def rec_07(s, sid) -> Control:
    # Diferencia 1 del plan: hoy no existe una puerta de control para el
    # equipo (validar un lote de muestra sin identidad). Hasta que se
    # construya (bloque 4), no hay de dónde calcularlo.
    return _por_confirmar("Todavía no existe la puerta para validar el lote de muestra sin identidad.")


def rec_08(s, sid) -> Control:
    fila = _sindicato(s, sid)
    convenio = (fila[8] if fila else "") or ""
    if not convenio:
        return _incompleta("El sindicato no tiene un convenio asignado.",
                           ["Asignar el convenio en la ficha del sindicato"], {"convenio_asignado": 0})
    publicadas = _n(s, select(func.count()).select_from(GrillaSalarial).where(
        GrillaSalarial.convenio == convenio, GrillaSalarial.estado == "publicada"))
    cifras = {"convenio_asignado": 1, "grillas_publicadas": publicadas}
    if not publicadas:
        return _incompleta("No hay una grilla salarial publicada.",
                           ["Publicar la grilla del convenio"], cifras)
    return _completa("Convenio asignado y grilla publicada.", cifras)


# ----------------------------------------------------------------- Padrón

def pad_01(s, sid) -> Control:
    return _por_confirmar("Que llegó la planilla del padrón, con su total declarado, lo confirma el equipo.")


def pad_02(s, sid) -> Control:
    activos = _n(s, select(func.count()).select_from(Trabajador).where(
        Trabajador.sindicato_id == sid, Trabajador.activo == True))    # noqa: E712
    sin_seccional = _n(s, select(func.count()).select_from(Trabajador).where(
        Trabajador.sindicato_id == sid, Trabajador.activo == True,     # noqa: E712
        Trabajador.seccional_id.is_(None)))
    hay_seccionales = _n(s, select(func.count()).select_from(Seccional).where(
        Seccional.sindicato_id == sid)) > 0
    cifras = {"afiliados_activos": activos, "sin_seccional": sin_seccional}
    if not activos:
        return _incompleta("El padrón está vacío.", ["Cargar el padrón"], cifras)
    avisos = ["Falta confirmar la cantidad contra el total declarado por el sindicato"]
    if hay_seccionales and sin_seccional:
        avisos.append(f"{_plural(sin_seccional, 'afiliado sin seccional', 'afiliados sin seccional')}")
    return _con_avisos(f"Hay {_plural(activos, 'afiliado cargado', 'afiliados cargados')}.", avisos, cifras)


def pad_03(s, sid) -> Control:
    activos = _n(s, select(func.count()).select_from(Trabajador).where(
        Trabajador.sindicato_id == sid, Trabajador.activo == True))    # noqa: E712
    if not activos:
        return _incompleta("No hay padrón para ubicar.", ["Cargar el padrón primero"],
                           {"afiliados_activos": 0, "pendientes_de_ubicar": 0})
    # Mismo criterio que `db.trabajadores_sin_geo`: sin coordenadas y con
    # localidad (sin localidad no hay nada que geocodificar). Solo el conteo.
    pendientes = int(s.execute(text(
        "SELECT count(*) FROM trabajador t JOIN cuentatrabajador c ON c.cuil = t.cuil "
        "WHERE t.sindicato_id = :sid AND t.activo AND c.latitud IS NULL AND c.localidad != ''"),
        {"sid": sid}).scalar() or 0)
    cifras = {"afiliados_activos": activos, "pendientes_de_ubicar": pendientes}
    if pendientes:
        return _con_avisos("Hay domicilios sin ubicar en el mapa.",
                           [f"{_plural(pendientes, 'domicilio pendiente', 'domicilios pendientes')} de ubicar"], cifras)
    return _completa("Todos los domicilios con localidad están ubicados.", cifras)


def pad_04(s, sid) -> Control:
    empleadores = {r[0] for r in s.execute(select(Empleador.cuit).where(
        Empleador.sindicato_id == sid, Empleador.activo == True)).all()}    # noqa: E712
    de_conceptos = {r[0] for r in s.execute(select(Concepto.cuit_empleador).where(
        Concepto.sindicato_id == sid, Concepto.cuit_empleador.is_not(None)).distinct()).all()}
    sin_importar = de_conceptos - empleadores
    cifras = {"empleadores": len(empleadores), "cuit_de_conceptos_sin_importar": len(sin_importar)}
    if not empleadores:
        return _incompleta("Todavía no hay empleadores.", ["Dar de alta los empleadores"], cifras)
    if sin_importar:
        return _con_avisos("Hay empleadores; faltan algunos de los conceptos.",
                           [f"{_plural(len(sin_importar), 'CUIT de un concepto', 'CUIT de conceptos')} sin dar de alta como empleador"],
                           cifras)
    return _completa("Hay empleadores cargados.", cifras)


def _plantillas_pedidas(s, sid) -> set:
    """Las plantillas de lista que nombran los formularios publicados, en los
    requisitos y en las validaciones de sus campos."""
    pedidas: set = set()

    def mirar(validaciones):
        for v in validaciones or []:
            if isinstance(v, dict) and v.get("origen") == "lista" and v.get("lista"):
                pedidas.add(v["lista"])

    publicados = s.execute(select(TipoTramite.id, TipoTramite.requisitos).where(
        TipoTramite.sindicato_id == sid, TipoTramite.activo == True,        # noqa: E712
        TipoTramite.borrador == False)).all()                               # noqa: E712
    for _, requisitos in publicados:
        mirar(requisitos)
    if publicados:
        for (validaciones,) in s.execute(select(CampoTramite.validaciones).where(
                CampoTramite.tipo_tramite_id.in_([p[0] for p in publicados]),
                CampoTramite.retirado == False)).all():                      # noqa: E712
            mirar(validaciones)
    return pedidas


def pad_05(s, sid) -> Control:
    cargadas = {r[0] for r in s.execute(select(ListaSindicato.plantilla).where(
        ListaSindicato.sindicato_id == sid)).all()}
    pedidas = _plantillas_pedidas(s, sid)
    faltan = sorted(pedidas - cargadas)
    cifras = {"listas_cargadas": len(cargadas), "plantillas_pedidas": len(pedidas),
              "plantillas_sin_cargar": len(faltan)}
    if faltan:
        return _incompleta("Los formularios piden listas que no están cargadas.",
                           [f"Cargar la lista «{p}»" for p in faltan], cifras, en_curso=bool(cargadas))
    if not cargadas:
        return _incompleta("No hay ninguna lista cargada.", ["Cargar las listas del sindicato"], cifras)
    return _completa("Las listas que piden los formularios están cargadas.", cifras)


# --------------------------------------------------------------- Trámites

def tra_01(s, sid) -> Control:
    filas = s.execute(select(TipoTramite.id, TipoTramite.activo, TipoTramite.borrador,
                             TipoTramite.area_destino_default_id).where(
        TipoTramite.sindicato_id == sid)).all()
    publicados = [f for f in filas if f[1] and not f[2]]
    borradores = [f for f in filas if f[2]]
    con_campos = set()
    if publicados:
        con_campos = {r[0] for r in s.execute(select(CampoTramite.tipo_tramite_id).where(
            CampoTramite.tipo_tramite_id.in_([f[0] for f in publicados]),
            CampoTramite.retirado == False,                               # noqa: E712
            CampoTramite.tipo_dato != "separador").distinct()).all()}
    validos = [f for f in publicados if f[3] is not None and f[0] in con_campos]
    cifras = {"publicados": len(publicados), "validos": len(validos), "borradores": len(borradores)}
    if len(validos) < MINIMO_FORMULARIOS:
        faltan = ["Publicar al menos un formulario con área de destino y campos"]
        return _incompleta("Todavía no hay formularios publicados.", faltan, cifras,
                           en_curso=bool(filas))
    avisos = []
    if borradores:
        avisos.append(f"{_plural(len(borradores), 'formulario en borrador', 'formularios en borrador')}")
    if len(validos) < len(publicados):
        avisos.append("Hay formularios publicados sin área de destino o sin campos")
    if avisos:
        return _con_avisos(f"Hay {_plural(len(validos), 'formulario publicado', 'formularios publicados')}.",
                           avisos, cifras)
    return _completa(f"Hay {_plural(len(validos), 'formulario publicado', 'formularios publicados')}.", cifras)


def tra_02(s, sid) -> Control:
    estados = dict(s.execute(select(Tramite.estado, func.count()).where(
        Tramite.sindicato_id == sid).group_by(Tramite.estado)).all())
    total = sum(estados.values())
    cerrados = estados.get("terminado", 0)
    cifras = {"tramites": total, "terminados": cerrados}
    if cerrados:
        return _completa("Hay un trámite que recorrió todo el circuito.", cifras)
    if total:
        return _incompleta("Hay trámites iniciados, ninguno cerrado.",
                           ["Responder y cerrar un trámite de prueba"], cifras, en_curso=True)
    return _incompleta("Todavía no hay ningún trámite.", ["Iniciar un trámite de prueba como afiliado"], cifras)


# ---------------------------------------------------------- Comunicación

def com_01(s, sid) -> Control:
    return _por_confirmar("Que el modelo, la paleta y la foto quedaron elegidos lo confirma el equipo.")


def com_02(s, sid) -> Control:
    hoy = fechas.hoy_texto()
    n = _n(s, select(func.count()).select_from(Noticia).where(
        Noticia.sindicato_id == sid, Noticia.fecha_desde <= hoy, Noticia.fecha_hasta >= hoy))
    if n:
        return _completa(f"Hay {_plural(n, 'noticia vigente', 'noticias vigentes')}.", {"vigentes": n})
    return _incompleta("No hay noticias vigentes.", ["Cargar al menos una noticia"], {"vigentes": 0})


def com_03(s, sid) -> Control:
    hoy = fechas.hoy_texto()
    n = _n(s, select(func.count()).select_from(Beneficio).where(
        Beneficio.sindicato_id == sid, Beneficio.fecha_desde <= hoy, Beneficio.fecha_hasta >= hoy))
    if n:
        return _completa(f"Hay {_plural(n, 'beneficio vigente', 'beneficios vigentes')}.", {"vigentes": n})
    return _incompleta("No hay beneficios vigentes.", ["Cargar al menos un beneficio"], {"vigentes": 0})


def com_04(s, sid) -> Control:
    n = _n(s, select(func.count()).select_from(Notificacion).where(
        Notificacion.sindicato_id == sid, Notificacion.origen == "manual",
        Notificacion.enviado_en != ""))
    if n:
        return _completa(f"Se envió {_plural(n, 'notificación', 'notificaciones')}.", {"enviadas": n})
    return _incompleta("Todavía no se envió ninguna notificación.",
                       ["Enviar la notificación de bienvenida"], {"enviadas": 0})


def com_05(s, sid) -> Control:
    vigentes = _n(s, select(func.count()).select_from(DocumentoConvenio).where(
        DocumentoConvenio.sindicato_id == sid, DocumentoConvenio.vigente == True))   # noqa: E712
    listos = _n(s, select(func.count()).select_from(DocumentoConvenio).where(
        DocumentoConvenio.sindicato_id == sid, DocumentoConvenio.vigente == True,    # noqa: E712
        DocumentoConvenio.estado == "listo"))
    cifras = {"documentos_vigentes": vigentes, "indexados": listos}
    if listos:
        return _completa("Hay un convenio vigente e indexado.", cifras)
    if vigentes:
        return _incompleta("El convenio todavía no terminó de indexarse.",
                           ["Esperar la indexación o reintentarla"], cifras, en_curso=True)
    return _incompleta("No hay un convenio cargado.", ["Cargar el convenio en PDF"], cifras)


def com_06(s, sid) -> Control:
    n = _n(s, select(func.count()).select_from(Encuesta).where(
        Encuesta.sindicato_id == sid, Encuesta.publicada == True))    # noqa: E712
    if n:
        return _completa(f"Hay {_plural(n, 'encuesta publicada', 'encuestas publicadas')}.", {"publicadas": n})
    return _incompleta("Todavía no se publicó ninguna encuesta.", ["Armar y publicar una encuesta"],
                       {"publicadas": 0})


# ----------------------------------------------------------------- Cierre

def cie_01(s, sid) -> Control:
    n = int(s.execute(text(
        "SELECT count(DISTINCT r.cuil) FROM reciboverificado r "
        "JOIN trabajador t ON t.cuil = r.cuil AND t.sindicato_id = r.sindicato_id "
        "WHERE r.sindicato_id = :sid AND t.registrado"), {"sid": sid}).scalar() or 0)
    if n:
        return _completa("Hay una cuenta registrada que verificó un recibo.", {"cuentas_con_recibo": n})
    return _incompleta("Ninguna cuenta registrada verificó un recibo todavía.",
                       ["Registrar un afiliado de prueba y verificar su recibo"], {"cuentas_con_recibo": 0})


def cie_02(s, sid) -> Control:
    # El robot por sindicato no existe todavía (ayuda 7 del plan).
    return _por_confirmar("Todavía no existe el robot que recorre cada rol del sindicato.")


def cie_03(s, sid) -> Control:
    # Una aprobación de la Mesa resuelta por el lado del sindicato. Hoy no se
    # distingue CUÁL es la de aceptación final: el bloque 5 las vincula.
    n = _n(s, select(func.count()).select_from(ImplTarjeta).join(
        ImplProyecto, ImplProyecto.id == ImplTarjeta.proyecto_id).where(
        ImplProyecto.sindicato_id == sid, ImplTarjeta.tipo == "aprobacion",
        ImplTarjeta.resuelta_en != "", ImplTarjeta.resuelta_por_lado == "sindicato"))
    if n:
        return _completa("El sindicato resolvió una aprobación en la Mesa.", {"aprobaciones_resueltas": n})
    return _incompleta("El sindicato todavía no aceptó.",
                       ["Pedir la aceptación con una tarjeta de Aprobación en la Mesa"],
                       {"aprobaciones_resueltas": 0})

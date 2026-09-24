"""Catálogo de secciones del panel del sindicato y cálculo de permisos.

Este archivo es al panel del admin lo que modulos.py es al trabajador, pero
NO son la misma cosa y esa distinción es la decisión central del sistema
(ver SPRINT_AREAS.md, "Catálogo de secciones"):

- `modulos.py` dice qué CONTRATÓ el sindicato. Lo decide plataforma.
- `permisos.py` dice qué puede TOCAR cada usuario dentro de eso. Lo decide
  el Super Admin del sindicato.

Un módulo puede abrir varias secciones: "recibos" abre cinco. Por eso los
permisos se guardan por sección y no por módulo -- si la unidad fuera el
módulo, no habría forma de decir "revisá los reportes de recibos pero no
toques las fórmulas", que es justamente el caso que motivó todo esto.

Los módulos del sindicato FILTRAN qué secciones se pueden ofrecer: una
sección cuyo módulo está apagado no se muestra ni se puede asignar.
"""

# seccion -> (etiqueta, modulo_requerido, grupo)
#
# `modulo_requerido` en "" significa que la sección no depende de ningún
# módulo y siempre se puede ofrecer (mismo criterio que Trabajadores y
# Seccionales, que hoy están siempre visibles en el panel).
#
# `grupo` es solo para la UI: las secciones se muestran agrupadas con un
# check en el título que tilda el grupo entero, así asignar "Recibos"
# completo sigue siendo un clic.
SECCIONES = {
    # Reportes: TODOS los recibos verificados (enviados o no, estos
    # anonimizados). Absorbió a la vieja "cotizantes" el 2026-09-24.
    "reportes":                 ("Reportes de recibos",      "recibos",        "Recibos"),
    "formulas":                 ("Fórmulas",                 "recibos",        "Recibos"),
    "conceptos":                ("Conceptos",                "recibos",        "Recibos"),
    "aprendizaje":              ("Aprendizaje",              "recibos",        "Recibos"),
    # Panel Sindical (módulo "dashboard"). Es una PÁGINA aparte
    # (/admin/dashboard), no una pestaña del panel, pero se gatea igual: el
    # permiso no es "ver la pestaña" sino "entrar a la sección".
    # El explorador de datos sigue con su propio gate de módulo
    # (_exigir_dashboard_detalle en main.py), que existe para el día que
    # dashboard se parta en STD y PRO -- son dos ejes distintos: el módulo
    # dice qué CONTRATÓ el sindicato, esta sección quién puede ENTRAR.
    "dashboard":                ("Panel Sindical",           "dashboard",      "Recibos"),
    "trabajadores":             ("Trabajadores",             "",               "Padrón"),
    "seccionales":              ("Seccionales",              "",               "Padrón"),
    "noticias":                 ("Noticias",                 "noticias",       "Comunicación"),
    "beneficios":               ("Beneficios",               "beneficios",     "Comunicación"),
    "notificaciones":           ("Notificaciones",           "notificaciones", "Comunicación"),
    # Encuestas se abre en dos por el mismo motivo que Trámites: armar la
    # encuesta y publicarla a nombre del sindicato no es lo mismo que leer
    # los resultados. En un gremio grande lo hacen personas distintas
    # (Prensa lanza, la conducción lee). Exportar va dentro de "resultados":
    # es la misma decisión de confianza que ver el tablero.
    "encuestas":                ("Encuestas",                "encuestas",      "Comunicación"),
    "encuestas_resultados":     ("Resultados de encuestas",  "encuestas",      "Comunicación"),
    # Trámites se abre en dos: responder no es lo mismo que diseñar el
    # formulario. Quien puede editar el formulario elige el área receptora,
    # así que podría autoasignarse trámites -- por eso "crear formularios"
    # tiene que poder darse por separado.
    "tramites_recibidos":       ("Trámites recibidos",       "tramites",       "Trámites"),
    "tramites_formularios":     ("Crear formularios",        "tramites",       "Trámites"),
    # Consultas sobre el convenio (RAG). La carga y reindexado de documentos
    # es tarea de quien administra el contenido, no de quien contesta
    # trámites, así que va como sección propia y no colgada de otra.
    "convenio":                 ("Convenio",                 "convenio",       "Comunicación"),
    # Las 3 subpestañas que hoy viven bajo el módulo "empleadores".
    "emp_empresas":             ("Empresas",                 "empleadores",    "Empleadores"),
    "emp_notificaciones":       ("Notificaciones a empresas", "empleadores",   "Empleadores"),
    "emp_tramites_recibidos":   ("Trámites de empresa",      "empleadores",    "Empleadores"),
    "emp_tramites_formularios": ("Crear formularios externos", "empleadores",  "Empleadores"),
}

# Sección exclusiva del Super Admin: NO se puede asignar a un área ni a un
# usuario. No está en SECCIONES a propósito -- si estuviera, aparecería
# como un check más en la pantalla de permisos y sería asignable.
SECCION_SUPER_ADMIN = "areas_usuarios"

# Orden en que se muestran los grupos en la UI.
ORDEN_GRUPOS = ["Recibos", "Padrón", "Comunicación", "Trámites", "Empleadores"]


def secciones_de_modulos(modulos: list) -> list:
    """Las secciones que un sindicato con estos módulos puede ofrecer.

    Es lo que se le muestra al Super Admin cuando arma un perfil: no tiene
    sentido ofrecerle "Noticias" a un sindicato que no tiene el módulo.
    """
    activos = set(modulos or [])
    return [s for s, (_, mod, _) in SECCIONES.items() if not mod or mod in activos]


def agrupar_para_ui(secciones: list) -> list:
    """[(grupo, [(seccion, etiqueta), ...]), ...] en el orden de ORDEN_GRUPOS.

    Los grupos vacíos (todas sus secciones filtradas por módulo) no se
    devuelven, así la pantalla no muestra títulos huérfanos.
    """
    disponibles = set(secciones or [])
    salida = []
    for grupo in ORDEN_GRUPOS:
        items = [(s, SECCIONES[s][0]) for s in SECCIONES
                 if SECCIONES[s][2] == grupo and s in disponibles]
        if items:
            salida.append((grupo, items))
    return salida


def calcular_efectivos(del_area: list, agregados: list, bloqueados: list,
                       modulos: list) -> set:
    """Permisos efectivos de un usuario de área.

    efectivo = ((área + agregados) - bloqueados) ∩ secciones_de_modulos

    El bloqueo le gana al área y también a un agregado individual: es el
    único orden que hace que "bloqueado" signifique algo. La intersección
    final con los módulos del sindicato es la red de seguridad -- si
    plataforma le apaga un módulo, los permisos viejos dejan de valer solos,
    sin tener que salir a limpiar filas.
    """
    ofrecibles = set(secciones_de_modulos(modulos))
    efectivos = (set(del_area or []) | set(agregados or [])) - set(bloqueados or [])
    return efectivos & ofrecibles

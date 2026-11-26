"""Las tareas para dejar un sindicato de Colm3na en su primera versión
funcional (PLAN_XSII.md, «Catálogo v0 de Colm3na», X5 y X14).

Declarativo: cada tarea apunta a modelos, rutas y módulos REALES, y
`test_xsii_colm3na.py` falla si dejan de coincidir con el código (que el
`aplica_si` sea un módulo de `modulos.MODULOS`, que el `donde` sea una ruta
de la app, que toda tarea tenga su función de control). El catálogo se arma
desde el sistema y no desde los hitos de la Mesa, que son texto escrito a
mano (X5).

Las dependencias duras (`necesita`) son las que de verdad frenan: sin áreas no
se publica un formulario, sin seccionales la carga del padrón deja gente sin
seccional. Las blandas (`mejora_con`) solo avisan.
"""

from __future__ import annotations

from xsii.motor.catalogo import Tarea

GRUPOS = ("Base", "Estructura", "Recibos", "Padrón", "Trámites", "Comunicación", "Cierre")

# Una tarea es una función de controles.py con el MISMO nombre que `control`.
TAREAS = (
    # ---------------------------------------------------------------- Base
    Tarea("BAS-01", "Ficha del sindicato", "Base", "aplicacion",
          donde="/plataforma", control="bas_01",
          descripcion="El sindicato existe en plataforma, con nombre y un CUIT válido."),
    Tarea("BAS-02", "Marca: logo, colores y prueba de lectura", "Base", "aplicacion",
          necesita=("BAS-01",), donde="/plataforma", control="bas_02",
          descripcion="Logo cargado y colores que se leen bien en los dos modelos de diseño."),
    Tarea("BAS-03", "Módulos contratados", "Base", "aplicacion",
          necesita=("BAS-01",), donde="/plataforma", control="bas_03",
          descripcion="Qué funcionalidades tiene el sindicato; lo confirma el equipo."),
    Tarea("BAS-04", "Primer administrador con clave propia", "Base", "aplicacion",
          necesita=("BAS-01",), donde="/plataforma", control="bas_04",
          descripcion="Un Super Admin activo que ya eligió su clave (la inicial es transitoria)."),
    Tarea("BAS-05", "Política de registro y canal de mail", "Base", "aplicacion",
          necesita=("BAS-01",), donde="/plataforma", control="bas_05",
          descripcion="Cómo se registran los afiliados y si el canal de mail está prendido."),
    Tarea("BAS-06", "Cláusula de confidencialidad y contrato", "Base", "manual",
          necesita=("BAS-01",), donde="/plataforma", control="bas_06",
          descripcion="Contrato firmado cargado y cláusula marcada por plataforma."),
    # ---------------------------------------------------------- Estructura
    Tarea("EST-01", "Seccionales", "Estructura", "asistida",
          necesita=("BAS-01",), insumos=("lista_seccionales",),
          donde="/admin#seccionales", control="est_01",
          descripcion="Las seccionales del sindicato (y Sede Central), con sus domicilios."),
    Tarea("EST-02", "Seccionales ubicadas en el mapa", "Estructura", "asistida",
          necesita=("EST-01",), donde="/admin#seccionales", control="est_02",
          descripcion="Cada seccional con el globo puesto en la puerta."),
    Tarea("EST-03", "Áreas con permisos", "Estructura", "asistida",
          necesita=("EST-01", "BAS-03"), donde="/admin#administradores", control="est_03",
          descripcion="Las áreas de cada seccional, cada una con al menos una sección habilitada."),
    Tarea("EST-04", "Usuarios del panel", "Estructura", "asistida",
          necesita=("EST-03",), donde="/admin#administradores", control="est_04",
          descripcion="Cada área que recibe trámites con al menos un usuario activo."),
    # ------------------------------------------------------------- Recibos
    Tarea("REC-01", "Recibos de muestra", "Recibos", "manual",
          insumos=("recibos_muestra",), aplica_si="recibos", control="rec_01",
          descripcion="Entre 30 y 60 recibos de varios empleadores, entregados por el sindicato."),
    Tarea("REC-02", "Aportes de ley", "Recibos", "automatica",
          necesita=("BAS-01",), aplica_si="recibos", donde="/admin#conceptos", control="rec_02",
          descripcion="Jubilación, PAMI y obra social con sus reglas: se crean al dar de alta el sindicato."),
    Tarea("REC-03", "Cuota sindical y aporte solidario", "Recibos", "asistida",
          necesita=("BAS-01",), insumos=("porcentajes_cuota",), aplica_si="recibos",
          donde="/admin#conceptos", control="rec_03",
          descripcion="Un concepto de afiliación con su regla de control."),
    Tarea("REC-04", "Catálogo de conceptos", "Recibos", "asistida",
          necesita=("REC-01",), aplica_si="recibos", donde="/admin#aprendizaje", control="rec_04",
          descripcion="Los conceptos de los recibos de muestra, sin ninguno pendiente de revisión."),
    Tarea("REC-05", "Reglas de control", "Recibos", "asistida",
          necesita=("REC-04", "REC-03"), aplica_si="recibos", donde="/admin#formulas", control="rec_05",
          descripcion="Toda regla evalúa, sin tolerancias excesivas ni vigencias superpuestas."),
    Tarea("REC-06", "Topes vigentes para la muestra", "Recibos", "aplicacion",
          aplica_si="recibos", donde="/plataforma", control="rec_06",
          descripcion="Tope de base imponible vigente para los períodos de los recibos de muestra."),
    Tarea("REC-07", "Recibos de control", "Recibos", "asistida",
          necesita=("REC-05", "REC-06"), aplica_si="recibos", control="rec_07",
          descripcion="Validar el lote de muestra sin identidad contra el catálogo y las reglas."),
    Tarea("REC-08", "Escala salarial y convenio", "Recibos", "herramienta",
          necesita=("BAS-03",), aplica_si="grilla_convenio",
          donde="/entornos/herramientas/convenio-escalas", control="rec_08",
          descripcion="Convenio asignado al sindicato y grilla salarial publicada."),
    # -------------------------------------------------------------- Padrón
    Tarea("PAD-01", "Padrón recibido", "Padrón", "manual",
          insumos=("planilla_padron",), control="pad_01",
          descripcion="La planilla del padrón entregada por el sindicato, con el total declarado."),
    Tarea("PAD-02", "Padrón cargado", "Padrón", "asistida",
          necesita=("EST-01", "PAD-01"), donde="/admin#trabajadores", control="pad_02",
          descripcion="Los afiliados cargados contra el total declarado, con los rechazos revisados."),
    Tarea("PAD-03", "Domicilios ubicados", "Padrón", "asistida",
          necesita=("PAD-02",), donde="/admin#trabajadores", control="pad_03",
          descripcion="Los domicilios del padrón georreferenciados; los pendientes no frenan."),
    Tarea("PAD-04", "Empleadores", "Padrón", "asistida",
          necesita=("BAS-03",), mejora_con=("REC-04",), aplica_si="empleadores",
          donde="/admin#empleadores", control="pad_04",
          descripcion="Las empresas dadas de alta, con los CUIT de los conceptos importados."),
    Tarea("PAD-05", "Listas del sindicato", "Padrón", "aplicacion",
          necesita=("EST-01",), aplica_si="tramites", donde="/admin#listas", control="pad_05",
          descripcion="Las listas que nombran los formularios (grupo familiar, etc.) cargadas."),
    # ------------------------------------------------------------ Trámites
    Tarea("TRA-01", "Formularios de trámite", "Trámites", "herramienta",
          necesita=("EST-03",), mejora_con=("PAD-05",), aplica_si="tramites",
          donde="/entornos/herramientas/asistente-tramites", control="tra_01",
          descripcion="Formularios publicados, con área de destino y campos."),
    Tarea("TRA-02", "Trámite de prueba", "Trámites", "manual",
          necesita=("TRA-01", "PAD-02", "EST-04"), aplica_si="tramites",
          donde="/app", control="tra_02",
          descripcion="Un trámite iniciado, respondido y cerrado de punta a punta."),
    # --------------------------------------------------------- Comunicación
    Tarea("COM-01", "Apariencia: modelo, paleta y foto", "Comunicación", "aplicacion",
          necesita=("BAS-02",), donde="/admin#apariencia", control="com_01",
          descripcion="El modelo de diseño, la paleta y la foto de portada; lo confirma el equipo."),
    Tarea("COM-02", "Noticias iniciales", "Comunicación", "aplicacion",
          aplica_si="noticias", donde="/admin#noticias", control="com_02",
          descripcion="Al menos una noticia vigente."),
    Tarea("COM-03", "Beneficios", "Comunicación", "aplicacion",
          aplica_si="beneficios", donde="/admin#beneficios", control="com_03",
          descripcion="Al menos un beneficio vigente."),
    Tarea("COM-04", "Notificación de bienvenida", "Comunicación", "aplicacion",
          necesita=("PAD-02",), aplica_si="notificaciones",
          donde="/admin#notificaciones", control="com_04",
          descripcion="Una notificación enviada a los afiliados."),
    Tarea("COM-05", "Convenio para consultas", "Comunicación", "aplicacion",
          necesita=("BAS-03",), aplica_si="convenio", donde="/admin#convenio", control="com_05",
          descripcion="Un documento de convenio vigente e indexado."),
    Tarea("COM-06", "Encuestas", "Comunicación", "aplicacion",
          necesita=("PAD-02",), aplica_si="encuestas", donde="/admin#encuestas", control="com_06",
          descripcion="Al menos una encuesta publicada (no aplica salvo que el sindicato la contrate)."),
    # -------------------------------------------------------------- Cierre
    Tarea("CIE-01", "Afiliado de prueba con recibo propio", "Cierre", "manual",
          necesita=("PAD-02", "REC-05"), aplica_si="recibos", donde="/app", control="cie_01",
          descripcion="Una cuenta registrada que leyó y validó un recibo propio."),
    Tarea("CIE-02", "Recorrido por rol", "Cierre", "asistida",
          necesita=("CIE-01", "TRA-02", "EST-04"), control="cie_02",
          descripcion="El robot entra con cada rol del sindicato y completa su recorrido."),
    Tarea("CIE-03", "Aceptación del sindicato", "Cierre", "manual",
          necesita=("CIE-02",), donde="/implementacion", control="cie_03",
          descripcion="La tarjeta de Aprobación de la Mesa, resuelta por el sindicato."),
)

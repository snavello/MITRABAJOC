# -*- coding: utf-8 -*-
"""Regularizar los CUIL/CUIT que no cumplen el módulo 11 (PLAN_CUIT_MOD11.md,
etapas 1 y 2).

El CUIL/CUIT es el campo más importante del modelo y entre tablas se une POR
TEXTO, sin claves foráneas: si se cambia un número en una tabla y no en otra,
la relación se corta en silencio. Por eso esta herramienta (a) sabe en qué
columnas y en qué rutas de un JSON puede vivir un número (INVENTARIO), (b) lo
cambia en TODAS en una sola transacción y (c) antes del COMMIT verifica,
dentro de la misma transacción, que no quedó ni una aparición del viejo y que
el nuevo tiene exactamente las que tenía el viejo.

Dos comandos:

    python regularizar_cuit.py diagnostico [--salida X.csv]
        Solo lectura. Resumen en pantalla y una planilla (CSV) con una fila
        por número inválido: nuevo propuesto, origen, si se convierte y por
        qué no. La planilla lleva nombres: no se versiona (.gitignore).

    python regularizar_cuit.py aplicar --planilla X.csv [--si --quien SDN]
                                       [--sin-backup]
        Convierte las filas con convertir=si. SIN --si es un ensayo: hace
        todo adentro de una transacción, muestra qué cambiaría y la deshace;
        no escribe nada ni hace backup. CON --si exige --quien, hace el
        backup (pg_dump) y deja una fila en `cambioidentificador` por número.

Lo que decide cada fila (origen):

    demo      está en identificadores_demo.REEMPLAZOS_MOD11: el nuevo es
              EXACTAMENTE el del mapa. Se convierte.
    lote      lo generó un script sintético (cargar_lote_*, demo_encuestas,
              carga/, medir_dashboard). NO se convierte en esta etapa.
    lectura   solo aparece en columnas que guardan lo que la IA leyó de un
              documento (un CUIT de empleador mal leído, por ejemplo). NO se
              convierte: el documento es la prueba y no se "corrige" lo que
              dice un papel.
    manual    todo lo demás. Se convierte al número válido más cercano
              (cuit.corregir) si no choca con nadie.

Una colisión (el nuevo ya existe en cualquier tabla, o lo reclaman dos
viejos) frena esa fila: sale como COLISION y la persona elige. La FUSIÓN de
dos personas no la hace esta herramienta jamás; renumerar sí (columna
`alternativa`).

Qué NO se reescribe (D5, la historia no se toca) está en EXCLUIDAS con su
motivo; la traza de lo que sí se cambió queda en `cambioidentificador`.

Importable: `diagnosticar(conexion)`, `aplicar(planilla, ...)`. Los tests los
llaman sin subprocess.
"""
import argparse
import csv
import functools
import io
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session as _SesionSA

import cuit
import db
import entorno
import fechas
import identificadores_demo
import pg_cliente

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Inventario: cada lugar donde vive un CUIL/CUIT
# ---------------------------------------------------------------------------
TEXTO, JSON = "texto", "json"
ALTA, LECTURA, COPIA = "alta", "lectura", "copia"
PERSONA, EMPRESA, CUALQUIERA = cuit.PERSONA, cuit.EMPRESA, "cualquiera"

ORIGEN_MANUAL, ORIGEN_DEMO, ORIGEN_LOTE, ORIGEN_LECTURA = "manual", "demo", "lote", "lectura"
ORDEN_ORIGEN = (ORIGEN_MANUAL, ORIGEN_DEMO, ORIGEN_LOTE, ORIGEN_LECTURA)

TABLA_TRAZA = "cambioidentificador"


@dataclass(frozen=True)
class Columna:
    """Una columna de la base donde puede vivir un CUIL/CUIT.

    clase   PERSONA (es un CUIL), EMPRESA (es el CUIT de una persona jurídica)
            o CUALQUIERA (un empleador puede ser una persona física: su CUIT
            tiene prefijo de persona, y un login puede ser CUIT o CUIL).
    valor   TEXTO (la columna ES el número) o JSON (el número está adentro,
            en cualquier ruta).
    fuente  de dónde sale el dato: ALTA (lo escribe un alta, el registro, un
            panel o la sesión), LECTURA (lo que leyó la IA de un documento) o
            COPIA (una copia de un dato que ya vive en otro lado).
    donde   filtro SQL de filas (solo JSON): una columna `criterio_valores`
            guarda ids o nombres salvo cuando el criterio es por CUIL/CUIT.
    estricta  (solo TEXTO) todo valor no vacío TIENE que ser un número; si no
            lo es sale como FORMATO. False para un campo libre como
            `usuariosindicato.usuario`, que puede ser un login que no es un
            número.
    """
    tabla: str
    columna: str
    clase: str
    valor: str
    fuente: str
    donde: str = ""
    estricta: bool = True
    nota: str = ""

    @property
    def clave(self) -> str:
        return f"{self.tabla}.{self.columna}"


def _c(tabla, columna, clase, valor, fuente, **kw) -> Columna:
    return Columna(tabla, columna, clase, valor, fuente, **kw)


INVENTARIO = (
    # ---- Personas (CUIL) ----------------------------------------------
    _c("cuentatrabajador", "cuil", PERSONA, TEXTO, ALTA,
       nota="la persona: una fila por CUIL (único)"),
    _c("trabajador", "cuil", PERSONA, TEXTO, ALTA,
       nota="el empadronamiento en cada sindicato"),
    _c("trabajador", "semaforo_datos", PERSONA, JSON, LECTURA,
       nota="lo que leyó la IA del comprobante de ARCA"),
    _c("usuariosindicato", "usuario", CUALQUIERA, TEXTO, ALTA, estricta=False,
       nota="el login del operador (hoy es su CUIL); puede no ser un número"),
    _c("usuariosindicato", "cuil", PERSONA, TEXTO, ALTA,
       nota="quién es el operador; lo vincula al padrón"),
    _c("usuarioplataforma", "cuil", PERSONA, TEXTO, ALTA,
       nota="lo carga la persona en su primer ingreso"),
    _c("reciboverificado", "cuil", PERSONA, TEXTO, ALTA,
       nota="el de la SESIÓN (cuil_sesion), no el que leyó la IA"),
    _c("enviosindicato", "cuil", PERSONA, TEXTO, COPIA,
       nota="resultado.cuil, ya verificado contra el de la sesión"),
    _c("reporte", "cuil", PERSONA, TEXTO, COPIA,
       nota="resultado.cuil, ya verificado contra el de la sesión"),
    _c("recibosospechoso", "cuil", PERSONA, TEXTO, COPIA, nota="el de la sesión"),
    _c("usoia", "cuil", PERSONA, TEXTO, COPIA, nota="el de la sesión"),
    _c("tramite", "cuil", PERSONA, TEXTO, COPIA, nota="el de la sesión"),
    _c("notificaciondestinatario", "cuil", PERSONA, TEXTO, COPIA,
       nota="resuelto del padrón al enviar"),
    _c("encuestaparticipante", "cuil", PERSONA, TEXTO, COPIA,
       nota="el padrón fijado al publicar"),
    _c("respuestanominal", "cuil", PERSONA, TEXTO, COPIA,
       nota="solo existe en las encuestas NOMINALES"),
    _c("suscripcionpush", "cuil", PERSONA, TEXTO, COPIA),
    _c("consultaconvenio", "cuil", PERSONA, TEXTO, COPIA),
    # ---- Empresas (CUIT) ----------------------------------------------
    _c("cuentaempleador", "cuit", CUALQUIERA, TEXTO, ALTA,
       nota="la empresa con login (único)"),
    _c("empleador", "cuit", CUALQUIERA, TEXTO, ALTA,
       nota="su alta en cada sindicato"),
    _c("sindicato", "cuit", EMPRESA, TEXTO, ALTA,
       nota="el CUIT del gremio; en la demo se guardó con guiones"),
    _c("trabajador", "cuit_empleador", CUALQUIERA, TEXTO, ALTA,
       nota="lo carga el admin en el alta (sin normalizar: puede traer guiones)"),
    _c("concepto", "cuit_empleador", CUALQUIERA, TEXTO, ALTA,
       nota="origen mixto: el panel (alta) o el aprendizaje desde un recibo (lectura); "
            "se toma como alta para que nunca quede sin convertir un número tipeado"),
    _c("reciboverificado", "cuit_empleador", CUALQUIERA, TEXTO, LECTURA,
       nota="el CUIT que leyó la IA del recibo"),
    _c("respuestaencuesta", "cuit_empleador", CUALQUIERA, TEXTO, COPIA,
       nota="corte por empleador de la urna; reescribirlo no suma ningún vínculo a una persona"),
    _c("tramiteempleador", "cuit", CUALQUIERA, TEXTO, COPIA, nota="el de la sesión"),
    _c("notificacionempleadordestinatario", "cuit", CUALQUIERA, TEXTO, COPIA),
    # ---- JSON: el número puede estar en cualquier ruta -----------------
    _c("reciboverificado", "detalle", CUALQUIERA, JSON, LECTURA,
       nota="{recibo, resultado}: lo que leyó la IA + lo que calculó el motor"),
    _c("enviosindicato", "detalle", CUALQUIERA, JSON, LECTURA, nota="{recibo, resultado}"),
    _c("reporte", "detalle", CUALQUIERA, JSON, LECTURA, nota="{recibo, resultado}"),
    _c("notificacion", "criterio_valores", CUALQUIERA, JSON, ALTA,
       donde="criterio IN ('cuil', 'cuit_empleador')",
       nota="lista de CUIL/CUIT tipeados por el admin; con otros criterios son ids o nombres"),
    _c("notificacionempleador", "criterio_valores", EMPRESA, JSON, ALTA,
       donde="criterio = 'cuit'"),
    _c("encuesta", "criterio_valores", CUALQUIERA, JSON, ALTA,
       donde="criterio IN ('cuil', 'cuit_empleador')",
       nota="los criterios de una encuesta son los de Notificacion: cuil, cuit_empleador, "
            "seccional, provincia y todos"),
)

# Lo que NO se reescribe, con el motivo. Clave = "tabla.columna".
# Tiene dos funciones: documentar (D5: la historia no se toca) y que el test
# fail-closed pueda distinguir "lo decidimos" de "nadie lo miró".
EXCLUIDAS = {
    # -- Bitácoras: la historia no se reescribe (D5). La traza de lo que sí
    #    se cambió es `cambioidentificador`.
    "logplataforma.usuario": "bitácora: el usuario NOMINAL de plataforma que hizo la acción (D5)",
    "logplataforma.objetivo": "bitácora: texto de a quién recayó la acción (D5)",
    "logplataforma.detalle": "bitácora: texto libre (D5)",
    "tramitelog.detalle": "bitácora de trámites: texto libre (D5)",
    "tramiteempleadorlog.detalle": "bitácora de trámites de empresa: texto libre (D5)",
    "eventoencuesta.detalle": "bitácora de la encuesta: texto libre (D5)",
    "cambioplan.detalle": "bitácora de planes de Render: no lleva identidades (D5)",
    "avisoenviado.clave": "candado de avisos por día: no lleva identidades",
    "cambioidentificador.anterior": "la traza de ESTA herramienta: es la historia y no se reescribe (D5)",
    "cambioidentificador.nuevo": "la traza de ESTA herramienta: es la historia y no se reescribe (D5)",
    "cambioidentificador.detalle": "la traza de ESTA herramienta: conteo de filas por tabla.columna",
    # -- Textos libres y archivos: lo que escribió una persona o dice un papel.
    "respuestatramite.valor_texto": "respuesta tipeada a un formulario: texto libre (D5)",
    "respuestatramiteempleador.valor_texto": "respuesta tipeada a un formulario: texto libre (D5)",
    "notatramite.texto": "chat del trámite: texto libre (D5)",
    "notatramiteempleador.texto": "chat del trámite de empresa: texto libre (D5)",
    "consultaasistente.pregunta": "lo que tipeó el admin, tal cual: texto libre (D5)",
    "consultaasistente.respuesta": "lo que contestó el modelo: texto libre (D5)",
    "consultaconvenio.pregunta": "lo que tipeó el afiliado, tal cual: texto libre (D5)",
    "notificacion.texto": "texto del mensaje: libre (D5)",
    "notificacionempleador.texto": "texto del mensaje: libre (D5)",
    "respuestaencuesta.valor_texto": "respuesta libre de la urna: texto (D5)",
    # -- Datos que se llaman parecido pero no son un CUIL/CUIT
    "registroenmascarado.cuil_encontrado": "es un booleano (si el enmascarado encontró el CUIL), no el número",
    "usuarioplataforma.usuario": "usuario NOMINAL de plataforma (p. ej. 'snavello'): no es un CUIL/CUIT",
    "usuarioplataforma.dni": "el DNI es un dato propio de la persona; no se deriva ni se toca al convertir el CUIL",
    # -- JSON que se revisó y no lleva CUIL/CUIT
    "consultaasistente.filtros": "filtros del panel por ID numérico y enumerados (empresa, afiliado y "
                                 "seccional van por id); el CUIL que tipea el admin queda solo en `pregunta`",
    "testcarga.parametros": "metadatos de los experimentos de carga: texto descriptivo, sin identidades",
    "testcarga.resumen": "filas de métricas de los tests de carga: sin identidades",
    "geocache.respuesta_json": "respuesta cruda de Georef/Nominatim: direcciones, sin identidades",
    "sindicato.modulos_habilitados": "nombres de módulos",
    "concepto.alias": "descripciones del concepto tal como las imprime el recibo",
    "encuesta.cortes": "nombres de los cortes de la encuesta",
    "beneficio.destino_seccionales": "ids de seccional",
    "noticia.destino_seccionales": "ids de seccional",
    "consultaconvenio.fragmentos_usados": "ids de fragmentos del convenio",
    "campotramite.validaciones": "reglas de validación del formulario: no son identidad de nadie",
    "campotramiteempleador.validaciones": "reglas de validación del formulario: no son identidad de nadie",
    "tipotramite.reglas_consistencia": "reglas entre campos, por orden",
    "tipotramiteempleador.reglas_consistencia": "reglas entre campos, por orden",
    "tramite.advertencias": "mensajes de advertencia del formulario (texto del admin)",
    "tramiteempleador.advertencias": "mensajes de advertencia del formulario (texto del admin)",
}

# Nombres de columna que tienen que estar decididos (INVENTARIO o EXCLUIDAS).
# Se mira el NOMBRE, no la tabla: una columna nueva con "cuil"/"cuit" en el
# nombre, o un campo `usuario`/`dni`, fuerza una decisión (ver el test
# fail-closed de test_regularizar_cuit.py).
_PALABRAS_DE_IDENTIDAD = ("cuil", "cuit")
_NOMBRES_DE_IDENTIDAD = ("usuario", "dni")


def columnas_sin_decidir(metadata=None) -> list:
    """Columnas de la base que parecen guardar un CUIL/CUIT (o un login, o un
    DNI) y no están ni en INVENTARIO ni en EXCLUIDAS; y también TODA columna
    JSON sin decidir, porque un número puede esconderse en cualquier ruta.
    Vacía = el inventario cubre el esquema. Es lo que verifica el test."""
    from sqlmodel import SQLModel
    metadata = metadata if metadata is not None else SQLModel.metadata
    decididas = {c.clave for c in INVENTARIO} | set(EXCLUIDAS)
    pendientes = []
    for nombre_tabla, tabla in sorted(metadata.tables.items()):
        for col in tabla.columns:
            clave = f"{nombre_tabla}.{col.name}"
            parece = (any(p in col.name.lower() for p in _PALABRAS_DE_IDENTIDAD)
                      or col.name.lower() in _NOMBRES_DE_IDENTIDAD)
            es_json = isinstance(col.type, sa.JSON)
            if (parece or es_json) and clave not in decididas:
                pendientes.append(clave)
    return pendientes


def inventario_por_clave() -> dict:
    return {c.clave: c for c in INVENTARIO}


# ---------------------------------------------------------------------------
# Reconocer un número
# ---------------------------------------------------------------------------
_FORMA = re.compile(r"^\d{2}[\s\-./]?\d{8}[\s\-./]?\d$", re.ASCII)


def tiene_forma_de_numero(valor) -> bool:
    """¿Este valor ENTERO (sin contar los espacios de los bordes) tiene forma
    de CUIL/CUIT? Nunca se busca un número adentro de un texto más largo."""
    if isinstance(valor, bool):
        return False
    if isinstance(valor, int):
        texto = str(valor)
    elif isinstance(valor, str):
        texto = valor.strip()
    else:
        return False
    return bool(_FORMA.match(texto))


def _es_hoja_de_numero(valor) -> bool:
    """Forma de número Y prefijo conocido: en un JSON hay muchos textos de once
    dígitos que no son un CUIL/CUIT y de esos no se dice nada."""
    return tiene_forma_de_numero(valor) and cuit.tipo(valor) != ""


def caminar_json(nodo, f, ruta: str = ""):
    """Recorre un valor JSON (dicts y listas, a cualquier profundidad). A cada
    hoja que es un número de CUIL/CUIT la ofrece a `f(ruta, hoja)`: si
    devuelve algo distinto de None, la hoja se reemplaza. Devuelve
    (nodo, hubo_cambios). `ruta` usa puntos para las claves y `[]` para
    cualquier posición de una lista, así 100 recibos dan una sola ruta."""
    if isinstance(nodo, dict):
        cambio = False
        for k, v in list(nodo.items()):
            nuevo, c = caminar_json(v, f, f"{ruta}.{k}" if ruta else str(k))
            if c:
                nodo[k] = nuevo
                cambio = True
        return nodo, cambio
    if isinstance(nodo, list):
        cambio = False
        for i, v in enumerate(nodo):
            nuevo, c = caminar_json(v, f, f"{ruta}[]")
            if c:
                nodo[i] = nuevo
                cambio = True
        return nodo, cambio
    if _es_hoja_de_numero(nodo):
        reemplazo = f(ruta or "(raíz)", nodo)
        if reemplazo is not None:
            return reemplazo, True
    return nodo, False


# ---------------------------------------------------------------------------
# Lo que genera cada script sintético (origen "lote")
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def identificadores_de_lote() -> frozenset:
    """Todo CUIL/CUIT que pueden producir los generadores sintéticos. Cada
    generador expone `identificadores_sinteticos()` (la regla que él mismo
    usa), así que acá no se copia ninguna fórmula. Los imports son perezosos y
    NO se atrapan: si un generador no se puede importar, la herramienta tiene
    que fallar y no clasificar sus números como "manuales" (que se
    convertirían)."""
    import cargar_lote_sindicato
    import cargar_lote_uom
    import demo_encuestas
    import medir_dashboard
    from carga import preparar_datos
    todos = set()
    for modulo in (cargar_lote_sindicato, cargar_lote_uom, demo_encuestas,
                   preparar_datos, medir_dashboard):
        cuils, cuits = modulo.identificadores_sinteticos()
        todos |= set(cuils) | set(cuits)
    return frozenset(todos)


# ---------------------------------------------------------------------------
# Escaneo de la base
# ---------------------------------------------------------------------------
class ErrorRegularizacion(Exception):
    """Algo que hay que contarle a la persona, no un traceback. `errores`
    lleva todos los motivos cuando son varios."""

    def __init__(self, mensaje, errores=None):
        super().__init__(mensaje)
        self.errores = list(errores or [])


def _conexion(origen):
    """Acepta una Connection de SQLAlchemy o una Session (sqlmodel incluida)."""
    if isinstance(origen, _SesionSA):
        return origen.connection()
    return origen


@dataclass
class Escaneo:
    """Lo que hay en la base, normalizado.

    apariciones  número -> {tabla.columna: filas}. En JSON una fila cuenta una
                 vez por columna aunque el número esté repetido adentro.
    rutas        número -> {"tabla.columna:ruta": ocurrencias} (solo JSON).
    rotos        texto crudo -> {tabla.columna: filas}: valores de una columna
                 de identidad que NO son un número (forma rota o prefijo
                 desconocido).
    anomalias    [(tabla.columna, número, tipo del número, clase de la
                 columna)]: un CUIL con prefijo de empresa o al revés.
    """
    apariciones: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    rutas: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    rotos: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    anomalias: list = field(default_factory=list)

    @property
    def ocupados(self) -> set:
        # Con una aparición de verdad: un acceso a un defaultdict no "ocupa" nada.
        return {n for n, columnas in self.apariciones.items() if columnas}

    def plano(self) -> dict:
        """Una versión comparable (dicts comunes, sin defaultdict)."""
        return {
            "apariciones": {n: dict(c) for n, c in self.apariciones.items()},
            "rutas": {n: dict(c) for n, c in self.rutas.items()},
            "rotos": {n: dict(c) for n, c in self.rotos.items()},
        }


def verificar_esquema(conexion, columnas=INVENTARIO) -> None:
    """La base tiene que tener las tablas y columnas del inventario: si no, se
    corre `alembic upgrade head` antes. Falla con un mensaje y no con un
    traceback de SQL."""
    insp = sa.inspect(_conexion(conexion))
    faltan = []
    for c in columnas:
        if not insp.has_table(c.tabla):
            faltan.append(f"tabla {c.tabla}")
        elif c.columna not in {x["name"] for x in insp.get_columns(c.tabla)}:
            faltan.append(f"columna {c.clave}")
    if faltan:
        raise ErrorRegularizacion(
            "La base no tiene lo que el inventario espera (" + ", ".join(sorted(set(faltan))) +
            "). Corré `alembic upgrade head` y volvé a intentar.")


def escanear(conexion, columnas=INVENTARIO) -> Escaneo:
    """Recorre TODAS las columnas del inventario y arma el Escaneo. Solo lee.
    Los textos se agrupan en SQL (un GROUP BY por columna) y los JSON se leen
    en streaming, así que la memoria no crece con la cantidad de recibos."""
    conn = _conexion(conexion)
    esc = Escaneo()
    for c in columnas:
        if c.valor == TEXTO:
            _escanear_texto(conn, c, esc)
        else:
            _escanear_json(conn, c, esc)
    return esc


def _escanear_texto(conn, c: Columna, esc: Escaneo) -> None:
    col, tabla = f'"{c.columna}"', f'"{c.tabla}"'
    filas = conn.execute(sa.text(
        f"SELECT {col}, COUNT(*) FROM {tabla} "
        f"WHERE {col} IS NOT NULL AND {col} <> '' GROUP BY {col}")).all()
    for valor, n in filas:
        if not valor.strip():
            continue
        if _es_hoja_de_numero(valor):
            numero = cuit.normalizar(valor)
            esc.apariciones[numero][c.clave] += n
            t = cuit.tipo(numero)
            if (c.clase == PERSONA and t == EMPRESA) or (c.clase == EMPRESA and t == PERSONA):
                esc.anomalias.append((c.clave, numero, t, c.clase))
        elif c.estricta:
            esc.rotos[valor.strip()][c.clave] += n


def _escanear_json(conn, c: Columna, esc: Escaneo) -> None:
    sql = f'SELECT "{c.columna}" FROM "{c.tabla}"'
    if c.donde:
        sql += f" WHERE {c.donde}"
    res = conn.execute(sa.text(sql).execution_options(stream_results=True, max_row_buffer=500))
    for (doc,) in res:
        vistos = set()

        def visitar(ruta, hoja):
            numero = cuit.normalizar(hoja)
            vistos.add(numero)
            esc.rutas[numero][f"{c.clave}:{ruta}"] += 1
            return None

        caminar_json(doc, visitar)
        for numero in vistos:
            esc.apariciones[numero][c.clave] += 1


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------
@dataclass
class Fila:
    """Una fila de la planilla: un número inválido."""
    anterior: str
    nuevo: str = ""
    alternativa: str = ""
    tipo: str = ""
    origen: str = ORIGEN_MANUAL
    convertir: bool = False
    motivo: str = ""
    nombre: str = ""
    apariciones: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {
            "anterior": self.anterior, "nuevo": self.nuevo, "alternativa": self.alternativa,
            "tipo": self.tipo, "origen": self.origen,
            "convertir": "si" if self.convertir else "no", "motivo": self.motivo,
            "nombre": self.nombre,
            "apariciones": "; ".join(f"{k}:{v}" for k, v in sorted(self.apariciones.items())),
        }


COLUMNAS_PLANILLA = ("anterior", "nuevo", "alternativa", "tipo", "origen",
                     "convertir", "motivo", "nombre", "apariciones")


@dataclass
class Diagnostico:
    filas: list
    escaneo: Escaneo
    entorno: str
    validos: int = 0

    @property
    def invalidos(self) -> int:
        return len(self.filas)

    def por_origen(self) -> dict:
        r = defaultdict(int)
        for f in self.filas:
            r[f.origen] += 1
        return dict(r)

    def por_motivo(self) -> dict:
        r = defaultdict(int)
        for f in self.filas:
            r[f.motivo or "se convierte"] += 1
        return dict(r)

    def por_columna(self) -> dict:
        r = defaultdict(int)
        for f in self.filas:
            for k, v in f.apariciones.items():
                r[k] += v
        return dict(r)


def _fuentes_de(apariciones_de_un_numero: dict, por_clave: dict) -> set:
    return {por_clave[k].fuente for k in apariciones_de_un_numero if k in por_clave}


def clasificar_origen(numero: str, apariciones_de_un_numero: dict, lote: frozenset,
                      por_clave: Optional[dict] = None) -> str:
    """demo > lote > lectura > manual (ver el docstring del módulo)."""
    por_clave = por_clave or inventario_por_clave()
    if numero in identificadores_demo.REEMPLAZOS_MOD11:
        return ORIGEN_DEMO
    if numero in lote:
        return ORIGEN_LOTE
    fuentes = _fuentes_de(apariciones_de_un_numero, por_clave)
    if fuentes and fuentes <= {LECTURA}:
        return ORIGEN_LECTURA
    return ORIGEN_MANUAL


def nombres_de(conexion, numeros) -> dict:
    """número -> nombre o razón social para reconocerlo en la planilla. Se
    comparan normalizados (un CUIT del sindicato puede estar con guiones)."""
    conn = _conexion(conexion)
    buscados = set(numeros)
    hallados = defaultdict(set)
    consultas = (
        "SELECT cuil, nombre FROM cuentatrabajador",
        "SELECT usuario, nombre FROM usuariosindicato",
        "SELECT cuil, nombre FROM usuariosindicato",
        "SELECT cuil, nombre FROM usuarioplataforma",
        "SELECT cuit, razon_social FROM empleador",
        "SELECT cuit, nombre FROM sindicato",
    )
    for sql in consultas:
        for clave, nombre in conn.execute(sa.text(sql)):
            numero = cuit.normalizar(clave)
            if numero in buscados and (nombre or "").strip():
                hallados[numero].add(nombre.strip())
    return {n: " / ".join(sorted(v)) for n, v in hallados.items()}


def diagnosticar(conexion, lote: Optional[frozenset] = None) -> Diagnostico:
    """Solo lectura. Arma la planilla: una fila por número inválido, con su
    origen, el nuevo propuesto y las colisiones (D4) resueltas de forma global,
    personas y empresas juntas."""
    conn = _conexion(conexion)
    verificar_esquema(conn)
    esc = escanear(conn)
    filas, validos = filas_de_escaneo(esc, identificadores_de_lote() if lote is None else lote)
    nombres = nombres_de(conn, {f.anterior for f in filas})
    for f in filas:
        f.nombre = nombres.get(f.anterior, "")
    return Diagnostico(filas=filas, escaneo=esc, entorno=entorno.ENTORNO or "local",
                       validos=validos)


def filas_de_escaneo(esc: Escaneo, lote: frozenset) -> tuple:
    """(filas, cantidad de números válidos) a partir de un Escaneo. Puro: no
    toca la base (los nombres se agregan aparte). Es lo que comparan el antes
    y el después de `aplicar`."""
    por_clave = inventario_por_clave()
    ocupados = esc.ocupados

    filas, validos = [], 0
    for numero in sorted(ocupados):
        if cuit.es_valido(numero):
            validos += 1
            continue
        origen = clasificar_origen(numero, esc.apariciones[numero], lote, por_clave)
        f = Fila(anterior=numero, tipo=cuit.tipo(numero), origen=origen,
                 apariciones=dict(esc.apariciones[numero]))
        # Un prefijo desconocido no tiene corrección posible: forma rota.
        if not f.tipo:
            f.motivo = "FORMATO"
        else:
            f.nuevo = (identificadores_demo.REEMPLAZOS_MOD11[numero] if origen == ORIGEN_DEMO
                       else cuit.corregir(numero))
            if origen == ORIGEN_LOTE:
                f.motivo = "LOTE"
            elif origen == ORIGEN_LECTURA:
                f.motivo = "LECTURA"
            elif not f.nuevo:
                f.motivo = "SIN_CORRECCION"
            else:
                f.convertir = True
        filas.append(f)

    # Los valores que ni siquiera son un número (o tienen un prefijo que no
    # existe) también salen, para que se vean; nunca se convierten.
    for texto, cols in sorted(esc.rotos.items()):
        fuentes = _fuentes_de(cols, por_clave)
        filas.append(Fila(anterior=texto, origen=(ORIGEN_LECTURA if fuentes and fuentes <= {LECTURA}
                                                   else ORIGEN_MANUAL),
                          motivo="FORMATO", apariciones=dict(cols)))

    _resolver_colisiones(filas, ocupados)
    filas.sort(key=lambda f: (ORDEN_ORIGEN.index(f.origen), f.motivo != "", f.anterior))
    return filas, validos


def resumen_de_filas(filas: list) -> dict:
    """Los números que se comparan antes y después de convertir."""
    por_origen = defaultdict(int)
    for f in filas:
        por_origen[f.origen] += 1
    return {"para_revisar": len(filas), "por_origen": dict(por_origen),
            "convertibles": sum(1 for f in filas if f.convertir),
            "colisiones": sum(1 for f in filas if f.motivo == "COLISION")}


def _resolver_colisiones(filas: list, ocupados: set) -> None:
    """D4. Entre las filas que se convertirían (manual y demo, con propuesta),
    marca COLISION cuando el nuevo ya existe en cualquier tabla o lo reclaman
    dos números viejos, y propone en `alternativa` el siguiente DNI libre.
    Las filas LOTE y LECTURA no participan: no se convierten ahora; si algún
    día se convierten, el número que hoy ocupa otra fila ya no estará libre y
    lo dirá esa corrida."""
    candidatas = [f for f in filas if f.convertir]
    reclamos = defaultdict(int)
    for f in candidatas:
        reclamos[f.nuevo] += 1
    for f in candidatas:
        if f.nuevo in ocupados or reclamos[f.nuevo] > 1:
            f.convertir = False
            f.motivo = "COLISION"

    # Alternativas: hay que evitar los ocupados, TODO lo que se propone y las
    # alternativas ya repartidas (dos números que difieren solo en el
    # verificador tienen el mismo "siguiente DNI libre").
    reservados = set(ocupados) | {f.nuevo for f in candidatas}
    for f in sorted((f for f in filas if f.motivo in ("COLISION", "SIN_CORRECCION")),
                    key=lambda f: f.anterior):
        alt = cuit.siguiente_libre(f.anterior, reservados)
        f.alternativa = alt
        if alt:
            reservados.add(alt)


def resumen_texto(diag: Diagnostico, base: str = "") -> str:
    """El resumen que imprime `diagnostico`."""
    out = io.StringIO()
    p = lambda *a: print(*a, file=out)
    p(f"Diagnóstico de CUIL/CUIT -- entorno: {diag.entorno}" + (f" -- base: {base}" if base else ""))
    p(f"  Valores distintos de CUIL/CUIT en la base: {diag.validos + diag.invalidos} "
      f"({diag.validos} válidos, {diag.invalidos} para revisar)")
    p("  Inválidos por origen:")
    por_origen = diag.por_origen()
    for o in ORDEN_ORIGEN:
        p(f"    {o:<8} {por_origen.get(o, 0)}")
    p("  Qué pasa con cada fila:")
    for motivo, n in sorted(diag.por_motivo().items()):
        p(f"    {motivo:<16} {n}")
    p("  Apariciones de inválidos por tabla.columna (filas):")
    por_columna = diag.por_columna()
    for k in sorted(por_columna):
        p(f"    {k:<42} {por_columna[k]}")
    if diag.escaneo.anomalias:
        p(f"  Aviso: {len(diag.escaneo.anomalias)} número(s) con prefijo de otro tipo que su columna "
          "(un CUIL con prefijo de empresa, o al revés); no se tocan:")
        for clave, numero, t, clase in diag.escaneo.anomalias[:10]:
            p(f"    {clave}: {numero} es de {t}, la columna espera {clase}")
    return out.getvalue().rstrip()


# ---------------------------------------------------------------------------
# La planilla (CSV)
# ---------------------------------------------------------------------------
# Separador por defecto ";": SDN abre la planilla en Excel de Windows con la
# configuración regional de Argentina, donde el separador de listas es ";" y
# un CSV con comas se abre todo en una sola columna. Al LEER se detecta solo
# (Excel guarda con ";" en esa configuración) y se acepta "," también.
SEPARADOR = ";"


def escribir_planilla(diag: Diagnostico, ruta, separador: str = SEPARADOR) -> Path:
    ruta = Path(ruta)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_PLANILLA, delimiter=separador,
                           lineterminator="\r\n")
        w.writeheader()
        for fila in diag.filas:
            w.writerow(fila.como_dict())
    return ruta


def leer_planilla(ruta) -> list:
    """Lista de dicts con las columnas de la planilla. Tolera lo que le hace
    Excel: separador ';' o ',', BOM, y el guardado en cp1252 (el "CSV" común,
    sin UTF-8, que rompe los acentos de un nombre)."""
    crudo = Path(ruta).read_bytes()
    try:
        texto = crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = crudo.decode("cp1252", errors="replace")
    primera = texto.splitlines()[0] if texto.strip() else ""
    separador = ";" if primera.count(";") > primera.count(",") else ","
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)
    filas = []
    for fila in lector:
        filas.append({(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()})
    faltan = {"anterior", "nuevo", "convertir"} - set(k.strip().lower() for k in (lector.fieldnames or []))
    if faltan:
        raise ErrorRegularizacion(
            f"La planilla no tiene las columnas {sorted(faltan)}. ¿Es la que generó `diagnostico`?")
    return filas


def _quiere_convertir(valor: str) -> bool:
    return (valor or "").strip().lower() in ("si", "sí")


# ---------------------------------------------------------------------------
# Aplicar
# ---------------------------------------------------------------------------
@dataclass
class Cambio:
    anterior: str
    nuevo: str
    tipo: str = ""
    origen: str = ""
    nombre: str = ""
    filas: int = 0
    detalle: dict = field(default_factory=dict)


@dataclass
class Resultado:
    cambios: list
    por_columna: dict
    rutas: dict
    aplicado: bool
    backup: Optional[Path] = None
    antes: dict = field(default_factory=dict)       # resumen_de_filas() antes de convertir
    despues: dict = field(default_factory=dict)     # ... y de cómo quedaría / quedó


def _cambios_de_la_planilla(filas) -> list:
    """Las filas con convertir=si, ya con los números normalizados. Valida
    todo lo que se puede validar SIN mirar la base; junta TODOS los errores."""
    cambios, errores = [], []
    for i, fila in enumerate(filas, start=2):          # la fila 1 es el encabezado
        if not _quiere_convertir(fila.get("convertir", "")):
            continue
        viejo = cuit.normalizar(fila.get("anterior", ""))
        nuevo = cuit.normalizar(fila.get("nuevo", ""))
        donde = f"fila {i} ({fila.get('anterior', '')!r} -> {fila.get('nuevo', '')!r})"
        if len(viejo) != 11:
            errores.append(f"{donde}: 'anterior' no tiene 11 dígitos. Si abriste la planilla en "
                           "Excel, revisá que no haya convertido el número a notación científica.")
            continue
        if not nuevo:
            errores.append(f"{donde}: dice convertir=si pero no tiene 'nuevo'.")
            continue
        if cuit.es_valido(viejo):
            errores.append(f"{donde}: el anterior ya cumple el módulo 11; esta herramienta no renumera "
                           "números válidos.")
        if not cuit.es_valido(nuevo):
            errores.append(f"{donde}: el nuevo no es un CUIL/CUIT válido (verificador o prefijo).")
        elif cuit.tipo(nuevo) != cuit.tipo(viejo):
            errores.append(f"{donde}: cambia de tipo ({cuit.tipo(viejo) or '?'} -> {cuit.tipo(nuevo)}); "
                           "el nuevo tiene que ser de la misma clase que el anterior.")
        cambios.append(Cambio(anterior=viejo, nuevo=nuevo, tipo=cuit.tipo(viejo)))

    vistos_viejos, vistos_nuevos = defaultdict(int), defaultdict(int)
    for c in cambios:
        vistos_viejos[c.anterior] += 1
        vistos_nuevos[c.nuevo] += 1
    for numero, n in sorted(vistos_viejos.items()):
        if n > 1:
            errores.append(f"El anterior {numero} está {n} veces en la planilla.")
    for numero, n in sorted(vistos_nuevos.items()):
        if n > 1:
            errores.append(f"El nuevo {numero} está repetido en {n} filas: dos números distintos "
                           "no pueden quedar con el mismo. Esta herramienta no fusiona personas.")
    todos_los_viejos = set(vistos_viejos)
    for c in cambios:
        if c.nuevo in todos_los_viejos and c.nuevo != c.anterior:
            errores.append(f"El nuevo {c.nuevo} (de {c.anterior}) es a la vez el anterior de otra fila: "
                           "habría que convertir en cadena y no se hace.")
    if errores:
        raise ErrorRegularizacion("La planilla no se puede aplicar (no se escribió nada):", errores)
    return cambios


def _validar_contra_la_base(cambios: list, esc: Escaneo) -> None:
    errores = []
    ocupados = esc.ocupados
    for c in cambios:
        if c.anterior not in ocupados:
            errores.append(f"El anterior {c.anterior} no está en la base (¿ya se convirtió, o la "
                           "planilla es de otro entorno?).")
        if c.nuevo in ocupados:
            errores.append(
                f"El nuevo {c.nuevo} (de {c.anterior}) YA existe en la base. Esta herramienta no "
                "fusiona dos personas ni dos empresas: si es la misma persona con un dígito mal "
                "tipeado hay que resolverlo a mano; si no, usá otro número (columna 'alternativa').")
    if errores:
        raise ErrorRegularizacion("La planilla no se puede aplicar (no se escribió nada):", errores)


def _reescribir_texto(conn, c: Columna, mapa: dict) -> dict:
    """UPDATE de una columna de texto. Los valores se toman de a uno (distintos)
    y cada uno se reescribe EN EL FORMATO que tenía ('30-11111111-1' sigue con
    guiones). Devuelve {número viejo: filas}."""
    tabla, col = f'"{c.tabla}"', f'"{c.columna}"'
    valores = [r[0] for r in conn.execute(sa.text(
        f"SELECT DISTINCT {col} FROM {tabla} WHERE {col} IS NOT NULL AND {col} <> ''"))]
    filas = defaultdict(int)
    for valor in valores:
        if not _es_hoja_de_numero(valor):
            continue
        numero = cuit.normalizar(valor)
        if numero not in mapa:
            continue
        r = conn.execute(sa.text(f"UPDATE {tabla} SET {col} = :nuevo WHERE {col} = :viejo"),
                         {"nuevo": cuit.con_formato_de(valor, mapa[numero]), "viejo": valor})
        filas[numero] += r.rowcount
    return dict(filas)


LOTE_DE_FILAS = 1000


def _reescribir_json(conn, c: Columna, mapa: dict, rutas: dict) -> dict:
    """UPDATE de una columna JSON: recorre todas las filas (de a LOTE_DE_FILAS,
    por id) y reescribe SOLO las que mencionan algún número a convertir. El
    costo es el de leer la tabla una vez, no crece con la cantidad de números
    de la planilla (probado con 2.600 números sobre 30.000 recibos). Se pagina
    por id y no con un cursor abierto porque entre lote y lote se escribe, en
    la misma conexión. Devuelve {número viejo: filas} y suma a `rutas` las
    rutas tocadas."""
    donde = f" AND ({c.donde})" if c.donde else ""
    leer = sa.text(f'SELECT id, "{c.columna}" FROM "{c.tabla}" WHERE id > :ultimo{donde} '
                   f"ORDER BY id LIMIT {LOTE_DE_FILAS}")
    actualizar = sa.text(f'UPDATE "{c.tabla}" SET "{c.columna}" = :doc WHERE id = :id').bindparams(
        sa.bindparam("doc", type_=postgresql.JSONB))
    filas = defaultdict(int)
    ultimo = 0
    while True:
        lote = conn.execute(leer, {"ultimo": ultimo}).all()
        if not lote:
            break
        ultimo = lote[-1][0]
        cambiadas = []
        for id_, doc in lote:
            tocados = set()

            def reemplazar(ruta, hoja):
                numero = cuit.normalizar(hoja)
                if numero not in mapa:
                    return None
                tocados.add(numero)
                rutas[f"{c.clave}:{ruta}"] += 1
                if isinstance(hoja, int):
                    return int(mapa[numero])
                return cuit.con_formato_de(hoja, mapa[numero])

            doc, cambio = caminar_json(doc, reemplazar)
            if cambio:
                cambiadas.append({"doc": doc, "id": id_})
                for numero in tocados:
                    filas[numero] += 1
        if cambiadas:
            conn.execute(actualizar, cambiadas)
    return dict(filas)


def _verificar(cambios: list, antes: Escaneo, despues: Escaneo) -> None:
    """Dentro de la transacción y antes del COMMIT: de cada viejo no queda ni
    una aparición, el nuevo tiene EXACTAMENTE las que tenía el viejo (por
    columna y por ruta de JSON), y ningún otro número cambió."""
    errores = []
    viejos = {c.anterior for c in cambios}
    nuevos = {c.nuevo for c in cambios}
    for c in cambios:
        if despues.apariciones.get(c.anterior):
            errores.append(f"{c.anterior}: quedaron apariciones del número viejo en "
                           f"{sorted(despues.apariciones[c.anterior])}")
        if despues.rutas.get(c.anterior):
            errores.append(f"{c.anterior}: quedaron rutas de JSON con el número viejo: "
                           f"{sorted(despues.rutas[c.anterior])}")
        esperado = {k: v for k, v in antes.apariciones[c.anterior].items()}
        obtenido = dict(despues.apariciones.get(c.nuevo, {}))
        if obtenido != esperado:
            errores.append(f"{c.anterior} -> {c.nuevo}: el nuevo tiene {obtenido} y el viejo tenía {esperado}")
        esperado_r = dict(antes.rutas.get(c.anterior, {}))
        obtenido_r = dict(despues.rutas.get(c.nuevo, {}))
        if obtenido_r != esperado_r:
            errores.append(f"{c.anterior} -> {c.nuevo}: las rutas de JSON no coinciden "
                           f"({obtenido_r} contra {esperado_r})")
    for numero in (set(antes.apariciones) | set(despues.apariciones)) - viejos - nuevos:
        if dict(antes.apariciones.get(numero, {})) != dict(despues.apariciones.get(numero, {})):
            errores.append(f"{numero}: cambió y no estaba en la planilla")
    if antes.plano()["rotos"] != despues.plano()["rotos"]:
        errores.append("cambiaron valores que no eran números")
    if errores:
        raise ErrorRegularizacion("La verificación previa al COMMIT falló; se deshace todo:", errores)


def url_para_cliente(url: str) -> str:
    """psql y pg_dump no entienden el '+psycopg' del prefijo de SQLAlchemy."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def hacer_backup(url: str, directorio: Path = RAIZ) -> Path:
    """pg_dump de la base, con el cliente que elige pg_cliente.py (el de la
    misma versión que el servidor), como `promover_demo.py`."""
    url = url_para_cliente(url)
    try:
        version = pg_cliente.version_de_servidor(url, "la base", cwd=directorio)
        comando, de_donde = pg_cliente.cliente_para("pg_dump", version)
    except pg_cliente.ErrorPg as e:
        raise ErrorRegularizacion(f"No se pudo preparar el backup: {e}\n"
                                  "Resolvelo, o corré con --sin-backup si de verdad no querés copia.")
    destino = Path(directorio) / (
        f"backup_regularizacion_{entorno.ENTORNO or 'local'}_{fechas.ahora():%Y-%m-%d-%H%M}.dump")
    with open(destino, "wb") as salida:
        r = subprocess.run([*comando, url, "-Fc", "--no-owner", "--no-privileges"],
                           cwd=directorio, stdout=salida)
    if r.returncode != 0 or not destino.exists() or destino.stat().st_size == 0:
        destino.unlink(missing_ok=True)
        raise ErrorRegularizacion("El backup falló; no se convierte nada sin copia.")
    return destino


def aplicar(planilla, *, si: bool = False, quien: str = "", sin_backup: bool = False,
            engine=None, salida=print, directorio_backup: Path = RAIZ) -> Resultado:
    """Convierte las filas con convertir=si. Sin `si` es un ensayo completo
    (hace los UPDATE y los deshace). Todo o nada: ante cualquier problema se
    lanza ErrorRegularizacion y la base queda como estaba.

    `planilla`: la ruta de un CSV o una lista de dicts con las columnas
    anterior / nuevo / convertir."""
    filas = leer_planilla(planilla) if isinstance(planilla, (str, Path)) else list(planilla)
    cambios = _cambios_de_la_planilla(filas)
    if si and not quien.strip():
        raise ErrorRegularizacion("Con --si hace falta --quien: queda registrado en la traza.")
    if not cambios:
        salida("La planilla no tiene ninguna fila con convertir=si: no hay nada para hacer.")
        return Resultado([], {}, {}, aplicado=False)

    backup = None
    if si and not sin_backup:
        salida("Backup previo de la base (pg_dump)...")
        backup = hacer_backup(db.DATABASE_URL, directorio_backup)
        salida(f"  {backup.name} ({backup.stat().st_size // 1024} KB)")
    elif si:
        salida("ATENCIÓN: se aplica SIN backup (--sin-backup).")

    propio = engine is None
    engine = engine or db.engine_para_migraciones()
    try:
        with engine.connect() as conn:
            tx = conn.begin()
            try:
                resultado = _aplicar_en_transaccion(conn, cambios, si, quien.strip(), salida)
                resultado.backup = backup
                if si:
                    tx.commit()
                    resultado.aplicado = True
                else:
                    tx.rollback()
            except BaseException:
                tx.rollback()
                raise
    except sa.exc.OperationalError as e:
        if "lock" in str(e).lower():
            raise ErrorRegularizacion("La base está ocupada (no se pudo tomar el candado de las tablas "
                                      "en 5 segundos). No se escribió nada; reintentá en un momento.")
        raise
    finally:
        if propio:
            engine.dispose()
    _informe(resultado, si, salida)
    return resultado


def _aplicar_en_transaccion(conn, cambios: list, si: bool, quien: str, salida) -> Resultado:
    verificar_esquema(conn)
    if not sa.inspect(conn).has_table(TABLA_TRAZA):
        raise ErrorRegularizacion(f"Falta la tabla {TABLA_TRAZA}: corré `alembic upgrade head`.")
    if si:
        # Nadie escribe estas tablas mientras dura la conversión (se puede
        # leer). Sin esto, un alta que entre justo después del escaneo dejaría
        # un número viejo sin convertir y la verificación no lo vería. El
        # ensayo no lo toma: no tiene por qué frenar a la app.
        tablas = sorted({c.tabla for c in INVENTARIO} | {TABLA_TRAZA})
        conn.execute(sa.text("LOCK TABLE " + ", ".join(f'"{t}"' for t in tablas) +
                             " IN SHARE ROW EXCLUSIVE MODE"))

    antes = escanear(conn)
    _validar_contra_la_base(cambios, antes)

    por_clave = inventario_por_clave()
    lote = identificadores_de_lote()
    nombres = nombres_de(conn, {c.anterior for c in cambios})
    for c in cambios:
        c.origen = clasificar_origen(c.anterior, antes.apariciones[c.anterior], lote, por_clave)
        c.nombre = nombres.get(c.anterior, "")

    mapa = {c.anterior: c.nuevo for c in cambios}
    filas_por_numero = defaultdict(lambda: defaultdict(int))     # número -> {clave: filas}
    rutas = defaultdict(int)
    for col in INVENTARIO:
        hechas = (_reescribir_texto(conn, col, mapa) if col.valor == TEXTO
                  else _reescribir_json(conn, col, mapa, rutas))
        for numero, n in hechas.items():
            filas_por_numero[numero][col.clave] += n

    for c in cambios:
        c.detalle = dict(filas_por_numero[c.anterior])
        c.filas = sum(c.detalle.values())

    despues = escanear(conn)
    _verificar(cambios, antes, despues)
    resumen_antes = resumen_de_filas(filas_de_escaneo(antes, lote)[0])
    resumen_despues = resumen_de_filas(filas_de_escaneo(despues, lote)[0])

    conn.execute(sa.insert(db.CambioIdentificador.__table__), [{
        "anterior": c.anterior, "nuevo": c.nuevo, "tipo": c.tipo, "origen": c.origen,
        "entorno": entorno.ENTORNO or "local", "fecha": fechas.ahora_texto(),
        "quien": quien, "filas": c.filas, "detalle": c.detalle} for c in cambios])

    por_columna = defaultdict(int)
    for c in cambios:
        for k, v in c.detalle.items():
            por_columna[k] += v
    return Resultado(cambios=cambios, por_columna=dict(por_columna), rutas=dict(rutas),
                     aplicado=False, antes=resumen_antes, despues=resumen_despues)


def _informe(res: Resultado, si: bool, salida) -> None:
    titulo = "CONVERSIÓN APLICADA" if si else "ENSAYO (no se escribió nada; se deshizo todo)"
    salida(f"\n{titulo}: {len(res.cambios)} número(s)")
    salida("  Filas tocadas por tabla.columna:")
    for k in sorted(res.por_columna):
        salida(f"    {k:<42} {res.por_columna[k]}")
    if res.rutas:
        salida("  Rutas dentro de los JSON:")
        for k in sorted(res.rutas):
            salida(f"    {k:<60} {res.rutas[k]}")
    if res.antes:
        for nombre, r in (("Antes  ", res.antes), ("Después", res.despues)):
            origenes = ", ".join(f"{o} {r['por_origen'].get(o, 0)}" for o in ORDEN_ORIGEN)
            salida(f"  {nombre}: {r['para_revisar']} número(s) inválido(s) o rotos ({origenes}); "
                   f"convertibles sin colisión: {r['convertibles']}; con colisión: {r['colisiones']}")
    salida("\nTienen que enterarse: entran con el número NUEVO (la clave no cambia). Quien tenga la "
           "sesión abierta con el viejo queda sin acceso hasta que vuelva a entrar (como mucho 15 "
           "minutos).")
    for c in sorted(res.cambios, key=lambda c: (c.tipo, c.anterior)):
        salida(f"    {c.tipo:<8} {c.nombre or '(sin nombre)':<34} {c.anterior} -> {c.nuevo}   [{c.origen}]")
    if not si:
        salida("\nPara aplicarlo de verdad: el mismo comando con --si --quien <iniciales>.")


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------
def _nombre_de_base() -> str:
    u = db.engine.url
    return f"{u.host or 'local'}/{u.database}"


def comando_diagnostico(args) -> int:
    engine = db.engine_para_migraciones()
    try:
        with engine.connect() as conn:
            diag = diagnosticar(conn)
            conn.rollback()
    except ErrorRegularizacion as e:
        print(f"ABORTADO: {e}")
        return 1
    finally:
        engine.dispose()
    salida = Path(args.salida or f"regularizacion_cuit_{diag.entorno}.csv")
    escribir_planilla(diag, salida, separador=args.separador)
    print(resumen_texto(diag, _nombre_de_base()))
    print(f"\nPlanilla: {salida} ({len(diag.filas)} fila(s)). Se abre con Excel; editá solo la "
          "columna 'convertir' y, si hace falta, 'nuevo'.")
    return 0


def comando_aplicar(args) -> int:
    if args.si and not (args.quien or "").strip():
        print("ABORTADO: con --si hace falta --quien <iniciales> (queda en la traza).")
        return 2
    try:
        aplicar(args.planilla, si=args.si, quien=args.quien or "", sin_backup=args.sin_backup)
    except ErrorRegularizacion as e:
        print(f"ABORTADO: {e}")
        for linea in e.errores:
            print(f"  - {linea}")
        return 1
    return 0


def armar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Regulariza los CUIL/CUIT que no cumplen el módulo 11 (PLAN_CUIT_MOD11.md).")
    sub = ap.add_subparsers(dest="comando", required=True)
    d = sub.add_parser("diagnostico", help="solo lectura: resumen y planilla CSV")
    d.add_argument("--salida", help="ruta del CSV (default regularizacion_cuit_<entorno>.csv)")
    d.add_argument("--separador", default=SEPARADOR, choices=[";", ","],
                   help="separador del CSV (default ';', el de Excel en español)")
    d.set_defaults(func=comando_diagnostico)
    a = sub.add_parser("aplicar", help="convierte las filas con convertir=si (ensayo sin --si)")
    a.add_argument("--planilla", required=True, help="el CSV que salió de `diagnostico`, ya revisado")
    a.add_argument("--si", action="store_true", help="aplicar de verdad (sin esto es un ensayo)")
    a.add_argument("--quien", default="", help="iniciales de quien lo corre (obligatorio con --si)")
    a.add_argument("--sin-backup", action="store_true", help="no hacer pg_dump antes (no recomendado)")
    a.set_defaults(func=comando_aplicar)
    return ap


def main(argv=None) -> int:
    args = armar_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

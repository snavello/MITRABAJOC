"""Panel Sindical (docs/DASHBOARD.md): agregados SQL para el dashboard del
admin de sindicato.

Reglas que este módulo respeta a rajatabla:
- TODO agregado se calcula en SQL, filtrado SIEMPRE por sindicato_id primero
  (los índices compuestos empiezan por esa columna). Jamás se traen registros
  crudos masivos para agregarlos en Python.
- El aislamiento de tenant está en el WHERE de cada consulta, no en un filtro
  posterior: el sindicato_id viene de la sesión (main.py), nunca de un
  parámetro del request.
- Privacidad del detalle de recibos: nombre y CUIL del trabajador se incluyen
  ÚNICAMENTE si el recibo fue enviado voluntariamente al sindicato
  (enviado_sindicato = true). La regla vive acá, en el servidor -- el
  frontend nunca recibe el dato que no corresponde.
- Fechas: las columnas analíticas guardan strings ordenables
  ("AAAA-MM-DD HH:MM"), así el rango se filtra por comparación de strings y
  usa el índice tanto en Postgres como en SQLite (tests).

Los nombres/etiquetas (seccionales, empresas) se resuelven en Python contra
los catálogos del tenant (chicos), para no depender del formato con el que se
haya cargado cada CUIT en el CRUD de Empleadores.
"""
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import bindparam, text

import db
from validador import _norm_cuil, a_numero


# Estados del dashboard (3) <- estados reales de Tramite (5).
ESTADOS_TRAMITE_DASHBOARD = {
    "abierto": ["iniciado"],
    "en_proceso": ["en_tratamiento", "respondido", "espera_info"],
    "resuelto": ["terminado"],
}
# CASE portable (SQLite y Postgres) que pliega el estado real al del dashboard.
_CASE_ESTADO_TRAMITE = (
    "CASE WHEN tr.estado = 'iniciado' THEN 'abierto' "
    "WHEN tr.estado = 'terminado' THEN 'resuelto' "
    "ELSE 'en_proceso' END"
)

# Tipos de notificación del dashboard = orígenes reales de Notificacion.
TIPOS_NOTIF = {"manual": "Comunicaciones", "sistema": "Trámites"}

RANGO_MAXIMO_DIAS = 366


# ---------- Columnas analíticas de ReciboVerificado ----------

def _fecha_iso_de_ar(valor: Optional[str]) -> Optional[str]:
    """"10/06/2026" (como la imprime un recibo) -> "2026-06-10". Tolera que
    ya venga en ISO. None/ilegible -> None, nunca revienta: es salida de IA."""
    if not valor or not isinstance(valor, str):
        return None
    valor = valor.strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(valor, formato).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def campos_analiticos(recibo: dict, resultado: dict) -> dict:
    """Los campos SQL del Panel Sindical, derivados del mismo par
    recibo/resultado que se guarda en ReciboVerificado.detalle. La migración
    de backfill replica esta misma lógica sobre las filas viejas."""
    formulas = resultado.get("formulas_validadas") or []
    monto = 0.0
    for fv in formulas:
        if not fv.get("ok"):
            dif = a_numero(fv.get("diferencia"))
            if dif is not None:
                monto += abs(dif)
    totales = resultado.get("totales") or {}
    return {
        "procesado_en": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cuit_empleador": _norm_cuil((recibo.get("empleador") or {}).get("cuit")),
        "categoria": ((recibo.get("empleado") or {}).get("categoria") or "").strip(),
        "formato": recibo.get("formato") or "",
        "bruto": a_numero(totales.get("ingresos")),
        "monto_diferencia": round(monto, 2),
        "fecha_ultimo_deposito": _fecha_iso_de_ar(
            (recibo.get("ultimo_deposito") or {}).get("fecha")
            if isinstance(recibo.get("ultimo_deposito"), dict) else None),
    }


# ---------- Filtros comunes (§3.1) ----------

def parsear_filtros(params, hoy: Optional[date] = None) -> dict:
    """Valida y normaliza los query params comunes del dashboard.
    `params` es un QueryParams de Starlette (o cualquier cosa con .get y
    .getlist). Lanza ValueError con mensaje mostrable si algo no cierra.
    Cada endpoint después usa solo las claves que le aplican."""
    hoy = hoy or date.today()

    def _fecha(nombre):
        crudo = params.get(nombre)
        if not crudo:
            raise ValueError(f"Falta el parámetro obligatorio '{nombre}' (AAAA-MM-DD).")
        try:
            return date.fromisoformat(crudo)
        except ValueError:
            raise ValueError(f"'{nombre}' tiene que ser una fecha AAAA-MM-DD.")

    desde, hasta = _fecha("desde"), _fecha("hasta")
    if hasta > hoy:
        raise ValueError("'hasta' no puede ser una fecha futura.")
    if desde > hasta:
        raise ValueError("'desde' no puede ser posterior a 'hasta'.")
    if (hasta - desde).days + 1 > RANGO_MAXIMO_DIAS:
        raise ValueError(f"El rango máximo es de {RANGO_MAXIMO_DIAS} días.")

    def _ids(nombre):
        valores = []
        for crudo in params.getlist(nombre):
            for pedazo in str(crudo).split(","):
                pedazo = pedazo.strip()
                if not pedazo:
                    continue
                try:
                    valores.append(int(pedazo))
                except ValueError:
                    raise ValueError(f"'{nombre}' lleva ids numéricos.")
        return valores

    def _entero(nombre):
        crudo = params.get(nombre)
        if crudo in (None, ""):
            return None
        try:
            return int(crudo)
        except ValueError:
            raise ValueError(f"'{nombre}' tiene que ser un entero (pesos).")

    formato = params.get("formato") or ""
    # La spec habla de "viejo"; el extractor persiste "clasico".
    formato = {"viejo": "clasico", "clasico": "clasico", "nuevo": "nuevo", "": ""}.get(formato)
    if formato is None:
        raise ValueError("'formato' admite 'viejo' o 'nuevo'.")

    resultado = params.get("resultado") or ""
    resultado = {"ok": "OK", "con_diferencias": "CON_DISCREPANCIAS", "": ""}.get(resultado)
    if resultado is None:
        raise ValueError("'resultado' admite 'ok' o 'con_diferencias'.")

    estado_tramite = params.get("estado_tramite") or ""
    if estado_tramite and estado_tramite not in ESTADOS_TRAMITE_DASHBOARD:
        raise ValueError("'estado_tramite' admite 'abierto', 'en_proceso' o 'resuelto'.")

    tipo_notif = params.get("tipo_notif") or ""
    if tipo_notif and tipo_notif not in TIPOS_NOTIF:
        raise ValueError("'tipo_notif' admite 'manual' o 'sistema'.")

    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "desde_ts": desde.isoformat() + " 00:00", "hasta_ts": hasta.isoformat() + " 23:59",
        "dias": (hasta - desde).days + 1,
        "seccionales": _ids("seccionales"),
        "empresas": _ids("empresas"),
        "categoria": (params.get("categoria") or "").strip(),
        "formato": formato,
        "sal_min": _entero("sal_min"), "sal_max": _entero("sal_max"),
        "resultado": resultado,
        "estado_tramite": estado_tramite,
        "tipo_notif": tipo_notif,
        "tema": (params.get("tema") or "").strip(),
    }


def _rango_previo(f: dict) -> dict:
    """El período inmediato anterior de igual longitud, para los deltas."""
    desde = date.fromisoformat(f["desde"])
    hasta_prev = desde - timedelta(days=1)
    desde_prev = hasta_prev - timedelta(days=f["dias"] - 1)
    return dict(f, desde=desde_prev.isoformat(), hasta=hasta_prev.isoformat(),
                desde_ts=desde_prev.isoformat() + " 00:00",
                hasta_ts=hasta_prev.isoformat() + " 23:59")


# ---------- Catálogos del tenant (labels y resolución de filtros) ----------

def limites_bruto(sid: int) -> tuple:
    """Límites del slider de remuneración bruta (§4.3): percentiles 1 y 99
    del tenant, para que un outlier no estire la escala. percentile_cont es
    de Postgres; en SQLite (tests) se cae a MIN/MAX, que para bases chicas
    es lo mismo."""
    with db.get_session() as s:
        if db.USANDO_POSTGRES:
            fila = s.execute(text("""
                SELECT percentile_cont(0.01) WITHIN GROUP (ORDER BY bruto),
                       percentile_cont(0.99) WITHIN GROUP (ORDER BY bruto)
                FROM reciboverificado
                WHERE sindicato_id = :sid AND bruto IS NOT NULL"""),
                {"sid": sid}).one()
        else:
            fila = s.execute(text(
                "SELECT MIN(bruto), MAX(bruto) FROM reciboverificado "
                "WHERE sindicato_id = :sid AND bruto IS NOT NULL"), {"sid": sid}).one()
    return fila[0], fila[1]


def catalogo_empresas(sid: int) -> list:
    """Empleadores del sindicato con su CUIT normalizado -- para poblar el
    filtro de empresas y para etiquetar cuits en gráficos/tablas."""
    with db.get_session() as s:
        filas = s.execute(text(
            "SELECT id, cuit, razon_social FROM empleador "
            "WHERE sindicato_id = :sid AND activo ORDER BY razon_social, cuit"
        ), {"sid": sid}).all()
    return [{"id": fila[0], "cuit": _norm_cuil(fila[1]),
             "nombre": fila[2] or fila[1]} for fila in filas]


def _cuits_de_empresas(sid: int, ids: list) -> Optional[list]:
    """ids de Empleador (del PROPIO sindicato) -> CUITs normalizados. Un id
    ajeno o inexistente no resuelve a nada: si el filtro vino con ids y
    ninguno es del tenant, devuelve [] y el que llama no matchea NADA (nunca
    "todo"). None = sin filtro."""
    if not ids:
        return None
    return [e["cuit"] for e in catalogo_empresas(sid) if e["id"] in set(ids)]


def _etiquetas_empresas(sid: int) -> dict:
    return {e["cuit"]: e["nombre"] for e in catalogo_empresas(sid)}


def _etiquetas_seccionales(sid: int) -> dict:
    with db.get_session() as s:
        filas = s.execute(text(
            "SELECT id, nombre FROM seccional WHERE sindicato_id = :sid"
        ), {"sid": sid}).all()
    return {fila[0]: fila[1] for fila in filas}


# ---------- Armado de WHERE por fuente ----------

def _stmt(sql: str, params: dict):
    """text() con IN(...) expandibles para los parámetros que son listas."""
    stmt = text(sql)
    expandibles = [bindparam(k, expanding=True) for k, v in params.items()
                   if isinstance(v, list)]
    return stmt.bindparams(*expandibles) if expandibles else stmt


def _sql_recibos(sid: int, f: dict, extra_conds: str = "", forzar_join: bool = False):
    """(joins, WHERE, params) de la fuente recibos con los filtros que le
    aplican. El join a trabajador (por seccional) solo se agrega si hace
    falta -- es LEFT: un recibo sin fila en el padrón no desaparece de los
    totales, solo queda "sin seccional"."""
    conds = ["r.sindicato_id = :sid",
             "r.procesado_en >= :desde_ts", "r.procesado_en <= :hasta_ts"]
    params = {"sid": sid, "desde_ts": f["desde_ts"], "hasta_ts": f["hasta_ts"]}
    joins = ""
    if f["seccionales"] or forzar_join:
        joins = (" LEFT JOIN trabajador t ON t.sindicato_id = r.sindicato_id "
                 "AND t.cuil = r.cuil")
    if f["seccionales"]:
        conds.append("t.seccional_id IN :seccionales")
        params["seccionales"] = f["seccionales"]
    cuits = _cuits_de_empresas(sid, f["empresas"])
    if cuits is not None:
        conds.append("r.cuit_empleador IN :cuits")
        params["cuits"] = cuits or ["__ninguna__"]
    if f["categoria"]:
        conds.append("r.categoria = :categoria")
        params["categoria"] = f["categoria"]
    if f["formato"]:
        conds.append("r.formato = :formato")
        params["formato"] = f["formato"]
    if f["sal_min"] is not None:
        conds.append("r.bruto >= :sal_min")
        params["sal_min"] = f["sal_min"]
    if f["sal_max"] is not None:
        conds.append("r.bruto <= :sal_max")
        params["sal_max"] = f["sal_max"]
    if f["resultado"]:
        conds.append("r.estado = :resultado")
        params["resultado"] = f["resultado"]
    if extra_conds:
        conds.append(extra_conds)
    return joins, " AND ".join(conds), params


def _sql_tramites(sid: int, f: dict, forzar_join: bool = False):
    conds = ["tr.sindicato_id = :sid",
             "tr.creado >= :desde_ts", "tr.creado <= :hasta_ts"]
    params = {"sid": sid, "desde_ts": f["desde_ts"], "hasta_ts": f["hasta_ts"]}
    joins = ""
    if f["seccionales"] or forzar_join:
        joins = (" LEFT JOIN trabajador t ON t.sindicato_id = tr.sindicato_id "
                 "AND t.cuil = tr.cuil")
    if f["seccionales"]:
        conds.append("t.seccional_id IN :seccionales")
        params["seccionales"] = f["seccionales"]
    if f["estado_tramite"]:
        conds.append("tr.estado IN :estados")
        params["estados"] = ESTADOS_TRAMITE_DASHBOARD[f["estado_tramite"]]
    return joins, " AND ".join(conds), params


def _sql_notificaciones(sid: int, f: dict, forzar_join: bool = False):
    """Base: destinatarios (una fila por CUIL notificado) con su Notificacion.
    La seccional es la ACTUAL del trabajador destinatario (§1.1: se deriva
    del dueño del dato)."""
    conds = ["n.sindicato_id = :sid",
             "n.enviado_en >= :desde_ts", "n.enviado_en <= :hasta_ts"]
    params = {"sid": sid, "desde_ts": f["desde_ts"], "hasta_ts": f["hasta_ts"]}
    joins = " JOIN notificacion n ON n.id = d.notificacion_id"
    if f["seccionales"] or forzar_join:
        joins += (" LEFT JOIN trabajador t ON t.sindicato_id = n.sindicato_id "
                  "AND t.cuil = d.cuil")
    if f["seccionales"]:
        conds.append("t.seccional_id IN :seccionales")
        params["seccionales"] = f["seccionales"]
    if f["tipo_notif"]:
        conds.append("n.origen = :tipo_notif")
        params["tipo_notif"] = f["tipo_notif"]
    return joins, " AND ".join(conds), params


def _sql_consultas(sid: int, f: dict, forzar_join: bool = False):
    conds = ["c.sindicato_id = :sid",
             "c.creado >= :desde_ts", "c.creado <= :hasta_ts"]
    params = {"sid": sid, "desde_ts": f["desde_ts"], "hasta_ts": f["hasta_ts"]}
    joins = ""
    if f["seccionales"] or forzar_join:
        joins = (" LEFT JOIN trabajador t ON t.sindicato_id = c.sindicato_id "
                 "AND t.cuil = c.cuil")
    if f["seccionales"]:
        conds.append("t.seccional_id IN :seccionales")
        params["seccionales"] = f["seccionales"]
    if f["tema"]:
        conds.append("c.tema = :tema")
        params["tema"] = f["tema"]
    return joins, " AND ".join(conds), params


def _uno(s, sql: str, params: dict):
    return s.execute(_stmt(sql, params), params).one()


# ---------- Agregados (§3.2) ----------

def _kpis_de_rango(s, sid: int, f: dict) -> dict:
    joins, where, params = _sql_recibos(sid, f)
    fila = _uno(s, f"""
        SELECT COUNT(*),
               COALESCE(SUM(CASE WHEN r.estado = 'CON_DISCREPANCIAS' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(r.monto_diferencia), 0),
               COALESCE(SUM(CASE WHEN r.enviado_sindicato THEN 1 ELSE 0 END), 0)
        FROM reciboverificado r{joins} WHERE {where}""", params)
    recibos, con_dif, monto, enviados = fila

    joins, where, params = _sql_tramites(sid, f)
    fila = _uno(s, f"""
        SELECT COUNT(*),
               COALESCE(SUM(CASE WHEN tr.estado != 'terminado' THEN 1 ELSE 0 END), 0)
        FROM tramite tr{joins} WHERE {where}""", params)
    tramites, tramites_sin_resolver = fila

    joins, where, params = _sql_notificaciones(sid, f)
    fila = _uno(s, f"""
        SELECT COUNT(*),
               COALESCE(SUM(CASE WHEN d.leida_en IS NOT NULL THEN 1 ELSE 0 END), 0)
        FROM notificaciondestinatario d{joins} WHERE {where}""", params)
    notif_enviadas, notif_leidas = fila

    return {
        "recibos": recibos,
        "pct_con_diferencias": round(con_dif / recibos * 100, 1) if recibos else 0.0,
        "monto_observado": round(float(monto), 2),
        "enviados_sindicato": enviados,
        "tramites": tramites,
        "tramites_sin_resolver": tramites_sin_resolver,
        "notif_enviadas": notif_enviadas,
        "tasa_lectura": round(notif_leidas / notif_enviadas * 100, 1) if notif_enviadas else None,
    }


def kpis(sid: int, f: dict) -> dict:
    """Los KPIs del período + los mismos valores del período inmediato
    anterior de igual longitud (para los deltas), en un solo JSON."""
    with db.get_session() as s:
        actual = _kpis_de_rango(s, sid, f)
        anterior = _kpis_de_rango(s, sid, _rango_previo(f))

        # Afiliados registrados: foto del padrón (sin rango de fechas); le
        # aplican seccional y empresa. REPLACE normaliza el CUIT cargado a
        # mano en el padrón (puede venir con guiones).
        conds = ["sindicato_id = :sid", "activo"]
        params = {"sid": sid}
        if f["seccionales"]:
            conds.append("seccional_id IN :seccionales")
            params["seccionales"] = f["seccionales"]
        cuits = _cuits_de_empresas(sid, f["empresas"])
        if cuits is not None:
            conds.append("REPLACE(REPLACE(COALESCE(cuit_empleador, ''), '-', ''), ' ', '') IN :cuits")
            params["cuits"] = cuits or ["__ninguna__"]
        fila = _uno(s, f"""
            SELECT COUNT(*),
                   COALESCE(SUM(CASE WHEN registrado THEN 1 ELSE 0 END), 0)
            FROM trabajador WHERE {' AND '.join(conds)}""", params)
        padron_total, padron_registrados = fila

        consultas = None
        if db.config_dashboard()["consultas_bot_habilitado"]:
            joins, where, params = _sql_consultas(sid, f)
            consultas = _uno(s, f"SELECT COUNT(*) FROM consultaconvenio c{joins} WHERE {where}",
                             params)[0]

    actual.update({"padron_total": padron_total, "padron_registrados": padron_registrados,
                   "consultas": consultas})
    return {"actual": actual, "anterior": anterior,
            "rango": {"desde": f["desde"], "hasta": f["hasta"], "dias": f["dias"]}}


def serie_recibos(sid: int, f: dict) -> list:
    """Recibos procesados por día del rango, con los días sin datos en 0."""
    joins, where, params = _sql_recibos(sid, f)
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT substr(r.procesado_en, 1, 10) AS dia, COUNT(*)
            FROM reciboverificado r{joins} WHERE {where}
            GROUP BY dia ORDER BY dia""", params), params).all()
    por_dia = {fila[0]: fila[1] for fila in filas}
    desde = date.fromisoformat(f["desde"])
    return [{"dia": (desde + timedelta(days=i)).isoformat(),
             "cantidad": por_dia.get((desde + timedelta(days=i)).isoformat(), 0)}
            for i in range(f["dias"])]


def validacion(sid: int, f: dict) -> dict:
    """Conteo por resultado. Dos estados: no existe "en revisión" a nivel
    recibo (decisión de Sd del 2026-08-29)."""
    joins, where, params = _sql_recibos(sid, f)
    with db.get_session() as s:
        fila = _uno(s, f"""
            SELECT COALESCE(SUM(CASE WHEN r.estado = 'OK' THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN r.estado = 'CON_DISCREPANCIAS' THEN 1 ELSE 0 END), 0)
            FROM reciboverificado r{joins} WHERE {where}""", params)
    return {"ok": fila[0], "con_diferencias": fila[1]}


def diferencias_empresa(sid: int, f: dict) -> list:
    """Top 6 empresas por monto total de diferencias del período. El filtro
    de resultado no le aplica (este gráfico ES de los con diferencias)."""
    f = dict(f, resultado="")
    joins, where, params = _sql_recibos(sid, f, extra_conds="r.estado = 'CON_DISCREPANCIAS'")
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT r.cuit_empleador, COALESCE(SUM(r.monto_diferencia), 0), COUNT(*)
            FROM reciboverificado r{joins} WHERE {where}
            GROUP BY r.cuit_empleador
            ORDER BY SUM(r.monto_diferencia) DESC LIMIT 6""", params), params).all()
    etiquetas = _etiquetas_empresas(sid)
    ids = {e["cuit"]: e["id"] for e in catalogo_empresas(sid)}
    return [{"cuit": fila[0], "empresa_id": ids.get(fila[0]),
             "nombre": etiquetas.get(fila[0]) or fila[0] or "Sin CUIT legible",
             "monto": round(float(fila[1]), 2), "recibos": fila[2]} for fila in filas]


def tramites_seccional(sid: int, f: dict) -> dict:
    """Matriz seccional × estado (3 estados del dashboard) con conteos."""
    joins, where, params = _sql_tramites(sid, f, forzar_join=True)
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT t.seccional_id, {_CASE_ESTADO_TRAMITE} AS estado_d, COUNT(*)
            FROM tramite tr{joins} WHERE {where}
            GROUP BY t.seccional_id, estado_d""", params), params).all()
    nombres = _etiquetas_seccionales(sid)
    matriz = {}
    for secc_id, estado_d, cantidad in filas:
        clave = secc_id or 0
        fila = matriz.setdefault(clave, {
            "seccional_id": secc_id,
            "seccional": nombres.get(secc_id, "Sin seccional"),
            "abierto": 0, "en_proceso": 0, "resuelto": 0})
        fila[estado_d] += cantidad
    orden = sorted(matriz.values(), key=lambda x: -(x["abierto"] + x["en_proceso"] + x["resuelto"]))
    return {"seccionales": orden}


def notificaciones(sid: int, f: dict) -> dict:
    """Totales enviadas/leídas y desglose por tipo (origen real)."""
    joins, where, params = _sql_notificaciones(sid, f)
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT n.origen, COUNT(*),
                   COALESCE(SUM(CASE WHEN d.leida_en IS NOT NULL THEN 1 ELSE 0 END), 0)
            FROM notificaciondestinatario d{joins} WHERE {where}
            GROUP BY n.origen""", params), params).all()
    por_tipo = []
    enviadas = leidas = 0
    conteos = {fila[0]: (fila[1], fila[2]) for fila in filas}
    for origen, etiqueta in TIPOS_NOTIF.items():
        env, lei = conteos.get(origen, (0, 0))
        enviadas, leidas = enviadas + env, leidas + lei
        por_tipo.append({"tipo": origen, "etiqueta": etiqueta,
                         "enviadas": env, "leidas": lei, "sin_leer": env - lei})
    # Un origen fuera del catálogo (futuro) no se pierde: se suma igual.
    for origen, (env, lei) in conteos.items():
        if origen not in TIPOS_NOTIF:
            enviadas, leidas = enviadas + env, leidas + lei
            por_tipo.append({"tipo": origen, "etiqueta": origen.capitalize(),
                             "enviadas": env, "leidas": lei, "sin_leer": env - lei})
    return {"enviadas": enviadas, "leidas": leidas, "sin_leer": enviadas - leidas,
            "tasa_lectura": round(leidas / enviadas * 100, 1) if enviadas else None,
            "por_tipo": por_tipo}


def formato_semana(sid: int, f: dict) -> list:
    """Recibos por formato agrupados por semana (lunes como inicio). Se
    agrega por día en SQL y se pliega a semanas en Python: son <=366 filas.
    El filtro de formato no le aplica (el gráfico compara ambos)."""
    f = dict(f, formato="")
    joins, where, params = _sql_recibos(sid, f)
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT substr(r.procesado_en, 1, 10) AS dia, r.formato, COUNT(*)
            FROM reciboverificado r{joins} WHERE {where}
            GROUP BY dia, r.formato ORDER BY dia""", params), params).all()
    semanas = {}
    for dia, formato, cantidad in filas:
        fecha = date.fromisoformat(dia)
        lunes = (fecha - timedelta(days=fecha.weekday())).isoformat()
        sem = semanas.setdefault(lunes, {"semana": lunes, "clasico": 0, "nuevo": 0})
        sem["nuevo" if formato == "nuevo" else "clasico"] += cantidad
    return [semanas[k] for k in sorted(semanas)]


def semaforo(sid: int, f: dict, hoy: Optional[date] = None) -> dict:
    """Por empresa del tenant: MAX(fecha_ultimo_deposito) sobre sus recibos,
    días transcurridos y estado según umbrales de plataforma. Es una foto del
    estado ACTUAL: el rango de fechas no le aplica (sí seccional/empresa)."""
    hoy = hoy or date.today()
    conds = ["r.sindicato_id = :sid", "r.fecha_ultimo_deposito IS NOT NULL",
             "r.cuit_empleador != ''"]
    params = {"sid": sid}
    joins = ""
    if f["seccionales"]:
        joins = (" LEFT JOIN trabajador t ON t.sindicato_id = r.sindicato_id "
                 "AND t.cuil = r.cuil")
        conds.append("t.seccional_id IN :seccionales")
        params["seccionales"] = f["seccionales"]
    cuits = _cuits_de_empresas(sid, f["empresas"])
    if cuits is not None:
        conds.append("r.cuit_empleador IN :cuits")
        params["cuits"] = cuits or ["__ninguna__"]
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT r.cuit_empleador, MAX(r.fecha_ultimo_deposito)
            FROM reciboverificado r{joins} WHERE {' AND '.join(conds)}
            GROUP BY r.cuit_empleador""", params), params).all()
    cfg = db.config_dashboard()
    verde, amarillo = cfg["semaforo_verde_hasta_dias"], cfg["semaforo_amarillo_hasta_dias"]
    etiquetas = _etiquetas_empresas(sid)
    empresas, resumen = [], {"verde": 0, "amarillo": 0, "rojo": 0}
    for cuit, fecha_dep in filas:
        try:
            dias = (hoy - date.fromisoformat(fecha_dep)).days
        except ValueError:
            continue
        estado = "verde" if dias <= verde else ("amarillo" if dias <= amarillo else "rojo")
        resumen[estado] += 1
        empresas.append({"cuit": cuit, "nombre": etiquetas.get(cuit) or cuit,
                         "ultimo_deposito": fecha_dep, "dias": dias, "estado": estado})
    empresas.sort(key=lambda e: -e["dias"])
    return {"resumen": resumen, "empresas": empresas,
            "umbrales": {"verde_hasta": verde, "amarillo_hasta": amarillo}}


def consultas_por_tema(sid: int, f: dict) -> list:
    """Conteo por tema. El gate del feature flag lo hace la ruta (404)."""
    joins, where, params = _sql_consultas(sid, f)
    with db.get_session() as s:
        filas = s.execute(_stmt(f"""
            SELECT COALESCE(c.tema, 'Sin clasificar'), COUNT(*)
            FROM consultaconvenio c{joins} WHERE {where}
            GROUP BY c.tema ORDER BY COUNT(*) DESC""", params), params).all()
    return [{"tema": fila[0], "cantidad": fila[1]} for fila in filas]


# ---------- Explorador de datos (§3.3) ----------

PAGINA_DEFAULT, PAGINA_MAXIMA = 10, 50


def _paginacion(params) -> tuple:
    try:
        page = max(1, int(params.get("page") or 1))
        page_size = int(params.get("page_size") or PAGINA_DEFAULT)
    except ValueError:
        raise ValueError("'page' y 'page_size' tienen que ser enteros.")
    page_size = max(1, min(page_size, PAGINA_MAXIMA))
    return page, page_size


def explorador_recibos(sid: int, f: dict, page: int, page_size: int) -> dict:
    """Detalle de recibos con diferencias, ordenado por monto observado desc.
    PRIVACIDAD (§1.3, con test): nombre y CUIL van SOLO si el trabajador
    envió voluntariamente el recibo al sindicato. El CASE está en el SQL: el
    dato de un recibo no enviado ni siquiera sale de la base."""
    joins, where, params = _sql_recibos(sid, f, extra_conds="r.estado != 'OK'",
                                        forzar_join=True)
    joins += " LEFT JOIN seccional sec ON sec.id = t.seccional_id"
    with db.get_session() as s:
        total = _uno(s, f"SELECT COUNT(*) FROM reciboverificado r{joins} WHERE {where}",
                     params)[0]
        params_pagina = dict(params, limite=page_size, salto=(page - 1) * page_size)
        filas = s.execute(_stmt(f"""
            SELECT r.procesado_en, sec.nombre, r.cuit_empleador, r.categoria,
                   r.formato, r.bruto, r.monto_diferencia, r.estado, r.enviado_sindicato,
                   CASE WHEN r.enviado_sindicato THEN t.nombre ELSE NULL END,
                   CASE WHEN r.enviado_sindicato THEN r.cuil ELSE NULL END,
                   r.periodo
            FROM reciboverificado r{joins} WHERE {where}
            ORDER BY r.monto_diferencia DESC, r.id DESC
            LIMIT :limite OFFSET :salto""", params_pagina), params_pagina).all()
    etiquetas = _etiquetas_empresas(sid)
    items = [{
        "fecha": fila[0], "seccional": fila[1] or "Sin seccional",
        "empresa": etiquetas.get(fila[2]) or fila[2] or "—",
        "categoria": fila[3] or "—", "formato": fila[4] or "",
        "bruto": fila[5], "diferencia": fila[6],
        "resultado": "con_diferencias" if fila[7] == "CON_DISCREPANCIAS" else "ok",
        "enviado": bool(fila[8]),
        "trabajador_nombre": fila[9], "trabajador_cuil": fila[10],
        "periodo": fila[11],
    } for fila in filas]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def explorador_tramites(sid: int, f: dict, page: int, page_size: int,
                        hoy: Optional[date] = None) -> dict:
    hoy = hoy or date.today()
    joins, where, params = _sql_tramites(sid, f, forzar_join=True)
    joins += (" LEFT JOIN seccional sec ON sec.id = t.seccional_id"
              " LEFT JOIN tipotramite tt ON tt.id = tr.tipo_tramite_id")
    with db.get_session() as s:
        total = _uno(s, f"SELECT COUNT(*) FROM tramite tr{joins} WHERE {where}", params)[0]
        params_pagina = dict(params, limite=page_size, salto=(page - 1) * page_size)
        filas = s.execute(_stmt(f"""
            SELECT tr.numero_expediente, tr.creado, sec.nombre, tt.titulo,
                   {_CASE_ESTADO_TRAMITE}, tr.resuelto_en
            FROM tramite tr{joins} WHERE {where}
            ORDER BY tr.creado DESC, tr.id DESC
            LIMIT :limite OFFSET :salto""", params_pagina), params_pagina).all()
    items = []
    for numero, creado, seccional, tipo, estado_d, resuelto_en in filas:
        dias, sigue = None, estado_d != "resuelto"
        try:
            inicio = date.fromisoformat((creado or "")[:10])
            fin = date.fromisoformat(resuelto_en[:10]) if (resuelto_en and not sigue) else hoy
            dias = (fin - inicio).days
        except ValueError:
            pass
        items.append({"numero": numero, "fecha_inicio": creado,
                      "seccional": seccional or "Sin seccional", "tipo": tipo or "—",
                      "estado": estado_d, "dias": dias, "sigue": sigue})
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def explorador_consultas(sid: int, f: dict, page: int, page_size: int) -> dict:
    joins, where, params = _sql_consultas(sid, f, forzar_join=True)
    joins += " LEFT JOIN seccional sec ON sec.id = t.seccional_id"
    with db.get_session() as s:
        total = _uno(s, f"SELECT COUNT(*) FROM consultaconvenio c{joins} WHERE {where}",
                     params)[0]
        params_pagina = dict(params, limite=page_size, salto=(page - 1) * page_size)
        filas = s.execute(_stmt(f"""
            SELECT c.creado, sec.nombre, c.tema, c.hubo_respuesta
            FROM consultaconvenio c{joins} WHERE {where}
            ORDER BY c.creado DESC, c.id DESC
            LIMIT :limite OFFSET :salto""", params_pagina), params_pagina).all()
    items = [{"fecha": fila[0], "seccional": fila[1] or "Sin seccional",
              "tema": fila[2] or "Sin clasificar",
              "resuelta_por_bot": bool(fila[3])} for fila in filas]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def explorador_notificaciones(sid: int, f: dict, page: int, page_size: int) -> dict:
    """Agregado diario por seccional y tipo: enviadas, leídas, sin leer y
    tasa de lectura. La paginación es sobre las filas agregadas."""
    joins, where, params = _sql_notificaciones(sid, f, forzar_join=True)
    grupos = "substr(n.enviado_en, 1, 10), t.seccional_id, n.origen"
    with db.get_session() as s:
        total = _uno(s, f"""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM notificaciondestinatario d{joins} WHERE {where}
                GROUP BY {grupos}) sub""", params)[0]
        params_pagina = dict(params, limite=page_size, salto=(page - 1) * page_size)
        filas = s.execute(_stmt(f"""
            SELECT substr(n.enviado_en, 1, 10) AS dia, t.seccional_id, n.origen,
                   COUNT(*),
                   COALESCE(SUM(CASE WHEN d.leida_en IS NOT NULL THEN 1 ELSE 0 END), 0)
            FROM notificaciondestinatario d{joins} WHERE {where}
            GROUP BY {grupos} ORDER BY dia DESC
            LIMIT :limite OFFSET :salto""", params_pagina), params_pagina).all()
    nombres = _etiquetas_seccionales(sid)
    items = []
    for dia, secc_id, origen, enviadas, leidas in filas:
        items.append({
            "fecha": dia, "seccional": nombres.get(secc_id, "Sin seccional"),
            "tipo": origen, "etiqueta": TIPOS_NOTIF.get(origen, origen),
            "enviadas": enviadas, "leidas": leidas, "sin_leer": enviadas - leidas,
            "tasa_lectura": round(leidas / enviadas * 100) if enviadas else 0})
    return {"total": total, "page": page, "page_size": page_size, "items": items}

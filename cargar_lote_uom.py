# -*- coding: utf-8 -*-
"""Lote de datos sintéticos "más o menos realistas" para la UOM de demo.

Puebla el sindicato "Unión Obrera Metalúrgica" con:
- 6 seccionales y 12 empresas metalúrgicas ficticias.
- 100 trabajadores con CUIL ficticio de 11 dígitos y cuenta creada
  (clave = los 5 primeros dígitos del CUIL).
- 5.000 recibos verificados del 70% de esos CUILes, ~80% OK y ~20% con
  errores variados. LOS RECIBOS NO SE FABRICAN: se genera el recibo
  sintético (líneas + totales) y se lo pasa por validador.validar() con
  los conceptos, fórmulas y topes REALES del sindicato -- las
  discrepancias, montos y columnas del dashboard salen del motor de
  verdad, igual que en /api/validar.
- 2.000 trámites de 5 tipos (numeración de expediente real vía
  db.crear_tramite), repartidos por seccional, con estados e historia.
- 200 notificaciones (con lecturas parciales), 30 noticias y 20 beneficios.

Determinista (semilla fija): correrlo dos veces no duplica (aborta si el
lote ya está), y `--limpiar` borra exactamente lo que este script creó.

Uso:
    python cargar_lote_uom.py            # siembra (local o Shell de Render)
    python cargar_lote_uom.py --limpiar  # borra el lote
"""
import random
import sys
from datetime import date, datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import select

import auth
import dashboard
import db
from db import (Sindicato, Seccional, Empleador, Trabajador, CuentaTrabajador,
                ReciboVerificado, EnvioSindicato, Reporte, TipoTramite, CampoTramite,
                Tramite, RespuestaTramite, NotaTramite, TramiteLog,
                Notificacion, NotificacionDestinatario, Noticia, Beneficio)
from validador import validar

SINDICATO_NOMBRE = "Unión Obrera Metalúrgica"
rnd = random.Random(20260829)
HOY = date.today()
DIAS_HISTORIA = 120

SECCIONALES = ["Avellaneda", "Quilmes", "La Matanza", "Rosario", "Córdoba", "San Nicolás"]
CATEGORIAS = ["Operario", "Operario calificado", "Medio oficial", "Oficial",
              "Oficial múltiple", "Administrativo"]

# (razón social, conducta de depósito de aportes en días de atraso típico;
#  None = nunca informa fecha de depósito en sus recibos)
EMPRESAS = [
    ("Metalúrgica San Justo SA", (5, 22)), ("Aceros del Paraná SRL", (5, 20)),
    ("Fundición Rivadavia SA", (8, 25)), ("Estampados Bernal SRL", (10, 30)),
    ("Talleres Unidos de Quilmes SA", (5, 18)), ("Perfiles del Sur SA", (12, 30)),
    ("Autopartes Matanza SRL", (40, 58)), ("Caños y Tubos Rosario SA", (42, 60)),
    ("Zincado Industrial SRL", (65, 95)), ("Laminados Córdoba SA", (70, 100)),
    ("Herrajes El Progreso SRL", None), ("Montajes Nicoleños SA", (6, 24)),
]

NOMBRES = ["Juan", "María", "Carlos", "Ana", "Jorge", "Lucía", "Pedro", "Sofía",
           "Miguel", "Valentina", "Ricardo", "Camila", "Héctor", "Julieta", "Oscar",
           "Paula", "Rubén", "Florencia", "Daniel", "Marina"]
APELLIDOS = ["Gómez", "Fernández", "Rodríguez", "López", "Martínez", "Díaz", "Pérez",
             "Sánchez", "Romero", "Suárez", "Torres", "Álvarez", "Ruiz", "Ramírez",
             "Flores", "Benítez", "Acosta", "Medina", "Herrera", "Aguirre"]

TIPOS_TRAMITE = [
    ("Reclamo de aportes", "F01", [
        {"etiqueta": "Período reclamado", "tipo_dato": "texto", "longitud_maxima": 20},
        {"etiqueta": "Empleador", "tipo_dato": "texto", "longitud_maxima": 80},
        {"etiqueta": "Detalle del reclamo", "tipo_dato": "texto", "longitud_maxima": 400}]),
    ("Actualización de datos", "F02", [
        {"etiqueta": "Domicilio nuevo", "tipo_dato": "texto", "longitud_maxima": 120},
        {"etiqueta": "Teléfono", "tipo_dato": "texto", "longitud_maxima": 30}]),
    ("Solicitud de credencial", "F03", [
        {"etiqueta": "Motivo", "tipo_dato": "seleccion",
         "opciones": "Primera vez,Extravío,Deterioro,Cambio de datos"}]),
    ("Reintegro de obra social", "F04", [
        {"etiqueta": "Fecha de la prestación", "tipo_dato": "fecha"},
        {"etiqueta": "Monto a reintegrar", "tipo_dato": "numero", "decimales": 2},
        {"etiqueta": "Detalle", "tipo_dato": "texto", "longitud_maxima": 300}]),
    ("Consulta gremial", "F05", [
        {"etiqueta": "Tema", "tipo_dato": "seleccion",
         "opciones": "Encuadre,Paritarias,Condiciones de trabajo,Licencias,Otro"},
        {"etiqueta": "Consulta", "tipo_dato": "texto", "longitud_maxima": 500}]),
]

REMITENTES = ["Comisión Directiva", "Secretaría Gremial", "Secretaría de Prensa"]
TEXTOS_NOTIF = [
    "Recordá presentar tu último recibo verificado antes de fin de mes.",
    "Nueva jornada de capacitación sobre el recibo de la Ley 27.802: inscribite en tu seccional.",
    "Actualización de datos del padrón: revisá que tu domicilio y teléfono estén al día.",
    "Asamblea informativa de paritarias este viernes en tu seccional.",
    "Campaña de credencialización: acercate a tu seccional a retirar tu credencial.",
    "Verificá tu recibo del mes: detectamos empleadores con aportes demorados.",
    "Nuevo beneficio para afiliados disponible en la app: entrá a Beneficios.",
    "Operativo de salud ocupacional: turnos disponibles en tu seccional.",
]

NOTICIAS = [
    ("Avanza la paritaria metalúrgica", "La comisión negociadora presentó la propuesta de recomposición salarial del trimestre."),
    ("Nuevo recibo de sueldo: qué cambia", "Entró en vigencia el formato del Anexo III con el detalle de contribuciones patronales."),
    ("Plenario de delegados", "Se realizó el plenario mensual con la participación de todas las seccionales."),
    ("Capacitación en seguridad e higiene", "Nuevo ciclo de talleres gratuitos para afiliados y delegados."),
    ("Verificá tu recibo desde la app", "Ya podés controlar tus aportes desde el celular y enviar el recibo al sindicato."),
    ("Aportes al día: campaña de control", "El sindicato intensifica el control de depósitos de aportes de los empleadores."),
    ("Torneo deportivo metalúrgico", "Abrió la inscripción para el torneo anual de fútbol entre seccionales."),
    ("Convenio con red de farmacias", "Descuentos para afiliados en medicamentos de venta libre y recetados."),
    ("Obras en la seccional Rosario", "Comenzó la renovación del salón de usos múltiples."),
    ("Día del Trabajador Metalúrgico", "Actividades y festejos en todas las seccionales."),
]

BENEFICIOS = [
    ("Farmacias", "20% de descuento en la red de farmacias adheridas presentando la credencial."),
    ("Turismo", "Planes de turismo familiar con financiación en el hotel de la organización."),
    ("Óptica", "Anteojos recetados con 30% de descuento para afiliados y familiares."),
    ("Librería escolar", "Kit escolar con descuento para hijos de afiliados."),
    ("Deportes", "Acceso libre al polideportivo para el grupo familiar."),
    ("Odontología", "Consultas y tratamientos con arancel preferencial."),
    ("Electrodomésticos", "Convenio con casas de electrodomésticos en cuotas sin interés."),
    ("Capacitación", "Cursos de oficios gratuitos con certificación."),
    ("Proveeduría", "Canasta de alimentos con precios de proveeduría sindical."),
    ("Salud", "Chequeo médico anual sin cargo en los consultorios del sindicato."),
]


def _cuil(i: int) -> str:
    prefijo = "20" if i % 3 else "27"
    return f"{prefijo}{60000000 + i:08d}{(i * 7) % 10}"


def _cuit_empresa(j: int) -> str:
    return f"30{61000000 + j:08d}{(j * 3) % 10}"


CUILS = [_cuil(i) for i in range(100)]
CUITS_EMPRESA = [_cuit_empresa(j) for j in range(len(EMPRESAS))]
CODIGOS_TIPO = [codigo for _, codigo, _ in TIPOS_TRAMITE]


def _ts(dias_atras: int, hora: int = None) -> str:
    h = hora if hora is not None else rnd.randint(8, 20)
    return f"{(HOY - timedelta(days=dias_atras)).isoformat()} {h:02d}:{rnd.randint(0, 59):02d}"


def _fecha_ar(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def sindicato_uom() -> int:
    with db.get_session() as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre == SINDICATO_NOMBRE)).first()
        if not sind:
            sys.exit(f"No existe el sindicato '{SINDICATO_NOMBRE}'. Corré cargar_demo.py primero.")
        return sind.id


# ---------------------------------------------------------------- limpiar
def limpiar(sid: int):
    cuils = set(CUILS)
    with db.get_session() as s:
        # Los hijos se borran y CONFIRMAN antes que los trámites: los modelos
        # declaran la FK como columna pero no como relationship(), así que
        # SQLAlchemy no conoce el orden y puede emitir el DELETE del padre
        # primero (mismo criterio que la limpieza de cargar_demo.py).
        tramites = [t for t in s.exec(select(Tramite).where(
            Tramite.sindicato_id == sid)).all() if t.cuil in cuils]
        ids_tramites = {t.id for t in tramites}
        for m, col in [(RespuestaTramite, RespuestaTramite.tramite_id),
                       (NotaTramite, NotaTramite.tramite_id),
                       (TramiteLog, TramiteLog.tramite_id)]:
            for fila in s.exec(select(m).where(col.in_(ids_tramites))).all():
                s.delete(fila)
        s.commit()
        for tr in tramites:
            s.delete(tr)
        s.commit()
        tipos_lote = [tt for tt in s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == sid)).all()
            if tt.codigo in CODIGOS_TIPO and not s.exec(select(Tramite).where(
                Tramite.tipo_tramite_id == tt.id)).first()]
        for tt in tipos_lote:
            for c in s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tt.id)).all():
                s.delete(c)
        s.commit()
        for tt in tipos_lote:
            s.delete(tt)
        s.commit()
        notifs_lote = [n for n in s.exec(select(Notificacion).where(
            Notificacion.sindicato_id == sid)).all()
            if n.texto in TEXTOS_NOTIF or (n.origen == "sistema" and "expediente" in n.texto)]
        for n in notifs_lote:
            for d_ in s.exec(select(NotificacionDestinatario).where(
                    NotificacionDestinatario.notificacion_id == n.id)).all():
                s.delete(d_)
        s.commit()
        for n in notifs_lote:
            s.delete(n)
        # startswith: las repeticiones del lote llevan sufijo "(2)"/"(3)".
        titulos = tuple(t for t, _ in NOTICIAS)
        for n in s.exec(select(Noticia).where(Noticia.sindicato_id == sid)).all():
            if n.titulo.startswith(titulos):
                s.delete(n)
        rubros = tuple(r for r, _ in BENEFICIOS)
        for b in s.exec(select(Beneficio).where(Beneficio.sindicato_id == sid)).all():
            if b.rubro.startswith(rubros):
                s.delete(b)
        for m, col_sid, col_cuil in [(ReciboVerificado, ReciboVerificado.sindicato_id, ReciboVerificado.cuil),
                                     (EnvioSindicato, EnvioSindicato.sindicato_id, EnvioSindicato.cuil),
                                     (Reporte, Reporte.sindicato_id, Reporte.cuil)]:
            for fila in s.exec(select(m).where(col_sid == sid)).all():
                if fila.cuil in cuils:
                    s.delete(fila)
        s.commit()
        for t in s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid)).all():
            if t.cuil in cuils:
                s.delete(t)
        s.commit()
        for c in s.exec(select(CuentaTrabajador)).all():
            if c.cuil in cuils:
                s.delete(c)
        for e in s.exec(select(Empleador).where(Empleador.sindicato_id == sid)).all():
            if e.cuit in set(CUITS_EMPRESA):
                s.delete(e)
        s.commit()
        # Seccionales del lote solo si quedaron sin trabajadores de nadie.
        for sec in s.exec(select(Seccional).where(Seccional.sindicato_id == sid)).all():
            if sec.nombre in SECCIONALES and not s.exec(select(Trabajador).where(
                    Trabajador.seccional_id == sec.id)).first():
                s.delete(sec)
        s.commit()
    print("Lote UOM borrado.")


# ---------------------------------------------------------------- base
def sembrar_base(sid: int):
    """Seccionales, empresas, trabajadores y cuentas. Devuelve los catálogos."""
    with db.get_session() as s:
        actuales = db.modulos_habilitados(sid)
        db.set_modulos_sindicato(sid, list(dict.fromkeys(
            actuales + ["dashboard", "tramites", "notificaciones", "noticias", "beneficios"])))

        secc_ids = {}
        for nombre in SECCIONALES:
            sec = s.exec(select(Seccional).where(Seccional.sindicato_id == sid,
                                                 Seccional.nombre == nombre)).first()
            if not sec:
                sec = Seccional(sindicato_id=sid, nombre=nombre,
                                direccion=f"Av. de los Metalúrgicos {rnd.randint(100, 4500)}")
                s.add(sec); s.commit(); s.refresh(sec)
            secc_ids[nombre] = sec.id

        empresas = []
        for j, (razon, conducta) in enumerate(EMPRESAS):
            cuit = CUITS_EMPRESA[j]
            e = s.exec(select(Empleador).where(Empleador.sindicato_id == sid,
                                               Empleador.cuit == cuit)).first()
            if not e:
                s.add(Empleador(sindicato_id=sid, cuit=cuit, razon_social=razon,
                                provincia=rnd.choice(["Buenos Aires", "Santa Fe", "Córdoba"]),
                                activo=True))
            empresas.append({"cuit": cuit, "razon": razon, "conducta": conducta})
        s.commit()

        trabajadores = []
        for i, cuil in enumerate(CUILS):
            nombre = f"{rnd.choice(NOMBRES)} {rnd.choice(APELLIDOS)}"
            secc = rnd.choice(list(secc_ids.values()))
            emp = rnd.choice(empresas)
            t = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                                Trabajador.cuil == cuil)).first()
            if not t:
                s.add(Trabajador(sindicato_id=sid, cuil=cuil, nombre=nombre,
                                 registrado=True, seccional_id=secc,
                                 cuit_empleador=emp["cuit"],
                                 provincia=rnd.choice(["Buenos Aires", "Santa Fe", "Córdoba"])))
            if not s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first():
                # La regla del lote: la clave son los 5 primeros dígitos del CUIL.
                s.add(CuentaTrabajador(cuil=cuil, nombre=nombre,
                                       clave_hash=auth.hashear_clave(cuil[:5])))
            trabajadores.append({"cuil": cuil, "nombre": nombre, "seccional_id": secc,
                                 "empresa": emp,
                                 "sueldo": rnd.randint(900, 3200) * 1000})
        s.commit()
    return trabajadores, empresas, secc_ids


# ---------------------------------------------------------------- recibos
def _recibo_sintetico(trab: dict, dias_atras: int, con_error: bool):
    """Un recibo como lo devolvería el extractor, para el catálogo UOM
    (SUELDO/PRESENT/VIATICO/JUB/SINDMET). Si con_error, se inyectan 1-2
    defectos que el validador REAL tiene que detectar."""
    fecha_proceso = HOY - timedelta(days=dias_atras)
    periodo_dt = (fecha_proceso.replace(day=1) - timedelta(days=1))
    periodo = periodo_dt.strftime("%Y-%m")

    sueldo = round(trab["sueldo"] * rnd.uniform(0.97, 1.06), 2)
    present = round(sueldo * 0.0833, 2)
    base = sueldo + present
    viatico = round(rnd.uniform(40000, 120000), 2) if rnd.random() < 0.6 else None
    jub = round(-0.11 * base, 2)
    sind = round(-0.025 * base, 2)

    errores = []
    if con_error:
        for e in rnd.sample(["jub_mal", "cuota_mal", "jub_faltante", "totales_mal"],
                            k=1 if rnd.random() < 0.7 else 2):
            errores.append(e)
    if "jub_mal" in errores:
        jub = round(jub * rnd.choice([0.7, 0.82, 1.2, 1.35]), 2)
    if "cuota_mal" in errores:
        sind = round(sind * rnd.choice([0.5, 1.4, 1.8]), 2)

    lineas = [
        {"codigo": "SUELDO", "descripcion": "Sueldo básico", "importe": sueldo,
         "tipo": "remuneracion", "categoria_universal": None},
        {"codigo": "PRESENT", "descripcion": "Presentismo", "importe": present,
         "tipo": "remuneracion", "categoria_universal": None},
    ]
    if viatico:
        lineas.append({"codigo": "VIATICO", "descripcion": "Viáticos", "importe": viatico,
                       "tipo": "remuneracion", "categoria_universal": None})
    if "jub_faltante" not in errores:
        lineas.append({"codigo": "JUB", "descripcion": "Aporte jubilatorio", "importe": jub,
                       "tipo": "aporte_trabajador", "categoria_universal": "jubilacion"})
    lineas.append({"codigo": "SINDMET", "descripcion": "Cuota sindical UOM", "importe": sind,
                   "tipo": "aporte_trabajador", "categoria_universal": "cuota_sindical"})

    total_ingresos = sueldo + present + (viatico or 0)
    total_descuentos = sum(l["importe"] for l in lineas if l["importe"] < 0)
    neto = total_ingresos + total_descuentos
    totales = {"remuneraciones": round(total_ingresos, 2),
               "descuentos": round(total_descuentos, 2), "neto": round(neto, 2)}
    if "totales_mal" in errores:
        totales["neto"] = round(neto - rnd.uniform(8000, 60000), 2)

    # Adopción del formato nuevo: crece con la cercanía a hoy.
    p_nuevo = 0.25 + (DIAS_HISTORIA - dias_atras) / DIAS_HISTORIA * 0.65
    formato = "nuevo" if rnd.random() < p_nuevo else "clasico"

    conducta = trab["empresa"]["conducta"]
    ultimo_deposito = None
    if conducta and rnd.random() < 0.85:
        atraso = rnd.randint(*conducta)
        ultimo_deposito = {"fecha": _fecha_ar(fecha_proceso - timedelta(days=atraso)),
                           "periodo": None, "banco": None}

    recibo = {
        "formato": formato,
        "empleado": {"apellido_nombre": trab["nombre"], "cuil": trab["cuil"],
                     "legajo": str(rnd.randint(100, 9999)),
                     "categoria": rnd.choice(CATEGORIAS), "fecha_ingreso": None},
        "empleador": {"nombre": trab["empresa"]["razon"], "cuit": trab["empresa"]["cuit"]},
        "periodo": periodo, "fecha_pago": _fecha_ar(fecha_proceso),
        "lineas": lineas, "totales_impresos": totales,
        "contribuciones_patronales": [], "costo_laboral_total": None,
        "ultimo_deposito": ultimo_deposito,
        "confianza": "alta", "observaciones": None,
        "alerta_adulteracion": {"detectada": False, "motivo": None},
    }
    if formato == "nuevo":
        contribs = [
            {"concepto": "Contribución jubilatoria", "base": round(base, 2),
             "porcentaje": "10,77%", "importe": round(base * 0.1077, 2)},
            {"concepto": "Obra social patronal", "base": round(base, 2),
             "porcentaje": "6%", "importe": round(base * 0.06, 2)},
            {"concepto": "ART", "base": round(base, 2),
             "porcentaje": "3,5%", "importe": round(base * 0.035, 2)},
        ]
        recibo["contribuciones_patronales"] = contribs
        recibo["costo_laboral_total"] = round(
            total_ingresos + sum(c["importe"] for c in contribs), 2)
    return recibo, fecha_proceso


def sembrar_recibos(sid: int, trabajadores: list):
    verificadores = trabajadores[:70]     # el 70% del padrón verifica recibos
    conceptos = db.conceptos_como_dicts(sid)
    formulas = db.formulas_como_dicts(sid)
    topes = db.topes_como_dicts()
    tope_pct = db.obtener_tope_sindical()

    contadores = {"OK": 0, "CON_DISCREPANCIAS": 0, "enviados": 0, "reportados": 0}
    lote = []
    for _ in range(5000):
        trab = rnd.choice(verificadores)
        # Volumen creciente hacia hoy (ver cargar_lote_sindicato): con el pico
        # 12 días atrás, el tablero abría casi vacío en su vista "Hoy".
        dias_atras = min(DIAS_HISTORIA - 1, int(rnd.triangular(0, DIAS_HISTORIA, 0)))
        con_error = rnd.random() < 0.20
        recibo, fecha_proceso = _recibo_sintetico(trab, dias_atras, con_error)

        resultado = validar(conceptos, formulas, recibo, tope_sindical_pct=tope_pct,
                            cuil_sesion=trab["cuil"], topes=topes)
        estado = resultado.get("estado", "")
        contadores[estado] = contadores.get(estado, 0) + 1

        procesado_en = _ts(dias_atras)
        campos = dashboard.campos_analiticos(recibo, resultado)
        campos["procesado_en"] = procesado_en

        enviado = (estado == "OK" and rnd.random() < 0.30)
        reportado = (estado == "CON_DISCREPANCIAS" and rnd.random() < 0.40)
        fecha_ar = f"{fecha_proceso.strftime('%d/%m/%Y')} {procesado_en[-5:]}"
        lote.append({
            "registro": ReciboVerificado(
                sindicato_id=sid, cuil=trab["cuil"], periodo=resultado.get("periodo", ""),
                fecha=fecha_ar, estado=estado,
                enviado_sindicato=enviado or reportado,
                fecha_envio=fecha_ar if (enviado or reportado) else "",
                detalle={"recibo": recibo, "resultado": resultado},
                **campos),
            "enviado": enviado, "reportado": reportado,
            "detalle": {"recibo": recibo, "resultado": resultado},
            "monto_cuota": (resultado.get("retencion_sindical") or {}).get("total", 0.0),
            "fecha_ar": fecha_ar,
        })

    with db.get_session() as s:
        for i, item in enumerate(lote):
            s.add(item["registro"])
            r = item["registro"]
            if item["enviado"] or item["reportado"]:
                contadores["enviados"] += 1
                s.add(EnvioSindicato(sindicato_id=sid, cuil=r.cuil, periodo=r.periodo,
                                     monto_cuota=item["monto_cuota"], fecha=item["fecha_ar"],
                                     detalle=item["detalle"]))
            if item["reportado"]:
                contadores["reportados"] += 1
                s.add(Reporte(sindicato_id=sid, cuil=r.cuil, periodo=r.periodo,
                              fecha=item["fecha_ar"],
                              estado=rnd.choice(["nuevo", "nuevo", "en_revision", "resuelto"]),
                              detalle=item["detalle"]))
            if i % 500 == 499:
                s.commit()
        s.commit()
    return contadores


# ---------------------------------------------------------------- trámites
def sembrar_tramites(sid: int, trabajadores: list):
    # Los 5 tipos, reusando el que ya exista con ese código (idempotencia).
    tipos = []
    with db.get_session() as s:
        existentes = {t.codigo: t.id for t in s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == sid)).all()}
    for titulo, codigo, campos in TIPOS_TRAMITE:
        tipos.append(existentes.get(codigo) or db.crear_tipo_tramite(sid, titulo, codigo, campos))

    valores_ejemplo = {
        "texto": ["Ver detalle adjunto en la seccional", "Consultar con el delegado",
                  "Se adjuntó documentación en papel", "Reclamo por diferencia del último período"],
        "fecha": None, "numero": None, "seleccion": None,
    }
    estados_transicion = {
        "en_tratamiento": ["Iniciado → En tratamiento"],
        "respondido": ["Iniciado → En tratamiento", "En tratamiento → Respondido"],
        "espera_info": ["Iniciado → En tratamiento",
                        "En tratamiento → A la espera de información del afiliado"],
        "terminado": ["Iniciado → En tratamiento", "En tratamiento → Terminado"],
    }

    with db.get_session() as s:
        tipos_con_campos = {}
        for tid in tipos:
            campos = s.exec(select(CampoTramite).where(
                CampoTramite.tipo_tramite_id == tid).order_by(CampoTramite.orden)).all()
            tipos_con_campos[tid] = campos

    creados = 0
    for _ in range(2000):
        trab = rnd.choice(trabajadores)
        tid = rnd.choice(tipos)
        respuestas = []
        for c in tipos_con_campos[tid]:
            if c.tipo_dato == "fecha":
                valor = (HOY - timedelta(days=rnd.randint(5, 90))).isoformat()
            elif c.tipo_dato == "numero":
                valor = str(rnd.randint(5000, 250000))
            elif c.tipo_dato in ("seleccion", "opcion_unica"):
                valor = rnd.choice([o.strip() for o in c.opciones.split(",") if o.strip()])
            else:
                valor = rnd.choice(valores_ejemplo["texto"])
            respuestas.append({"campo_tramite_id": c.id, "valor_texto": valor})
        res = db.crear_tramite(sid, tid, trab["cuil"], respuestas)
        if not res:
            continue
        creados += 1

        # Historia hacia atrás: antigüedad, estado según antigüedad, y las
        # fechas del trámite y su log corregidas a ESA fecha.
        dias_atras = rnd.randint(0, DIAS_HISTORIA)
        creado_ts = _ts(dias_atras)
        if dias_atras > 30:
            estado = rnd.choices(["terminado", "respondido", "en_tratamiento", "iniciado"],
                                 weights=[70, 12, 10, 8])[0]
        elif dias_atras > 10:
            estado = rnd.choices(["terminado", "respondido", "en_tratamiento",
                                  "espera_info", "iniciado"], weights=[35, 15, 25, 10, 15])[0]
        else:
            estado = rnd.choices(["terminado", "en_tratamiento", "espera_info", "iniciado"],
                                 weights=[8, 35, 12, 45])[0]
        dias_resolucion = rnd.randint(1, max(1, min(dias_atras, 25))) if estado == "terminado" else None
        actualizado_ts = (_ts(max(0, dias_atras - dias_resolucion)) if dias_resolucion
                          else (creado_ts if estado == "iniciado" else _ts(max(0, dias_atras - rnd.randint(1, 8)))))

        with db.get_session() as s:
            tr = s.get(Tramite, res["id"])
            tr.creado, tr.actualizado, tr.estado = creado_ts, actualizado_ts, estado
            if estado == "terminado":
                tr.resuelto_en = actualizado_ts
            s.add(tr)
            logs = s.exec(select(TramiteLog).where(TramiteLog.tramite_id == tr.id)).all()
            for lg in logs:
                lg.creado = creado_ts
                s.add(lg)
            for detalle in estados_transicion.get(estado, []):
                s.add(TramiteLog(tramite_id=tr.id, evento="cambio_estado",
                                 detalle=detalle, creado=actualizado_ts))
            s.commit()
    return creados


# ------------------------------------------------------- notificaciones y contenido
def sembrar_notificaciones(sid: int, secc_ids: dict, trabajadores: list):
    creadas = 0
    for i in range(200):
        dias_atras = rnd.randint(0, DIAS_HISTORIA)
        if i % 4 == 3:
            # Automática de trámite (origen sistema), a un CUIL puntual.
            trab = rnd.choice(trabajadores)
            res = db.crear_notificacion(
                sid, None, "Mesa de Entradas",
                f"Tu expediente cambió de estado. Entrá a Trámites para ver el detalle.",
                "cuil", [trab["cuil"]], origen="sistema")
        else:
            criterio, valores = rnd.choice([
                ("seccional", [rnd.choice(list(secc_ids.values()))]),
                ("seccional", rnd.sample(list(secc_ids.values()), k=2)),
                ("cuil", [t["cuil"] for t in rnd.sample(trabajadores, k=rnd.randint(5, 30))]),
            ])
            res = db.crear_notificacion(sid, None, rnd.choice(REMITENTES),
                                        rnd.choice(TEXTOS_NOTIF), criterio, valores)
        if not res["cantidad_destinatarios"]:
            continue
        creadas += 1
        enviado_ts = _ts(dias_atras)
        tasa = rnd.uniform(0.35, 0.85)
        with db.get_session() as s:
            n = s.get(Notificacion, res["id"])
            n.enviado_en = enviado_ts
            s.add(n)
            for d_ in s.exec(select(NotificacionDestinatario).where(
                    NotificacionDestinatario.notificacion_id == n.id)).all():
                if rnd.random() < tasa:
                    d_.leida_en = _ts(max(0, dias_atras - rnd.randint(0, min(7, dias_atras) or 1)))
                    s.add(d_)
            s.commit()
    return creadas


def sembrar_contenido(sid: int, secc_ids: dict):
    with db.get_session() as s:
        for i in range(30):
            titulo, bajada = NOTICIAS[i % len(NOTICIAS)]
            if i >= len(NOTICIAS):
                titulo = f"{titulo} ({i // len(NOTICIAS) + 1})"
            dias_atras = rnd.randint(0, DIAS_HISTORIA)
            desde = HOY - timedelta(days=dias_atras)
            hasta = desde + timedelta(days=rnd.randint(20, 60))
            s.add(Noticia(sindicato_id=sid, titulo=titulo, bajada=bajada,
                          texto_completo=bajada + " Más información en tu seccional o en la app.",
                          fecha_desde=desde.isoformat(), fecha_hasta=hasta.isoformat(),
                          creada=_ts(dias_atras),
                          destino_seccionales=([rnd.choice(list(secc_ids.values()))]
                                               if rnd.random() < 0.3 else [])))
        for i in range(20):
            rubro, descripcion = BENEFICIOS[i % len(BENEFICIOS)]
            if i >= len(BENEFICIOS):
                rubro = f"{rubro} {i // len(BENEFICIOS) + 1}"
            dias_atras = rnd.randint(0, 60)
            desde = HOY - timedelta(days=dias_atras)
            s.add(Beneficio(sindicato_id=sid, rubro=rubro, descripcion=descripcion,
                            link="https://uom.org.ar/beneficios" if rnd.random() < 0.4 else "",
                            fecha_desde=desde.isoformat(),
                            fecha_hasta=(desde + timedelta(days=rnd.randint(60, 180))).isoformat(),
                            creada=_ts(dias_atras), destino_seccionales=[]))
        s.commit()


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    sid = sindicato_uom()
    if "--limpiar" in sys.argv:
        limpiar(sid)
        sys.exit(0)

    with db.get_session() as s:
        ya = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                             Trabajador.cuil == CUILS[0])).first()
    if ya:
        sys.exit("El lote ya está cargado (correr con --limpiar primero para regenerarlo).")

    print("Sembrando base (seccionales, empresas, 100 trabajadores con cuenta)...")
    trabajadores, empresas, secc_ids = sembrar_base(sid)
    print("Generando y VALIDANDO 5.000 recibos con el motor real (paciencia)...")
    contadores = sembrar_recibos(sid, trabajadores)
    print(f"  Recibos: {contadores.get('OK', 0)} OK, "
          f"{contadores.get('CON_DISCREPANCIAS', 0)} con discrepancias, "
          f"{contadores['enviados']} enviados al sindicato, {contadores['reportados']} reportados.")
    print("Creando 5 tipos de trámite y 2.000 trámites...")
    tramites = sembrar_tramites(sid, trabajadores)
    print(f"  Trámites creados: {tramites}.")
    print("Enviando 200 notificaciones con lecturas parciales...")
    notifs = sembrar_notificaciones(sid, secc_ids, trabajadores)
    print(f"  Notificaciones: {notifs}.")
    print("Cargando 30 noticias y 20 beneficios...")
    sembrar_contenido(sid, secc_ids)

    print("\nLote UOM cargado. Accesos de ejemplo (clave = 5 primeros dígitos del CUIL):")
    for t in trabajadores[:3]:
        print(f"  Trabajador {t['nombre']}: CUIL {t['cuil']} / clave {t['cuil'][:5]}")
    print("  Admin UOM: 20111111110 / uom-demo  →  /admin/dashboard")

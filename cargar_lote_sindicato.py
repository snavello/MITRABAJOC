# -*- coding: utf-8 -*-
"""Lote de datos sintéticos COMPLETOS para cualquier sindicato existente.

Generalización de cargar_lote_uom.py (pedido de Sd, 2026-08-31): en vez de
un catálogo hardcodeado, lee los conceptos, fórmulas, topes, empleadores y
seccionales REALES del sindicato que se le indique y genera:

- 100 trabajadores con cuenta (clave = 5 primeros dígitos del CUIL).
- 5.000 recibos del 70% de esos CUILes, ~80% OK / ~20% con errores variados.
  Los recibos se AUTOCORRIGEN contra el validador real: se construye el
  recibo, se valida, y cada aporte se ajusta al "esperado" que devolvió el
  motor (hasta 4 pasadas, por si una fórmula referencia a otra) -- así el
  80% OK sale OK con CUALQUIER catálogo de fórmulas, y los errores se
  inyectan recién después, sobre un recibo correcto.
- 5 tipos de trámite temáticos (3-4 campos c/u) y 2.000 trámites con el
  formulario RESPONDIDO con contenido coherente al tema y, en los que
  avanzaron de estado, el IDA Y VUELTA sindicato ↔ afiliado (notas de los
  dos lados + historial). Nada queda "solo un título".
- 200 notificaciones con contenido real (las de sistema citan el expediente
  verdadero del trabajador), 30 noticias con texto completo y 20 beneficios.

Determinista por sindicato, idempotente, y `--limpiar` borra solo el lote.

Uso:
    python cargar_lote_sindicato.py --sindicato "AEFIP"
    python cargar_lote_sindicato.py --sindicato "AEFIP" --limpiar
"""
import random
import sys
from datetime import date, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import select

import auth
import dashboard
import db
import geo
from db import (Sindicato, Seccional, Empleador, Trabajador, CuentaTrabajador,
                ReciboVerificado, EnvioSindicato, Reporte, TipoTramite, CampoTramite,
                Tramite, RespuestaTramite, NotaTramite, TramiteLog,
                Notificacion, NotificacionDestinatario, Noticia, Beneficio)
from validador import validar, a_numero
import fechas

HOY = fechas.hoy()
DIAS_HISTORIA = 120
CANT_TRABAJADORES, CANT_RECIBOS, CANT_TRAMITES, CANT_NOTIFS = 100, 5000, 2000, 200

SECCIONALES_GENERICAS = ["Buenos Aires", "Rosario", "Córdoba", "Mendoza", "Tucumán", "Bahía Blanca"]
CATEGORIAS = ["Auxiliar", "Administrativo", "Técnico", "Profesional", "Supervisor", "Jefe de sección"]

ORGANISMOS_FISCALES = [
    ("ARCA - Dirección Regional Centro", (5, 20)), ("ARCA - Dirección Regional Norte", (5, 18)),
    ("ARCA - Dirección Regional Sur", (8, 25)), ("Aduana Buenos Aires", (6, 22)),
    ("Aduana Rosario", (10, 28)), ("ARCA - Dirección de Grandes Contribuyentes", (5, 15)),
    ("Delegación Córdoba", (42, 60)), ("Delegación Mendoza", (45, 62)),
    ("Depósito Fiscal Zárate", (68, 95)), ("Receptoría Tucumán", (70, 100)),
    ("Agencia Bahía Blanca", None), ("Aduana Ezeiza", (6, 24)),
]
BANCOS = [
    ("Banco de la Nación Argentina", (5, 18)), ("Banco de la Provincia de Buenos Aires", (5, 20)),
    ("Banco Galicia", (5, 16)), ("Banco Santander Argentina", (6, 20)),
    ("BBVA Argentina", (5, 18)), ("Banco Macro", (8, 24)),
    ("Banco Credicoop", (10, 26)), ("Banco Ciudad de Buenos Aires", (6, 22)),
    ("Banco Patagonia", (40, 58)), ("Banco Supervielle", (44, 62)),
    ("Banco Comafi", (66, 96)), ("Banco Hipotecario", None),
]
EMPRESAS_GENERICAS = [
    ("Industrias del Litoral SA", (5, 22)), ("Servicios Federales SRL", (5, 20)),
    ("Compañía del Sur SA", (8, 25)), ("Talleres Asociados SRL", (10, 30)),
    ("Logística Central SA", (5, 18)), ("Manufacturas Unidas SA", (12, 30)),
    ("Distribuidora Pampeana SRL", (40, 58)), ("Envases Nacionales SA", (42, 60)),
    ("Procesadora del Oeste SRL", (65, 95)), ("Depósitos Integrados SA", (70, 100)),
    ("Insumos del Centro SRL", None), ("Transportes Regionales SA", (6, 24)),
]

NOMBRES = ["Juan", "María", "Carlos", "Ana", "Jorge", "Lucía", "Pedro", "Sofía",
           "Miguel", "Valentina", "Ricardo", "Camila", "Héctor", "Julieta", "Oscar",
           "Paula", "Rubén", "Florencia", "Daniel", "Marina"]
APELLIDOS = ["Gómez", "Fernández", "Rodríguez", "López", "Martínez", "Díaz", "Pérez",
             "Sánchez", "Romero", "Suárez", "Torres", "Álvarez", "Ruiz", "Ramírez",
             "Flores", "Benítez", "Acosta", "Medina", "Herrera", "Aguirre"]

# ---- Trámites: tipos temáticos, con respuestas y diálogos coherentes al tema ----
TIPOS_TRAMITE = [
    {"titulo": "Reclamo de aportes", "codigo": "F01", "campos": [
        {"etiqueta": "Período reclamado", "tipo_dato": "texto", "longitud_maxima": 20},
        {"etiqueta": "Empleador", "tipo_dato": "texto", "longitud_maxima": 80},
        {"etiqueta": "¿Qué detectaste en el recibo?", "tipo_dato": "seleccion",
         "opciones": "Aporte no depositado,Retención de más,Retención de menos,Aporte que no figura"},
        {"etiqueta": "Detalle del reclamo", "tipo_dato": "texto", "longitud_maxima": 400}],
     "respuestas": {
        "Período reclamado": lambda r: f"{r.randint(1, 12):02d}/{r.choice(['2025', '2026'])}",
        "Detalle del reclamo": lambda r: r.choice([
            "En el recibo figura el descuento pero en la constancia de ARCA no aparece el depósito de ese mes.",
            "Comparé el recibo con la app y la retención supera el porcentaje del convenio.",
            "El aporte de obra social no figura en el recibo aunque siempre me lo descontaron.",
            "Verifiqué el recibo en la app y marcó diferencias en la jubilación; adjunto captura en la seccional."])},
     "dialogo": [
        ("admin", "Recibimos tu reclamo. Estamos verificando los depósitos con el área de fiscalización."),
        ("trabajador", "Gracias. ¿Necesitan que acerque los recibos de los meses anteriores?"),
        ("admin", "Sí, acercá los últimos tres recibos a tu seccional o subilos verificados desde la app."),
        ("admin", "Confirmamos la diferencia y se intimó al empleador a regularizar. Te avisamos ante novedades.")]},
    {"titulo": "Actualización de datos", "codigo": "F02", "campos": [
        {"etiqueta": "Domicilio nuevo", "tipo_dato": "texto", "longitud_maxima": 120},
        {"etiqueta": "Localidad", "tipo_dato": "texto", "longitud_maxima": 60},
        {"etiqueta": "Teléfono de contacto", "tipo_dato": "texto", "longitud_maxima": 30}],
     "respuestas": {
        "Domicilio nuevo": lambda r: f"{r.choice(['Av. San Martín', 'Belgrano', 'Mitre', 'Urquiza', 'Sarmiento'])} {r.randint(100, 4800)}",
        "Localidad": lambda r: r.choice(["Rosario", "Córdoba", "Quilmes", "San Miguel de Tucumán", "Mendoza"]),
        "Teléfono de contacto": lambda r: f"11{r.randint(30000000, 69999999)}"},
     "dialogo": [
        ("admin", "Datos actualizados en el padrón. Revisá que figuren bien en tu perfil de la app."),
        ("trabajador", "Ya lo revisé, quedó perfecto. ¡Gracias!")]},
    {"titulo": "Solicitud de credencial", "codigo": "F03", "campos": [
        {"etiqueta": "Motivo", "tipo_dato": "seleccion",
         "opciones": "Primera vez,Extravío,Deterioro,Cambio de datos"},
        {"etiqueta": "Seccional de retiro", "tipo_dato": "texto", "longitud_maxima": 60},
        {"etiqueta": "Comentario", "tipo_dato": "texto", "longitud_maxima": 200, "obligatorio": False}],
     "respuestas": {
        "Comentario": lambda r: r.choice([
            "La necesito para el descuento en farmacias.", "Perdí la billetera con la credencial adentro.",
            "La mía quedó ilegible.", ""])},
     "dialogo": [
        ("admin", "Tu credencial está en emisión. En unos días te avisamos cuándo retirarla."),
        ("admin", "Ya podés retirar tu credencial en la seccional elegida, de 9 a 16 h."),
        ("trabajador", "Retirada, muchas gracias.")]},
    {"titulo": "Reintegro de obra social", "codigo": "F04", "campos": [
        {"etiqueta": "Fecha de la prestación", "tipo_dato": "fecha"},
        {"etiqueta": "Monto a reintegrar", "tipo_dato": "numero", "decimales": 2},
        {"etiqueta": "Tipo de prestación", "tipo_dato": "seleccion",
         "opciones": "Consulta médica,Estudios,Medicamentos,Odontología,Anteojos"},
        {"etiqueta": "Detalle", "tipo_dato": "texto", "longitud_maxima": 300}],
     "respuestas": {
        "Detalle": lambda r: r.choice([
            "Adjunto factura y receta en la seccional.", "Consulta con especialista fuera de cartilla.",
            "Compra de anteojos recetados, presento la factura original.",
            "Estudios de laboratorio indicados por el médico de cabecera."])},
     "dialogo": [
        ("admin", "Recibimos tu pedido de reintegro. Falta la factura original: acercala a tu seccional."),
        ("trabajador", "La llevé hoy a la mañana, la recibió Marta en mesa de entradas."),
        ("admin", "Perfecto, quedó completo. El reintegro se acredita con la próxima liquidación."),
        ("trabajador", "Ya lo vi acreditado. Gracias por la gestión.")]},
    {"titulo": "Consulta gremial", "codigo": "F05", "campos": [
        {"etiqueta": "Tema", "tipo_dato": "seleccion",
         "opciones": "Encuadre,Paritarias,Condiciones de trabajo,Licencias,Sanciones,Otro"},
        {"etiqueta": "Consulta", "tipo_dato": "texto", "longitud_maxima": 500},
        {"etiqueta": "¿Preferís que te llamemos?", "tipo_dato": "seleccion", "opciones": "Sí,No"}],
     "respuestas": {
        "Consulta": lambda r: r.choice([
            "Me cambiaron el horario sin avisarme con anticipación, ¿corresponde?",
            "¿Cuántos días de licencia por mudanza me corresponden por convenio?",
            "Me descontaron un día por un paro al que no adherí, ¿cómo lo reclamo?",
            "¿El adicional por título se paga también durante las vacaciones?",
            "Quiero saber si mi categoría está bien encuadrada según las tareas que hago."])},
     "dialogo": [
        ("admin", "Tu consulta pasó al asesor gremial de tu seccional."),
        ("admin", "Según el convenio te corresponde: te dejamos el detalle y el artículo aplicable. Cualquier duda, escribinos."),
        ("trabajador", "Clarísimo, muchas gracias por la respuesta.")]},
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
    ("Avanza la paritaria del sector", "La comisión negociadora presentó la propuesta de recomposición salarial del trimestre."),
    ("Nuevo recibo de sueldo: qué cambia", "Entró en vigencia el formato del Anexo III con el detalle de contribuciones patronales."),
    ("Plenario de delegados", "Se realizó el plenario mensual con la participación de todas las seccionales."),
    ("Capacitación en seguridad e higiene", "Nuevo ciclo de talleres gratuitos para afiliados y delegados."),
    ("Verificá tu recibo desde la app", "Ya podés controlar tus aportes desde el celular y enviar el recibo al sindicato."),
    ("Aportes al día: campaña de control", "La organización intensifica el control de depósitos de aportes de los empleadores."),
    ("Torneo deportivo interseccionales", "Abrió la inscripción para el torneo anual de fútbol entre seccionales."),
    ("Convenio con red de farmacias", "Descuentos para afiliados en medicamentos de venta libre y recetados."),
    ("Obras en la seccional Rosario", "Comenzó la renovación del salón de usos múltiples."),
    ("Aniversario de la organización", "Actividades y festejos en todas las seccionales."),
]
CIERRE_NOTICIA = (" La medida alcanza a todos los afiliados en actividad y se implementa de manera "
                  "escalonada durante los próximos meses. Desde la organización recordamos que ante "
                  "cualquier duda podés acercarte a tu seccional, escribir por la app en la sección "
                  "Trámites, o consultar al delegado de tu establecimiento. Vamos a seguir informando "
                  "por este medio cada novedad.")

BENEFICIOS = [
    ("Farmacias", "20% de descuento en la red de farmacias adheridas presentando la credencial vigente. Válido para medicamentos de venta libre y recetados."),
    ("Turismo", "Planes de turismo familiar con financiación propia en el hotel de la organización. Temporada alta con reserva anticipada."),
    ("Óptica", "Anteojos recetados con 30% de descuento para afiliados y su grupo familiar en ópticas adheridas."),
    ("Librería escolar", "Kit escolar completo con descuento para hijos de afiliados, retiro en cada seccional."),
    ("Deportes", "Acceso libre al polideportivo para el grupo familiar y escuelas deportivas para chicos."),
    ("Odontología", "Consultas y tratamientos con arancel preferencial en los consultorios propios."),
    ("Electrodomésticos", "Convenio con casas de electrodomésticos: cuotas sin interés con débito por recibo."),
    ("Capacitación", "Cursos de oficios y de informática gratuitos con certificación oficial."),
    ("Proveeduría", "Canasta de alimentos con precios de proveeduría sindical, entrega mensual."),
    ("Salud", "Chequeo médico anual sin cargo en los consultorios de la organización."),
]


# ---------------------------------------------------------------- identidad del lote
# Perfiles de recibo por sindicato: clave = fragmento del nombre en
# MAYÚSCULAS, valor = función que arma las líneas de ingreso según SU
# convenio. Lo llena quien lo necesite antes de sembrar (ver cargar_bancaria).
PERFILES = {}


def argumento(nombre: str) -> str:
    if nombre in sys.argv:
        i = sys.argv.index(nombre)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return ""


def buscar_sindicato(texto: str):
    with db.get_session() as s:
        sinds = s.exec(select(Sindicato).where(Sindicato.activo == True)).all()
        candidatos = [x for x in sinds if texto.lower() in x.nombre.lower()]
    if not candidatos:
        sys.exit(f"No hay ningún sindicato activo cuyo nombre contenga '{texto}'. "
                 f"Existen: {', '.join(x.nombre for x in sinds)}")
    if len(candidatos) > 1:
        sys.exit(f"'{texto}' es ambiguo: {', '.join(x.nombre for x in candidatos)}")
    return candidatos[0].id, candidatos[0].nombre


def contexto_lote(sid: int, nombre: str) -> dict:
    """Todo lo determinista del lote depende del sindicato: CUILes propios
    (bloque separado por sid para no chocar con otros lotes), semilla propia."""
    rnd = random.Random(73000 + sid)
    base_cuil = 65000000 + (sid % 40) * 1_000_000
    cuils = [f"{'20' if i % 3 else '27'}{base_cuil + i:08d}{(i * 7) % 10}"
             for i in range(CANT_TRABAJADORES)]
    if any(p in nombre.upper() for p in ("AEFIP", "FISCAL")):
        empresas_base = ORGANISMOS_FISCALES
    elif "BANCARIA" in nombre.upper() or "BANCARIO" in nombre.upper():
        empresas_base = BANCOS
    else:
        empresas_base = EMPRESAS_GENERICAS
    cuits = [f"30{base_cuil + 900000 + j:08d}{(j * 3) % 10}" for j in range(len(empresas_base))]
    # El número de expediente es ÚNICO EN TODA LA PLATAFORMA y su prefijo
    # sale del código del tipo: si dos sindicatos usan el mismo código
    # ("F01"), sus expedientes chocan (hallazgo anotado en BACKLOG.md). Los
    # tipos del lote llevan la sigla del sindicato para no pisarse.
    sigla = "".join(ch for ch in nombre.upper() if ch.isalnum())[:4] or f"S{sid}"
    # Perfil de recibo propio del sindicato (opcional): una función
    # (rnd, trabajador, conceptos, fecha) -> lista de líneas de ingreso, para
    # armar recibos fieles a SU convenio en vez del genérico. Lo registran
    # scripts como cargar_bancaria.py en PERFILES antes de sembrar.
    perfil = None
    for clave, funcion in PERFILES.items():
        if clave in nombre.upper():
            perfil = funcion
            break
    return {"rnd": rnd, "cuils": cuils, "empresas_base": empresas_base, "cuits": cuits,
            "sigla": sigla, "perfil": perfil,
            "codigos_tipo": [f"{sigla}-{t['codigo']}" for t in TIPOS_TRAMITE]}


def _ts(rnd, dias_atras: int, hora: int = None) -> str:
    h = hora if hora is not None else rnd.randint(8, 20)
    return f"{(HOY - timedelta(days=dias_atras)).isoformat()} {h:02d}:{rnd.randint(0, 59):02d}"


def _fecha_ar(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ---------------------------------------------------------------- limpiar
def limpiar(sid: int, ctx: dict):
    cuils = set(ctx["cuils"])
    with db.get_session() as s:
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
            if tt.codigo in ctx["codigos_tipo"] and not s.exec(select(Tramite).where(
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
        titulos = tuple(t for t, _ in NOTICIAS)
        for n in s.exec(select(Noticia).where(Noticia.sindicato_id == sid)).all():
            if n.titulo.startswith(titulos):
                s.delete(n)
        rubros = tuple(r for r, _ in BENEFICIOS)
        for b in s.exec(select(Beneficio).where(Beneficio.sindicato_id == sid)).all():
            if b.rubro.startswith(rubros):
                s.delete(b)
        for m in (ReciboVerificado, EnvioSindicato, Reporte):
            for fila in s.exec(select(m).where(m.sindicato_id == sid)).all():
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
            if e.cuit in set(ctx["cuits"]):
                s.delete(e)
        s.commit()
        for sec in s.exec(select(Seccional).where(Seccional.sindicato_id == sid)).all():
            if sec.nombre in SECCIONALES_GENERICAS and not s.exec(select(Trabajador).where(
                    Trabajador.seccional_id == sec.id)).first():
                s.delete(sec)
        s.commit()
    print("Lote borrado.")


# ---------------------------------------------------------------- base
def sembrar_base(sid: int, ctx: dict):
    rnd = ctx["rnd"]
    with db.get_session() as s:
        actuales = db.modulos_habilitados(sid)
        db.set_modulos_sindicato(sid, list(dict.fromkeys(
            actuales + ["dashboard", "tramites", "notificaciones", "noticias", "beneficios"])))

        # Seccionales: usa las reales; completa con genéricas hasta tener 4+.
        existentes = s.exec(select(Seccional).where(Seccional.sindicato_id == sid)).all()
        secc_ids = [sec.id for sec in existentes]
        for nombre in SECCIONALES_GENERICAS:
            if len(secc_ids) >= 6:
                break
            if any(sec.nombre == nombre for sec in existentes):
                continue
            # Sin coordenadas a propósito: una seccional genérica del
            # lote no tiene domicilio real, y un globo inventado en el mapa
            # del Panel es peor que la marca honesta de "sin ubicar". Las
            # seccionales de verdad del sindicato ya vienen georreferenciadas.
            sec = Seccional(sindicato_id=sid, nombre=nombre,
                            **geo.campos_para_guardar(
                                {"calle": "Av. Rivadavia", "numero": str(rnd.randint(100, 4500)),
                                 "localidad": nombre}, precision="sin_geo"))
            s.add(sec); s.commit(); s.refresh(sec)
            secc_ids.append(sec.id)

        # Empleadores: usa los reales activos; completa con sintéticos hasta ~12.
        reales = s.exec(select(Empleador).where(Empleador.sindicato_id == sid,
                                                Empleador.activo == True)).all()
        empresas = [{"cuit": e.cuit.replace("-", "").replace(" ", ""),
                     "razon": e.razon_social or e.cuit,
                     "conducta": rnd.choice([(5, 22), (8, 28), (40, 60), None])}
                    for e in reales]
        for j, (razon, conducta) in enumerate(ctx["empresas_base"]):
            if len(empresas) >= 12:
                break
            cuit = ctx["cuits"][j]
            if not s.exec(select(Empleador).where(Empleador.sindicato_id == sid,
                                                  Empleador.cuit == cuit)).first():
                s.add(Empleador(sindicato_id=sid, cuit=cuit, razon_social=razon,
                                provincia=rnd.choice(["Buenos Aires", "Santa Fe", "Córdoba"]),
                                activo=True))
            empresas.append({"cuit": cuit, "razon": razon, "conducta": conducta})
        s.commit()

        trabajadores = []
        for cuil in ctx["cuils"]:
            nombre = f"{rnd.choice(NOMBRES)} {rnd.choice(APELLIDOS)}"
            emp = rnd.choice(empresas)
            if not s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                                   Trabajador.cuil == cuil)).first():
                s.add(Trabajador(sindicato_id=sid, cuil=cuil, nombre=nombre,
                                 registrado=True, seccional_id=rnd.choice(secc_ids),
                                 cuit_empleador=emp["cuit"],
                                 provincia=rnd.choice(["Buenos Aires", "Santa Fe", "Córdoba"])))
            if not s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil)).first():
                s.add(CuentaTrabajador(cuil=cuil, nombre=nombre,
                                       clave_hash=auth.hashear_clave(cuil[:5])))
            # `semilla` deja que un perfil derive rasgos ESTABLES del
            # trabajador (antigüedad, función, título): tienen que ser los
            # mismos en todos sus recibos, no sortearse en cada uno.
            trabajadores.append({"cuil": cuil, "nombre": nombre, "empresa": emp,
                                 "sueldo": rnd.randint(900, 3200) * 1000,
                                 "semilla": int(cuil[-7:]), "antiguedad": rnd.randint(0, 38)})
        s.commit()
    return trabajadores, empresas, secc_ids


# ---------------------------------------------------------------- recibos
def _armar_recibo(ctx, trab, conceptos, dias_atras):
    """Recibo base con el CATÁLOGO REAL del sindicato: ingresos de sus
    conceptos de tipo ingreso, y una línea por cada concepto de descuento
    controlado por fórmula (el importe correcto lo pone la autocorrección)."""
    rnd = ctx["rnd"]
    fecha_proceso = HOY - timedelta(days=dias_atras)
    periodo = (fecha_proceso.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    genericos = [c for c in conceptos if not c.get("cuit_empleador")]
    ingresos = [c for c in genericos if c["tipo"] == "ingreso"]
    ingresos_rem = [c for c in ingresos if c.get("remunerativo", True)] or ingresos

    # Con perfil propio, las líneas las arma el convenio del sindicato.
    if ctx.get("perfil"):
        lineas = ctx["perfil"](rnd, trab, genericos, fecha_proceso)
        return _envoltorio_recibo(ctx, trab, lineas, periodo, fecha_proceso, dias_atras), fecha_proceso

    if not ingresos_rem:
        sys.exit("Este sindicato no tiene ningún concepto de tipo 'ingreso' cargado: sin\n"
                 "catálogo no se pueden armar ni validar recibos. Cargá sus conceptos desde\n"
                 "/admin → Conceptos (o con el script de alta del sindicato) y volvé a correr.")

    lineas = []
    principal = ingresos_rem[0]
    sueldo = round(trab["sueldo"] * rnd.uniform(0.97, 1.06), 2)
    lineas.append({"codigo": principal["codigo"], "descripcion": principal["nombre"],
                   "importe": sueldo, "tipo": "remuneracion", "categoria_universal": None})
    for extra in ingresos_rem[1:3]:
        if rnd.random() < 0.7:
            lineas.append({"codigo": extra["codigo"], "descripcion": extra["nombre"],
                           "importe": round(sueldo * rnd.uniform(0.05, 0.18), 2),
                           "tipo": "remuneracion", "categoria_universal": None})
    no_rem = [c for c in ingresos if not c.get("remunerativo", True)]
    if no_rem and rnd.random() < 0.5:
        c = rnd.choice(no_rem)
        lineas.append({"codigo": c["codigo"], "descripcion": c["nombre"],
                       "importe": round(rnd.uniform(30000, 110000), 2),
                       "tipo": "remuneracion", "categoria_universal": None})
    return _envoltorio_recibo(ctx, trab, lineas, periodo, fecha_proceso, dias_atras), fecha_proceso


def _envoltorio_recibo(ctx, trab, lineas, periodo, fecha_proceso, dias_atras):
    """El recibo alrededor de sus líneas (encabezado, período, formato). Lo
    comparten el armado genérico y los perfiles por convenio."""
    rnd = ctx["rnd"]
    categoria = trab.get("categoria") or rnd.choice(CATEGORIAS)
    return {
        "formato": "nuevo" if rnd.random() < (0.25 + (DIAS_HISTORIA - dias_atras) / DIAS_HISTORIA * 0.65) else "clasico",
        "empleado": {"apellido_nombre": trab["nombre"], "cuil": trab["cuil"],
                     "legajo": str(rnd.randint(100, 9999)),
                     "categoria": categoria, "fecha_ingreso": None},
        "empleador": {"nombre": trab["empresa"]["razon"], "cuit": trab["empresa"]["cuit"]},
        "periodo": periodo, "fecha_pago": _fecha_ar(fecha_proceso),
        "lineas": lineas, "totales_impresos": {},
        "contribuciones_patronales": [], "costo_laboral_total": None,
        "ultimo_deposito": None, "confianza": "alta", "observaciones": None,
        "alerta_adulteracion": {"detectada": False, "motivo": None},
    }


def _cerrar_totales(recibo):
    ingresos = sum(l["importe"] for l in recibo["lineas"] if l["importe"] > 0)
    descuentos = sum(l["importe"] for l in recibo["lineas"] if l["importe"] < 0)
    recibo["totales_impresos"] = {"remuneraciones": round(ingresos, 2),
                                  "descuentos": round(descuentos, 2),
                                  "neto": round(ingresos + descuentos, 2)}


def _autocorregir(recibo, conceptos, formulas, topes, tope_pct, cuil, catalogo_por_codigo):
    """Ajusta cada aporte al "esperado" del validador real, hasta 4 pasadas
    (por si una fórmula referencia el importe de otra). Devuelve el resultado
    de la última validación."""
    resultado = None
    for _ in range(4):
        _cerrar_totales(recibo)
        resultado = validar(conceptos, formulas, recibo, tope_sindical_pct=tope_pct,
                            cuil_sesion=cuil, topes=topes)
        pendiente = False
        codigos_en_recibo = {l["codigo"] for l in recibo["lineas"]}
        for fv in resultado.get("formulas_validadas") or []:
            esperado = a_numero(fv.get("esperado"))
            if esperado is None:
                continue
            if fv["codigo"] not in codigos_en_recibo:
                concepto = catalogo_por_codigo.get(fv["codigo"])
                recibo["lineas"].append({
                    "codigo": fv["codigo"],
                    "descripcion": concepto["nombre"] if concepto else fv["codigo"],
                    "importe": -round(esperado, 2), "tipo": "aporte_trabajador",
                    "categoria_universal": None})
                pendiente = True
                continue
            for l in recibo["lineas"]:
                if l["codigo"] == fv["codigo"] and abs(abs(l["importe"]) - esperado) > 0.5:
                    l["importe"] = -round(esperado, 2)
                    pendiente = True
        # Un "concepto_faltante" agrega la línea que faltaba.
        for d_ in resultado.get("discrepancias") or []:
            if d_["tipo"] == "concepto_faltante" and d_["codigo"] not in codigos_en_recibo:
                concepto = catalogo_por_codigo.get(d_["codigo"])
                recibo["lineas"].append({
                    "codigo": d_["codigo"],
                    "descripcion": concepto["nombre"] if concepto else d_["codigo"],
                    "importe": -1000.0, "tipo": "aporte_trabajador",
                    "categoria_universal": None})
                pendiente = True
        if not pendiente:
            break
    return resultado


def _inyectar_error(ctx, recibo):
    rnd = ctx["rnd"]
    aportes = [l for l in recibo["lineas"] if l["importe"] < 0]
    opciones = ["totales_mal"] + (["aporte_mal", "aporte_faltante"] if aportes else [])
    for e in rnd.sample(opciones, k=min(len(opciones), 1 if rnd.random() < 0.7 else 2)):
        if e == "aporte_mal":
            l = rnd.choice(aportes)
            l["importe"] = round(l["importe"] * rnd.choice([0.5, 0.7, 1.3, 1.6]), 2)
        elif e == "aporte_faltante":
            recibo["lineas"].remove(rnd.choice(aportes))
            aportes = [l for l in recibo["lineas"] if l["importe"] < 0]
        elif e == "totales_mal":
            _cerrar_totales(recibo)
            recibo["totales_impresos"]["neto"] = round(
                recibo["totales_impresos"]["neto"] - rnd.uniform(8000, 60000), 2)
            return  # los totales quedan como están, no volver a cerrarlos
    _cerrar_totales(recibo)


def sembrar_recibos(sid: int, ctx: dict, trabajadores: list):
    rnd = ctx["rnd"]
    verificadores = trabajadores[:int(CANT_TRABAJADORES * 0.7)]
    conceptos = db.conceptos_como_dicts(sid)
    formulas = db.formulas_como_dicts(sid)
    topes = db.topes_como_dicts()
    tope_pct = db.obtener_tope_sindical()
    catalogo_por_codigo = {c["codigo"]: c for c in conceptos if not c.get("cuit_empleador")}

    contadores = {"OK": 0, "CON_DISCREPANCIAS": 0, "enviados": 0, "reportados": 0}
    lote = []
    for _ in range(CANT_RECIBOS):
        trab = rnd.choice(verificadores)
        # El volumen CRECE hacia hoy (curva de adopción de la app). Con el
        # pico 12 días atrás quedaban ~4 recibos hoy contra ~80 en el medio, y
        # el tablero -- que abre en "Hoy" -- parecía vacío al entrar.
        dias_atras = min(DIAS_HISTORIA - 1, int(rnd.triangular(0, DIAS_HISTORIA, 0)))
        recibo, fecha_proceso = _armar_recibo(ctx, trab, conceptos, dias_atras)

        resultado = _autocorregir(recibo, conceptos, formulas, topes, tope_pct,
                                  trab["cuil"], catalogo_por_codigo)
        if rnd.random() < 0.20:
            _inyectar_error(ctx, recibo)
            resultado = validar(conceptos, formulas, recibo, tope_sindical_pct=tope_pct,
                                cuil_sesion=trab["cuil"], topes=topes)

        conducta = trab["empresa"]["conducta"]
        if conducta and rnd.random() < 0.85:
            recibo["ultimo_deposito"] = {
                "fecha": _fecha_ar(fecha_proceso - timedelta(days=rnd.randint(*conducta))),
                "periodo": None, "banco": None}
        if recibo["formato"] == "nuevo":
            base = sum(l["importe"] for l in recibo["lineas"] if l["importe"] > 0)
            contribs = [
                {"concepto": "Contribución jubilatoria", "base": round(base, 2),
                 "porcentaje": "10,77%", "importe": round(base * 0.1077, 2)},
                {"concepto": "Obra social patronal", "base": round(base, 2),
                 "porcentaje": "6%", "importe": round(base * 0.06, 2)},
                {"concepto": "ART", "base": round(base, 2),
                 "porcentaje": "3,5%", "importe": round(base * 0.035, 2)},
            ]
            recibo["contribuciones_patronales"] = contribs
            recibo["costo_laboral_total"] = round(base + sum(c["importe"] for c in contribs), 2)

        estado = resultado.get("estado", "")
        contadores[estado] = contadores.get(estado, 0) + 1
        procesado_en = _ts(rnd, dias_atras)
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
                              estado=ctx["rnd"].choice(["nuevo", "nuevo", "en_revision", "resuelto"]),
                              detalle=item["detalle"]))
            if i % 500 == 499:
                s.commit()
        s.commit()
    return contadores


# ---------------------------------------------------------------- trámites
def sembrar_tramites(sid: int, ctx: dict, trabajadores: list):
    rnd = ctx["rnd"]
    with db.get_session() as s:
        existentes = {t.codigo: t.id for t in s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == sid)).all()}
    defs_por_tipo = {}
    for t in TIPOS_TRAMITE:
        codigo = f"{ctx['sigla']}-{t['codigo']}"
        tid = existentes.get(codigo) or db.crear_tipo_tramite(
            sid, t["titulo"], codigo, t["campos"])
        defs_por_tipo[tid] = t

    with db.get_session() as s:
        campos_por_tipo = {tid: s.exec(select(CampoTramite).where(
            CampoTramite.tipo_tramite_id == tid).order_by(CampoTramite.orden)).all()
            for tid in defs_por_tipo}

    estados_transicion = {
        "en_tratamiento": ["Iniciado → En tratamiento"],
        "respondido": ["Iniciado → En tratamiento", "En tratamiento → Respondido"],
        "espera_info": ["Iniciado → En tratamiento",
                        "En tratamiento → A la espera de información del afiliado"],
        "terminado": ["Iniciado → En tratamiento", "En tratamiento → Terminado"],
    }
    creados = 0
    for _ in range(CANT_TRAMITES):
        trab = rnd.choice(trabajadores)
        tid = rnd.choice(list(defs_por_tipo))
        definicion = defs_por_tipo[tid]

        # Formulario COMPLETO: cada campo con una respuesta coherente al tema.
        respuestas = []
        for c in campos_por_tipo[tid]:
            generador = definicion["respuestas"].get(c.etiqueta)
            if generador:
                valor = generador(rnd)
            elif c.tipo_dato == "fecha":
                valor = (HOY - timedelta(days=rnd.randint(5, 90))).isoformat()
            elif c.tipo_dato == "numero":
                valor = str(rnd.randint(5000, 250000))
            elif c.tipo_dato in ("seleccion", "opcion_unica"):
                valor = rnd.choice([o.strip() for o in c.opciones.split(",") if o.strip()])
            else:
                valor = trab["empresa"]["razon"] if "mpleador" in c.etiqueta else "Sin comentarios."
            respuestas.append({"campo_tramite_id": c.id, "valor_texto": valor})
        res = db.crear_tramite(sid, tid, trab["cuil"], respuestas)
        if not res:
            continue
        creados += 1

        dias_atras = rnd.randint(0, DIAS_HISTORIA)
        creado_ts = _ts(rnd, dias_atras)
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
        actualizado_ts = (_ts(rnd, max(0, dias_atras - dias_resolucion)) if dias_resolucion
                          else (creado_ts if estado == "iniciado"
                                else _ts(rnd, max(0, dias_atras - rnd.randint(1, 8)))))

        with db.get_session() as s:
            tr = s.get(Tramite, res["id"])
            tr.creado, tr.actualizado, tr.estado = creado_ts, actualizado_ts, estado
            if estado == "terminado":
                tr.resuelto_en = actualizado_ts
            s.add(tr)
            for lg in s.exec(select(TramiteLog).where(TramiteLog.tramite_id == tr.id)).all():
                lg.creado = creado_ts
                s.add(lg)
            for detalle in estados_transicion.get(estado, []):
                s.add(TramiteLog(tramite_id=tr.id, evento="cambio_estado",
                                 detalle=detalle, creado=actualizado_ts))
            # IDA Y VUELTA sindicato ↔ afiliado: en todo trámite que avanzó,
            # el diálogo temático del tipo (2 a 4 mensajes), con su log.
            if estado != "iniciado":
                cuantas = {"en_tratamiento": 1, "espera_info": 2,
                           "respondido": rnd.randint(2, 3)}.get(estado, rnd.randint(2, 4))
                for orden, (autor, texto) in enumerate(definicion["dialogo"][:cuantas]):
                    nota_ts = _ts(rnd, max(0, dias_atras - orden - 1))
                    s.add(NotaTramite(tramite_id=tr.id, autor=autor, texto=texto,
                                      creado=nota_ts))
                    s.add(TramiteLog(tramite_id=tr.id, evento=f"nota_{autor}",
                                     detalle=texto[:80], creado=nota_ts))
            s.commit()
    return creados


# ------------------------------------------------------- notificaciones y contenido
def sembrar_notificaciones(sid: int, ctx: dict, secc_ids: list, trabajadores: list):
    rnd = ctx["rnd"]
    # Para las automáticas: expediente real de cada trabajador (si tiene).
    with db.get_session() as s:
        expedientes = {}
        for tr in s.exec(select(Tramite).where(Tramite.sindicato_id == sid)).all():
            expedientes.setdefault(tr.cuil, tr.numero_expediente)
    creadas = 0
    for i in range(CANT_NOTIFS):
        dias_atras = rnd.randint(0, DIAS_HISTORIA)
        if i % 4 == 3:
            trab = rnd.choice(trabajadores)
            expediente = expedientes.get(trab["cuil"])
            texto = (f"Tu expediente {expediente} cambió de estado. Entrá a Trámites para ver el detalle."
                     if expediente else
                     "Tu expediente cambió de estado. Entrá a Trámites para ver el detalle.")
            res = db.crear_notificacion(sid, None, "Mesa de Entradas", texto,
                                        "cuil", [trab["cuil"]], origen="sistema")
        else:
            criterio, valores = rnd.choice([
                ("seccional", [rnd.choice(secc_ids)]),
                ("seccional", rnd.sample(secc_ids, k=min(2, len(secc_ids)))),
                ("cuil", [t["cuil"] for t in rnd.sample(trabajadores, k=rnd.randint(5, 30))]),
            ])
            res = db.crear_notificacion(sid, None, rnd.choice(REMITENTES),
                                        rnd.choice(TEXTOS_NOTIF), criterio, valores)
        if not res["cantidad_destinatarios"]:
            continue
        creadas += 1
        tasa = rnd.uniform(0.35, 0.85)
        with db.get_session() as s:
            n = s.get(Notificacion, res["id"])
            n.enviado_en = _ts(rnd, dias_atras)
            s.add(n)
            for d_ in s.exec(select(NotificacionDestinatario).where(
                    NotificacionDestinatario.notificacion_id == n.id)).all():
                if rnd.random() < tasa:
                    d_.leida_en = _ts(rnd, max(0, dias_atras - rnd.randint(0, 7)))
                    s.add(d_)
            s.commit()
    return creadas


def sembrar_contenido(sid: int, ctx: dict, secc_ids: list):
    rnd = ctx["rnd"]
    with db.get_session() as s:
        for i in range(30):
            titulo, bajada = NOTICIAS[i % len(NOTICIAS)]
            if i >= len(NOTICIAS):
                titulo = f"{titulo} ({i // len(NOTICIAS) + 1})"
            dias_atras = rnd.randint(0, DIAS_HISTORIA)
            desde = HOY - timedelta(days=dias_atras)
            s.add(Noticia(sindicato_id=sid, titulo=titulo, bajada=bajada,
                          texto_completo=bajada + CIERRE_NOTICIA,
                          fecha_desde=desde.isoformat(),
                          fecha_hasta=(desde + timedelta(days=rnd.randint(20, 60))).isoformat(),
                          creada=_ts(rnd, dias_atras),
                          destino_seccionales=([rnd.choice(secc_ids)] if rnd.random() < 0.3 else [])))
        for i in range(20):
            rubro, descripcion = BENEFICIOS[i % len(BENEFICIOS)]
            if i >= len(BENEFICIOS):
                rubro = f"{rubro} {i // len(BENEFICIOS) + 1}"
            dias_atras = rnd.randint(0, 60)
            desde = HOY - timedelta(days=dias_atras)
            s.add(Beneficio(sindicato_id=sid, rubro=rubro, descripcion=descripcion,
                            link="https://beneficios.ejemplo.org.ar" if rnd.random() < 0.4 else "",
                            fecha_desde=desde.isoformat(),
                            fecha_hasta=(desde + timedelta(days=rnd.randint(60, 180))).isoformat(),
                            creada=_ts(rnd, dias_atras), destino_seccionales=[]))
        s.commit()


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    objetivo = argumento("--sindicato")
    if not objetivo:
        sys.exit('Falta --sindicato "NOMBRE" (busca por nombre, ej: --sindicato "AEFIP").')
    sid, nombre = buscar_sindicato(objetivo)
    ctx = contexto_lote(sid, nombre)
    print(f"Sindicato: {nombre} (id={sid})")

    if "--limpiar" in sys.argv:
        limpiar(sid, ctx)
        sys.exit(0)

    # Mira los RECIBOS, no los trabajadores: si una corrida anterior se cortó
    # después de sembrar la base, hay que poder retomarla (sembrar_base es
    # idempotente).
    with db.get_session() as s:
        ya = s.exec(select(ReciboVerificado).where(
            ReciboVerificado.sindicato_id == sid,
            ReciboVerificado.cuil.in_(ctx["cuils"][:5]))).first()
    if ya:
        sys.exit("El lote ya está cargado para este sindicato (usá --limpiar para regenerarlo).")

    print("Sembrando base (seccionales, empresas, 100 trabajadores con cuenta)...")
    trabajadores, empresas, secc_ids = sembrar_base(sid, ctx)
    print("Generando y VALIDANDO 5.000 recibos con el catálogo real (paciencia)...")
    contadores = sembrar_recibos(sid, ctx, trabajadores)
    print(f"  Recibos: {contadores.get('OK', 0)} OK, "
          f"{contadores.get('CON_DISCREPANCIAS', 0)} con discrepancias, "
          f"{contadores['enviados']} enviados, {contadores['reportados']} reportados.")
    print("Creando 5 tipos de trámite y 2.000 trámites con formulario y diálogo...")
    print(f"  Trámites creados: {sembrar_tramites(sid, ctx, trabajadores)}.")
    print("Enviando 200 notificaciones...")
    print(f"  Notificaciones: {sembrar_notificaciones(sid, ctx, secc_ids, trabajadores)}.")
    print("Cargando 30 noticias y 20 beneficios...")
    sembrar_contenido(sid, ctx, secc_ids)

    print("\nLote cargado. Accesos de ejemplo (clave = 5 primeros dígitos del CUIL):")
    for t in trabajadores[:3]:
        print(f"  Trabajador {t['nombre']}: CUIL {t['cuil']} / clave {t['cuil'][:5]}")

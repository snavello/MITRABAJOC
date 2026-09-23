"""Carga dos sindicatos de demostración completos, para mostrar la plataforma.

Ejecutar UNA vez con el servidor apagado:  python cargar_demo.py
Crea: 2 sindicatos con marca, sus admins, conceptos, fórmulas, trabajadores,
empleadores y -- desde el sprint de Áreas V2 -- la estructura organizativa
completa: seccionales, áreas con perfiles distintos, un Admin de Seccional,
usuarios de área y formularios ruteados por área.

Los dos sindicatos son a propósito distintos entre sí: la UOM es federada
(Sede Central + dos delegaciones, con pase entre áreas) y la Gastronómica es
centralizada (una sola seccional, un área). Sin el contraste, la demo no
muestra que el rol de Admin de Seccional es opt-in y que un sindicato chico
sigue funcionando como antes.
"""
import sys
# La consola de Windows usa cp1252 y no puede imprimir el ✓ ni las flechas
# del resumen de accesos: el script moría con UnicodeEncodeError DESPUÉS de
# haber escrito parte de los datos, dejando la demo cargada a medias con un
# traceback que parecía una falla real y no lo era.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import db
import geo
import demo_encuestas
from db import (Sindicato, UsuarioSindicato, Concepto, Formula, Trabajador, Empleador,
                Seccional, Area)
from sqlmodel import SQLModel, select
from sqlalchemy import delete as sa_delete, or_ as sa_or, select as sa_select
import auth
from modulos import MODULOS_INICIALES

# Teléfonos de las seccionales de demo. Ficticios, con código de área real
# de cada ciudad: sin ellos los botones Llamar y WhatsApp de "Mi seccional"
# no aparecen y esa pantalla se ve a medias justo cuando se la muestra.
TELEFONOS_DEMO = {
    "Sede Central": "11 4555 1200", "Rosario": "341 425 0850",
    "Córdoba": "351 422 0430", "La Matanza": "11 4651 2900",
    "Mar del Plata": "223 495 3100", "Bariloche": "294 442 0550",
    "Salta": "387 421 0640",
}

SINDICATOS = [
    {
        "nombre": "Unión Obrera Metalúrgica", "descripcion": "Trabajadores del metal",
        "cuit": "30-11111111-1", "mail": "info@uom.org.ar", "autoridad": "Ana Pérez",
        "cargo_autoridad": "Secretaria General",
        "color_primario": "#1a3d6b", "color_secundario": "#2fa88f", "color_acento": "#e8b84b",
        "admin": ("20111111110", "uom-demo"),   # CUIT del admin UOM
        "conceptos": [
            ("SUELDO", "Sueldo básico", "ingreso", True),
            ("PRESENT", "Presentismo", "ingreso", True),
            ("VIATICO", "Viáticos", "ingreso", False),
            ("JUB", "Aporte jubilatorio", "descuento", False),
            ("SINDMET", "Cuota sindical UOM", "descuento", False),
        ],
        "formulas": [
            ("JUB", "Jubilación = 11% del remunerativo", "0.11 * base_remunerativa", 1.0),
            ("SINDMET", "Cuota UOM = 2.5% del remunerativo", "0.025 * base_remunerativa", 1.0),
        ],
        # (nombre, ve_todas, domicilio). Sede Central es la única con
        # ve_todas: sus usuarios alcanzan a todo el país, los de una
        # delegación solo a la suya.
        #
        # Las DIRECCIONES SON FICTICIAS pero verosímiles: no conozco con
        # certeza los domicilios reales de estos gremios y no los invento
        # como si lo fueran. Las COORDENADAS, en cambio, son reales para esa
        # esquina -- salieron de geocodificar estas direcciones una vez, a
        # mano, el 2026-09-12. Van como `manual` justamente para no dar a
        # entender que son domicilios verificados del sindicato.
        "seccionales": [
            ("Sede Central", True, ("La Rioja", "1975", "Ciudad Autónoma de Buenos Aires",
                                    "Ciudad Autónoma de Buenos Aires", "C1260AAK",
                                    -34.634446, -58.406019)),
            ("Rosario", False, ("San Martín", "850", "Rosario", "Santa Fe", "2000",
                                -32.947338, -60.636893)),
            ("Córdoba", False, ("Boulevard San Juan", "430", "Córdoba", "Córdoba", "X5000",
                                -31.419157, -64.191904)),
            ("La Matanza", False, ("Arieta", "2900", "San Justo", "Buenos Aires", "1754",
                                   -34.676590, -58.563065)),
        ],
        # (seccional, área, secciones del panel que hereda quien está en ella).
        # Los perfiles son distintos a propósito: la demo tiene que mostrar
        # que un usuario de Prensa NO ve Trámites y uno de Mesa de Entradas
        # NO ve Noticias. Con todas las áreas iguales, la pantalla de
        # permisos parece decorativa.
        "areas": [
            ("Sede Central", "Mesa de Entradas", ["tramites_recibidos", "trabajadores"]),
            ("Sede Central", "Legales", ["tramites_recibidos", "tramites_formularios"]),
            # Prensa Central arma encuestas Y lee resultados; Prensa Córdoba
            # SOLO lee. Es lo que muestra que las dos secciones de N17 no son
            # la misma cosa: un delegado puede mirar el dashboard sin poder
            # lanzar nada.
            ("Sede Central", "Prensa", ["noticias", "beneficios", "notificaciones",
                                        "encuestas", "encuestas_resultados"]),
            ("Rosario", "Mesa de Entradas", ["tramites_recibidos", "trabajadores"]),
            ("Rosario", "Legales", ["tramites_recibidos"]),
            ("Córdoba", "Mesa de Entradas", ["tramites_recibidos", "trabajadores"]),
            ("Córdoba", "Prensa", ["noticias", "notificaciones", "encuestas_resultados"]),
        ],
        # (usuario/CUIL, clave, nombre, rol, seccional, área). El rol es
        # "admin_seccional" o "area"; el Super Admin va aparte, en "admin".
        # Hay un usuario por área a propósito: un área destino de trámite (o
        # de pase) sin nadie adentro es un trámite que en la demo no lo
        # atiende nadie, y el circuito se corta a la vista del sindicato.
        "usuarios": [
            ("20555555553", "rosario-demo", "Carla Ruiz", "admin_seccional",
             "Rosario", "Mesa de Entradas"),
            ("20666666665", "mesa-demo", "Diego Sosa", "area",
             "Rosario", "Mesa de Entradas"),
            ("27131313136", "legalros-demo", "Nadia Ortiz", "area",
             "Rosario", "Legales"),
            ("20101010109", "mesacentral-demo", "Inés Ferrer", "area",
             "Sede Central", "Mesa de Entradas"),
            ("20121212127", "legalcentral-demo", "Hugo Peña", "area",
             "Sede Central", "Legales"),
            ("27777777774", "prensa-demo", "Elena Vidal", "area",
             "Sede Central", "Prensa"),
            ("20141414145", "mesacba-demo", "Raúl Bravo", "area",
             "Córdoba", "Mesa de Entradas"),
            ("20888888887", "prensacba-demo", "Fabián Luna", "area",
             "Córdoba", "Prensa"),
        ],
        # (CUIL, nombre, seccional) del padrón de afiliados.
        "cuils": [
            ("20111111119", "Juan Molina", "Sede Central"),
            ("27222222224", "María Sánchez", "Rosario"),
            ("20333333336", "Pedro Ibarra", "Córdoba"),
        ],
        # Empleados del sindicato que ADEMÁS están afiliados: entran al
        # padrón y `sincronizar_por_cuil` les prende la marca sola. Elena
        # Vidal (Prensa) queda afuera a propósito -- trabaja en el gremio
        # sin estar afiliada a él, que es un caso real y no un error.
        "empleados_afiliados": ["20555555553", "20666666665", "27131313136",
                                "20101010109", "20121212127", "20141414145",
                                "20888888887"],
        # Formularios con ruteo por área. El primero habilita el pase; el
        # segundo no, para que se vea el contraste en el chat del trabajador.
        "tramites": [
            {
                "titulo": "Solicitud de licencia gremial", "codigo": "F10 UOM",
                "permite_pase": True,
                "default": ("Sede Central", "Mesa de Entradas"),
                "destinos": {"Rosario": ("Rosario", "Mesa de Entradas"),
                             "Córdoba": ("Córdoba", "Mesa de Entradas")},
                "pases": [("Sede Central", "Legales"), ("Rosario", "Legales")],
                "campos": [
                    {"etiqueta": "Motivo de la licencia", "tipo_dato": "texto"},
                    {"etiqueta": "Desde", "tipo_dato": "fecha"},
                    {"etiqueta": "Hasta", "tipo_dato": "fecha"},
                ],
            },
            {
                "titulo": "Cambio de domicilio", "codigo": "F11 UOM",
                "permite_pase": False,
                "default": ("Sede Central", "Mesa de Entradas"),
                "destinos": {"Rosario": ("Rosario", "Mesa de Entradas"),
                             "Córdoba": ("Córdoba", "Mesa de Entradas")},
                "pases": [],
                "campos": [
                    {"etiqueta": "Domicilio nuevo", "tipo_dato": "texto"},
                    {"etiqueta": "Localidad", "tipo_dato": "texto"},
                ],
            },
        ],
        "empleadores": [
            ("30111222339", "Constructora Ejemplo SA"),
            ("30999888776", "Metalúrgica del Sur SRL"),
        ],
    },
    {
        "nombre": "Federación Gastronómica", "descripcion": "Trabajadores gastronómicos",
        "cuit": "30-22222222-2", "mail": "info@fega.org.ar", "autoridad": "Luis Gómez",
        "cargo_autoridad": "Secretario General",
        "color_primario": "#7a1f2b", "color_secundario": "#c19a3e", "color_acento": "#3d6b4a",
        "admin": ("20222222220", "fega-demo"),  # CUIT del admin Gastronómica
        "conceptos": [
            ("BASICO", "Sueldo básico", "ingreso", True),
            ("ADIC", "Adicional por categoría", "ingreso", True),
            ("PROP", "Propinas (no remun.)", "ingreso", False),
            ("JUBG", "Aporte jubilatorio", "descuento", False),
            ("SINDGAS", "Cuota sindical gastronómica", "descuento", False),
        ],
        "formulas": [
            ("JUBG", "Jubilación = 11% del remunerativo", "0.11 * base_remunerativa", 1.0),
            ("SINDGAS", "Cuota gastronómica = 2% del remunerativo", "0.02 * base_remunerativa", 1.0),
        ],
        # Sindicato CENTRALIZADO, y sigue siéndolo aunque ahora tenga
        # delegaciones: NO tiene Admin de Seccional ni áreas por delegación,
        # todo se atiende desde Sede Central, que es lo que lo diferencia de
        # la UOM. Tiene cuatro seccionales para que el mapa del Panel se vea
        # poblado en una demostración; el contraste de ROLES se mantiene.
        # Direcciones ficticias, coordenadas reales (ver la nota en la UOM).
        "seccionales": [
            ("Sede Central", True, ("Avenida Rivadavia", "2530",
                                    "Ciudad Autónoma de Buenos Aires",
                                    "Ciudad Autónoma de Buenos Aires", "C1034ACR",
                                    -34.610009, -58.402274)),
            ("Mar del Plata", False, ("Avenida Luro", "3100", "Mar del Plata",
                                      "Buenos Aires", "B7600DRN", -37.996284, -57.551156)),
            ("Bariloche", False, ("Mitre", "550", "San Carlos de Bariloche", "Río Negro",
                                  "8400", -41.134270, -71.301931)),
            ("Salta", False, ("Caseros", "640", "Salta", "Salta", "4400",
                              -24.789722, -65.411569)),
        ],
        "areas": [
            ("Sede Central", "Atención al Afiliado",
             ["tramites_recibidos", "trabajadores", "noticias", "beneficios", "notificaciones"]),
        ],
        "usuarios": [
            ("20999999991", "atencion-demo", "Gabriela Paz", "area",
             "Sede Central", "Atención al Afiliado"),
        ],
        "cuils": [
            # el 222 también está en UOM (pluriempleo)
            ("27222222224", "María Sánchez", "Sede Central"),
            ("20444444440", "Sergio Ledesma", "Sede Central"),
        ],
        "empleados_afiliados": ["20999999991"],
        "tramites": [
            {
                "titulo": "Reclamo por propinas", "codigo": "F20 FEGA",
                "permite_pase": False,
                "default": ("Sede Central", "Atención al Afiliado"),
                "destinos": {}, "pases": [],
                "campos": [{"etiqueta": "Detalle del reclamo", "tipo_dato": "texto"}],
            },
        ],
        # el CUIT de "Constructora Ejemplo SA" también está en UOM -- mismo
        # criterio que el CUIL de pluriempleo, para probar el selector
        # multisindicato del lado del empleador.
        "empleadores": [("30111222339", "Constructora Ejemplo SA")],
    },
]

def borrar_sindicato_completo(s, sindicato_id: int) -> None:
    """Borra un sindicato y TODO lo que cuelga de él, en el orden correcto.

    La versión anterior enumeraba las tablas a mano y se quedaba corta cada
    vez que el esquema crecía: el script se podía correr dos veces solo si
    nadie había USADO la demo. En cuanto había un trámite presentado (o una
    noticia, o un acceso registrado), Postgres rechazaba el DELETE del
    sindicato por FK y el script moría a mitad de camino -- dejando la demo
    cargada a medias, que es exactamente lo que el resto del archivo se
    cuida de evitar.

    Así que el orden no se escribe: se deduce. `sorted_tables` viene
    ordenado por dependencia (padres primero), así que una sola pasada
    hacia adelante alcanza para marcar lo que cuelga del sindicato --
    cuando llega el turno de una tabla, sus padres ya están marcados -- y
    la pasada inversa lo borra de hijo a padre. Una tabla nueva con su FK
    entra sola.
    """
    tablas = list(SQLModel.metadata.sorted_tables)
    condenados = {"sindicato": {sindicato_id}}
    for tabla in tablas:
        if tabla.name == "sindicato":
            continue
        # Una fila cae si CUALQUIERA de sus FK apunta a algo ya condenado.
        condiciones = [fk.parent.in_(condenados[fk.column.table.name])
                       for fk in tabla.foreign_keys
                       if condenados.get(fk.column.table.name)]
        if not condiciones:
            continue
        pk = list(tabla.primary_key.columns)[0]
        filas = s.connection().execute(sa_select(pk).where(sa_or(*condiciones))).scalars().all()
        if filas:
            condenados[tabla.name] = set(filas)
    for tabla in reversed(tablas):
        ids = condenados.get(tabla.name)
        if ids:
            pk = list(tabla.primary_key.columns)[0]
            s.connection().execute(sa_delete(tabla).where(pk.in_(ids)))
    s.commit()


with db.get_session() as s:
    # Limpiar sindicatos demo previos (por si se corre dos veces).
    for nom in [x["nombre"] for x in SINDICATOS]:
        for sind in s.exec(select(Sindicato).where(Sindicato.nombre == nom)).all():
            borrar_sindicato_completo(s, sind.id)

import re
def slug(n):
    x = n.lower()
    for a,b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]: x=x.replace(a,b)
    return re.sub(r"[^a-z0-9]+","-",x).strip("-")

ROLES = {"admin_seccional": "Admin de Seccional", "area": "usuario de área"}
resumen_usuarios = []

for d in SINDICATOS:
    with db.get_session() as s:
        sind = Sindicato(
            nombre=d["nombre"], descripcion=d["descripcion"], slug=slug(d["nombre"]),
            cuit=d["cuit"], mail=d["mail"], autoridad=d["autoridad"],
            cargo_autoridad=d["cargo_autoridad"], color_primario=d["color_primario"],
            color_secundario=d["color_secundario"], color_acento=d["color_acento"],
            # Los dos sindicatos de la demo tienen ADEMÁS los módulos que
            # MODULOS_INICIALES deja afuera por ser opt-in comercial:
            # sin "tramites" y "notificaciones" no habría nada que rutear
            # por área, que es justamente lo que la demo muestra. Los que
            # siguen apagados ("convenio", "dashboard") son los que se
            # venden aparte.
            modulos_habilitados=list(MODULOS_INICIALES) + ["notificaciones", "tramites",
                                                           "empleadores", "encuestas"],
        )
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id

        # 1. Seccionales y áreas primero: todo lo demás las referencia.
        secs = {}
        zona = {}   # seccional -> (localidad, provincia), para el padrón
        for nombre, ve_todas, dom in d["seccionales"]:
            calle, numero, localidad, provincia, cp, lat, lon = dom
            zona[nombre] = (localidad, provincia)
            x = Seccional(sindicato_id=sid, nombre=nombre, ve_todas=ve_todas,
                          telefono=TELEFONOS_DEMO.get(nombre, ""),
                          whatsapp=TELEFONOS_DEMO.get(nombre, ""),
                          horario_atencion="Lunes a viernes de 9 a 17",
                          **geo.campos_para_guardar(
                              {"calle": calle, "numero": numero, "localidad": localidad,
                               "provincia": provincia, "codigo_postal": cp},
                              precision="manual", lat=lat, lon=lon))
            s.add(x); s.commit(); s.refresh(x)
            secs[nombre] = x.id
        areas = {}
        for seccional, nombre, _ in d["areas"]:
            a = Area(sindicato_id=sid, seccional_id=secs[seccional], nombre=nombre)
            s.add(a); s.commit(); s.refresh(a)
            areas[(seccional, nombre)] = a.id

        # 2. Padrón. Los empleados afiliados entran acá SIN la marca: se la
        # prende sola `sincronizar_por_cuil` cuando existe el usuario, que
        # es exactamente el camino que corre en el alta real.
        por_cuil = {u[0]: u for u in d["usuarios"]}
        filas = list(d["cuils"]) + [
            (cuil, por_cuil[cuil][2], por_cuil[cuil][4])
            for cuil in d.get("empleados_afiliados", []) if cuil in por_cuil]
        for cuil, nombre, seccional in filas:
            # Localidad y provincia de SU seccional: desde el 2026-09-13 son
            # obligatorias en las cuatro puertas por las que entra un
            # domicilio (geo.OBLIGATORIOS_AFILIADO), así que un padrón de demo
            # sin esos campos mostraría justo lo que la app ya no permite
            # cargar. Y la seccional es la mejor respuesta que hay acá: quien
            # está asignado a Rosario vive en Rosario.
            localidad, provincia = zona[seccional]
            s.add(Trabajador(sindicato_id=sid, cuil=cuil,
                             seccional_id=secs[seccional], registrado=False))
            # Los datos personales van en la PERSONA, no en el
            # empadronamiento: la fila de `cuentatrabajador` nace con el alta
            # del padrón y sin clave (todavía no se registró).
            db.guardar_datos_personales(
                s, cuil, nombre=nombre,
                domicilio=geo.campos_para_guardar(
                    {"localidad": localidad, "provincia": provincia},
                    precision="sin_geo"))

        # 3. El Super Admin de Sede Central: el admin de siempre, con los
        # accesos de siempre. La premisa del sprint es que no pierda nada.
        u, cl = d["admin"]
        central = d["seccionales"][0][0]
        s.add(UsuarioSindicato(sindicato_id=sid, usuario=u, cuil=u, nombre="Administrador",
                               clave_hash=auth.hashear_clave(cl), debe_cambiar_clave=False,
                               es_super_admin=True, seccional_id=secs[central]))
        for usuario, clave, nombre, rol, seccional, area in d["usuarios"]:
            s.add(UsuarioSindicato(
                sindicato_id=sid, usuario=usuario, cuil=usuario, nombre=nombre,
                clave_hash=auth.hashear_clave(clave), debe_cambiar_clave=False,
                es_super_admin=False, es_admin_seccional=(rol == "admin_seccional"),
                seccional_id=secs[seccional], area_id=areas[(seccional, area)]))

        for cod, nom, tipo, rem in d["conceptos"]:
            s.add(Concepto(sindicato_id=sid, codigo=cod, nombre=nom, tipo=tipo,
                           remunerativo=rem, alias=[nom]))
        for tgt, desc, expr, tol in d["formulas"]:
            s.add(Formula(sindicato_id=sid, target=tgt, descripcion=desc, expr=expr, tolerancia=tol))
        # Empleadores de prueba -- NO se precrea CuentaEmpleador (el
        # autorregistro es el flujo real): la empresa se registra sola en
        # /ingresar-empresa con el CUIT que ya está dado de alta acá.
        for cuit_emp, razon_social in d.get("empleadores", []):
            s.add(Empleador(sindicato_id=sid, cuit=cuit_emp, razon_social=razon_social, activo=True))
        s.commit()

    # 4. Permisos de cada área, formularios ruteados y marca de empleado.
    # Van por las funciones de db (y no por INSERT directo) a propósito:
    # son las mismas que corren en el panel, así la demo no puede quedar en
    # un estado que la aplicación real no sepa producir.
    for seccional, nombre, secciones in d["areas"]:
        db.set_permisos_area(areas[(seccional, nombre)], secciones, sid)
    for t in d.get("tramites", []):
        tipo_id = db.crear_tipo_tramite(
            sid, t["titulo"], t["codigo"], t["campos"],
            area_destino_default_id=areas[t["default"]], permite_pase=t["permite_pase"])
        if t.get("destinos"):
            db.set_destinos_tipo_tramite(
                tipo_id, {secs[k]: areas[v] for k, v in t["destinos"].items()}, sid)
        if t.get("pases"):
            db.set_areas_de_pase(tipo_id, [areas[k] for k in t["pases"]], sid)
    for usuario, _, _, _, _, _ in d["usuarios"]:
        db.sincronizar_por_cuil(sid, usuario)

    # 5. Encuestas: padrón sintético y tres tomas en el tiempo. Solo en el
    # sindicato FEDERADO -- el módulo se muestra con sus cortes por seccional
    # y en la Gastronómica, que tiene una sola, no habría nada que filtrar.
    resumen_encuestas = None
    if len(d["seccionales"]) > 1:
        with db.get_session() as s:
            admin = s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sid,
                UsuarioSindicato.es_super_admin == True)).first()   # noqa: E712
            admin_id = admin.id if admin else None
        resumen_encuestas = demo_encuestas.sembrar(
            sid, secs, [c for c, _ in d.get("empleadores", [])], admin_id)

    u, cl = d["admin"]
    for usuario, clave, nombre, rol, seccional, area in d["usuarios"]:
        resumen_usuarios.append(f"    {usuario} / {clave}  →  {nombre}, "
                                f"{ROLES[rol]} · {seccional} / {area}")
    print(f"✓ {d['nombre']}: admin {u}/{cl}, {len(d['seccionales'])} seccionales, "
          f"{len(d['areas'])} áreas, {len(d['usuarios'])} usuarios de panel, "
          f"{len(d['conceptos'])} conceptos, {len(d['cuils'])} trabajadores, "
          f"{len(d.get('empleadores', []))} empleadores")
    if resumen_encuestas:
        r = resumen_encuestas
        print(f"  Encuestas: +{r['padron']} afiliados sintéticos, "
              + " · ".join(f"«{t['titulo']}» {t['respondieron']} resp." for t in r["tomas"])
              + f" · nominal «{r['nominal']['titulo']}» {r['nominal']['respondieron']} resp.")

print("\nDemo cargada. Accesos:")
print("  Plataforma:  /plataforma  (clave en variable PLATAFORMA_PASSWORD)")
print("  UOM:         /admin  →  CUIT 20111111110 / uom-demo  (Super Admin)")
print("  Gastronómica:/admin  →  CUIT 20222222220 / fega-demo  (Super Admin)")
print("  Otros usuarios del panel (misma pantalla /admin):")
for linea in resumen_usuarios:
    print(linea)
print("  Trabajador:  /ingresar  →  registrarse con un CUIL habilitado")
print("  Pluriempleo: CUIL 27222222224 está en ambos sindicatos")
print("  Empresa:     /ingresar-empresa  →  registrarse con un CUIT habilitado")
print("  Empresa multisindicato: CUIT 30111222339 está en ambos sindicatos")
print("  Empleado sin afiliar: 27777777774 (Prensa) NO está en el padrón, a propósito")

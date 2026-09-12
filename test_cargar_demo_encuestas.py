"""Las encuestas que carga cargar_demo.py, verificadas corriendo el script
real contra la base de test.

Mismo criterio que test_cargar_demo_areas.py: no se duplica la lógica de
carga, se verifica el resultado tal como lo vería quien corre el script.

Vale la pena porque la demo de Encuestas es lo ÚNICO que muestra las dos
cosas más difíciles de explicar del módulo: el umbral, que con un padrón de
tres afiliados escondería absolutamente todo, y la evolución entre tomas,
que no existe hasta que hay dos. Si la siembra se rompe, el sindicato lo
descubre en vivo y con las dos pantallas vacías.

Correr con: python -m pytest test_cargar_demo_encuestas.py -q
"""
import os
import subprocess
import sys

env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
resultado = subprocess.run(
    [sys.executable, "cargar_demo.py"], cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env, capture_output=True, text=True, timeout=300,
)
assert resultado.returncode == 0, resultado.stdout + resultado.stderr

import db                      # noqa: E402
import encuestas              # noqa: E402
import fechas                 # noqa: E402
import resultados_encuesta as res   # noqa: E402
from db import Sindicato, Seccional   # noqa: E402
from sqlmodel import Session, select  # noqa: E402


def _federado():
    """El sindicato con varias seccionales: es el único que siembra
    encuestas, porque con una sola no habría nada que filtrar."""
    with Session(db.engine) as s:
        for sind in s.exec(select(Sindicato)).all():
            secs = s.exec(select(Seccional).where(Seccional.sindicato_id == sind.id)).all()
            if len(secs) > 1:
                return sind.id, {x.nombre: x.id for x in secs}
    raise AssertionError("la demo no tiene ningún sindicato federado")


SID, SECS = _federado()
ENCUESTAS = db.encuestas_del_sindicato(SID)


def test_la_demo_trae_tres_tomas_de_la_misma_encuesta_y_una_nominal():
    anonimas = [e for e in ENCUESTAS if e["modo"] == encuestas.ANONIMA]
    assert len(anonimas) == 3, [e["titulo"] for e in anonimas]
    # Linaje aplanado a la raíz, como lo deja duplicar_encuesta.
    raiz = min(e["id"] for e in anonimas)
    assert sorted((e["origen_id"] or 0) for e in anonimas) == [0, raiz, raiz]
    # Dos cerradas y una en curso: sin una abierta, la demo no puede mostrar
    # el paso de avisar ni el recordatorio.
    assert sorted(e["estado"] for e in anonimas) == ["abierta", "cerrada", "cerrada"]
    # Y una nominal, que es la que muestra el CSV con nombre y apellido.
    assert [e["titulo"] for e in ENCUESTAS if e["modo"] == encuestas.NOMINAL]


def test_hay_padron_suficiente_para_que_el_umbral_no_esconda_todo():
    """Con tres afiliados el umbral esconde hasta el total general, y las
    dos pantallas que más cuesta explicar aparecen vacías."""
    abierta = next(e for e in ENCUESTAS
                   if e["estado"] == "abierta" and e["modo"] == encuestas.ANONIMA)
    d = res.resultados(abierta["id"], SID, {})
    assert d["oculto"] is False
    assert d["respondentes"] >= abierta["umbral_minimo"] * 4
    assert d["indicadores"]["participacion"]["padron"] >= 100
    # Y cada seccional por separado también llega: si no, el filtro existe
    # pero al usarlo la pantalla se vacía y parece roto.
    for nombre, sec in SECS.items():
        g = res.resultados(abierta["id"], SID, {"seccional": [str(sec)]})
        assert g["oculto"] is False, nombre
        assert g["respondentes"] >= abierta["umbral_minimo"], nombre


def test_los_avisos_tienen_lectura_para_que_el_par_de_kpis_se_entienda():
    """Participación y lectura solo sirven juntos. Con "0 leídos" el
    dashboard no puede contar su historia."""
    abierta = next(e for e in ENCUESTAS
                   if e["estado"] == "abierta" and e["modo"] == encuestas.ANONIMA)
    avisos = res.resultados(abierta["id"], SID, {})["indicadores"]["avisos"]
    assert avisos["enviados"] > 0 and 0 < avisos["leidos"] < avisos["enviados"]


def test_la_curva_de_ritmo_no_es_un_punto_solo():
    """La toma en curso tiene que llevar días corridos: con todas las
    respuestas en el mismo día, el gráfico de ritmo es un punto."""
    abierta = next(e for e in ENCUESTAS
                   if e["estado"] == "abierta" and e["modo"] == encuestas.ANONIMA)
    ritmo = res.resultados(abierta["id"], SID, {})["indicadores"]["ritmo"]
    assert len(ritmo) >= 4, ritmo
    hoy = fechas.hoy_texto()
    # Y ninguna respuesta con fecha futura: una encuesta abierta no puede
    # tener contestaciones de la semana que viene.
    assert all(x["dia"] <= hoy for x in ritmo), ritmo


def test_la_evolucion_cuenta_una_historia_y_no_ruido():
    """Entre la primera toma y la tercera el clima mejora y la preocupación
    se corre del sueldo a la seguridad. Si las tres tomas dieran lo mismo,
    la pantalla existiría y no se entendería para qué."""
    abierta = next(e for e in ENCUESTAS
                   if e["estado"] == "abierta" and e["modo"] == encuestas.ANONIMA)
    ev = res.evolucion(abierta["id"], SID)
    assert len(ev["tomas"]) == 3 and not any(t["oculto"] for t in ev["tomas"])

    escala = next(p for p in ev["preguntas"] if p["tipo_dato"] == "escala")
    valores = escala["lineas"][0]["valores"]
    assert None not in valores and valores[0] < valores[-1], valores

    preocupa = next(p for p in ev["preguntas"] if p["tipo_dato"] == "opcion_unica")
    sueldo = next(l for l in preocupa["lineas"] if "sueldo" in l["nombre"].lower())
    seguridad = next(l for l in preocupa["lineas"] if "seguridad" in l["nombre"].lower())
    assert sueldo["valores"][0] > sueldo["valores"][-1], sueldo["valores"]
    assert seguridad["valores"][0] < seguridad["valores"][-1], seguridad["valores"]


def test_una_seccional_se_mueve_distinto_que_las_otras():
    """Sin esa diferencia el filtro por seccional muestra tres curvas
    iguales y no se entiende para qué está."""
    abierta = next(e for e in ENCUESTAS
                   if e["estado"] == "abierta" and e["modo"] == encuestas.ANONIMA)
    climas = {}
    for nombre, sec in SECS.items():
        d = res.resultados(abierta["id"], SID, {"seccional": [str(sec)]})
        escala = next((p for p in d["preguntas"] if p["tipo_dato"] == "escala"), None)
        if escala and escala["escala"]["promedio"] is not None:
            climas[nombre] = escala["escala"]["promedio"]
    assert len(climas) >= 3, climas
    assert max(climas.values()) - min(climas.values()) >= 0.5, climas


def test_el_historial_no_dice_que_todo_pasó_hoy():
    """Una toma con ventana de febrero y un historial fechado hoy es lo
    primero que pregunta quien mira la demo -- y con razón."""
    cerrada = next(e for e in ENCUESTAS
                   if e["estado"] == "cerrada" and e["modo"] == encuestas.ANONIMA)
    eventos = db.eventos_de_encuesta(cerrada["id"])
    assert eventos
    for v in eventos:
        assert v["fecha"][:10] <= cerrada["fecha_hasta"], v


def test_las_dos_secciones_de_encuestas_se_reparten_distinto():
    """N17: la demo tiene que mostrar que armar una encuesta y leer sus
    resultados son permisos distintos. Con todas las áreas iguales, la
    pantalla de permisos parece decorativa."""
    with Session(db.engine) as s:
        areas = s.exec(select(db.Area).where(db.Area.sindicato_id == SID)).all()
        perfiles = {}
        for a in areas:
            secciones = {p.seccion for p in s.exec(select(db.PermisoArea).where(
                db.PermisoArea.area_id == a.id)).all()}
            if secciones & {"encuestas", "encuestas_resultados"}:
                perfiles[f"{a.seccional_id}/{a.nombre}"] = secciones
    assert perfiles, "ninguna área de la demo toca Encuestas"
    completas = [k for k, v in perfiles.items() if "encuestas" in v]
    solo_lectura = [k for k, v in perfiles.items()
                    if "encuestas" not in v and "encuestas_resultados" in v]
    assert completas and solo_lectura, perfiles

"""Listas del sindicato (PLAN_LISTAS_VALIDACIONES.md, bloque 1): las
plantillas y el parseo del CSV (listas.py, puro), la carga con ensayo y
reemplazo entero, el permiso `listas` y el alcance por seccional.

Correr con: python -m pytest test_listas.py -q
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import auth
import db
import listas
import main
from db import Sindicato, UsuarioSindicato, Seccional, Area
from modulos import MODULOS_INICIALES

db.crear_tablas()

with db.get_session() as s:
    sind = Sindicato(nombre="UOM Listas", slug="uom-listas", modulos_habilitados=list(MODULOS_INICIALES))
    otro = Sindicato(nombre="Otro Listas", slug="otro-listas", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID, SID_OTRO = sind.id, otro.id
    central = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    rosario = Seccional(sindicato_id=SID, nombre="Rosario")
    s.add(central); s.add(rosario); s.commit(); s.refresh(central); s.refresh(rosario)
    SEC_CENTRAL, SEC_ROSARIO = central.id, rosario.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20111111120", nombre="Super", seccional_id=SEC_CENTRAL,
                           clave_hash=auth.hashear_clave("super"), debe_cambiar_clave=False, es_super_admin=True))
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="20555555556", nombre="Local", seccional_id=SEC_ROSARIO,
                           clave_hash=auth.hashear_clave("local"), debe_cambiar_clave=False, es_admin_seccional=True))
    prensa = Area(sindicato_id=SID, seccional_id=SEC_CENTRAL, nombre="Prensa")
    s.add(prensa); s.commit(); s.refresh(prensa)
    s.add(UsuarioSindicato(sindicato_id=SID, usuario="27777777772", nombre="Prensa", seccional_id=SEC_CENTRAL,
                           area_id=prensa.id, clave_hash=auth.hashear_clave("prensa"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_OTRO, usuario="20222222223", nombre="Otro", clave_hash=auth.hashear_clave("otro"),
                           debe_cambiar_clave=False, es_super_admin=True))
    s.commit()


def _admin(usuario, clave):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    return c


super_c = _admin("20111111120", "super")
local_c = _admin("20555555556", "local")
area_c = _admin("27777777772", "prensa")
otro_c = _admin("20222222223", "otro")

CSV_FAMILIA = (
    "cuil;dni;apellido_nombre;vinculo;fecha_nacimiento\n"
    "20111111112;55123456;Pérez, Martina;Hija;09/03/2017\n"
    "20-11111111-2;58765432;Pérez, Tomás;Hijo;2021-11-21\n"
    "20111111113;1;mal;x;2020-13-40\n"            # CUIL inválido, DNI corto, fecha ilegible
    "27222222228;40111222;López, Ana;Cónyuge;\n"   # fecha vacía: vale
    "20111111112;55123456;Repetida;Hija;2017-03-09\n"
    "\n"
)


def _archivo(texto, nombre="familia.csv"):
    return {"archivo": (nombre, io.BytesIO(texto.encode("utf-8")), "text/csv")}


# ---------------------------------------------------------------- listas.py (puro)
def test_las_plantillas_estan_completas_y_la_primera_clave_es_el_cuil():
    for clave, p in listas.PLANTILLAS.items():
        c1, c2 = listas.claves_de(clave)
        assert c1 == "cuil" and p["columnas"][0]["tipo"] == "cuil"
        assert all(c["tipo"] in ("cuil", "dni", "texto", "fecha") for c in p["columnas"])
        assert len(p["ejemplo"]) == 2 and all(len(f) == len(p["columnas"]) for f in p["ejemplo"])
    assert listas.claves_de("grupo_familiar") == ("cuil", "dni")
    assert listas.claves_de("simple") == ("cuil", None)


def test_el_modelo_se_vuelve_a_leer_sin_errores():
    for clave in listas.PLANTILLAS:
        r = listas.parsear_csv(clave, listas.csv_modelo(clave).encode("utf-8"))
        assert r["con_error"] == 0 and r["validas"] == 2, (clave, r["errores"])


def test_parsear_normaliza_valida_y_cuenta():
    r = listas.parsear_csv("grupo_familiar", CSV_FAMILIA.encode("utf-8"))
    assert r["total"] == 5 and r["validas"] == 3 and r["con_error"] == 2
    primera = r["filas"][0]
    assert primera["clave1"] == "20111111112" and primera["clave2"] == "55123456"
    assert primera["datos"]["fecha_nacimiento"] == "2017-03-09", "DD/MM/AAAA se guarda ISO"
    assert r["filas"][1]["clave1"] == "20111111112", "el CUIL con guiones se normaliza"
    assert r["filas"][2]["datos"]["fecha_nacimiento"] == "", "una fecha vacía no es error"
    motivos = {e["linea"]: e["motivo"] for e in r["errores"]}
    assert "CUIL inválido" in motivos[4] and "DNI inválido" in motivos[4] and "fecha ilegible" in motivos[4]
    assert "repetida" in motivos[6]


def test_parsear_acepta_coma_y_cabecera_con_rotulos_y_latin1():
    texto = "CUIL del afiliado,Fecha de afiliación,Fecha de nacimiento,Categoría\n20111111112,2019-05-02,1988-07-15,Cajero\n"
    r = listas.parsear_csv("datos_afiliado", texto.encode("latin-1"))
    assert r["validas"] == 1 and r["filas"][0]["datos"]["categoria"] == "Cajero"
    falta = listas.parsear_csv("datos_afiliado", b"cuil;categoria\n20111111112;x\n")
    assert falta["validas"] == 0 and "Falta la columna" in falta["errores"][0]["motivo"]
    assert listas.parsear_csv("simple", b"")["errores"][0]["motivo"] == "El archivo está vacío."


def test_normalizar_fecha():
    assert listas.normalizar_fecha("31/12/2025") == "2025-12-31"
    assert listas.normalizar_fecha("2025-02-30") is None
    assert listas.normalizar_fecha("ayer") is None


# ---------------------------------------------------------------- permiso y alcance
def test_sin_sesion_y_sin_permiso_403():
    assert TestClient(main.app).get("/admin/listas").status_code == 403
    # Un usuario de área sin la sección: 403 (gateo fail-closed de la ruta).
    assert area_c.get("/admin/listas").status_code == 403
    assert area_c.post("/admin/lista/cargar", data={"plantilla": "simple"}, files=_archivo("cuil\n20111111112\n")).status_code == 403


def test_la_pestana_aparece_solo_con_el_permiso():
    assert 'data-panel="listas"' in super_c.get("/admin").text
    assert 'data-panel="listas"' in local_c.get("/admin").text
    assert 'data-panel="listas"' not in area_c.get("/admin").text


def test_el_ensayo_no_escribe_y_la_confirmacion_reemplaza():
    r = super_c.post("/admin/lista/cargar", data={"plantilla": "grupo_familiar", "nombre": "Familias 2027", "seccional_id": ""},
                     files=_archivo(CSV_FAMILIA)).json()
    assert r["ensayo"] is True and r["validas"] == 3 and r["con_error"] == 2 and len(r["muestra"]) == 3
    assert super_c.get("/admin/listas").json()["listas"] == [], "el ensayo no guarda nada"

    r = super_c.post("/admin/lista/cargar", data={"plantilla": "grupo_familiar", "nombre": "Familias 2027", "seccional_id": "", "confirmar": "1"},
                     files=_archivo(CSV_FAMILIA)).json()
    assert r["ensayo"] is False and r["id"]
    lista_id = r["id"]
    l = super_c.get("/admin/listas").json()["listas"]
    assert len(l) == 1 and l[0]["filas"] == 3 and l[0]["seccional"] == "" and l[0]["cargada_por"] == "Super (20111111120)"
    assert l[0]["archivo"] == "familia.csv" and l[0]["cargada_en"]

    # Otra carga con el mismo nombre REEMPLAZA entera (no suma).
    r = super_c.post("/admin/lista/cargar", data={"plantilla": "grupo_familiar", "nombre": "Familias 2027", "seccional_id": "", "confirmar": "1"},
                     files=_archivo("cuil;dni;apellido_nombre;vinculo;fecha_nacimiento\n27222222228;40111222;López, Ana;Cónyuge;1990-01-01\n")).json()
    assert r["id"] == lista_id
    l = super_c.get("/admin/listas").json()["listas"]
    assert len(l) == 1 and l[0]["filas"] == 1
    with Session(db.engine) as s:
        assert len(s.exec(select(db.FilaLista).where(db.FilaLista.lista_id == lista_id)).all()) == 1

    # Ver, descargar, buscar.
    det = super_c.get(f"/admin/lista/{lista_id}").json()
    assert det["muestra"] == [{"cuil": "27222222228", "dni": "40111222", "apellido_nombre": "López, Ana", "vinculo": "Cónyuge", "fecha_nacimiento": "1990-01-01"}]
    csv = super_c.get(f"/admin/lista/{lista_id}/datos.csv").text
    assert "cuil;dni;apellido_nombre;vinculo;fecha_nacimiento" in csv and "27222222228;40111222" in csv
    assert db.buscar_en_lista(SID, "grupo_familiar", "27-22222222-8", "40111222")["vinculo"] == "Cónyuge"
    assert db.buscar_en_lista(SID, "grupo_familiar", "27222222228", "99999999") is None
    assert db.buscar_en_lista(SID_OTRO, "grupo_familiar", "27222222228", "40111222") is None, "aislamiento"

    # Sin filas válidas no se carga nada.
    r = super_c.post("/admin/lista/cargar", data={"plantilla": "simple", "confirmar": "1"}, files=_archivo("cuil\n123\n"))
    assert r.status_code == 422

    # Borrar.
    r = super_c.post("/admin/lista/borrar", data={"id": str(lista_id)}, follow_redirects=False)
    assert r.status_code == 303 and super_c.get("/admin/listas").json()["listas"] == []


def test_el_admin_de_seccional_solo_carga_y_ve_las_suyas():
    # No puede cargar una lista para todo el sindicato…
    r = local_c.post("/admin/lista/cargar", data={"plantilla": "simple", "seccional_id": "", "confirmar": "1"},
                     files=_archivo("cuil\n20111111112\n"))
    assert r.status_code == 403
    # …ni para otra seccional…
    r = local_c.post("/admin/lista/cargar", data={"plantilla": "simple", "seccional_id": str(SEC_CENTRAL), "confirmar": "1"},
                     files=_archivo("cuil\n20111111112\n"))
    assert r.status_code == 403
    # …pero sí para la suya.
    r = local_c.post("/admin/lista/cargar", data={"plantilla": "simple", "nombre": "Delegados", "seccional_id": str(SEC_ROSARIO), "confirmar": "1"},
                     files=_archivo("cuil\n20111111112\n27222222228\n"))
    assert r.status_code == 200, r.text
    mia = r.json()["id"]
    # El super admin carga una global; el local no la ve ni la toca.
    r = super_c.post("/admin/lista/cargar", data={"plantilla": "simple", "nombre": "Excluidos", "seccional_id": "", "confirmar": "1"},
                     files=_archivo("cuil\n20111111112\n"))
    global_id = r.json()["id"]
    vistas = local_c.get("/admin/listas").json()
    assert [l["id"] for l in vistas["listas"]] == [mia] and vistas["alcance"] == [SEC_ROSARIO]
    assert local_c.get(f"/admin/lista/{global_id}").status_code == 403
    assert local_c.get(f"/admin/lista/{global_id}/datos.csv").status_code == 403
    assert local_c.post("/admin/lista/borrar", data={"id": str(global_id)}, follow_redirects=False).status_code == 403
    assert len(super_c.get("/admin/listas").json()["listas"]) == 2
    html = local_c.get("/admin").text
    assert "Delegados" in html and "Excluidos" not in html
    # La global vale para la seccional; la de Rosario, solo para Rosario.
    assert db.buscar_en_lista(SID, "simple", "20111111112", seccional_id=SEC_CENTRAL, nombre="Excluidos")
    assert db.buscar_en_lista(SID, "simple", "27222222228", seccional_id=SEC_CENTRAL) is None
    assert db.buscar_en_lista(SID, "simple", "27222222228", seccional_id=SEC_ROSARIO)


def test_otro_sindicato_no_ve_nada():
    assert otro_c.get("/admin/listas").json()["listas"] == []
    with Session(db.engine) as s:
        alguna = s.exec(select(db.ListaSindicato).where(db.ListaSindicato.sindicato_id == SID)).first()
    assert alguna is not None
    assert otro_c.get(f"/admin/lista/{alguna.id}").status_code == 404


def test_el_modelo_se_descarga_y_una_plantilla_rara_es_404():
    r = super_c.get("/admin/listas/modelo/grupo_familiar.csv")
    assert r.status_code == 200 and r.text.lstrip("﻿").startswith("cuil;dni;apellido_nombre")
    assert super_c.get("/admin/listas/modelo/rara.csv").status_code == 404


@pytest.mark.parametrize("plantilla", sorted(listas.PLANTILLAS))
def test_cada_plantilla_se_carga_con_su_propio_modelo(plantilla):
    r = super_c.post("/admin/lista/cargar", data={"plantilla": plantilla, "nombre": "Modelo " + plantilla, "seccional_id": "", "confirmar": "1"},
                     files=_archivo(listas.csv_modelo(plantilla), nombre="modelo.csv")).json()
    assert r["validas"] == 2 and r["con_error"] == 0

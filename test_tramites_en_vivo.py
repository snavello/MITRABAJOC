"""Bloque 4 de PLAN_LISTAS_VALIDACIONES.md (D3): la validación EN VIVO de un
campo (`POST /api/tramite/validar-campo`, solo pasa / no pasa, diez intentos
por sesión y formulario) y los requisitos al abrir el formulario
(`GET /api/tramite/requisitos/{id}`, con los calculados que ya se pueden
completar).

Correr con: python -m pytest test_tramites_en_vivo.py -q
"""
import io
import json
from datetime import timedelta

import auth
import cuit
import db
import fechas
import main
import validaciones_tramite as vt
from db import Area, Seccional, Sindicato, Trabajador, UsuarioSindicato
from fastapi.testclient import TestClient
from modulos import MODULOS_INICIALES

db.crear_tablas()

JUAN = cuit.corregir("20310000010")
ANA = cuit.corregir("27310000020")
ADMIN = cuit.corregir("20310000040")
HOY = fechas.hoy()

with db.get_session() as s:
    sind = Sindicato(nombre="Gremio En Vivo", slug="gremio-en-vivo",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["tramites"])
    otro = Sindicato(nombre="Gremio Ajeno Vivo", slug="gremio-ajeno-vivo",
                     modulos_habilitados=list(MODULOS_INICIALES) + ["tramites"])
    s.add(sind); s.add(otro); s.commit(); s.refresh(sind); s.refresh(otro)
    SID, SID_OTRO = sind.id, otro.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=ADMIN, nombre="Admin Vivo",
                           clave_hash=auth.hashear_clave("admin-demo"), debe_cambiar_clave=False, es_super_admin=True))
    sec = Seccional(sindicato_id=SID, nombre="Sede Central", ve_todas=True)
    s.add(sec); s.commit(); s.refresh(sec)
    mesa = Area(sindicato_id=SID, seccional_id=sec.id, nombre="Mesa"); s.add(mesa); s.commit(); s.refresh(mesa)
    AREA = mesa.id
    s.add(Trabajador(sindicato_id=SID, cuil=JUAN, activo=True, registrado=True, seccional_id=sec.id, fecha_afiliacion="2019-05-02"))
    db.guardar_datos_personales(s, JUAN, nombre="Juan"); db.asegurar_cuenta(s, JUAN).clave_hash = auth.hashear_clave("clave-larga-123")
    s.add(Trabajador(sindicato_id=SID, cuil=ANA, activo=True, registrado=True,
                     fecha_afiliacion=(HOY - timedelta(days=40)).isoformat()))
    db.guardar_datos_personales(s, ANA, nombre="Ana"); db.asegurar_cuenta(s, ANA).clave_hash = auth.hashear_clave("clave-larga-123")
    s.commit()

admin = TestClient(main.app)
admin.post("/admin/login", data={"usuario": ADMIN, "clave": "admin-demo"})


def _trab(cuil, sid=SID):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0, ident=cuil))
    c.cookies.set("cuil_trab", cuil)
    c.cookies.set("sind_elegido", str(sid))
    return c


CAMPOS = [
    {"etiqueta": "DNI del chico", "tipo_dato": "texto", "obligatorio": True, "validaciones": [
        {"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar", "clave2": 0, "trae": "existe",
         "mensaje": "Ese DNI no figura en tu grupo familiar.", "bloquea": True, "en_vivo": True},
        {"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar", "clave2": 0, "trae": "vinculo",
         "operador": "==", "valor": "Hija", "mensaje": "Solo hijas (no en vivo).", "bloquea": True, "en_vivo": False}]},
    {"etiqueta": "Edad del chico", "tipo_dato": "calculado", "validaciones": [
        {"fuente": "funcion", "origen": "lista", "lista": "grupo_familiar", "clave2": 0,
         "formula": "anios_entre(lista.fecha_nacimiento, hoy())"}]},
    {"etiqueta": "Antigüedad (meses)", "tipo_dato": "calculado", "validaciones": [
        {"fuente": "funcion", "origen": "sistema", "formula": "meses_entre(sistema.fecha_afiliacion, hoy())"}]},
]
REQUISITOS = [{"origen": "sistema", "formula": "meses_entre(sistema.fecha_afiliacion, hoy()) >= 6",
               "mensaje": "Necesitás seis meses de antigüedad."}]


def test_preparacion_lista_y_tipo():
    csv = ("cuil;dni;apellido_nombre;vinculo;fecha_nacimiento\n"
           f"{JUAN};55123456;Pérez, Martina;Hija;{(HOY - timedelta(days=365 * 9)).isoformat()}\n"
           f"{JUAN};58765432;Pérez, Tomás;Hijo;{(HOY - timedelta(days=365 * 7)).isoformat()}\n")
    r = admin.post("/admin/lista/cargar", data={"plantilla": "grupo_familiar", "nombre": "Familias", "seccional_id": "", "confirmar": "1"},
                   files={"archivo": ("f.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")})
    assert r.status_code == 200 and r.json()["validas"] == 2
    r = admin.post("/admin/tramite-tipo", data={"titulo": "Kit", "codigo": "KIT VIVO", "campos_json": json.dumps(CAMPOS),
                                                "requisitos_json": json.dumps(REQUISITOS), "area_destino_default_id": str(AREA)},
                   follow_redirects=False)
    assert r.status_code == 303
    global TIPO
    TIPO = db.tipo_tramite_por_id(next(t for t in db.tipos_tramite_del_sindicato(SID) if t["codigo"] == "KIT VIVO")["id"])


# ------------------------------------------------------------ motor puro

def test_el_motor_en_vivo_solo_mira_las_marcadas_y_recalcula_lo_que_depende():
    campos = main._campos_tramite_validos(json.loads(json.dumps(CAMPOS)))
    for i, c in enumerate(campos):
        c["id"] = 10 + i
    tomas = {"cuil": JUAN, "dni": "58765432", "apellido_nombre": "Pérez, Tomás", "vinculo": "Hijo",
             "fecha_nacimiento": (HOY - timedelta(days=365 * 7 + 5)).isoformat()}
    ctx = {"sistema": {"fecha_afiliacion": "2019-05-02"}, "buscar": lambda p, k: tomas if k == "58765432" else None}
    r = vt.evaluar_campo_en_vivo(campos, 0, {10: "58765432"}, ctx)
    assert r["pasa"] is True, "la de «solo hijas» no está en vivo: no se mira acá"
    assert r["calculados"] == {11: "7"}, "el calculado que usa el DNI como segunda clave se completa"
    r = vt.evaluar_campo_en_vivo(campos, 0, {10: "1"}, ctx)
    assert r["pasa"] is False and r["mensaje"] == "Ese DNI no figura en tu grupo familiar." and r["calculados"] == {11: ""}
    assert "fila" not in json.dumps(r) and "Tomás" not in json.dumps(r)
    assert vt.evaluar_campo_en_vivo(campos, 0, {10: ""}, ctx)["pasa"] is True, "vacío no se valida"
    assert vt.evaluar_campo_en_vivo(campos, 9, {}, ctx)["pasa"] is True
    al_abrir = vt.requisitos_al_abrir(campos, vt.requisitos_saneados(REQUISITOS, campos), ctx)
    assert al_abrir["cumple"] is True and al_abrir["mensajes"] == []
    assert set(al_abrir["calculados"]) == {12}, "solo el que no depende de otro campo"
    al_abrir = vt.requisitos_al_abrir(campos, vt.requisitos_saneados(REQUISITOS, campos),
                                      {"sistema": {"fecha_afiliacion": (HOY - timedelta(days=40)).isoformat()}, "buscar": lambda p, k: None})
    assert al_abrir["cumple"] is False and al_abrir["mensajes"] == ["Necesitás seis meses de antigüedad."]


# ------------------------------------------------------------------ rutas

def test_los_requisitos_al_abrir():
    r = _trab(JUAN).get(f"/api/tramite/requisitos/{TIPO['id']}")
    d = r.json()
    assert r.status_code == 200 and d["cumple"] is True and d["mensajes"] == []
    assert d["calculados"] == {str(TIPO["campos"][2]["id"]): str(vt._meses_entre("2019-05-02", HOY.isoformat()))}
    r = _trab(ANA).get(f"/api/tramite/requisitos/{TIPO['id']}")
    assert r.json()["cumple"] is False and "seis meses" in r.json()["mensajes"][0]
    assert TestClient(main.app).get(f"/api/tramite/requisitos/{TIPO['id']}").status_code == 403
    assert _trab(JUAN).get("/api/tramite/requisitos/999999").status_code == 404
    # El sindicato sale de la SESIÓN (Juan solo está en uno): un tipo de otro gremio es 404.
    with db.get_session() as s:
        s.add(db.TipoTramite(sindicato_id=SID_OTRO, titulo="Ajeno", codigo="AJ", activo=True, creado=""))
        s.commit()
    ajeno = next(t for t in db.tipos_tramite_del_sindicato(SID_OTRO))
    assert _trab(JUAN).get(f"/api/tramite/requisitos/{ajeno['id']}").status_code == 404


def test_validar_campo_en_vivo_dice_si_o_no_y_nada_mas():
    main._intentos_en_vivo.clear()
    juan = _trab(JUAN)
    cuerpo = {"tipo_tramite_id": TIPO["id"], "indice_campo": 0, "valor": "55.123.456", "valores": {}}
    r = juan.post("/api/tramite/validar-campo", json=cuerpo)
    d = r.json()
    assert r.status_code == 200 and d["pasa"] is True
    assert d["calculados"] == {str(TIPO["campos"][1]["id"]): "8"} or d["calculados"] == {str(TIPO["campos"][1]["id"]): "9"}
    r = juan.post("/api/tramite/validar-campo", json={**cuerpo, "valor": "99999999"})
    d = r.json()
    assert d["pasa"] is False and d["mensaje"] == "Ese DNI no figura en tu grupo familiar."
    assert set(d) == {"pasa", "mensaje", "calculados"}, "nunca la fila"
    assert juan.post("/api/tramite/validar-campo", json={**cuerpo, "indice_campo": 7}).status_code == 400
    assert juan.post("/api/tramite/validar-campo", json={**cuerpo, "tipo_tramite_id": 999999}).status_code == 404
    assert TestClient(main.app).post("/api/tramite/validar-campo", json=cuerpo).status_code == 403


def test_diez_intentos_por_sesion_y_formulario_y_el_envio_los_limpia():
    main._intentos_en_vivo.clear()
    juan = _trab(JUAN)
    cuerpo = {"tipo_tramite_id": TIPO["id"], "indice_campo": 0, "valor": "99999999", "valores": {}}
    codigos = [juan.post("/api/tramite/validar-campo", json=cuerpo).status_code for _ in range(12)]
    assert codigos == [200] * 10 + [429, 429], codigos
    assert "envialo" in juan.post("/api/tramite/validar-campo", json=cuerpo).json()["detail"]
    # Ana tiene su propia cuenta de intentos; y otro formulario también.
    assert _trab(ANA).post("/api/tramite/validar-campo", json=cuerpo).status_code == 200
    # El envío (aunque falle por la lista) no limpia; el envío que entra, sí.
    ids = {c["etiqueta"]: c["id"] for c in TIPO["campos"]}
    r = juan.post("/api/tramite", data={"tipo_tramite_id": TIPO["id"], f'campo_{ids["DNI del chico"]}': "99999999"})
    assert r.status_code == 422
    assert juan.post("/api/tramite/validar-campo", json=cuerpo).status_code == 429
    r = juan.post("/api/tramite", data={"tipo_tramite_id": TIPO["id"], f'campo_{ids["DNI del chico"]}': "55123456"})
    assert r.status_code == 200, r.text
    assert juan.post("/api/tramite/validar-campo", json=cuerpo).status_code == 200
    # Y el sistema ya sabe que pidió este trámite (cierra «una sola vez» con un requisito).
    sistema = db.contexto_validaciones(SID, JUAN, TIPO, {})["sistema"]
    assert sistema["tramites_de_este_tipo"] == 1 and sistema["tramites_abiertos_de_este_tipo"] == 1
    assert db.contexto_validaciones(SID, ANA, TIPO, {})["sistema"]["tramites_de_este_tipo"] == 0
    assert db.contexto_validaciones(SID, JUAN, {"campos": [], "requisitos": []}, {})["sistema"]["tramites_de_este_tipo"] == 0, "sin id no hay pedidos"


def test_la_app_del_afiliado_pide_requisitos_y_valida_en_vivo():
    html = _trab(JUAN).get("/app").text
    assert "/api/tramite/requisitos/" in html and "/api/tramite/validar-campo" in html
    assert 'id="tram-form-requisitos"' in html and "enVivoAgotado" in html
    assert "429" in html, "después del tope se deja de preguntar"

"""Trámites (Fase 3 de Módulos + Notificaciones + Trámites): alta de tipo
con campos de cada tipo_dato, numeración de expediente sin colisión,
validación server-side de obligatorios/longitud/archivo, cambio de estado
dispara log + notificación de sistema, nota de cada lado en el thread
correcto, aislamiento entre sindicatos, bloqueo si el módulo está apagado.

Correr con: .venv/Scripts/python.exe test_tramites.py
"""
import os
import tempfile
import json

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DB_PATH"] = DB_FILE

import db
import auth
from db import Sindicato, UsuarioSindicato, Trabajador, TipoTramite, CampoTramite, Tramite, Notificacion
from modulos import MODULOS_INICIALES
import main
from fastapi.testclient import TestClient
from sqlmodel import Session, select

db.crear_tablas()

MODULOS_CON_TRAMITES = list(MODULOS_INICIALES) + ["tramites", "notificaciones"]

with db.get_session() as s:
    uom = Sindicato(nombre="UOM Tramites", slug="uom-tramites", modulos_habilitados=MODULOS_CON_TRAMITES)
    fega = Sindicato(nombre="Fega Tramites", slug="fega-tramites", modulos_habilitados=list(MODULOS_INICIALES))
    s.add(uom); s.add(fega); s.commit(); s.refresh(uom); s.refresh(fega)
    SID_UOM, SID_FEGA = uom.id, fega.id

    s.add(UsuarioSindicato(sindicato_id=SID_UOM, usuario="20111111110", nombre="Admin UOM",
                            clave_hash=auth.hashear_clave("uom-demo"), debe_cambiar_clave=False))
    s.add(UsuarioSindicato(sindicato_id=SID_FEGA, usuario="20222222220", nombre="Admin Fega",
                            clave_hash=auth.hashear_clave("fega-demo"), debe_cambiar_clave=False))
    s.add(Trabajador(sindicato_id=SID_UOM, cuil="20111111119", nombre="Juan", activo=True, registrado=True))
    s.commit()

admin_uom = TestClient(main.app)
admin_uom.post("/admin/login", data={"usuario": "20111111110", "clave": "uom-demo"})
admin_fega = TestClient(main.app)
admin_fega.post("/admin/login", data={"usuario": "20222222220", "clave": "fega-demo"})


def _sesion_trabajador(cuil):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=0))
    c.cookies.set("cuil_trab", cuil)
    return c


def test_alta_tipo_tramite_con_campos_de_cada_tipo_dato():
    campos = [
        {"etiqueta": "Solicitud", "tipo_dato": "texto", "longitud_maxima": 200, "obligatorio": True},
        {"etiqueta": "CVU", "tipo_dato": "texto", "longitud_exacta": 22, "obligatorio": True},
        {"etiqueta": "Monto", "tipo_dato": "numero", "decimales": 2, "obligatorio": True},
        {"etiqueta": "Fecha del hecho", "tipo_dato": "fecha", "obligatorio": False},
        {"etiqueta": "Comprobante", "tipo_dato": "archivo", "tipos_archivo_permitidos": "pdf,jpg", "obligatorio": True},
    ]
    r = admin_uom.post("/admin/tramite-tipo", data={
        "titulo": "Solicitud de Reintegro", "codigo": "F01 AEFIP", "campos_json": json.dumps(campos),
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        tipo = s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID_UOM, TipoTramite.codigo == "F01 AEFIP")).first()
        assert tipo is not None
        campos_db = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo.id)
                           .order_by(CampoTramite.orden)).all()
        assert len(campos_db) == 5
        assert [c.tipo_dato for c in campos_db] == ["texto", "texto", "numero", "fecha", "archivo"]
        assert campos_db[1].longitud_exacta == 22
        assert campos_db[2].decimales == 2
        assert campos_db[4].tipos_archivo_permitidos == "pdf,jpg"
        global TIPO_ID
        TIPO_ID = tipo.id
    print("OK  test_alta_tipo_tramite_con_campos_de_cada_tipo_dato")


def _campo_id(etiqueta):
    with Session(db.engine) as s:
        c = s.exec(select(CampoTramite).where(
            CampoTramite.tipo_tramite_id == TIPO_ID, CampoTramite.etiqueta == etiqueta)).first()
        return c.id


def test_validacion_obligatorio_falta_campo():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('CVU')}": "0" * 22,
        f"campo_{_campo_id('Monto')}": "1000",
    })  # falta "Solicitud" (obligatorio) y el archivo "Comprobante" (obligatorio)
    assert r.status_code == 422
    errores = r.json()["errores"]
    assert any("Solicitud" in e for e in errores)
    assert any("Comprobante" in e for e in errores)
    print("OK  test_validacion_obligatorio_falta_campo")


def test_validacion_longitud_exacta():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('Solicitud')}": "Pido reintegro",
        f"campo_{_campo_id('CVU')}": "123",  # no son 22 caracteres
        f"campo_{_campo_id('Monto')}": "1000",
    }, files={f"archivo_{_campo_id('Comprobante')}": ("comp.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 422
    assert any("22 caracteres" in e for e in r.json()["errores"])
    print("OK  test_validacion_longitud_exacta")


def test_validacion_tipo_archivo_no_permitido():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('Solicitud')}": "Pido reintegro",
        f"campo_{_campo_id('CVU')}": "0" * 22,
        f"campo_{_campo_id('Monto')}": "1000",
    }, files={f"archivo_{_campo_id('Comprobante')}": ("comp.docx", b"fake", "application/msword")})
    assert r.status_code == 422
    assert any("pdf" in e for e in r.json()["errores"])
    print("OK  test_validacion_tipo_archivo_no_permitido")


def test_envio_tramite_completo_ok():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('Solicitud')}": "Pido reintegro de gastos médicos",
        f"campo_{_campo_id('CVU')}": "1" * 22,
        f"campo_{_campo_id('Monto')}": "15000.50",
    }, files={f"archivo_{_campo_id('Comprobante')}": ("comp.pdf", b"%PDF-1.4 contenido", "application/pdf")})
    assert r.status_code == 200
    data = r.json()
    assert data["numero_expediente"].startswith("F01AEFIP-")
    global TRAMITE_ID, NUMERO_EXPEDIENTE
    TRAMITE_ID, NUMERO_EXPEDIENTE = data["id"], data["numero_expediente"]
    detalle = db.tramite_detalle(TRAMITE_ID)
    assert detalle["estado"] == "iniciado"
    assert len(detalle["respuestas"]) == 4
    archivo_resp = next(r for r in detalle["respuestas"] if r["etiqueta"] == "Comprobante")
    assert archivo_resp["tiene_archivo"]
    assert detalle["log"][0]["evento"] == "creado"
    print("OK  test_envio_tramite_completo_ok")


def test_numeracion_expediente_sin_colision():
    trab = _sesion_trabajador("20111111119")
    numeros = {NUMERO_EXPEDIENTE}
    for _ in range(3):
        r = trab.post("/api/tramite", data={
            "tipo_tramite_id": TIPO_ID,
            f"campo_{_campo_id('Solicitud')}": "Otro pedido",
            f"campo_{_campo_id('CVU')}": "2" * 22,
            f"campo_{_campo_id('Monto')}": "500",
        }, files={f"archivo_{_campo_id('Comprobante')}": ("c.pdf", b"%PDF", "application/pdf")})
        assert r.status_code == 200
        numero = r.json()["numero_expediente"]
        assert numero not in numeros
        numeros.add(numero)
    assert len(numeros) == 4
    print("OK  test_numeracion_expediente_sin_colision")


def test_cambio_estado_dispara_log_y_notificacion():
    # Criterio 2026-09-02: un cambio de tramite YA NO genera Notificacion --
    # el aviso viaja por el globo de Tramites (visto vs actualizado).
    with Session(db.engine) as s:
        antes = len(s.exec(select(Notificacion).where(Notificacion.sindicato_id == SID_UOM)).all())
    assert db.contar_tramites_con_novedades("20111111119", SID_UOM) == 0
    r = admin_uom.post(f"/admin/tramite/{TRAMITE_ID}/estado", data={"estado": "en_tratamiento"})
    assert r.status_code == 200
    detalle = db.tramite_detalle(TRAMITE_ID)
    assert detalle["estado"] == "en_tratamiento"
    assert any(l["evento"] == "cambio_estado" for l in detalle["log"])
    with Session(db.engine) as s:
        cantidad = len(s.exec(select(Notificacion).where(Notificacion.sindicato_id == SID_UOM)).all())
    assert cantidad == antes  # sin Notificacion nueva
    # el globo de Tramites SI se enciende...
    assert db.contar_tramites_con_novedades("20111111119", SID_UOM) == 1
    resumen = db.tramites_de_trabajador("20111111119", SID_UOM)
    assert any(t["novedad"] for t in resumen)
    # ...y abrir el detalle (la ruta del trabajador) lo apaga
    trab = _sesion_trabajador("20111111119")
    assert trab.get(f"/api/tramite/{NUMERO_EXPEDIENTE}").status_code == 200
    assert db.contar_tramites_con_novedades("20111111119", SID_UOM) == 0
    print("OK  test_cambio_estado_dispara_log_y_notificacion")


def test_nota_admin_y_trabajador_en_thread_correcto():
    with Session(db.engine) as s:
        antes = len(s.exec(select(Notificacion).where(Notificacion.sindicato_id == SID_UOM)).all())
    r1 = admin_uom.post(f"/admin/tramite/{TRAMITE_ID}/nota", data={"texto": "Nos falta el CBU del banco."})
    assert r1.status_code == 200
    trab = _sesion_trabajador("20111111119")
    r2 = trab.post(f"/api/tramite/{TRAMITE_ID}/nota", data={"texto": "Ya lo adjunté en el comprobante."})
    assert r2.status_code == 200

    detalle = db.tramite_detalle(TRAMITE_ID)
    notas = detalle["notas"]
    assert notas[-2]["autor"] == "admin" and "CBU" in notas[-2]["texto"]
    assert notas[-1]["autor"] == "trabajador" and "adjunté" in notas[-1]["texto"]
    eventos = [l["evento"] for l in detalle["log"]]
    assert "nota_admin" in eventos and "nota_trabajador" in eventos
    # El resumen de "Mis trámites" trae el ÚLTIMO mensaje del hilo (tarjeta
    # "Necesita tu atención" del rediseño Hilo) sin abrir el detalle.
    resumen = next(t for t in db.tramites_de_trabajador("20111111119", SID_UOM) if t["id"] == TRAMITE_ID)
    assert resumen["ultimo_mensaje"]["autor"] == "trabajador"
    assert "adjunté" in resumen["ultimo_mensaje"]["texto"]

    with Session(db.engine) as s:
        despues = len(s.exec(select(Notificacion).where(Notificacion.sindicato_id == SID_UOM)).all())
    # Criterio 2026-09-02: las notas tampoco generan Notificacion.
    assert despues == antes
    print("OK  test_nota_admin_y_trabajador_en_thread_correcto")


def test_campo_seleccion_fija():
    campos = [{"etiqueta": "Motivo", "tipo_dato": "seleccion", "opciones": "Salud, Estudio, Otro", "obligatorio": True}]
    r = admin_uom.post("/admin/tramite-tipo", data={
        "titulo": "Consulta", "codigo": "SEL", "campos_json": json.dumps(campos),
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        tipo = s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID_UOM, TipoTramite.codigo == "SEL")).first()
        campo = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo.id)).first()
        assert campo.opciones == "Salud, Estudio, Otro"
        tipo_id, campo_id = tipo.id, campo.id

    trab = _sesion_trabajador("20111111119")
    r_malo = trab.post("/api/tramite", data={"tipo_tramite_id": tipo_id, f"campo_{campo_id}": "Vacaciones"})
    assert r_malo.status_code == 422
    r_ok = trab.post("/api/tramite", data={"tipo_tramite_id": tipo_id, f"campo_{campo_id}": "Salud"})
    assert r_ok.status_code == 200
    print("OK  test_campo_seleccion_fija")


def test_terminado_bloquea_cambios():
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        f"campo_{_campo_id('Solicitud')}": "Otro pedido más",
        f"campo_{_campo_id('CVU')}": "3" * 22,
        f"campo_{_campo_id('Monto')}": "700",
    }, files={f"archivo_{_campo_id('Comprobante')}": ("c.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 200
    tid = r.json()["id"]
    r_term = admin_uom.post(f"/admin/tramite/{tid}/estado", data={"estado": "terminado"})
    assert r_term.status_code == 200
    assert db.tramite_detalle(tid)["estado"] == "terminado"

    r_reabrir = admin_uom.post(f"/admin/tramite/{tid}/estado", data={"estado": "en_tratamiento"})
    assert r_reabrir.status_code == 400
    assert db.tramite_detalle(tid)["estado"] == "terminado"

    r_nota_admin = admin_uom.post(f"/admin/tramite/{tid}/nota", data={"texto": "no debería poder"})
    assert r_nota_admin.status_code == 400
    r_nota_trab = trab.post(f"/api/tramite/{tid}/nota", data={"texto": "no debería poder"})
    assert r_nota_trab.status_code == 400
    assert db.tramite_detalle(tid)["notas"] == []
    print("OK  test_terminado_bloquea_cambios")


def test_ancho_campos_y_nuevos_tipos_de_campo():
    campos = [
        {"etiqueta": "Introducción", "tipo_dato": "separador", "obligatorio": False},
        {"etiqueta": "Acepto términos", "tipo_dato": "booleano", "ancho": "mitad", "obligatorio": True},
        {"etiqueta": "Turno preferido", "tipo_dato": "opcion_unica", "opciones": "Mañana, Tarde", "ancho": "tercio", "obligatorio": True},
        {"etiqueta": "Días disponibles", "tipo_dato": "multiple", "opciones": "Lunes, Martes, Miércoles", "obligatorio": True},
    ]
    r = admin_uom.post("/admin/tramite-tipo", data={
        "titulo": "Formulario nuevos tipos", "codigo": "NUEVOS", "campos_json": json.dumps(campos),
    }, follow_redirects=False)
    assert r.status_code == 303
    with Session(db.engine) as s:
        tipo = s.exec(select(TipoTramite).where(
            TipoTramite.sindicato_id == SID_UOM, TipoTramite.codigo == "NUEVOS")).first()
        campos_db = s.exec(select(CampoTramite).where(CampoTramite.tipo_tramite_id == tipo.id)
                           .order_by(CampoTramite.orden)).all()
        assert [c.tipo_dato for c in campos_db] == ["separador", "booleano", "opcion_unica", "multiple"]
        assert campos_db[0].etiqueta == "Introducción"  # separador con etiqueta opcional cargada igual
        assert campos_db[1].ancho == "mitad"
        assert campos_db[2].ancho == "tercio"
        assert campos_db[3].ancho == "completo"  # default cuando no se manda
        id_bool, id_unica, id_multi = campos_db[1].id, campos_db[2].id, campos_db[3].id
        tipo_id = tipo.id

    trab = _sesion_trabajador("20111111119")

    # Falta el radio obligatorio y el checkbox obligatorio -> 422, el booleano
    # (sin marcar) NO debería aparecer en los errores.
    r_falta = trab.post("/api/tramite", data={"tipo_tramite_id": tipo_id})
    assert r_falta.status_code == 422
    errores = r_falta.json()["errores"]
    assert any("Turno preferido" in e for e in errores)
    assert any("Días disponibles" in e for e in errores)
    assert not any("Acepto" in e for e in errores)

    # Opción fuera de la lista permitida -> rechazada.
    r_mal = trab.post("/api/tramite", data={
        "tipo_tramite_id": tipo_id, f"campo_{id_unica}": "Noche",
        f"campo_{id_multi}": "Lunes",
    })
    assert r_mal.status_code == 422
    assert any("Turno preferido" in e for e in r_mal.json()["errores"])

    # Envío válido: booleano sin marcar (ni siquiera viaja en el form, como
    # un checkbox real sin marcar), radio y 2 checkboxes marcados.
    r_ok = trab.post("/api/tramite", data={
        "tipo_tramite_id": tipo_id, f"campo_{id_unica}": "Mañana",
        f"campo_{id_multi}": ["Lunes", "Miércoles"],
    })
    assert r_ok.status_code == 200, r_ok.text
    detalle = db.tramite_detalle(r_ok.json()["id"])
    resp_por_etiqueta = {r["etiqueta"]: r["valor_texto"] for r in detalle["respuestas"]}
    assert resp_por_etiqueta["Acepto términos"] == "No"
    assert resp_por_etiqueta["Turno preferido"] == "Mañana"
    assert resp_por_etiqueta["Días disponibles"] == "Lunes, Miércoles"
    assert "Introducción" not in resp_por_etiqueta  # el separador no junta respuesta
    print("OK  test_ancho_campos_y_nuevos_tipos_de_campo")


def test_cantidad_nuevos_para_el_polling_del_globo():
    """GET /admin/tramites-nuevos-cantidad -- el globo de "Ver trámites" en
    admin.html lo consulta cada 30s para actualizarse sin recargar."""
    r = admin_uom.get("/admin/tramites-nuevos-cantidad")
    assert r.status_code == 200
    esperado = db.contar_tramites_nuevos(SID_UOM)
    assert r.json() == {"cantidad": esperado}
    r_sin_sesion = TestClient(main.app).get("/admin/tramites-nuevos-cantidad")
    assert r_sin_sesion.status_code == 403
    print("OK  test_cantidad_nuevos_para_el_polling_del_globo")


def test_aislamiento_entre_sindicatos():
    """Aísla la verificación de PERTENENCIA del trámite del gate de módulo
    (ya probado aparte): le prestamos el módulo a Fega solo para este test,
    así el 404 que importa es "no es tuyo", no "no tenés el módulo"."""
    with Session(db.engine) as s:
        fega = s.get(Sindicato, SID_FEGA)
        fega.modulos_habilitados = list(fega.modulos_habilitados) + ["tramites"]
        s.add(fega); s.commit()
    try:
        r = admin_fega.get(f"/admin/tramite/{TRAMITE_ID}")
        assert r.status_code == 404
        r2 = admin_fega.post(f"/admin/tramite/{TRAMITE_ID}/estado", data={"estado": "terminado"})
        assert r2.status_code == 404
    finally:
        with Session(db.engine) as s:
            fega = s.get(Sindicato, SID_FEGA)
            fega.modulos_habilitados = list(MODULOS_INICIALES)
            s.add(fega); s.commit()
    print("OK  test_aislamiento_entre_sindicatos")


def test_bloqueo_403_si_modulo_apagado():
    r1 = admin_fega.post("/admin/tramite-tipo", data={
        "titulo": "No debería crearse", "codigo": "X", "campos_json": json.dumps([
            {"etiqueta": "Campo", "tipo_dato": "texto", "obligatorio": True}]),
    })
    assert r1.status_code == 403
    r2 = admin_fega.post("/admin/tramite-tipo/borrar", data={"id": TIPO_ID})
    assert r2.status_code == 403
    with Session(db.engine) as s:
        fega_trab = Trabajador(sindicato_id=SID_FEGA, cuil="20444444440", nombre="Ana", activo=True, registrado=True)
        s.add(fega_trab); s.commit()
    trab_fega = _sesion_trabajador("20444444440")
    r3 = trab_fega.post("/api/tramite", data={"tipo_tramite_id": TIPO_ID, "campo_1": "x"})
    assert r3.status_code == 403
    print("OK  test_bloqueo_403_si_modulo_apagado")


def test_formulario_adjunto_en_chat():
    # El admin adjunta un formulario en un mensaje del chat: la nota guarda
    # la referencia y el detalle la resuelve con titulo/activo para que el
    # trabajador vea la tarjeta "Iniciar este tramite". Un formulario ajeno,
    # inactivo o inexistente se descarta en silencio (saneo defensivo).
    r = admin_uom.post("/admin/tramite-tipo", data={
        "titulo": "Registro de pasajeros", "codigo": "F02 AEFIP",
        "campos_json": json.dumps([{"etiqueta": "Nombre", "tipo_dato": "texto", "obligatorio": True}]),
    }, follow_redirects=False)
    assert r.status_code == 303
    pasajeros = next(t for t in db.tipos_tramite_del_sindicato(SID_UOM)
                     if t["codigo"] == "F02 AEFIP")

    r = admin_uom.post(f"/admin/tramite/{TRAMITE_ID}/nota", data={
        "texto": "Aprobado. Completá el registro de pasajeros.",
        "formulario_id": str(pasajeros["id"]),
    })
    assert r.status_code == 200
    detalle = db.tramite_detalle(TRAMITE_ID)
    nota = detalle["notas"][-1]
    assert nota["formulario_id"] == pasajeros["id"]
    assert nota["formulario_titulo"] == "Registro de pasajeros"
    assert nota["formulario_activo"] is True

    # Nota SOLO con formulario (sin texto ni adjunto): valida.
    r = admin_uom.post(f"/admin/tramite/{TRAMITE_ID}/nota",
                       data={"formulario_id": str(pasajeros["id"])})
    assert r.status_code == 200

    # Formulario inexistente o basura: la nota entra sin referencia.
    r = admin_uom.post(f"/admin/tramite/{TRAMITE_ID}/nota",
                       data={"texto": "hola", "formulario_id": "999999"})
    assert r.status_code == 200
    assert db.tramite_detalle(TRAMITE_ID)["notas"][-1]["formulario_id"] is None
    r = admin_uom.post(f"/admin/tramite/{TRAMITE_ID}/nota",
                       data={"texto": "hola", "formulario_id": "basura"})
    assert r.status_code == 200
    assert db.tramite_detalle(TRAMITE_ID)["notas"][-1]["formulario_id"] is None

    # Un tipo que despues se desactiva: la referencia queda pero el detalle
    # lo marca inactivo (la tarjeta dice "ya no disponible").
    db.editar_tipo_tramite(pasajeros["id"], SID_UOM, "Registro de pasajeros",
                           "F02 AEFIP", False, pasajeros["campos"])
    nota = db.tramite_detalle(TRAMITE_ID)["notas"][-3]
    assert nota["formulario_id"] == pasajeros["id"] and nota["formulario_activo"] is False
    print("OK  test_formulario_adjunto_en_chat")



def test_tramite_encadenado_desde_chat():
    # Un tramite iniciado desde el formulario adjunto en el chat de otro
    # queda vinculado: ambos detalles muestran el vinculo (origen/derivados).
    trab = _sesion_trabajador("20111111119")
    r = trab.post("/api/tramite", data={
        "tipo_tramite_id": TIPO_ID,
        "origen_tramite_id": str(TRAMITE_ID),
        f"campo_{_campo_id('Solicitud')}": "Registro de pasajeros del grupo familiar",
        f"campo_{_campo_id('CVU')}": "2" * 22,
        f"campo_{_campo_id('Monto')}": "100",
    }, files={f"archivo_{_campo_id('Comprobante')}": ("c.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200
    hijo_id = r.json()["id"]
    hijo = db.tramite_detalle(hijo_id)
    assert hijo["origen_tramite"]["id"] == TRAMITE_ID
    assert hijo["origen_tramite"]["numero_expediente"]
    padre = db.tramite_detalle(TRAMITE_ID)
    assert any(v["id"] == hijo_id for v in padre["derivados"])

    # Origen ajeno (tramite de OTRO cuil): el vinculo se ignora en silencio.
    with Session(db.engine) as s:
        ajeno = s.exec(select(Tramite).where(Tramite.cuil != "20111111119")).first()
    if ajeno:
        r2 = trab.post("/api/tramite", data={
            "tipo_tramite_id": TIPO_ID,
            "origen_tramite_id": str(ajeno.id),
            f"campo_{_campo_id('Solicitud')}": "x",
            f"campo_{_campo_id('CVU')}": "3" * 22,
            f"campo_{_campo_id('Monto')}": "1",
        }, files={f"archivo_{_campo_id('Comprobante')}": ("c.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r2.status_code == 200
        assert db.tramite_detalle(r2.json()["id"])["origen_tramite"] is None
    print("OK  test_tramite_encadenado_desde_chat")


if __name__ == "__main__":
    test_alta_tipo_tramite_con_campos_de_cada_tipo_dato()
    test_validacion_obligatorio_falta_campo()
    test_validacion_longitud_exacta()
    test_validacion_tipo_archivo_no_permitido()
    test_envio_tramite_completo_ok()
    test_numeracion_expediente_sin_colision()
    test_cambio_estado_dispara_log_y_notificacion()
    test_nota_admin_y_trabajador_en_thread_correcto()
    test_formulario_adjunto_en_chat()
    test_tramite_encadenado_desde_chat()
    test_campo_seleccion_fija()
    test_ancho_campos_y_nuevos_tipos_de_campo()
    test_cantidad_nuevos_para_el_polling_del_globo()
    test_terminado_bloquea_cambios()
    test_aislamiento_entre_sindicatos()
    test_bloqueo_403_si_modulo_apagado()
    print("\nTodo OK — trámites.")

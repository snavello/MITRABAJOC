"""Encuestas, Fase 0 de SPRINT_ENCUESTAS.md: catálogo, permisos y modelo.

Los tests de esta tanda son de dos clases muy distintas:

- los del catálogo (`encuestas.py`), que prueban reglas puras: estados,
  cortes, tipos de pregunta y el texto del disclaimer;
- los del MODELO, que son el primero de los cuatro tests de privacidad del
  plan (N21.2): verifican que la urna y el padrón NO SE PUEDAN CRUZAR, y lo
  hacen mirando la forma de las tablas, no el comportamiento de una ruta.
  Si alguien le suma a la urna una columna que lleve a una persona, o al
  padrón la hora en que respondió, estos tests fallan aunque toda la app
  siga andando -- que es exactamente para lo que están.

Correr con: .venv/Scripts/python.exe -m pytest test_encuestas.py -q
"""


import encuestas
import modulos
import permisos
import db
from sqlmodel import SQLModel

db.crear_tablas()

HOY = "2026-09-15"


def _sindicato_de_prueba() -> int:
    """Un sindicato de verdad, no un id inventado.

    Las FK se respetan porque el motor real (Postgres) las hace cumplir: un
    `sindicato_id=1` que no existe pasa desapercibido en SQLite y revienta
    en producción. Los tests de esta suite arman sus datos igual que
    test_noticias.py.
    """
    with db.get_session() as s:
        existente = s.exec(db.select(db.Sindicato).where(
            db.Sindicato.slug == "uom-encuestas")).first()
        if existente:
            return existente.id
        sind = db.Sindicato(nombre="UOM Encuestas", slug="uom-encuestas",
                            modulos_habilitados=list(modulos.MODULOS_INICIALES) + ["encuestas"])
        s.add(sind); s.commit(); s.refresh(sind)
        return sind.id


SID = _sindicato_de_prueba()


# ==================== Catálogo: estados ====================
def test_estado_borrador_mientras_no_se_publica():
    assert encuestas.estado(False, "2026-09-01", "2026-09-30", HOY) == encuestas.BORRADOR
    # Sin publicar es borrador aunque las fechas ya hayan pasado.
    assert encuestas.estado(False, "2026-01-01", "2026-01-31", HOY) == encuestas.BORRADOR


def test_estado_por_fechas():
    assert encuestas.estado(True, "2026-09-20", "2026-09-30", HOY) == encuestas.PROGRAMADA
    assert encuestas.estado(True, "2026-09-01", "2026-09-30", HOY) == encuestas.ABIERTA
    assert encuestas.estado(True, "2026-08-01", "2026-08-31", HOY) == encuestas.CERRADA
    # Los dos bordes son inclusive: el primer y el último día está abierta.
    assert encuestas.estado(True, HOY, "2026-09-30", HOY) == encuestas.ABIERTA
    assert encuestas.estado(True, "2026-09-01", HOY, HOY) == encuestas.ABIERTA


def test_cierre_anticipado_le_gana_a_la_fecha():
    # N7: se puede cerrar antes. Y una vez cerrada no hay forma de que
    # vuelva a "abierta" sola, que es lo que hace creíble el resultado.
    assert encuestas.estado(True, "2026-09-01", "2026-09-30", HOY,
                            cerrada_en="2026-09-12 10:00") == encuestas.CERRADA
    assert not encuestas.acepta_respuestas(True, "2026-09-01", "2026-09-30", HOY,
                                           cerrada_en="2026-09-12 10:00")
    assert encuestas.acepta_respuestas(True, "2026-09-01", "2026-09-30", HOY)


# ==================== Catálogo: cortes y tipos ====================
def test_cortes_de_una_anonima_son_solo_los_tildados():
    assert encuestas.cortes_saneados(encuestas.ANONIMA, []) == []
    assert encuestas.cortes_saneados(encuestas.ANONIMA, ["seccional"]) == ["seccional"]
    # Lo que no está en el catálogo no se guarda "por las dudas".
    assert encuestas.cortes_saneados(encuestas.ANONIMA, ["seccional", "sueldo"]) == ["seccional"]
    # Y salen siempre en el orden del catálogo, no en el que los mandaron.
    assert encuestas.cortes_saneados(
        encuestas.ANONIMA, ["empleador", "seccional"]) == ["seccional", "empleador"]


def test_una_nominal_tiene_todos_los_cortes():
    assert encuestas.cortes_saneados(encuestas.NOMINAL, []) == list(encuestas.CORTES)


def test_en_una_anonima_no_se_pueden_adjuntar_archivos():
    # N4b: una foto lleva metadatos y un PDF lleva autor. Es la forma más
    # fácil de romper el anonimato sin que nadie se dé cuenta.
    tipos_anonima = dict(encuestas.tipos_para(encuestas.ANONIMA))
    tipos_nominal = dict(encuestas.tipos_para(encuestas.NOMINAL))
    assert "archivo" not in tipos_anonima
    assert "archivo" in tipos_nominal
    # Los propios de encuestas están en los dos modos.
    assert "escala" in tipos_anonima and "ranking" in tipos_anonima


# ==================== Catálogo: el disclaimer ====================
def test_el_disclaimer_de_una_anonima_no_promete_lo_que_no_cumple():
    texto = " ".join(encuestas.disclaimer(encuestas.ANONIMA, ["seccional"])).lower()
    # La promesa que NO se puede cumplir (hay que registrar quién participó
    # para impedir el voto doble) no aparece por ningún lado.
    assert "ningún dato personal" not in texto
    # La que sí se cumple, textual.
    assert "queda registrado que participaste" in texto
    assert "nunca qué respondiste" in texto


def test_el_disclaimer_nombra_exactamente_lo_que_se_guarda():
    con_dos = " ".join(encuestas.disclaimer(encuestas.ANONIMA, ["seccional", "provincia"])).lower()
    assert "seccional" in con_dos and "provincia" in con_dos
    assert "empleador" not in con_dos          # no se tildó: no se nombra
    assert "menos de 5 personas" in con_dos    # el umbral, dicho en criollo

    sin_cortes = " ".join(encuestas.disclaimer(encuestas.ANONIMA, [])).lower()
    assert "no se guarda ningún dato tuyo junto a la respuesta" in sin_cortes
    assert "seccional" not in sin_cortes

    # El umbral que se muestra es el de la encuesta, no una constante suelta.
    assert "menos de 8 personas" in " ".join(
        encuestas.disclaimer(encuestas.ANONIMA, ["seccional"], umbral=8)).lower()


def test_la_nominal_avisa_que_no_es_anonima():
    texto = " ".join(encuestas.disclaimer(encuestas.NOMINAL)).lower()
    assert "nominal" in texto and "cuil" in texto


def test_ningun_modo_ofrece_editar_la_respuesta_despues():
    # N11: nadie edita, ni en nominal ni en anónima. El aviso está en los dos.
    for modo in (encuestas.ANONIMA, encuestas.NOMINAL):
        texto = " ".join(encuestas.disclaimer(modo, ["seccional"])).lower()
        assert "no vas a poder modificar tu respuesta" in texto


# ==================== Módulo y permisos ====================
def test_el_modulo_existe_y_es_opt_in():
    assert "encuestas" in modulos.MODULOS
    assert "encuestas" not in modulos.MODULOS_INICIALES


def test_las_dos_secciones_dependen_del_modulo():
    for seccion in ("encuestas", "encuestas_resultados"):
        etiqueta, modulo, grupo = permisos.SECCIONES[seccion]
        assert modulo == "encuestas", seccion
        assert grupo == "Comunicación", seccion
        assert etiqueta

    # Sin el módulo no se pueden ni ofrecer al armar un perfil de área.
    sin = permisos.secciones_de_modulos([])
    assert "encuestas" not in sin and "encuestas_resultados" not in sin
    con = permisos.secciones_de_modulos(["encuestas"])
    assert "encuestas" in con and "encuestas_resultados" in con


def test_apagar_el_modulo_invalida_los_permisos_viejos():
    # La red de seguridad de calcular_efectivos: si plataforma le apaga el
    # módulo al sindicato, los permisos que ya estaban dados dejan de valer
    # solos, sin salir a limpiar filas.
    del_area = ["encuestas", "encuestas_resultados", "noticias"]
    con = permisos.calcular_efectivos(del_area, [], [], ["encuestas", "noticias"])
    assert "encuestas" in con and "encuestas_resultados" in con
    sin = permisos.calcular_efectivos(del_area, [], [], ["noticias"])
    assert "encuestas" not in sin and "encuestas_resultados" not in sin
    assert "noticias" in sin


def test_ver_resultados_se_puede_dar_sin_poder_crear():
    # El motivo de partirlo en dos: Prensa lanza, la conducción lee.
    solo_lectura = permisos.calcular_efectivos(
        ["encuestas_resultados"], [], [], ["encuestas"])
    assert solo_lectura == {"encuestas_resultados"}


# ==================== Privacidad: la forma de las tablas (N21.2) ====================
# Nombres que, en la urna, significarían que una respuesta lleva a alguien.
COLUMNAS_PROHIBIDAS_EN_LA_URNA = {
    "cuil", "cuit", "trabajador_id", "participante_id", "usuario_id",
    "cuenta_id", "sesion", "session", "ip", "user_agent", "token",
    "creado", "creado_en", "enviado_en", "respondido_en", "hora", "timestamp",
}


def test_la_urna_no_tiene_ninguna_columna_que_lleve_a_una_persona():
    columnas = set(SQLModel.metadata.tables["respuestaencuesta"].columns.keys())
    prohibidas = columnas & COLUMNAS_PROHIBIDAS_EN_LA_URNA
    assert not prohibidas, (
        "RespuestaEncuesta (la urna) no puede guardar nada que lleve a una "
        f"persona ni una hora fina: {prohibidas}. Ver SPRINT_ENCUESTAS.md, "
        "'Cómo se sostiene el anonimato'.")


def test_la_urna_no_apunta_al_padron_ni_al_padron_de_afiliados():
    tabla = SQLModel.metadata.tables["respuestaencuesta"]
    apuntadas = {fk.column.table.name for fk in tabla.foreign_keys}
    assert apuntadas == {"encuesta", "preguntaencuesta"}, (
        f"la urna solo puede apuntar a la encuesta y a la pregunta: {apuntadas}")


def test_la_urna_guarda_el_dia_y_no_la_hora():
    columnas = SQLModel.metadata.tables["respuestaencuesta"].columns
    assert "dia" in columnas
    # Sin hora no hay forma de ordenar las respuestas en el tiempo para
    # alinearlas con nada. La curva de ritmo del dashboard sale de acá.
    assert columnas["dia"].index is True


def test_el_padron_no_guarda_cuando_respondio_cada_uno():
    columnas = set(SQLModel.metadata.tables["encuestaparticipante"].columns.keys())
    assert columnas == {"id", "encuesta_id", "cuil", "respondio"}, (
        "EncuestaParticipante (el padrón) guarda QUIÉN participó y nada más: "
        "una fecha acá, por gruesa que fuera, volvería a permitir cruzarla "
        f"con la urna. Columnas de más: {columnas - {'id','encuesta_id','cuil','respondio'}}")


def test_el_padron_se_prende_sin_mover_la_fila():
    # Que `respondio` sea un booleano de la MISMA fila (y no una fila nueva
    # al responder) es lo que hace que el orden de los id sea el del padrón
    # y no el de las respuestas.
    with db.get_session() as s:
        enc = db.Encuesta(sindicato_id=SID, titulo="Clima laboral",
                          fecha_desde="2026-09-01", fecha_hasta="2026-09-30")
        s.add(enc); s.commit(); s.refresh(enc)
        for cuil in ("20111111119", "27222222224", "20333333330"):
            s.add(db.EncuestaParticipante(encuesta_id=enc.id, cuil=cuil))
        s.commit()

        # El tercero responde primero: su fila NO cambia de lugar.
        # Acotado a ESTA encuesta: el mismo CUIL puede estar en el padrón de
        # varias, y una base que no se tira después de cada corrida lo tiene.
        tercero = s.exec(db.select(db.EncuestaParticipante).where(
            db.EncuestaParticipante.encuesta_id == enc.id,
            db.EncuestaParticipante.cuil == "20333333330")).one()
        id_antes = tercero.id
        tercero.respondio = True
        s.add(tercero); s.commit(); s.refresh(tercero)
        assert tercero.id == id_antes

        ids = [p.id for p in s.exec(db.select(db.EncuestaParticipante).where(
            db.EncuestaParticipante.encuesta_id == enc.id)).all()]
        assert ids == sorted(ids)


# ==================== Modelo: lo demás ====================
def test_la_encuesta_se_cuelga_de_noticias_y_notificaciones():
    # De Notificacion.encuesta_id sale el "leídas / no leídas" del dashboard.
    assert "encuesta_id" in SQLModel.metadata.tables["noticia"].columns
    assert "encuesta_id" in SQLModel.metadata.tables["notificacion"].columns


def test_el_umbral_sale_de_plataforma_con_default_propio():
    # El test arma su propio estado en vez de suponer una base recién
    # nacida: contra Postgres la fila de configuración puede existir de
    # antes, y suponer que no existía es lo que hace que un test pase en un
    # SQLite descartable y falle en el motor de verdad.
    with db.get_session() as s:
        fila = s.get(db.ConfiguracionPlataforma, 1)
        if fila:
            s.delete(fila); s.commit()
    assert db.umbral_encuestas() == encuestas.UMBRAL_MINIMO_DEFAULT  # sin fila

    with db.get_session() as s:
        s.add(db.ConfiguracionPlataforma(id=1, encuestas_umbral_minimo=8))
        s.commit()
    assert db.umbral_encuestas() == 8

    with db.get_session() as s:
        fila = s.get(db.ConfiguracionPlataforma, 1)
        fila.encuestas_umbral_minimo = encuestas.UMBRAL_MINIMO_DEFAULT
        s.add(fila); s.commit()


def test_una_encuesta_nace_en_borrador_y_nominal():
    with db.get_session() as s:
        enc = db.Encuesta(sindicato_id=SID, titulo="Paritaria 2026",
                          fecha_desde="2026-10-01", fecha_hasta="2026-10-15")
        s.add(enc); s.commit(); s.refresh(enc)
        assert enc.modo == encuestas.NOMINAL       # el modo seguro es el default
        assert enc.publicada is False
        assert enc.cortes == []
        assert enc.umbral_minimo == encuestas.UMBRAL_MINIMO_DEFAULT
        assert encuestas.estado(enc.publicada, enc.fecha_desde, enc.fecha_hasta,
                                "2026-10-05") == encuestas.BORRADOR


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))


# ==================== Fase 1: el constructor ====================
import json  # noqa: E402
from urllib.parse import unquote  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

cliente = TestClient(main.app)


def _sindicato_con(modulos: list, slug: str) -> tuple:
    """(sindicato_id, usuario_id) de un Super Admin de un sindicato nuevo."""
    with db.get_session() as s:
        sind = db.Sindicato(nombre=slug.upper(), slug=slug, modulos_habilitados=modulos)
        s.add(sind); s.commit(); s.refresh(sind)
        u = db.UsuarioSindicato(sindicato_id=sind.id, usuario=f"20{sind.id:09d}",
                                nombre="Admin", clave_hash=auth.hashear_clave("x"),
                                debe_cambiar_clave=False, es_super_admin=True)
        s.add(u); s.commit(); s.refresh(u)
        return sind.id, u.id


def _sesion(sid: int, uid: int):
    # clear() primero: el cookie jar conserva la cookie anterior y, al
    # mandar las dos, el servidor se queda con la de la sesión vieja -- el
    # test parecería estar mirando el sindicato nuevo y estaría mirando el
    # anterior.
    cliente.cookies.clear()
    cliente.cookies.set("sesion_sindicato", auth.crear_sesion("sindicato", uid, sid))


PREGUNTAS = [
    {"etiqueta": "¿Conforme con la obra social?", "tipo_dato": "escala",
     "escala_min": 1, "escala_max": 5, "etiqueta_min": "Nada", "etiqueta_max": "Mucho",
     "ancho": "completo", "obligatorio": True},
    {"etiqueta": "Ordená los reclamos", "tipo_dato": "ranking",
     "opciones": "Salario, Obra social, Jornada", "ancho": "completo", "obligatorio": True},
]


def _alta(titulo="Clima laboral", modo="anonima", cortes=("seccional",), preguntas=None):
    return cliente.post("/admin/encuesta", data={
        "titulo": titulo, "descripcion": "Tres minutos", "modo": modo,
        "cortes": list(cortes), "fecha_desde": "2026-10-01", "fecha_hasta": "2026-10-15",
        "mostrar_resultados": "1",
        "preguntas_json": json.dumps(preguntas if preguntas is not None else PREGUNTAS),
    }, follow_redirects=False)


def test_el_panel_aparece_solo_con_modulo_y_permiso():
    sid, uid = _sindicato_con(["encuestas"], "con-encuestas")
    _sesion(sid, uid)
    html = cliente.get("/admin").text
    assert 'id="panel-encuestas"' in html and 'data-panel="encuestas"' in html

    sid2, uid2 = _sindicato_con(["noticias"], "sin-encuestas")
    _sesion(sid2, uid2)
    html = cliente.get("/admin").text
    assert 'id="panel-encuestas"' not in html and 'data-panel="encuestas"' not in html


def test_sin_el_modulo_el_backend_rechaza_aunque_se_arme_el_post_a_mano():
    # Esconder la pestaña no es ningún control: el HTML se lee con Ver
    # Código Fuente y el POST se arma con curl.
    sid, uid = _sindicato_con(["noticias"], "sin-mod-post")
    _sesion(sid, uid)
    r = _alta()
    assert r.status_code == 403, r.status_code


def test_todas_las_rutas_de_encuestas_estan_clasificadas():
    # El gateo es fail-closed: una ruta que nadie clasificó se rechaza sola.
    # Este test evita el olvido al sumar rutas en las fases que siguen.
    rutas = {r.path for r in main.app.routes
             if getattr(r, "path", "").startswith("/admin/encuesta")}
    sin_clasificar = rutas - set(main.PERMISOS_RUTAS)
    assert not sin_clasificar, sin_clasificar
    assert all(main.PERMISOS_RUTAS[r] in ("encuestas", "encuestas_resultados")
               for r in rutas)


def test_alta_guarda_preguntas_escala_y_ranking():
    sid, uid = _sindicato_con(["encuestas"], "alta-ok")
    _sesion(sid, uid)
    assert _alta().status_code == 303
    e = db.encuestas_del_sindicato(sid)[0]
    assert e["modo"] == encuestas.ANONIMA and e["cortes"] == ["seccional"]
    assert e["estado"] == encuestas.BORRADOR      # publicar es otro acto (Fase 3)
    escala, ranking = e["preguntas"]
    assert (escala["tipo_dato"], escala["escala_min"], escala["escala_max"]) == ("escala", 1, 5)
    assert ranking["opciones"] == "Salario, Obra social, Jornada"


def test_una_pregunta_mal_formada_no_se_guarda_y_dice_por_que():
    sid, uid = _sindicato_con(["encuestas"], "alta-mala")
    _sesion(sid, uid)
    r = _alta(preguntas=[{"etiqueta": "Foto del recibo", "tipo_dato": "archivo"}])
    assert "error=encuesta" in r.headers["location"]
    assert "archivo" in unquote(r.headers["location"])
    assert not db.encuestas_del_sindicato(sid)

    r = _alta(preguntas=[{"etiqueta": "¿Cuál preferís?", "tipo_dato": "opcion_unica",
                          "opciones": "Una sola"}])
    assert "dos opciones" in unquote(r.headers["location"])
    assert not db.encuestas_del_sindicato(sid)


def test_el_disclaimer_de_la_vista_previa_lo_arma_el_servidor():
    # Una copia del texto en JS que se desincronice haría que la pantalla
    # prometa algo distinto de lo que el sistema cumple: por eso el
    # constructor lo PIDE y no lo escribe.
    sid, uid = _sindicato_con(["encuestas"], "disclaimer")
    _sesion(sid, uid)
    r = cliente.get("/admin/encuesta/disclaimer",
                    params={"modo": "anonima", "cortes": ["seccional"]})
    assert r.status_code == 200
    assert r.json()["lineas"] == encuestas.disclaimer(
        encuestas.ANONIMA, ["seccional"], db.umbral_encuestas())


def test_con_respuestas_se_congela_la_estructura_y_se_permite_la_errata():
    sid, uid = _sindicato_con(["encuestas"], "congelado")
    _sesion(sid, uid)
    _alta()
    e = db.encuestas_del_sindicato(sid)[0]
    with db.get_session() as s:
        s.add(db.RespuestaEncuesta(encuesta_id=e["id"], pregunta_id=e["preguntas"][0]["id"],
                                   valor_numero=4, dia="2026-10-02"))
        s.commit()

    # Quitar una pregunta: rechazado, y la encuesta queda intacta.
    r = cliente.post("/admin/encuesta", data={
        "id": e["id"], "titulo": "Clima laboral", "modo": "anonima",
        "fecha_hasta": "2026-10-20", "preguntas_json": json.dumps(PREGUNTAS[:1])},
        follow_redirects=False)
    assert "error=encuesta" in r.headers["location"]
    assert len(db.encuesta_por_id(e["id"])["preguntas"]) == 2

    # Corregir la redacción: permitido, y queda registrado con fecha.
    corregidas = [dict(p) for p in PREGUNTAS]
    corregidas[0]["etiqueta"] = "¿Estás conforme con la obra social?"
    r = cliente.post("/admin/encuesta", data={
        "id": e["id"], "titulo": "Clima laboral", "modo": "anonima",
        "fecha_hasta": "2026-10-25", "preguntas_json": json.dumps(corregidas)},
        follow_redirects=False)
    assert r.headers["location"] == "/admin#encuestas"
    despues = db.encuesta_por_id(e["id"])
    assert despues["preguntas"][0]["etiqueta"] == "¿Estás conforme con la obra social?"
    assert despues["fecha_hasta"] == "2026-10-25"
    evento = db.eventos_de_encuesta(e["id"])[0]
    assert evento["evento"] == "edicion" and "Corrección de texto" in evento["detalle"]
    assert evento["fecha"]


def test_duplicar_guarda_el_linaje_y_numera_el_titulo():
    sid, uid = _sindicato_con(["encuestas"], "duplicar")
    _sesion(sid, uid)
    _alta(titulo="Clima laboral")
    original = db.encuestas_del_sindicato(sid)[0]
    cliente.post("/admin/encuesta/duplicar", data={"id": original["id"]},
                 follow_redirects=False)
    copia = [e for e in db.encuestas_del_sindicato(sid) if e["id"] != original["id"]][0]
    assert copia["titulo"] == "Clima laboral (2)"
    assert copia["origen_id"] == original["id"]     # con esto se comparan las tomas
    assert copia["estado"] == encuestas.BORRADOR
    assert copia["fecha_desde"] == "" and copia["fecha_hasta"] == ""
    assert len(copia["preguntas"]) == len(original["preguntas"])

    # La copia de la copia sigue la numeración, no se llama "copia de copia".
    cliente.post("/admin/encuesta/duplicar", data={"id": copia["id"]}, follow_redirects=False)
    assert any(e["titulo"] == "Clima laboral (3)" for e in db.encuestas_del_sindicato(sid))


def test_borrar_solo_borradores():
    sid, uid = _sindicato_con(["encuestas"], "borrar")
    _sesion(sid, uid)
    _alta()
    e = db.encuestas_del_sindicato(sid)[0]
    r = cliente.post("/admin/encuesta/borrar", data={"id": e["id"]}, follow_redirects=False)
    assert r.headers["location"] == "/admin#encuestas"
    assert not db.encuestas_del_sindicato(sid)

    # Una publicada no se borra: tiene padrón fijado y es un hecho del sindicato.
    _alta(titulo="Publicada")
    e = db.encuestas_del_sindicato(sid)[0]
    with db.get_session() as s:
        fila = s.get(db.Encuesta, e["id"]); fila.publicada = True; s.add(fila); s.commit()
    r = cliente.post("/admin/encuesta/borrar", data={"id": e["id"]}, follow_redirects=False)
    assert "error=encuesta" in r.headers["location"]
    assert db.encuesta_por_id(e["id"]) is not None


def test_una_encuesta_de_otro_sindicato_no_se_toca():
    sid_a, uid_a = _sindicato_con(["encuestas"], "aislada-a")
    _sesion(sid_a, uid_a)
    _alta(titulo="De A")
    ajena = db.encuestas_del_sindicato(sid_a)[0]

    sid_b, uid_b = _sindicato_con(["encuestas"], "aislada-b")
    _sesion(sid_b, uid_b)
    assert not db.encuestas_del_sindicato(sid_b)
    r = cliente.post("/admin/encuesta/borrar", data={"id": ajena["id"]}, follow_redirects=False)
    assert "error=encuesta" in r.headers["location"]
    assert db.encuesta_por_id(ajena["id"]) is not None
    assert db.encuesta_por_id(ajena["id"], sid_b) is None

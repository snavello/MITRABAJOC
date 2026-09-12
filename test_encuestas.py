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


from datetime import timedelta

import encuestas
import fechas
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


def test_la_nominal_no_lleva_disclaimer():
    # Una encuesta nominal es el caso por defecto: el afiliado entró con su
    # CUIL y no espera otra cosa. Un cartel explicando lo obvio le resta
    # peso al que SÍ importa, el de las anónimas.
    assert encuestas.disclaimer(encuestas.NOMINAL) == []
    assert encuestas.disclaimer(encuestas.NOMINAL, ["seccional"]) == []


def test_la_anonima_avisa_que_no_se_puede_editar():
    # N11: nadie edita, en ningún modo. En la anónima además es la prueba de
    # que el anonimato es real -- el sistema no sabe cuál fue tu respuesta.
    # En la nominal lo dice el pie de la pantalla, no el disclaimer.
    texto = " ".join(encuestas.disclaimer(encuestas.ANONIMA, ["seccional"])).lower()
    assert "no vas a poder modificar tu respuesta" in texto


def test_cada_tipo_de_pregunta_dice_que_hacer():
    # "Opción única" y "múltiple" se ven casi igual (un círculo o un
    # cuadrado): sin esta línea nadie sabe si puede marcar una o varias.
    assert "una opción" in encuestas.ayuda_de("opcion_unica")
    assert "varias" in encuestas.ayuda_de("multiple")
    assert "escala" in encuestas.ayuda_de("escala")
    assert "ordená" in encuestas.ayuda_de("ranking").lower()
    assert encuestas.ayuda_de("separador") == ""      # no se responde
    # Una pregunta opcional lo dice, en vez de dejarlo a la interpretación
    # de un asterisco que no está.
    assert "dejarla en blanco" in encuestas.ayuda_de("texto", obligatorio=False)
    assert "dejarla en blanco" not in encuestas.ayuda_de("texto")
    # Todos los tipos del catálogo tienen su línea (menos el separador).
    faltan = [t for t in encuestas.TIPOS_PREGUNTA
              if t not in encuestas.TIPOS_SIN_RESPUESTA and not encuestas.ayuda_de(t)]
    assert not faltan, faltan


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


def _alta(titulo="Clima laboral", modo="anonima", cortes=("seccional",), preguntas=None,
          desde="2026-10-01", hasta="2026-10-15", extra=None):
    """POST al constructor. Con extra={"id": N} es una edición, no un alta."""
    datos = {
        "titulo": titulo, "descripcion": "Tres minutos", "modo": modo,
        "cortes": list(cortes), "fecha_desde": desde, "fecha_hasta": hasta,
        "mostrar_resultados": "1",
        "preguntas_json": json.dumps(preguntas if preguntas is not None else PREGUNTAS),
    }
    datos.update(extra or {})
    return cliente.post("/admin/encuesta", data=datos, follow_redirects=False)


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


# ==================== Fase 2: publicar y responder ====================
def _cuils(sid: int) -> tuple:
    """Dos CUIL propios de ESTE sindicato.

    Únicos por sindicato a propósito: si el mismo CUIL queda empadronado en
    varios, la app no puede resolver en cuál está parado el trabajador
    (pluriempleo) y responde 403 -- el test fallaría por un motivo que no
    tiene nada que ver con lo que está probando.
    """
    return f"20{sid:09d}", f"27{sid:09d}"


def _padron(sid: int, cuils=None, seccional_id=None, provincia="Santa Fe"):
    with db.get_session() as s:
        for c in (cuils if cuils is not None else _cuils(sid)):
            s.add(db.Trabajador(sindicato_id=sid, cuil=c, nombre="T " + c, activo=True,
                                registrado=True, seccional_id=seccional_id,
                                provincia=provincia, cuit_empleador="30999888776"))
        s.commit()


def _sesion_trabajador(cuil: str, sid: int = 0):
    cliente.cookies.clear()
    cliente.cookies.set("sesion_trabajador", auth.crear_sesion("trabajador"))
    cliente.cookies.set("cuil_trab", cuil)
    if sid:
        cliente.cookies.set("sind_elegido", str(sid))


def _encuesta_publicada(slug: str, modo="anonima", cortes=("seccional",),
                        preguntas=None, criterio="todos", valores=()):
    """(sid, uid, encuesta_id) con el padrón ya fijado."""
    sid, uid = _sindicato_con(["encuestas"], slug)
    _padron(sid)
    _sesion(sid, uid)
    # La ventana se calcula alrededor de HOY: una encuesta con fechas fijas
    # se vuelve "programada" o "cerrada" sola con el paso del tiempo, y el
    # test empezaría a fallar un día sin que nadie toque nada.
    hoy = fechas.hoy()
    _alta(modo=modo, cortes=cortes, preguntas=preguntas,
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    r = cliente.post("/admin/encuesta/publicar",
                     data={"id": eid, "criterio": criterio, "valores": list(valores)},
                     follow_redirects=False)
    assert r.headers["location"] == f"/admin?avisar={eid}#encuestas", unquote(r.headers["location"])
    return sid, uid, eid


def test_publicar_fija_el_padron():
    sid, uid, eid = _encuesta_publicada("publicar")
    e = db.encuestas_del_sindicato(sid)[0]
    assert e["estado"] == encuestas.ABIERTA
    assert e["participantes"] == 2 and e["cantidad_destinatarios"] == 2
    assert e["umbral_minimo"] == db.umbral_encuestas()   # congelado al publicar
    # Y no se recalcula: un afiliado nuevo no entra a una encuesta ya lanzada.
    _padron(sid, ("20333333330",))
    assert db.encuestas_del_sindicato(sid)[0]["participantes"] == 2


def test_no_se_publica_dos_veces_ni_sin_fechas_ni_sin_gente():
    sid, uid, eid = _encuesta_publicada("publicar-otra-vez")
    r = cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                     follow_redirects=False)
    assert "ya está publicada" in unquote(r.headers["location"])

    sid2, uid2 = _sindicato_con(["encuestas"], "sin-fechas")
    _padron(sid2)
    _sesion(sid2, uid2)
    cliente.post("/admin/encuesta", data={"titulo": "Sin fechas", "modo": "nominal",
                                          "preguntas_json": json.dumps(PREGUNTAS)},
                 follow_redirects=False)
    eid2 = db.encuestas_del_sindicato(sid2)[0]["id"]
    r = cliente.post("/admin/encuesta/publicar", data={"id": eid2, "criterio": "todos"},
                     follow_redirects=False)
    assert "las dos fechas" in unquote(r.headers["location"])
    assert not db.encuestas_del_sindicato(sid2)[0]["publicada"]

    sid3, uid3 = _sindicato_con(["encuestas"], "sin-gente")   # sin padrón
    _sesion(sid3, uid3)
    _alta()
    eid3 = db.encuestas_del_sindicato(sid3)[0]["id"]
    r = cliente.post("/admin/encuesta/publicar", data={"id": eid3, "criterio": "todos"},
                     follow_redirects=False)
    assert "no alcanza a ningún afiliado" in unquote(r.headers["location"])


def test_el_afiliado_ve_la_encuesta_y_la_responde_una_sola_vez():
    sid, uid, eid = _encuesta_publicada("responder")
    _sesion_trabajador(_cuils(sid)[0], sid)
    lista = cliente.get("/api/encuestas").json()["encuestas"]
    assert [e["id"] for e in lista] == [eid]
    assert lista[0]["respondio"] is False and lista[0]["disclaimer"]
    pids = [p["id"] for p in lista[0]["preguntas"]]

    r = cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 5, str(pids[1]): [1, 0, 2]}})
    assert r.status_code == 200
    assert cliente.get("/api/encuestas").json()["encuestas"][0]["respondio"] is True

    r = cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 1, str(pids[1]): [0, 1, 2]}})
    assert r.status_code == 400
    assert "Ya respondiste" in r.json()["detail"]
    assert r.json()["codigo"] == "E-ENCUESTA-01"
    # Y la segunda no dejó rastro: sigue habiendo una sola tanda de respuestas.
    with db.get_session() as s:
        filas = s.exec(db.select(db.RespuestaEncuesta)
                       .where(db.RespuestaEncuesta.encuesta_id == eid)).all()
    assert len({f.valor_numero for f in filas if f.valor_numero is not None}) == 1


def test_quien_no_esta_en_el_padron_no_entra_y_no_se_entera_de_nada():
    sid, uid = _sindicato_con(["encuestas"], "ajeno")
    invitado, ajeno = _cuils(sid)
    _padron(sid)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar",
                 data={"id": eid, "criterio": "cuil", "valores": [invitado]},
                 follow_redirects=False)

    _sesion_trabajador(ajeno, sid)
    assert cliente.get("/api/encuestas").json()["encuestas"] == []
    r = cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {}})
    assert r.status_code == 400
    # El mensaje es de ACCESO, no sobre las preguntas: al revés, alguien que
    # no fue invitado se enteraría de cómo está armada la encuesta.
    assert "no está dirigida a vos" in r.json()["detail"]
    assert "Falta responder" not in r.json()["detail"]


def test_fuera_de_la_ventana_no_se_responde():
    sid, uid, eid = _encuesta_publicada("ventana")
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    respuestas = {"respuestas": {str(pids[0]): 3, str(pids[1]): [0, 1, 2]}}

    _sesion(sid, uid)
    cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    _sesion_trabajador(_cuils(sid)[0], sid)
    r = cliente.post(f"/api/encuesta/{eid}", json=respuestas)
    assert r.status_code == 400 and "no está abierta" in r.json()["detail"]

    # Cerrada es cerrada: no hay forma de reabrirla (N7).
    _sesion(sid, uid)
    r = cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    assert "ya está cerrada" in unquote(r.headers["location"])


def test_solo_se_guardan_los_cortes_que_la_encuesta_habilito():
    sid, uid = _sindicato_con(["encuestas"], "cortes")
    with db.get_session() as s:
        sec = db.Seccional(sindicato_id=sid, nombre="Rosario")
        s.add(sec); s.commit(); s.refresh(sec)
        seccional_id = sec.id
    _padron(sid, seccional_id=seccional_id)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),     # provincia y empleador NO
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    _sesion_trabajador(_cuils(sid)[0], sid)
    # El status se afirma: sin esto, una respuesta rechazada dejaría la urna
    # vacía y el test podría pasar por el motivo equivocado.
    assert cliente.post(f"/api/encuesta/{eid}",
                        json={"respuestas": {str(pids[0]): 4,
                                             str(pids[1]): [0, 1, 2]}}).status_code == 200

    with db.get_session() as s:
        filas = s.exec(db.select(db.RespuestaEncuesta)
                       .where(db.RespuestaEncuesta.encuesta_id == eid)).all()
    assert filas
    for f in filas:
        assert f.seccional_id == seccional_id      # tildado: se guarda
        assert f.provincia == ""                   # no tildado: no se guarda
        assert f.cuit_empleador == ""              # tampoco
        assert f.dia and len(f.dia) == 10          # el día, nunca la hora


# ---------- Privacidad 1: ninguna ruta devuelve un CUIL (N21.1) ----------
def _tiene(dato, aguja: str) -> bool:
    """Busca un texto en cualquier lugar de una estructura, por anidado que esté."""
    if isinstance(dato, str):
        return aguja in dato
    if isinstance(dato, dict):
        return any(_tiene(k, aguja) or _tiene(v, aguja) for k, v in dato.items())
    if isinstance(dato, list):
        return any(_tiene(x, aguja) for x in dato)
    return False


def test_ninguna_salida_de_una_anonima_devuelve_un_cuil():
    sid, uid, eid = _encuesta_publicada("privacidad-rutas")
    cuil, _ = _cuils(sid)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    _sesion_trabajador(cuil, sid)
    assert cliente.post(f"/api/encuesta/{eid}",
                        json={"respuestas": {str(pids[0]): 5,
                                             str(pids[1]): [2, 1, 0]}}).status_code == 200

    # Lo que ve el afiliado.
    assert not _tiene(cliente.get("/api/encuestas").json(), cuil)
    # Lo que ve el sindicato del módulo: la encuesta serializada (es lo que
    # el panel embebe en el botón Editar) y los endpoints de encuestas. El
    # padrón de afiliados tiene su propia pestaña y ahí los CUIL van: lo que
    # no puede pasar es que salgan POR ACÁ.
    _sesion(sid, uid)
    assert not _tiene(db.encuestas_del_sindicato(sid), cuil)
    assert not _tiene(db.encuesta_por_id(eid, sid), cuil)
    assert not _tiene(cliente.get("/admin/encuesta/disclaimer",
                                  params={"modo": "anonima"}).json(), cuil)
    assert not _tiene(db.eventos_de_encuesta(eid), cuil)
    # Y el dashboard, que es el que agrega las respuestas: si un CUIL se
    # colara acá, todo el anonimato de la urna no serviría de nada.
    assert not _tiene(cliente.get("/admin/encuesta/resultados",
                                  params={"id": eid}).json(), cuil)
    assert not _tiene(cliente.get("/admin/encuesta/avisos",
                                  params={"id": eid}).json(), cuil)
    # Con el corte aplicado tampoco -- es donde el grupo se achica.
    assert not _tiene(cliente.get("/admin/encuesta/resultados",
                                  params={"id": eid, "seccional": "1"}).json(), cuil)
    # Y lo que ve el afiliado cuando cierra (N12).
    cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    _sesion_trabajador(cuil, sid)
    r = cliente.get(f"/api/encuesta/{eid}/resultados")
    if r.status_code == 200:
        assert not _tiene(r.json(), cuil)


# ---------- Privacidad 2: padrón y urna no se cruzan (N21.2) ----------
def test_en_una_anonima_no_existe_el_vinculo_con_la_persona():
    sid, uid, eid = _encuesta_publicada("privacidad-vinculo", modo="anonima")
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    _sesion_trabajador(_cuils(sid)[0], sid)
    cliente.post(f"/api/encuesta/{eid}",
                 json={"respuestas": {str(pids[0]): 5, str(pids[1]): [0, 1, 2]}})
    with db.get_session() as s:
        vinculos = s.exec(db.select(db.RespuestaNominal)
                          .where(db.RespuestaNominal.encuesta_id == eid)).all()
        filas = s.exec(db.select(db.RespuestaEncuesta)
                       .where(db.RespuestaEncuesta.encuesta_id == eid)).all()
        padron = s.exec(db.select(db.EncuestaParticipante)
                        .where(db.EncuestaParticipante.encuesta_id == eid)).all()
    assert filas and not vinculos, "una encuesta anónima no puede tener vínculos"
    # El padrón sabe QUIÉN participó y nada más; la urna, QUÉ se respondió.
    assert {p.cuil for p in padron} == set(_cuils(sid))
    assert all(p.respondio == (p.cuil == _cuils(sid)[0]) for p in padron)


def test_en_una_nominal_el_vinculo_existe_y_vive_en_su_tabla():
    sid, uid, eid = _encuesta_publicada("nominal-vinculo", modo="nominal", cortes=())
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    _sesion_trabajador(_cuils(sid)[0], sid)
    cliente.post(f"/api/encuesta/{eid}",
                 json={"respuestas": {str(pids[0]): 2, str(pids[1]): [1, 2, 0]}})
    with db.get_session() as s:
        vinculos = s.exec(db.select(db.RespuestaNominal)
                          .where(db.RespuestaNominal.encuesta_id == eid)).all()
        filas = s.exec(db.select(db.RespuestaEncuesta)
                       .where(db.RespuestaEncuesta.encuesta_id == eid)).all()
    assert len(vinculos) == len(filas) and {v.cuil for v in vinculos} == {_cuils(sid)[0]}
    # La flecha va de RespuestaNominal a la urna, nunca al revés: la urna
    # sigue sin ninguna columna que lleve a una persona, en los dos modos.
    assert {v.respuesta_id for v in vinculos} == {f.id for f in filas}


def test_una_encuesta_de_otro_sindicato_no_se_responde():
    sid_a, uid_a, eid = _encuesta_publicada("aislada-responder")
    sid_b, uid_b = _sindicato_con(["encuestas"], "aislada-otro")
    _padron(sid_b, ("20999999999",))
    _sesion_trabajador("20999999999")
    assert cliente.get("/api/encuestas").json()["encuestas"] == []
    r = cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {}})
    assert r.status_code == 400 and "no existe" in r.json()["detail"]


def test_la_portada_del_afiliado_tiene_su_puerta_de_entrada():
    """La pestaña no alcanza: el afiliado aterriza en la PORTADA.

    Sin esta tarjeta, una encuesta lanzada dependía de que entrara a la
    pestaña de casualidad -- que es exactamente lo que pasó la primera vez
    que se probó en Pruebas.
    """
    sid, uid, eid = _encuesta_publicada("portada")
    cuil, _ = _cuils(sid)
    _sesion_trabajador(cuil, sid)

    tarjeta = 'class="acceso" href="/app?tab=encuestas"'
    html = cliente.get("/app/inicio").text
    assert tarjeta in html
    assert "sin responder" in html          # la tarjeta dice cuántas faltan
    assert db.contar_encuestas_pendientes(cuil, sid) == 1

    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    assert cliente.post(f"/api/encuesta/{eid}",
                        json={"respuestas": {str(pids[0]): 4,
                                             str(pids[1]): [0, 1, 2]}}).status_code == 200
    assert db.contar_encuestas_pendientes(cuil, sid) == 0

    # Y sin el módulo, ni tarjeta ni cuenta.
    sid2, uid2 = _sindicato_con(["noticias"], "portada-sin-modulo")
    _padron(sid2)
    _sesion_trabajador(_cuils(sid2)[0], sid2)
    assert tarjeta not in cliente.get("/app/inicio").text


# ==================== Fase 3: comunicar ====================
def test_publicar_lleva_al_paso_de_avisar():
    """Publicar una encuesta y que nadie se entere de que existe es la falla
    más común y la más cara (N13): el paso es salteable, no invisible."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "avisar-paso")
    _padron(sid)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    r = cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                     follow_redirects=False)
    assert r.headers["location"] == f"/admin?avisar={eid}#encuestas"


def test_los_borradores_de_los_avisos_los_arma_el_servidor():
    # El lanzamiento y el recordatorio tienen que decir lo mismo sobre el
    # anonimato: dos textos escritos en dos lugares se desincronizan solos.
    sid, uid, eid = _encuesta_publicada("avisar-textos")
    e = db.encuesta_por_id(eid)
    d = cliente.get("/admin/encuesta/avisos", params={"id": eid}).json()
    assert d["lanzamiento"] == encuestas.texto_aviso(e["titulo"], e["fecha_hasta"], e["modo"])
    assert d["recordatorio"] == encuestas.texto_aviso(e["titulo"], e["fecha_hasta"],
                                                      e["modo"], encuestas.RECORDATORIO)
    assert d["noticia"] == encuestas.texto_noticia(e["titulo"], e["fecha_hasta"], e["modo"])
    # Una anónima lo dice en los dos textos, no solo en el primero.
    assert "anónima" in d["lanzamiento"] and "anónima" in d["recordatorio"]
    # Y la fecha se le muestra a una persona, no en el formato de la base:
    # "hasta el 2026-10-12" se lee como un mensaje del sistema.
    legible = fechas.dia_legible(e["fecha_hasta"])
    for texto in (d["lanzamiento"], d["recordatorio"], d["noticia"]["texto"]):
        assert legible in texto and e["fecha_hasta"] not in texto


def test_el_aviso_va_al_padron_fijado_de_la_encuesta():
    """Si fuera a otro criterio, "leídas / no leídas" se mediría contra un
    universo distinto al de "respondieron" y los dos números del dashboard
    no se podrían comparar (N13)."""
    sid, uid, eid = _encuesta_publicada("avisar-padron", criterio="todos")
    # Alguien que se afilia DESPUÉS de publicar no está en el padrón...
    _padron(sid, ("20999999999",))
    r = cliente.post("/admin/encuesta/notificar",
                     data={"id": eid, "texto": "Respondé la encuesta"}, follow_redirects=False)
    assert r.headers["location"] == "/admin?aviso=2#encuestas"
    # ...y por lo tanto tampoco recibe el aviso.
    destinatarios = {d["cuil"] for d in db.notificacion_destinatarios(
        db.avisos_de_encuesta(eid)[0]["id"])}
    assert destinatarios == set(_cuils(sid))
    assert "20999999999" not in destinatarios


def test_el_recordatorio_va_solo_a_los_que_faltan_y_uno_por_dia():
    sid, uid, eid = _encuesta_publicada("recordar")
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    uno, otro = _cuils(sid)
    _sesion_trabajador(uno, sid)
    assert cliente.post(f"/api/encuesta/{eid}",
                        json={"respuestas": {str(pids[0]): 4,
                                             str(pids[1]): [0, 1, 2]}}).status_code == 200

    _sesion(sid, uid)
    r = cliente.post("/admin/encuesta/notificar",
                     data={"id": eid, "texto": "Falta poco", "tipo": "recordatorio"},
                     follow_redirects=False)
    assert r.headers["location"] == "/admin?aviso=1#encuestas"
    # Funciona igual en una ANÓNIMA: quién falta sale del padrón, sin saber
    # qué respondió nadie.
    assert {d["cuil"] for d in db.notificacion_destinatarios(
        db.avisos_de_encuesta(eid)[-1]["id"])} == {otro}

    # El freno: uno por día. Cuatro recordatorios y el afiliado apaga las
    # notificaciones de la app -- y ahí se pierde el canal para todo.
    r = cliente.post("/admin/encuesta/notificar",
                     data={"id": eid, "texto": "Otro más", "tipo": "recordatorio"},
                     follow_redirects=False)
    assert "un recordatorio hoy" in unquote(r.headers["location"])
    assert db.recordatorios_de_hoy(eid) == 1


def test_no_se_recuerda_una_encuesta_cerrada():
    sid, uid, eid = _encuesta_publicada("recordar-cerrada")
    cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    r = cliente.post("/admin/encuesta/notificar",
                     data={"id": eid, "texto": "Falta poco", "tipo": "recordatorio"},
                     follow_redirects=False)
    assert "no está abierta" in unquote(r.headers["location"])


def test_la_noticia_hereda_la_ventana_de_la_encuesta():
    """La noticia es PÚBLICA: la ve cualquiera que entre a la app, esté o no
    en el padrón. Por eso vive exactamente lo que vive la encuesta."""
    sid, uid, eid = _encuesta_publicada("noticia")
    e = db.encuesta_por_id(eid)
    d = cliente.get("/admin/encuesta/avisos", params={"id": eid}).json()
    r = cliente.post("/admin/encuesta/noticia",
                     data={"id": eid, "titulo": d["noticia"]["titulo"],
                           "bajada": d["noticia"]["bajada"], "texto": d["noticia"]["texto"]},
                     follow_redirects=False)
    assert r.headers["location"] == "/admin?noticia=ok#encuestas"
    noticia = db.noticias_del_sindicato(sid)[0]
    assert noticia["encuesta_id"] == eid
    assert (noticia["fecha_desde"], noticia["fecha_hasta"]) == (e["fecha_desde"], e["fecha_hasta"])


def test_el_aviso_del_afiliado_lleva_a_la_encuesta_solo_mientras_este_abierta():
    sid, uid, eid = _encuesta_publicada("aviso-cta")
    cuil, _ = _cuils(sid)
    cliente.post("/admin/encuesta/notificar",
                 data={"id": eid, "texto": "Respondé la encuesta"}, follow_redirects=False)
    assert db.notificaciones_de_trabajador(cuil, sid)[0]["encuesta_id"] == eid

    # Cerrada, el aviso viejo ya no ofrece el botón: llevaría a una pantalla
    # que no acepta nada.
    cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    assert db.notificaciones_de_trabajador(cuil, sid)[0]["encuesta_id"] is None


def test_los_avisos_cuentan_lo_leido():
    sid, uid, eid = _encuesta_publicada("avisos-leidos")
    cuil, _ = _cuils(sid)
    cliente.post("/admin/encuesta/notificar",
                 data={"id": eid, "texto": "Respondé la encuesta"}, follow_redirects=False)
    avisos = db.avisos_de_encuesta(eid)
    assert len(avisos) == 1 and avisos[0]["enviados"] == 2 and avisos[0]["leidos"] == 0
    db.marcar_notificacion_leida(avisos[0]["id"], cuil)
    assert db.avisos_de_encuesta(eid)[0]["leidos"] == 1


def test_sin_publicar_no_hay_a_quien_avisarle():
    sid, uid = _sindicato_con(["encuestas"], "avisar-borrador")
    _padron(sid)
    _sesion(sid, uid)
    _alta()
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    r = cliente.post("/admin/encuesta/notificar", data={"id": eid, "texto": "Hola"},
                     follow_redirects=False)
    assert "Primero hay que publicar" in unquote(r.headers["location"])
    assert not db.avisos_de_encuesta(eid)


def test_prorrogar_una_encuesta_lanzada_queda_en_el_historial():
    """N7: cerrar antes sí, prorrogar sí, reabrir nunca -- y las dos cosas
    van al historial. Mover el cierre cuando ya hay gente avisada no es un
    retoque de redacción: cambia hasta cuándo se puede responder, y en un
    gremio con internas eso se discute."""
    sid, uid, eid = _encuesta_publicada("prorroga")
    nuevo = (fechas.hoy() + timedelta(days=60)).isoformat()
    r = _alta(desde=(fechas.hoy() - timedelta(days=1)).isoformat(), hasta=nuevo,
              extra={"id": eid})
    assert r.headers["location"] == "/admin#encuestas", unquote(r.headers["location"])
    assert db.encuesta_por_id(eid)["fecha_hasta"] == nuevo

    prorrogas = [v for v in db.eventos_de_encuesta(eid) if v["evento"] == "prorroga"]
    assert len(prorrogas) == 1
    assert fechas.dia_legible(nuevo) in prorrogas[0]["detalle"]

    # Guardar sin tocar la fecha no inventa una prórroga en el historial.
    _alta(desde=(fechas.hoy() - timedelta(days=1)).isoformat(), hasta=nuevo,
          extra={"id": eid})
    assert len([v for v in db.eventos_de_encuesta(eid) if v["evento"] == "prorroga"]) == 1


# ==================== Fase 4: el dashboard ====================
def _seccional(sid: int, nombre: str) -> int:
    with db.get_session() as s:
        x = db.Seccional(sindicato_id=sid, nombre=nombre)
        s.add(x); s.commit(); s.refresh(x)
        return x.id


def _admin_de_seccional(sid: int, seccional_id: int) -> int:
    """Un Admin de Seccional: las MISMAS secciones que el Super Admin, lo que
    lo achica es el alcance (ver db.permisos_efectivos y alcance_seccional)."""
    with db.get_session() as s:
        u = db.UsuarioSindicato(sindicato_id=sid, usuario=f"27{seccional_id:09d}",
                                nombre="Admin local", clave_hash=auth.hashear_clave("x"),
                                debe_cambiar_clave=False, es_admin_seccional=True,
                                seccional_id=seccional_id)
        s.add(u); s.commit(); s.refresh(u)
        return u.id


def _responden(eid: int, sid: int, cuils: list, valor=4, opciones=(0,)):
    """Contesta la encuesta con cada uno de esos CUIL (escala + ranking)."""
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in cuils:
        _sesion_trabajador(c, sid)
        r = cliente.post(f"/api/encuesta/{eid}",
                         json={"respuestas": {str(pids[0]): valor,
                                              str(pids[1]): [0, 1, 2]}})
        assert r.status_code == 200, r.text


def _padron_grande(sid: int, cantidad: int, seccional_id=None, provincia="Santa Fe") -> list:
    cuils = [f"20{sid:05d}{n:04d}" for n in range(cantidad)]
    _padron(sid, cuils, seccional_id=seccional_id, provincia=provincia)
    return cuils


def test_el_dashboard_agrega_en_sql_y_cuenta_gente_no_filas():
    """Una múltiple deja varias filas por persona: si la participación se
    contara con COUNT(*) de la urna, una encuesta de 3 personas informaría
    quince respuestas."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-agrega")
    cuils = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="nominal", cortes=(), desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils[:4])

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert d["indicadores"]["participacion"] == {"respondieron": 4, "padron": 6, "porcentaje": 66.7}
    assert d["respondentes"] == 4            # gente, no filas
    assert sum(x["cantidad"] for x in d["indicadores"]["ritmo"]) == 4

    escala = d["preguntas"][0]
    assert escala["tipo_dato"] == "escala" and escala["respondieron"] == 4
    assert escala["escala"]["promedio"] == 4.0
    assert [x["cantidad"] for x in escala["escala"]["distribucion"]] == [0, 0, 0, 4, 0]

    ranking = d["preguntas"][1]
    # Todos ordenaron igual, así que el promedio de posiciones es 1, 2 y 3.
    assert [x["promedio"] for x in ranking["ranking"]] == [1.0, 2.0, 3.0]
    assert ranking["ranking"][0]["primeras"] == 4
    assert ranking["respondieron"] == 4      # 12 filas / 3 opciones


def test_el_umbral_se_aplica_en_el_servidor_no_en_la_pantalla():
    """Tercer test de privacidad (N21.3): se pide el endpoint con un corte de
    3 respuestas y tiene que venir VACÍO del servidor. Que la pantalla lo
    esconda no protege nada -- el JSON se lee con el inspector."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-umbral")
    chica = _seccional(sid, "Rosario")
    grande = _seccional(sid, "Córdoba")
    pocos = _padron_grande(sid, 3, seccional_id=chica)
    muchos = [f"27{sid:05d}{n:04d}" for n in range(7)]
    _padron(sid, muchos, seccional_id=grande)

    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, pocos + muchos)

    _sesion(sid, uid)
    # El total general sí se ve: 10 respuestas.
    entero = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert entero["oculto"] is False and entero["respondentes"] == 10
    assert entero["umbral"] == {"minimo": 5, "aplica": True}

    # La seccional chica NO: tres respuestas no llegan al umbral.
    chico = cliente.get("/admin/encuesta/resultados",
                        params={"id": eid, "seccional": chica}).json()
    assert chico["oculto"] is True and chico["preguntas"] == []
    # Y ni un conteo se coló por otra vía del JSON.
    assert "4" not in json.dumps(chico["preguntas"])

    # La grande sí, porque llega.
    gordo = cliente.get("/admin/encuesta/resultados",
                        params={"id": eid, "seccional": grande}).json()
    assert gordo["oculto"] is False and gordo["respondentes"] == 7


def test_en_una_nominal_no_hay_umbral_que_esconda_nada():
    """El umbral protege el anonimato, así que en una nominal no rige: el
    admin puede ver respuesta por respuesta con nombre y apellido -- es lo
    que el afiliado aceptó y lo que el CSV nominal entrega (N20)."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-nominal")
    cuils = _padron_grande(sid, 2)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="nominal", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils)

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert d["umbral"] == {"minimo": 0, "aplica": False}
    assert d["oculto"] is False and d["respondentes"] == 2 and d["preguntas"]


def test_un_corte_que_la_encuesta_no_guarda_no_se_puede_filtrar():
    """La urna de una anónima sin corte de provincia no tiene ese dato:
    pedirlo por URL no lo inventa, y filtrar por él tampoco puede devolver
    un subconjunto que no existe."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-sin-corte")
    sec = _seccional(sid, "Centro")
    cuils = _padron_grande(sid, 6, seccional_id=sec, provincia="Santa Fe")
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils)

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados",
                    params={"id": eid, "provincia": "Santa Fe"}).json()
    assert "provincia" not in d["filtros"]["aplicados"]
    assert "provincia" not in d["filtros"]["disponibles"]
    assert d["respondentes"] == 6   # no recortó nada: el corte no existe


def test_la_seccional_ve_la_encuesta_central_recortada_a_su_gente():
    """N18. Y solo para MIRAR: editarla, publicarla, cerrarla o borrarla es
    de sede central, y lo frena el servidor aunque el POST venga a mano."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-n18")
    mia = _seccional(sid, "Rosario")
    otra = _seccional(sid, "Córdoba")
    mios = _padron_grande(sid, 6, seccional_id=mia)
    ajenos = [f"27{sid:05d}{n:04d}" for n in range(6)]
    _padron(sid, ajenos, seccional_id=otra)

    # La lanza sede central (super admin, sin seccional).
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, mios + ajenos)

    # Un admin de la seccional Rosario, con las dos secciones de Encuestas.
    uid_sec = _admin_de_seccional(sid, mia)
    _sesion(sid, uid_sec)

    lista = db.encuestas_del_sindicato(sid, alcance={mia})
    assert [e["id"] for e in lista] == [eid]
    assert lista[0]["propia"] is False      # la ve, no es suya

    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert d["filtros"]["fijos"] == ["seccional"]
    assert d["filtros"]["aplicados"]["seccional"] == [str(mia)]
    assert d["respondentes"] == 6           # los suyos, no los doce
    # Y pedir la otra seccional a mano no la saca de la suya.
    d2 = cliente.get("/admin/encuesta/resultados",
                     params={"id": eid, "seccional": otra}).json()
    assert d2["respondentes"] == 0 and d2["oculto"] is True

    # Tocarla, no.
    for ruta in ("/admin/encuesta/cerrar", "/admin/encuesta/borrar",
                 "/admin/encuesta/duplicar"):
        assert cliente.post(ruta, data={"id": eid}).status_code == 403, ruta
    assert cliente.post("/admin/encuesta/notificar",
                        data={"id": eid, "texto": "hola"}).status_code == 403


def test_el_afiliado_ve_los_totales_solo_si_cerro_y_el_admin_lo_tildo():
    """N12: un tilde por encuesta, y solo los totales GENERALES -- nunca los
    cortes, que es por donde se identifica gente."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-afiliado")
    cuils = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils)

    # Abierta todavía: no hay resultados para nadie de afuera.
    _sesion_trabajador(cuils[0], sid)
    assert cliente.get(f"/api/encuesta/{eid}/resultados").status_code == 404

    _sesion(sid, uid)
    cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    _sesion_trabajador(cuils[0], sid)
    d = cliente.get(f"/api/encuesta/{eid}/resultados").json()
    assert d["respondentes"] == 6
    # Totales y nada más: ni cortes, ni filtros, ni el padrón.
    crudo = json.dumps(d)
    assert "seccional" not in crudo and "filtros" not in crudo
    assert "cuil" not in crudo.lower() and cuils[0] not in crudo


def test_al_afiliado_no_le_llegan_ni_los_textos_libres():
    """Una respuesta escrita a mano puede identificar sola a quien la
    escribió. Se saca en el SERVIDOR: esconderla en el JS dejaría el dato
    en el JSON igual."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "dash-textos")
    cuils = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    preguntas = [{"etiqueta": "¿Algo para agregar?", "tipo_dato": "texto",
                  "ancho": "completo", "obligatorio": True}]
    _alta(modo="anonima", cortes=(), preguntas=preguntas,
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    pid = db.encuesta_por_id(eid)["preguntas"][0]["id"]
    for c in cuils:
        _sesion_trabajador(c, sid)
        assert cliente.post(f"/api/encuesta/{eid}",
                            json={"respuestas": {str(pid): f"soy {c} y digo esto"}}
                            ).status_code == 200

    # El admin sí los lee: es su encuesta y los pidió por escrito.
    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert len(d["preguntas"][0]["textos"]) == 6

    # El afiliado, no.
    cliente.post("/admin/encuesta/cerrar", data={"id": eid}, follow_redirects=False)
    _sesion_trabajador(cuils[0], sid)
    visto = cliente.get(f"/api/encuesta/{eid}/resultados").json()
    assert "textos" not in visto["preguntas"][0]
    assert "soy " not in json.dumps(visto)


def test_los_resultados_son_otra_seccion_que_armar_la_encuesta():
    """N17: un delegado puede leer el dashboard sin poder lanzar nada, y al
    revés. El gateo es el de siempre y falla cerrado."""
    assert main.PERMISOS_RUTAS["/admin/encuesta/resultados"] == "encuestas_resultados"
    assert main.PERMISOS_RUTAS["/admin/encuesta/{encuesta_id}/resultados"] \
        == "encuestas_resultados"
    assert main.PERMISOS_RUTAS["/admin/encuesta"] == "encuestas"


def test_una_encuesta_de_otro_sindicato_no_tiene_dashboard():
    sid_a, uid_a = _sindicato_con(["encuestas"], "dash-ajena-a")
    _sesion(sid_a, uid_a)
    _alta()
    eid = db.encuestas_del_sindicato(sid_a)[0]["id"]
    sid_b, uid_b = _sindicato_con(["encuestas"], "dash-ajena-b")
    _sesion(sid_b, uid_b)
    assert cliente.get("/admin/encuesta/resultados", params={"id": eid}).status_code == 404


def test_la_pantalla_del_dashboard_pide_su_seccion_y_el_modulo():
    """Es una PANTALLA, así que sin permiso redirige al panel en vez de
    tirar un JSON de error en pantalla completa -- mismo criterio que el
    Panel Sindical. El endpoint de datos sí responde 403."""
    sid, uid, eid = _encuesta_publicada("dash-pantalla")
    _sesion(sid, uid)
    r = cliente.get(f"/admin/encuesta/{eid}/resultados", follow_redirects=False)
    assert r.status_code == 200 and 'id="k-part"' in r.text

    # Un usuario de área sin la sección de resultados.
    uid_pelado = _usuario_sin_secciones(sid)
    _sesion(sid, uid_pelado)
    r = cliente.get(f"/admin/encuesta/{eid}/resultados", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert cliente.get("/admin/encuesta/resultados",
                       params={"id": eid}).status_code == 403


def _usuario_de_area(sid: int, secciones: list) -> int:
    """Un usuario de área con EXACTAMENTE esas secciones. Es como se prueba
    que las dos de Encuestas (N17) no son la misma cosa."""
    with db.get_session() as s:
        sec = db.Seccional(sindicato_id=sid, nombre="Delegación")
        s.add(sec); s.commit(); s.refresh(sec)
        area = db.Area(sindicato_id=sid, seccional_id=sec.id, nombre="Prensa")
        s.add(area); s.commit(); s.refresh(area)
        u = db.UsuarioSindicato(sindicato_id=sid, usuario=f"24{sid:09d}",
                                nombre="Delegado", clave_hash=auth.hashear_clave("x"),
                                debe_cambiar_clave=False, seccional_id=sec.id,
                                area_id=area.id)
        s.add(u); s.commit(); s.refresh(u)
        uid, area_id = u.id, area.id
    db.set_permisos_area(area_id, secciones, sid)
    return uid


def _usuario_sin_secciones(sid: int) -> int:
    """Un usuario de área sin área: permisos_efectivos() le da set()."""
    with db.get_session() as s:
        u = db.UsuarioSindicato(sindicato_id=sid, usuario=f"23{sid:09d}",
                                nombre="Sin secciones", clave_hash=auth.hashear_clave("x"),
                                debe_cambiar_clave=False)
        s.add(u); s.commit(); s.refresh(u)
        return u.id


def test_la_portada_del_admin_tiene_la_tarjeta_de_encuestas():
    """La pestaña de /admin no alcanza: el admin ATERRIZA en /admin/inicio.
    Una sección que solo se encuentra entrando a otra pantalla y buscando
    una pestaña es una sección que nadie usa."""
    sid, uid = _sindicato_con(["encuestas"], "portada-admin")
    _sesion(sid, uid)
    html = cliente.get("/admin/inicio").text
    assert 'href="/admin#encuestas"' in html and "#ic-encuestas" in html

    sid2, uid2 = _sindicato_con(["noticias"], "portada-admin-sin")
    _sesion(sid2, uid2)
    assert 'href="/admin#encuestas"' not in cliente.get("/admin/inicio").text


# ==================== Fase 5: exportar y evolución ====================
def _csv(eid: int, **params) -> str:
    r = cliente.get("/admin/encuesta/exportar", params={"id": eid, **params})
    assert r.status_code == 200, r.text
    return r.text


def _filas_csv(texto: str) -> list:
    """Parsea el CSV como lo haría una planilla: ; de separador, BOM afuera."""
    import csv as _csv_mod
    import io
    return list(_csv_mod.reader(io.StringIO(texto.lstrip("﻿")), delimiter=";"))


def test_el_csv_nominal_trae_una_fila_por_persona_con_nombre_y_cuil():
    """Es lo que el afiliado aceptó al responder una encuesta que dice
    "nominal" en la cara (N20). Va TODO el padrón, con la columna
    "Respondió": la lista de los que faltan es la mitad de para qué se baja
    este archivo."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "csv-nominal")
    cuils = _padron_grande(sid, 4)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="nominal", cortes=(), desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils[:3])

    _sesion(sid, uid)
    filas = _filas_csv(_csv(eid))
    assert filas[0][:6] == ["Nombre", "CUIL", "Seccional", "Provincia",
                            "CUIT empleador", "Respondió"]
    assert filas[0][6:] == ["¿Conforme con la obra social?", "Ordená los reclamos"]
    assert len(filas) == 5                      # cabecera + los 4 del padrón
    por_cuil = {f[1]: f for f in filas[1:]}
    assert set(por_cuil) == set(cuils)
    respondio = por_cuil[cuils[0]]
    assert respondio[5] == "Sí" and respondio[6] == "4"
    assert respondio[7] == "Salario > Obra social > Jornada"   # el ranking, en orden
    falta = por_cuil[cuils[3]]
    assert falta[5] == "No" and falta[6] == "" and falta[7] == ""


def test_el_csv_de_una_anonima_nunca_trae_filas_individuales():
    """Cuarto test de privacidad (N21.4). Si saliera crudo, cualquiera abre
    la planilla, filtra "Rosario + Empresa X" y se queda con dos filas que
    identifican a dos personas: el umbral que protege la pantalla no
    protegería nada."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "csv-anonima")
    cuils = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils)

    _sesion(sid, uid)
    texto = _csv(eid)
    # Ni un CUIL, ni un nombre, ni una columna que los pueda traer.
    for c in cuils:
        assert c not in texto
    assert "CUIL" not in texto and "Nombre" not in texto and "Respondió" not in texto
    filas = _filas_csv(texto)
    cabecera = next(f for f in filas if f and f[0] == "Pregunta")
    assert cabecera == ["Pregunta", "Tipo", "Opción", "Cantidad", "Porcentaje", "Promedio"]
    # Conteos: 6 respuestas con un 4 en la escala.
    escala = [f for f in filas if f and f[0] == "¿Conforme con la obra social?"]
    # 100, no "100,0": un entero sale sin decimales para que la columna se
    # lea de un vistazo.
    assert len(escala) == 5 and escala[3][3] == "6" and escala[3][4] == "100"
    # Y el archivo dice de qué grupo es: suelto, sin esa línea, no se puede
    # interpretar tres meses después.
    assert ["Grupo", "Todas las respuestas"] in filas


def test_pedir_el_csv_crudo_a_mano_no_cambia_nada():
    """Cambiarle los parámetros a la URL no convierte una anónima en
    nominal: el formato lo decide el MODO de la encuesta, en el servidor."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "csv-a-mano")
    cuils = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils)

    _sesion(sid, uid)
    for extra in ({"modo": "nominal"}, {"tipo": "nominal"}, {"crudo": "1"},
                  {"umbral": "0"}, {"formato": "detalle"}):
        r = cliente.get("/admin/encuesta/exportar", params={"id": eid, **extra})
        assert r.status_code == 200
        assert "CUIL" not in r.text
        for c in cuils:
            assert c not in r.text


def test_el_umbral_tambien_frena_la_descarga():
    """Si el umbral solo protegiera la pantalla, bastaría con bajar el
    archivo para saltearlo."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "csv-umbral")
    chica = _seccional(sid, "Rosario")
    grande = _seccional(sid, "Córdoba")
    pocos = _padron_grande(sid, 3, seccional_id=chica)
    muchos = [f"27{sid:05d}{n:04d}" for n in range(7)]
    _padron(sid, muchos, seccional_id=grande)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="anonima", cortes=("seccional",),
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, pocos + muchos)

    _sesion(sid, uid)
    r = cliente.get("/admin/encuesta/exportar", params={"id": eid, "seccional": chica})
    assert r.status_code == 400 and "E-ENCUESTA-02" in r.text
    assert cliente.get("/admin/encuesta/exportar",
                       params={"id": eid, "seccional": grande}).status_code == 200


def test_cada_descarga_queda_registrada_en_el_historial():
    """N20: quién, cuándo, qué encuesta y cuántas filas. Si algún día se
    filtra una planilla, el historial es lo único que permite saber de dónde
    salió."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "csv-registro")
    cuils = _padron_grande(sid, 4)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="nominal", cortes=(), desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=30)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    _sesion(sid, uid)
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid, sid, cuils)

    _sesion(sid, uid)
    assert not [v for v in db.eventos_de_encuesta(eid) if v["evento"] == "descarga"]
    _csv(eid)
    _csv(eid)
    descargas = [v for v in db.eventos_de_encuesta(eid) if v["evento"] == "descarga"]
    assert len(descargas) == 2
    assert "nominal" in descargas[0]["detalle"] and "4 filas" in descargas[0]["detalle"]
    assert descargas[0]["usuario"] == "Admin"       # quién, con nombre


def test_una_encuesta_sin_publicar_no_se_exporta():
    sid, uid = _sindicato_con(["encuestas"], "csv-borrador")
    _padron(sid)
    _sesion(sid, uid)
    _alta()
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    r = cliente.get("/admin/encuesta/exportar", params={"id": eid})
    assert r.status_code == 400 and "E-ENCUESTA-02" in r.text


def test_la_evolucion_compara_las_tomas_sucesivas_de_la_misma_encuesta():
    """N23: lo que convierte un dato suelto en una herramienta de gestión.
    Las preguntas se emparejan por orden y tipo, que es lo que `duplicar`
    preserva."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "evolucion")
    cuils = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    desde, hasta = (hoy - timedelta(days=1)).isoformat(), (hoy + timedelta(days=30)).isoformat()

    _alta(titulo="Clima", modo="nominal", cortes=(), desde=desde, hasta=hasta)
    primera = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar", data={"id": primera, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid=primera, sid=sid, cuils=cuils, valor=2)

    # Sola no se compara con nada.
    _sesion(sid, uid)
    assert cliente.get("/admin/encuesta/evolucion",
                       params={"id": primera}).json()["preguntas"] == []

    # Segunda toma: se duplica y se relanza.
    cliente.post("/admin/encuesta/duplicar", data={"id": primera}, follow_redirects=False)
    segunda = db.encuestas_del_sindicato(sid)[0]["id"]
    assert db.encuesta_por_id(segunda)["origen_id"] == primera
    _alta(titulo="Clima (2)", modo="nominal", cortes=(), desde=desde, hasta=hasta,
          extra={"id": segunda})
    cliente.post("/admin/encuesta/publicar", data={"id": segunda, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid=segunda, sid=sid, cuils=cuils, valor=5)

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/evolucion", params={"id": segunda}).json()
    assert [t["id"] for t in d["tomas"]] == [primera, segunda]
    escala = next(p for p in d["preguntas"] if p["tipo_dato"] == "escala")
    # El promedio subió de 2 a 5: eso es exactamente lo que se vino a ver.
    assert escala["lineas"][0]["valores"] == [2.0, 5.0]
    # Y se ve igual desde cualquiera de las dos tomas.
    assert cliente.get("/admin/encuesta/evolucion",
                       params={"id": primera}).json()["tomas"] == d["tomas"]


def test_una_toma_por_debajo_del_umbral_no_aporta_punto():
    """La comparación en el tiempo no puede ser la puerta de atrás del
    umbral: una toma chica no aporta un punto que identifique gente."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "evolucion-umbral")
    muchos = _padron_grande(sid, 6)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    desde, hasta = (hoy - timedelta(days=1)).isoformat(), (hoy + timedelta(days=30)).isoformat()

    _alta(titulo="Clima anónimo", modo="anonima", cortes=(), desde=desde, hasta=hasta)
    primera = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar", data={"id": primera, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid=primera, sid=sid, cuils=muchos, valor=3)

    _sesion(sid, uid)
    cliente.post("/admin/encuesta/duplicar", data={"id": primera}, follow_redirects=False)
    segunda = db.encuestas_del_sindicato(sid)[0]["id"]
    _alta(titulo="Clima anónimo (2)", modo="anonima", cortes=(), desde=desde, hasta=hasta,
          extra={"id": segunda})
    cliente.post("/admin/encuesta/publicar", data={"id": segunda, "criterio": "todos"},
                 follow_redirects=False)
    _responden(eid=segunda, sid=sid, cuils=muchos[:2], valor=5)   # solo 2: no llega

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/evolucion", params={"id": primera}).json()
    escala = next(p for p in d["preguntas"] if p["tipo_dato"] == "escala")
    assert escala["lineas"][0]["valores"] == [3.0, None]
    assert [t["oculto"] for t in d["tomas"]] == [False, True]


def test_la_tarjeta_del_afiliado_dice_cuanto_trabajo_es_y_cuanto_tiempo_queda():
    """Sin eso la tarjeta es una caja de texto y la encuesta se posterga --
    y postergada es no respondida. Los días los cuenta el SERVIDOR en hora
    de Buenos Aires: con el reloj del teléfono, uno mal puesto muestra un
    plazo que no existe."""
    sid, uid = _sindicato_con(["encuestas"], "tarjeta-datos")
    _padron(sid)
    cuil, _ = _cuils(sid)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    preguntas = PREGUNTAS + [
        {"etiqueta": "Datos de contexto", "tipo_dato": "separador", "ancho": "completo"},
        {"etiqueta": "¿Algo para agregar?", "tipo_dato": "texto", "ancho": "completo",
         "obligatorio": False},
    ]
    _alta(modo="anonima", preguntas=preguntas,
          desde=(hoy - timedelta(days=4)).isoformat(),
          hasta=(hoy + timedelta(days=6)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)

    _sesion_trabajador(cuil, sid)
    e = cliente.get("/api/encuestas").json()["encuestas"][0]
    # El separador es un título en el medio, no una pregunta: contarlo haría
    # que la tarjeta prometa más trabajo del que hay.
    assert e["preguntas_reales"] == 3 and len(e["preguntas"]) == 4
    assert e["minutos"] == 1                    # 3 × 20s, redondeado para arriba
    assert e["dias_restantes"] == 6
    assert e["avance"] == 40                    # 4 de 10 días del período

    # El último día todavía se puede responder: 0 no es "ya cerró".
    with db.get_session() as s:
        x = s.get(db.Encuesta, eid)
        x.fecha_hasta = hoy.isoformat()
        s.add(x); s.commit()
    e = cliente.get("/api/encuestas").json()["encuestas"][0]
    assert e["dias_restantes"] == 0 and e["estado"] == encuestas.ABIERTA


def test_el_minutaje_nunca_promete_menos_de_un_minuto():
    # Prometer de menos es peor que redondear para arriba: el afiliado
    # abandona a mitad de camino.
    assert encuestas.minutos_estimados([]) == 1
    assert encuestas.minutos_estimados([{"tipo_dato": "separador"}]) == 1
    assert encuestas.preguntas_reales([{"tipo_dato": "separador"}]) == 0
    assert encuestas.minutos_estimados([{"tipo_dato": "texto"}] * 3) == 1
    assert encuestas.minutos_estimados([{"tipo_dato": "texto"}] * 4) == 2
    assert encuestas.minutos_estimados([{"tipo_dato": "texto"}] * 9) == 3


def test_el_panel_arranca_en_la_lista_salvo_que_no_haya_ninguna():
    """Dos pastillas y no una pantalla sola: el constructor es largo y dejaba
    la lista tan abajo que parecía otra sección. Arranca en lo que se mira
    todos los días -- salvo cuando todavía no hay nada que mirar."""
    sid, uid = _sindicato_con(["encuestas"], "pastillas")
    _sesion(sid, uid)
    html = cliente.get("/admin").text
    # Sin encuestas, la abierta es la de crear: es lo único que se puede hacer.
    assert '<div class="enc-subpanel activo" id="enc-sub-nueva">' in html
    assert '<div class="enc-subpanel " id="enc-sub-lista">' in html

    _alta()
    html = cliente.get("/admin").text
    assert '<div class="enc-subpanel activo" id="enc-sub-lista">' in html
    assert '<div class="enc-subpanel " id="enc-sub-nueva">' in html
    assert "Ver / editar encuestas (1)" in html

    # A quien solo puede LEER no se le promete editar.
    uid_lector = _usuario_de_area(sid, ["encuestas_resultados"])
    _sesion(sid, uid_lector)
    html = cliente.get("/admin").text
    assert "Ver encuestas (1)" in html and "Ver / editar" not in html
    assert 'data-enc-sub="nueva"' not in html and 'id="enc-sub-nueva"' not in html


# ==================== Filtros y cruce (pedido de Sd 2026-09-12) ==========
def _encuesta_con_datos(slug: str, modo="anonima", cortes=("seccional", "empleador"),
                        preguntas=None, cantidad=24):
    """Una encuesta publicada con gente repartida en dos seccionales y dos
    empleadores, y respuestas cargadas. Devuelve (sid, uid, eid, secs)."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], slug)
    sec_a, sec_b = _seccional(sid, "Norte"), _seccional(sid, "Sur")
    grupo_a = [f"20{sid:05d}{n:04d}" for n in range(cantidad // 2)]
    grupo_b = [f"27{sid:05d}{n:04d}" for n in range(cantidad // 2)]
    with db.get_session() as s:
        for n, c in enumerate(grupo_a):
            s.add(db.Trabajador(sindicato_id=sid, cuil=c, nombre=f"A{n}", activo=True,
                                registrado=True, seccional_id=sec_a, provincia="Santa Fe",
                                cuit_empleador="30111111111"))
        for n, c in enumerate(grupo_b):
            s.add(db.Trabajador(sindicato_id=sid, cuil=c, nombre=f"B{n}", activo=True,
                                registrado=True, seccional_id=sec_b, provincia="Santa Fe",
                                cuit_empleador="30222222222"))
        s.commit()
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo=modo, cortes=cortes, preguntas=preguntas,
          desde=(hoy - timedelta(days=4)).isoformat(),
          hasta=(hoy + timedelta(days=10)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    return sid, uid, eid, {"norte": sec_a, "sur": sec_b}, grupo_a, grupo_b


PREG_CRUCE = [
    {"etiqueta": "¿Cómo está el ambiente?", "tipo_dato": "seleccion",
     "opciones": "Óptimo, Algo tenso, Nocivo", "ancho": "completo", "obligatorio": True},
    {"etiqueta": "¿Te representa el delegado?", "tipo_dato": "booleano",
     "ancho": "completo", "obligatorio": True},
]


def test_las_pastillas_cuentan_gente_y_no_filas_de_la_urna():
    """Una encuesta de varias preguntas deja varias filas por persona: la
    pastilla decía 125 donde hay 15 personas. Un número al lado de un filtro
    que no es el que después aparece en pantalla es peor que no tenerlo."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("chips", preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 1, str(pids[1]): "si"}})
    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    por_seccional = d["filtros"]["disponibles"]["seccional"]
    assert sum(v["cantidad"] for v in por_seccional) == d["respondentes"] == 24
    assert sorted(v["cantidad"] for v in por_seccional) == [12, 12]


def test_las_pastillas_del_resto_de_los_cortes_se_recalculan_con_el_filtro():
    """Asociativo (como Qlik): elegir un empleador que deja 10 casos y que
    las seccionales sigan mostrando el total es un número que miente. Con
    el filtro puesto, "3 de 12" quiere decir que 3 de esos 10 son del Norte.

    Y el corte ELEGIDO no se filtra a sí mismo: si lo hiciera, quedaría una
    sola pastilla y no habría con qué cambiar de opinión.
    """
    sid, uid, eid, secs, a, b = _encuesta_con_datos("asoc", preguntas=PREG_CRUCE)
    # Un empleador que cruza las dos seccionales: 3 del Norte y 7 del Sur.
    # Con el reparto de origen (una seccional por empleador) el cruce sería
    # 12 y 0, que no distingue un filtro asociativo de uno roto.
    with db.get_session() as s:
        for c in a[:3] + b[:7]:
            t = s.exec(db.select(db.Trabajador).where(
                db.Trabajador.sindicato_id == sid, db.Trabajador.cuil == c)).first()
            t.cuit_empleador = "30333333333"
            s.add(t)
        s.commit()
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 1, str(pids[1]): "si"}})

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    sin = {v["etiqueta"]: (v["cantidad"], v["total"])
           for v in d["filtros"]["disponibles"]["seccional"]}
    assert sin == {"Norte": (12, 12), "Sur": (12, 12)}

    d = cliente.get("/admin/encuesta/resultados",
                    params={"id": eid, "empleador": "30333333333"}).json()
    assert d["respondentes"] == 10
    con = {v["etiqueta"]: (v["cantidad"], v["total"])
           for v in d["filtros"]["disponibles"]["seccional"]}
    assert con == {"Norte": (3, 12), "Sur": (7, 12)}
    # El propio corte NO se recorta a sí mismo: las tres opciones siguen
    # ahí con su número entero, que es lo que permite cambiar de empleador
    # sin tener que limpiar el filtro primero.
    emp = {v["cantidad"] for v in d["filtros"]["disponibles"]["empleador"]}
    assert emp == {9, 5, 10}


def test_una_pastilla_sin_nadie_dentro_del_filtro_queda_en_cero_y_no_desaparece():
    """"Córdoba 0" es un dato: dice que ahí hay a quién preguntarle y que
    ninguno cayó dentro del recorte. Sacarla de la lista haría creer que esa
    seccional no existe, y además movería las pastillas de lugar en cada
    clic."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cero", preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 1, str(pids[1]): "si"}})
    _sesion(sid, uid)
    # El reparto de origen es una seccional por empleador: filtrando por el
    # del Norte, el Sur tiene que quedar visible y en cero.
    d = cliente.get("/admin/encuesta/resultados",
                    params={"id": eid, "empleador": "30222222222"}).json()
    por_seccional = {v["etiqueta"]: (v["cantidad"], v["total"])
                     for v in d["filtros"]["disponibles"]["seccional"]}
    assert por_seccional == {"Norte": (0, 12), "Sur": (12, 12)}


def test_el_alcance_de_seccional_no_se_filtra_a_si_mismo_pero_tampoco_se_abre():
    """N18: al corte IMPUESTO sí se le aplica su propio filtro. Si se lo
    exceptuara como a los demás, quien tiene alcance de una seccional
    leería de refilón cuánta gente respondió en las otras."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("n18asoc", preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 1, str(pids[1]): "si"}})
    _sesion(sid, _admin_de_seccional(sid, secs["norte"]))
    d = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert d["respondentes"] == 12
    por_seccional = d["filtros"]["disponibles"]["seccional"]
    assert [v["etiqueta"] for v in por_seccional] == ["Norte"]
    assert por_seccional[0] == {"valor": str(secs["norte"]), "etiqueta": "Norte",
                                "cantidad": 12, "total": 12}
    # Y el resto de los cortes se cuenta DENTRO de su alcance, no en total.
    emp = {v["cantidad"] for v in d["filtros"]["disponibles"]["empleador"]}
    assert emp == {12}


def test_el_filtro_de_fechas_recorta_la_urna_y_no_el_padron():
    """El día lo guarda la urna; el padrón NO sabe cuándo respondió cada uno
    (punto 3 del anonimato). Así que el rango mueve los gráficos y el ritmo,
    y deja quieta la participación."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("fechas", preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 0, str(pids[1]): "si"}})
    # La mitad se corre a anteayer, a mano: responder pone el día de hoy.
    ayer = (fechas.hoy() - timedelta(days=2)).isoformat()
    with db.get_session() as s:
        filas = s.exec(db.select(db.RespuestaEncuesta).where(
            db.RespuestaEncuesta.encuesta_id == eid).order_by(db.RespuestaEncuesta.id)).all()
        for f in filas[:len(filas) // 2]:
            f.dia = ayer
            s.add(f)
        s.commit()

    _sesion(sid, uid)
    entero = cliente.get("/admin/encuesta/resultados", params={"id": eid}).json()
    assert entero["respondentes"] == 24 and len(entero["indicadores"]["ritmo"]) == 2

    recorte = cliente.get("/admin/encuesta/resultados",
                          params={"id": eid, "desde": ayer, "hasta": ayer}).json()
    assert recorte["respondentes"] < 24
    assert [x["dia"] for x in recorte["indicadores"]["ritmo"]] == [ayer]
    # El padrón no se toca: no sabe de fechas.
    assert recorte["indicadores"]["participacion"] == entero["indicadores"]["participacion"]
    assert recorte["filtros"]["dias"] == [ayer, ayer]

    # Un rango inventado por la URL no devuelve un recorte al azar.
    roto = cliente.get("/admin/encuesta/resultados",
                       params={"id": eid, "desde": "ayer nomás"}).json()
    assert roto["filtros"]["dias"] == [] and roto["respondentes"] == 24


def test_varias_pastillas_a_la_vez_suman_los_grupos():
    sid, uid, eid, secs, a, b = _encuesta_con_datos("multi", preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 0, str(pids[1]): "no"}})
    _sesion(sid, uid)
    una = cliente.get("/admin/encuesta/resultados",
                      params={"id": eid, "seccional": secs["norte"]}).json()
    dos = cliente.get("/admin/encuesta/resultados",
                      params={"id": eid, "seccional": [secs["norte"], secs["sur"]]}).json()
    assert una["respondentes"] == 12 and dos["respondentes"] == 24
    assert sorted(dos["filtros"]["aplicados"]["seccional"]) == sorted(
        [str(secs["norte"]), str(secs["sur"])])


def test_el_cruce_dice_donde_se_concentra_una_respuesta():
    """Es la pregunta que un sindicato hace de verdad: "el 30% dice que el
    ambiente está tenso... ¿tenso DÓNDE?"."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cruce", modo="nominal",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    # Norte: 10 de 12 dicen "Algo tenso". Sur: 2 de 12.
    for n, c in enumerate(a):
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {
            str(pids[0]): 1 if n < 10 else 0, str(pids[1]): "no"}})
    for n, c in enumerate(b):
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {
            str(pids[0]): 1 if n < 2 else 0, str(pids[1]): "si"}})

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/cruce",
                    params={"id": eid, "pregunta": pids[0], "opcion": 1}).json()
    assert d["opcion"] == "Algo tenso"
    assert d["elegidos"] == 12 and d["total"] == 24 and d["porcentaje"] == 50.0

    filas = {f["etiqueta"]: f for f in d["cortes"]["seccional"]["filas"]}
    assert filas["Norte"]["dentro"] == 83.3 and filas["Norte"]["diferencia"] == 33.3
    assert filas["Sur"]["dentro"] == 16.7 and filas["Sur"]["diferencia"] == -33.3
    # Ordenado por concentración: lo que se vino a ver va primero.
    assert d["cortes"]["seccional"]["filas"][0]["etiqueta"] == "Norte"
    # Y el empleador también, que es el ejemplo que motivó esto.
    assert d["cortes"]["empleador"]["filas"][0]["cantidad"] == 10


def test_en_una_nominal_el_cruce_llega_hasta_las_otras_preguntas():
    """Saber que dos respuestas son de la misma persona solo se puede en una
    nominal -- y ahí el afiliado respondió sabiéndolo."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cruce-nominal", modo="nominal",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for n, c in enumerate(a + b):
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {
            str(pids[0]): 1 if n < 12 else 0,
            # Los que dicen "algo tenso" NO se sienten representados.
            str(pids[1]): "no" if n < 12 else "si"}})
    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/cruce",
                    params={"id": eid, "pregunta": pids[0], "opcion": 1}).json()
    assert d["puede_cruzar_preguntas"] is True
    otra = next(p for p in d["preguntas"] if p["id"] == pids[1])
    assert otra["personas"] == 12
    no = next(o for o in otra["opciones"] if o["texto"] == "No")
    assert no["cantidad"] == 12 and no["porcentaje"] == 100.0


def test_en_una_anonima_el_cruce_llega_a_los_cortes_y_no_a_las_preguntas():
    """No es una limitación técnica que haya que disculpar: es la garantía.
    Los cortes viajan pegados a cada respuesta; el vínculo entre dos
    respuestas de la misma persona, no."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cruce-anonima", modo="anonima",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 1, str(pids[1]): "no"}})
    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/cruce",
                    params={"id": eid, "pregunta": pids[0], "opcion": 1}).json()
    assert d["puede_cruzar_preguntas"] is False and d["preguntas"] == []
    assert d["cortes"]["seccional"]["filas"], "los cortes SÍ se pueden cruzar"
    # Y ni un CUIL se coló por esta puerta nueva.
    assert not _tiene(d, a[0])


def test_el_umbral_tambien_frena_el_cruce():
    """Si el umbral protegiera la pantalla pero no el cruce, bastaría con
    tocar una barra para saltearlo."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cruce-umbral", modo="anonima",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for n, c in enumerate(a + b):
        _sesion_trabajador(c, sid)
        # Solo 3 eligen "Nocivo": por debajo del umbral de 5.
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 2 if n < 3 else 0,
                                          str(pids[1]): "si"}})
    _sesion(sid, uid)
    chico = cliente.get("/admin/encuesta/cruce",
                        params={"id": eid, "pregunta": pids[0], "opcion": 2}).json()
    assert chico["oculto"] is True and chico["cortes"] == {} and chico["preguntas"] == []
    grande = cliente.get("/admin/encuesta/cruce",
                         params={"id": eid, "pregunta": pids[0], "opcion": 0}).json()
    assert grande["oculto"] is False and grande["cortes"]["seccional"]["filas"]


def test_una_opcion_inventada_en_la_url_no_devuelve_un_recorte_al_azar():
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cruce-roto", modo="nominal",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    _sesion_trabajador(a[0], sid)
    cliente.post(f"/api/encuesta/{eid}",
                 json={"respuestas": {str(pids[0]): 0, str(pids[1]): "si"}})
    _sesion(sid, uid)
    for params in ({"pregunta": pids[0], "opcion": 99}, {"pregunta": pids[0], "opcion": "-1"},
                   {"pregunta": pids[0], "opcion": "toda"}, {"pregunta": 999999, "opcion": 0}):
        r = cliente.get("/admin/encuesta/cruce", params={"id": eid, **params})
        assert r.status_code == 404, params


def test_el_cruce_respeta_el_recorte_por_seccional():
    """N18: si el cruce ignorara el alcance, una seccional vería por esa
    puerta lo que el dashboard le recorta por la de adelante."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("cruce-n18", modo="nominal",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 0, str(pids[1]): "si"}})
    _sesion(sid, uid)
    entero = cliente.get("/admin/encuesta/cruce",
                         params={"id": eid, "pregunta": pids[0], "opcion": 0}).json()
    assert entero["elegidos"] == 24

    uid_sec = _admin_de_seccional(sid, secs["norte"])
    _sesion(sid, uid_sec)
    suyo = cliente.get("/admin/encuesta/cruce",
                       params={"id": eid, "pregunta": pids[0], "opcion": 0}).json()
    assert suyo["elegidos"] == 12
    assert [f["etiqueta"] for f in suyo["cortes"]["seccional"]["filas"]] == ["Norte"]


def test_el_csv_dice_lo_mismo_que_la_pantalla_con_un_rango_de_fechas():
    """Si el archivo trae 66 personas donde el gráfico muestra 19, uno de
    los dos miente y no se sabe cuál."""
    sid, uid, eid, secs, a, b = _encuesta_con_datos("csv-fechas", modo="nominal",
                                                    preguntas=PREG_CRUCE)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for c in a + b:
        _sesion_trabajador(c, sid)
        cliente.post(f"/api/encuesta/{eid}",
                     json={"respuestas": {str(pids[0]): 0, str(pids[1]): "si"}})
    # La mitad se corre a anteayer -- TODAS las filas de esa persona, que es
    # lo que pasa de verdad: alguien responde una sola vez.
    ayer = (fechas.hoy() - timedelta(days=2)).isoformat()
    mitad = set(a)
    with db.get_session() as s:
        nominales = {n.respuesta_id: n.cuil for n in s.exec(db.select(db.RespuestaNominal)
                     .where(db.RespuestaNominal.encuesta_id == eid)).all()}
        for f in s.exec(db.select(db.RespuestaEncuesta).where(
                db.RespuestaEncuesta.encuesta_id == eid)).all():
            if nominales.get(f.id) in mitad:
                f.dia = ayer
                s.add(f)
        s.commit()

    _sesion(sid, uid)
    pantalla = cliente.get("/admin/encuesta/resultados",
                           params={"id": eid, "desde": ayer, "hasta": ayer}).json()
    archivo = cliente.get("/admin/encuesta/exportar",
                          params={"id": eid, "desde": ayer, "hasta": ayer}).text
    filas = [l for l in archivo.lstrip("﻿").splitlines()[1:] if l.strip()]
    assert pantalla["respondentes"] == len(filas) == len(mitad)
    # Y no se cuela nadie del otro día.
    for cuil in b:
        assert cuil not in archivo


def test_un_grupo_de_una_persona_no_se_lee_como_una_tendencia():
    """"El 100% de este empleador" con una sola persona encabezaba la lista
    como si fuera un hallazgo. El porcentaje es real; leerlo como tendencia
    manda al sindicato a mirar donde no hay nada."""
    sid, uid = _sindicato_con(["encuestas", "notificaciones"], "cruce-chicos")
    grande, chica = _seccional(sid, "Grande"), _seccional(sid, "Chica")
    muchos = [f"20{sid:05d}{n:04d}" for n in range(12)]
    uno = [f"27{sid:05d}0001"]
    _padron(sid, muchos, seccional_id=grande)
    _padron(sid, uno, seccional_id=chica)
    _sesion(sid, uid)
    hoy = fechas.hoy()
    _alta(modo="nominal", cortes=("seccional",), preguntas=PREG_CRUCE,
          desde=(hoy - timedelta(days=1)).isoformat(),
          hasta=(hoy + timedelta(days=10)).isoformat())
    eid = db.encuestas_del_sindicato(sid)[0]["id"]
    cliente.post("/admin/encuesta/publicar", data={"id": eid, "criterio": "todos"},
                 follow_redirects=False)
    pids = [p["id"] for p in db.encuesta_por_id(eid)["preguntas"]]
    for n, c in enumerate(muchos + uno):
        _sesion_trabajador(c, sid)
        # El único de la seccional chica elige la opción 1; de los doce, 3.
        cliente.post(f"/api/encuesta/{eid}", json={"respuestas": {
            str(pids[0]): 1 if (c in uno or n < 3) else 0, str(pids[1]): "si"}})

    _sesion(sid, uid)
    d = cliente.get("/admin/encuesta/cruce",
                    params={"id": eid, "pregunta": pids[0], "opcion": 1}).json()
    filas = d["cortes"]["seccional"]["filas"]
    por_nombre = {f["etiqueta"]: f for f in filas}
    assert por_nombre["Chica"]["dentro"] == 100.0 and por_nombre["Chica"]["poco"] is True
    assert por_nombre["Grande"]["poco"] is False
    # Y va ÚLTIMA, aunque su porcentaje sea el más alto.
    assert filas[-1]["etiqueta"] == "Chica"
    assert d["cortes"]["seccional"]["minimo_para_comparar"] == 5

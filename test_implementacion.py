"""Mesa de implementación: el motor puro (PLAN_IMPLEMENTACION.md).

Correr con: python -m pytest test_implementacion.py -q
"""
import pytest

import implementacion as im


def test_seis_tipos_con_color_e_icono_fijos():
    assert set(im.TIPOS) == {"pedido", "consulta", "entrega", "aprobacion", "error", "aviso"}
    assert tuple(im.ORDEN_TIPOS) == tuple(im.TIPOS) or set(im.ORDEN_TIPOS) == set(im.TIPOS)
    colores = [t["color"] for t in im.TIPOS.values()]
    assert len(set(colores)) == 6 and all(c.startswith("#") and len(c) == 7 for c in colores)
    assert all(t["icono"] and t["nombre"] and t["cierra"] for t in im.TIPOS.values())


def test_flujo_unico_y_reabrir():
    assert im.puede_transicionar("pedido", "abierta", "en_curso")
    assert im.puede_transicionar("pedido", "en_curso", "respondida")
    assert im.puede_transicionar("pedido", "respondida", "cerrada")
    assert im.puede_transicionar("pedido", "cerrada", "abierta")        # reabrir
    assert not im.puede_transicionar("pedido", "cerrada", "respondida")
    assert not im.puede_transicionar("pedido", "abierta", "abierta")
    assert not im.puede_transicionar("pedido", "abierta", "aprobada")   # solo resolviendo
    assert not im.puede_transicionar("pedido", "abierta", "inventado")
    assert not im.puede_transicionar("inventado", "abierta", "cerrada")


def test_aviso_nace_cerrado_y_no_se_mueve():
    assert im.estado_inicial("aviso") == "cerrada"
    assert all(im.estado_inicial(t) == "abierta" for t in im.TIPOS if t != "aviso")
    assert not im.puede_transicionar("aviso", "cerrada", "abierta")
    assert im.lado_inicial("aviso", "equipo") == ""


def test_aprobacion_no_se_cierra_y_es_inmutable_al_resolver():
    assert not im.puede_transicionar("aprobacion", "respondida", "cerrada")
    assert im.es_inmutable("aprobacion", "aprobada") and im.es_inmutable("aprobacion", "rechazada")
    assert not im.es_inmutable("aprobacion", "abierta")
    assert not im.es_inmutable("pedido", "cerrada")
    for e in ("aprobada", "rechazada"):
        assert all(not im.puede_transicionar("aprobacion", e, h) for h in im.ESTADOS)


def test_a_quien_le_toca():
    assert im.lado_inicial("pedido", "equipo") == "sindicato"
    assert im.lado_inicial("error", "sindicato") == "equipo"
    assert im.a_quien_le_toca("respondida", "equipo") == "sindicato"
    assert im.a_quien_le_toca("abierta", "sindicato") == "equipo"
    assert im.a_quien_le_toca("en_curso", "equipo") == "equipo"       # lo está trabajando
    for e in ("cerrada", "aprobada", "rechazada"):
        assert im.a_quien_le_toca(e, "equipo") == ""
    assert im.texto_espera("sindicato") == "espera al sindicato"
    assert im.texto_espera("equipo") == "espera a Colm3na"
    assert im.texto_espera("") == ""


def test_solo_resuelve_la_aprobacion_el_lado_que_no_la_pidio():
    """Una sola regla (QA-01/QA-02): el tercer argumento es el AUTOR; resuelve el otro lado,
    en cualquier estado abierto y sin importar a quién le toque el turno."""
    for estado in ("abierta", "en_curso", "respondida"):
        assert im.puede_resolver_aprobacion("aprobacion", estado, "equipo", "sindicato")
        assert im.puede_resolver_aprobacion("aprobacion", estado, "sindicato", "equipo")
        assert not im.puede_resolver_aprobacion("aprobacion", estado, "sindicato", "sindicato")
        assert not im.puede_resolver_aprobacion("aprobacion", estado, "equipo", "equipo")
    assert not im.puede_resolver_aprobacion("aprobacion", "aprobada", "equipo", "sindicato")
    assert not im.puede_resolver_aprobacion("aprobacion", "abierta", "", "sindicato")       # sin autor: nadie
    assert not im.puede_resolver_aprobacion("pedido", "abierta", "equipo", "sindicato")


def test_validar_tarjeta_nueva():
    ok = im.validar_tarjeta_nueva("pedido", "  Padrón  ", " Mandamos el padrón ", "2026-12-01")
    assert ok["ok"] and ok["datos"]["titulo"] == "Padrón" and ok["datos"]["texto"] == "Mandamos el padrón"
    assert set(im.validar_tarjeta_nueva("", "", "")["errores"]) == {"tipo", "titulo", "texto"}
    assert "titulo" in im.validar_tarjeta_nueva("pedido", "x" * 141, "t")["errores"]
    assert "texto" in im.validar_tarjeta_nueva("pedido", "t", "x" * 5001)["errores"]
    assert "fecha_limite" in im.validar_tarjeta_nueva("pedido", "t", "t", "30/02/2026")["errores"]
    assert im.validar_tarjeta_nueva("pedido", "t", "t", "")["ok"]


def test_vencida_usa_la_fecha_de_buenos_aires():
    assert im.vencida("2026-01-01", "abierta", hoy="2026-01-02")
    assert not im.vencida("2026-01-02", "abierta", hoy="2026-01-02")
    assert not im.vencida("2026-01-01", "cerrada", hoy="2026-01-02")
    assert not im.vencida("", "abierta", hoy="2026-01-02")


def test_tope_de_archivo_20_mb():
    assert im.TOPE_ARCHIVO == 20 * 1024 * 1024
    assert im.validar_archivo("a.pdf", 1) == ""
    assert im.validar_archivo("a.pdf", im.TOPE_ARCHIVO) == ""
    assert im.validar_archivo("a.pdf", im.TOPE_ARCHIVO + 1)
    assert im.validar_archivo("a.pdf", 0)
    assert im.validar_archivo("  ", 10)


def test_nombre_seguro():
    assert im.nombre_seguro("../../etc/passwd") == "passwd"
    assert im.nombre_seguro("C:\\x\\padron.xlsx") == "padron.xlsx"
    assert im.nombre_seguro("") == "archivo"
    assert len(im.nombre_seguro("a" * 500)) == im.TOPE_NOMBRE_ARCHIVO


def test_quien_baja_un_archivo_con_datos_personales():
    # sin datos personales: cualquiera del proyecto
    assert im.puede_bajar_archivo("sindicato", 2, False, "equipo", 1)
    # con datos personales: el equipo y quien lo subió
    assert im.puede_bajar_archivo("equipo", 9, True, "sindicato", 2)
    assert im.puede_bajar_archivo("sindicato", 2, True, "sindicato", 2)
    assert not im.puede_bajar_archivo("sindicato", 3, True, "sindicato", 2)    # otro del sindicato
    assert not im.puede_bajar_archivo("sindicato", 1, True, "equipo", 1)       # mismo id, otro lado
    assert not im.puede_bajar_archivo("equipo", 1, False, "equipo", 1, borrado=True)
    assert not im.puede_bajar_archivo("otro", 1, False, "equipo", 1)


def test_quien_borra_un_archivo():
    assert im.puede_borrar_archivo("equipo", 9, "sindicato", 2)
    assert im.puede_borrar_archivo("sindicato", 2, "sindicato", 2)
    assert not im.puede_borrar_archivo("sindicato", 3, "sindicato", 2)
    assert not im.puede_borrar_archivo("sindicato", 1, "equipo", 1)


def test_notas_internas_solo_equipo():
    assert im.puede_ver_nota_interna("equipo") and im.puede_escribir_nota_interna("equipo")
    assert not im.puede_ver_nota_interna("sindicato") and not im.puede_escribir_nota_interna("sindicato")
    assert not im.puede_ver_nota_interna("")


def test_seis_fases_por_defecto():
    nombres = [n for n, _ in im.FASES_POR_DEFECTO]
    assert nombres == ["Preparar", "Acordar", "Relevar", "Configurar", "Piloto", "Implementación total"]


def test_porcentaje():
    assert im.porcentaje(0, 0) == 0 and im.porcentaje(1, 3) == 33 and im.porcentaje(3, 3) == 100


def test_csv_de_aprobaciones_neutraliza_formulas():
    csv_ = im.aprobaciones_csv([{"numero": 1, "titulo": "=HYPERLINK(1)", "estado": "aprobada",
                                 "autor": "Ana", "resuelta_por": "Luis", "resuelta_en": "2026-11-14 10:00:00",
                                 "etapa": "Acordar"}])
    assert csv_.startswith("\ufeff")
    assert "'=HYPERLINK(1)" in csv_ and "Aprobada" in csv_ and "Número;Título" in csv_


def test_no_llama_a_datetime_now():
    # La regla del proyecto (test_fechas.py la verifica en general): acá, a mano.
    import ast, pathlib
    arbol = ast.parse(pathlib.Path(im.__file__).read_text(encoding="utf-8"))
    for n in ast.walk(arbol):
        if isinstance(n, ast.Attribute) and n.attr in ("now", "today", "utcnow"):
            pytest.fail("implementacion.py no puede usar now()/today(): usar fechas.py")


def test_error_impl_lleva_codigo_y_mensaje():
    e = im.ErrorImpl("x", "algo")
    assert e.codigo == "x" and e.mensaje == "algo" and str(e) == "algo"


def test_i16_acciones_de_una_entrega_recibido_y_problema_son_del_lado_que_no_la_creo():
    for estado in ("abierta", "en_curso", "respondida"):
        recibe = im.acciones_de("entrega", estado, "equipo", "sindicato", autor_lado="equipo")
        manda = im.acciones_de("entrega", estado, "equipo", "equipo", autor_lado="equipo")
        assert recibe["recibido"] is recibe["problema"] is True
        assert manda["recibido"] is manda["problema"] is False
        assert manda["responder"] and manda["subir"]               # quien la mandó sigue respondiendo y adjuntando
        assert "cerrada" not in [e["id"] for e in recibe["estados"] + manda["estados"]]
    cerrada = im.acciones_de("entrega", "cerrada", "", "sindicato", autor_lado="equipo")
    assert cerrada["recibido"] is cerrada["problema"] is False and cerrada["reabrir"] is True
    assert im.acciones_de("entrega", "abierta", "equipo", "sindicato", autor_lado="")["recibido"] is False   # sin autor, nadie
    for tipo in ("pedido", "consulta", "aprobacion", "error", "aviso"):
        ac = im.acciones_de(tipo, "abierta", "equipo", "sindicato", autor_lado="equipo")
        assert ac["recibido"] is False and ac["problema"] is False
    assert im.puede_transicionar("entrega", "respondida", "cerrada") is False
    assert im.puede_transicionar("pedido", "respondida", "cerrada") is True

"""Motor de XSK (`xsk/motor/registro.py`): lectura del registro, riesgo y
ranking. Puro, sin base. Además verifica que las plantillas y los archivos
reales del proyecto `mitrabajo` sean legibles por el motor: un registro que
el motor no puede leer no es un registro."""

from pathlib import Path

import pytest

from xsk.motor import registro as r

RAIZ = Path(__file__).resolve().parent
PROYECTO = RAIZ / "xsk" / "proyectos" / "mitrabajo"


def _hallazgo(**cambios):
    base = {
        "archivo": "H-0001.md", "id": "H-0001", "titulo": "t", "eje": "IDS",
        "test": "IDS-01", "estado": "abierto", "probabilidad": "3", "dano": "4",
        "complejidad": "2", "owasp": "A07", "asvs": "V2", "cwe": "CWE-1",
        "encontrado": "2026-09-20", "corrida": "2026-09-20-1000-IDS",
    }
    base.update(cambios)
    return base


# --- Cabecera -----------------------------------------------------------------

def test_leer_cabecera_separa_claves_y_cuerpo():
    cab, cuerpo = r.leer_cabecera("---\nid: H-0001\n# comentario\ntitulo: Algo: con dos puntos\n---\n\n## Cuerpo\n")
    assert cab == {"id": "H-0001", "titulo": "Algo: con dos puntos"}
    assert cuerpo.strip() == "## Cuerpo"


def test_leer_cabecera_acepta_crlf():
    cab, _ = r.leer_cabecera("---\r\nid: X\r\n---\r\ncuerpo")
    assert cab == {"id": "X"}


@pytest.mark.parametrize("texto", ["sin cabecera", "---\nid: X\n", "---\nlinea sin dos puntos\n---\n"])
def test_leer_cabecera_falla_con_mensaje(texto):
    with pytest.raises(r.ErrorRegistro):
        r.leer_cabecera(texto)


# --- Hallazgos ----------------------------------------------------------------

def test_validar_hallazgo_convierte_numeros():
    h = r.validar_hallazgo(_hallazgo())
    assert (h["probabilidad"], h["dano"], h["complejidad"]) == (3, 4, 2)


def test_validar_hallazgo_nombra_la_clave_que_falta():
    with pytest.raises(r.ErrorRegistro, match="faltan las claves cwe"):
        r.validar_hallazgo(_hallazgo(cwe=""))


@pytest.mark.parametrize("cambio", [
    {"id": "H-1"}, {"eje": "XXX"}, {"test": "ids-1"}, {"estado": "cerrado"},
    {"probabilidad": "6"}, {"dano": "0"}, {"complejidad": "alta"},
])
def test_validar_hallazgo_rechaza_valores_invalidos(cambio):
    with pytest.raises(r.ErrorRegistro):
        r.validar_hallazgo(_hallazgo(**cambio))


def test_aceptado_exige_motivo_y_firma():
    with pytest.raises(r.ErrorRegistro, match="aceptado_por"):
        r.validar_hallazgo(_hallazgo(estado="aceptado"))
    r.validar_hallazgo(_hallazgo(estado="aceptado", aceptado_por="SDN",
                                 aceptado_hasta="2027-01-01", motivo="x"))


@pytest.mark.parametrize("valor,esperado", [
    (1, "bajo"), (4, "bajo"), (5, "medio"), (9, "medio"),
    (10, "alto"), (14, "alto"), (15, "critico"), (25, "critico"),
])
def test_nivel_por_riesgo(valor, esperado):
    assert r.nivel(valor) == esperado


def test_ranking_ordena_por_riesgo_y_luego_complejidad_y_excluye_cerrados():
    hs = [
        r.validar_hallazgo(_hallazgo(id="H-0001", probabilidad="2", dano="2", complejidad="1")),  # 4
        r.validar_hallazgo(_hallazgo(id="H-0002", probabilidad="4", dano="4", complejidad="5")),  # 16
        r.validar_hallazgo(_hallazgo(id="H-0003", probabilidad="4", dano="4", complejidad="1")),  # 16, más fácil
        r.validar_hallazgo(_hallazgo(id="H-0004", probabilidad="5", dano="5", estado="verificado")),
        r.validar_hallazgo(_hallazgo(id="H-0005", probabilidad="3", dano="3", estado="en_correccion")),  # 9
    ]
    for h in hs:
        h["riesgo"], h["nivel"] = r.riesgo(h), r.nivel(r.riesgo(h))
    assert [h["id"] for h in r.ranking(hs)] == ["H-0003", "H-0002", "H-0005", "H-0001"]
    assert [h["id"] for h in r.bloquea_produccion(hs)] == ["H-0003", "H-0002"]


def test_resumen_y_proximo_id():
    hs = [r.validar_hallazgo(_hallazgo(id="H-0007", probabilidad="4", dano="4"))]
    hs[0]["riesgo"], hs[0]["nivel"] = 16, "critico"
    res = r.resumen(hs)
    assert res["por_estado"]["abierto"] == 1
    assert res["por_nivel"]["critico"] == 1
    assert res["por_eje"]["IDS"] == {"total": 1, "abiertos": 1}
    assert r.proximo_id(hs) == "H-0008"
    assert r.proximo_id([]) == "H-0001"


def test_leer_hallazgos_rechaza_ids_repetidos(tmp_path):
    for nombre in ("a.md", "b.md"):
        (tmp_path / nombre).write_text(
            "---\n" + "\n".join(f"{k}: {v}" for k, v in _hallazgo().items() if k != "archivo") + "\n---\n",
            encoding="utf-8")
    with pytest.raises(r.ErrorRegistro, match="ya está en a.md"):
        r.leer_hallazgos(tmp_path)


# --- Corridas -----------------------------------------------------------------

def test_resultados_de_corrida_lee_solo_las_lineas_con_forma():
    cuerpo = """## Resultados
- IDS-01: paso — todo bien
- IDS-02: fallo — abre H-0001
- IDS-03: no_aplica
- texto suelto que no es resultado
"""
    res = r.resultados_de_corrida(cuerpo)
    assert [(x["test"], x["resultado"]) for x in res] == [("IDS-01", "paso"), ("IDS-02", "fallo"), ("IDS-03", "no_aplica")]
    assert res[0]["nota"] == "todo bien" and res[2]["nota"] == ""


def test_resultado_desconocido_falla():
    with pytest.raises(r.ErrorRegistro, match="aprobado"):
        r.resultados_de_corrida("- IDS-01: aprobado")


def test_ultimo_resultado_por_test_toma_la_corrida_mas_reciente(tmp_path):
    (tmp_path / "2026-09-01-1000-IDS.md").write_text(
        "---\nfecha: 2026-09-01 10:00\neje: IDS\nentorno: pruebas\niteracion: 1\n---\n- IDS-01: fallo\n- IDS-02: paso\n",
        encoding="utf-8")
    (tmp_path / "2026-09-02-1000-IDS.md").write_text(
        "---\nfecha: 2026-09-02 10:00\neje: IDS\nentorno: pruebas\niteracion: 1\n---\n- IDS-01: paso\n",
        encoding="utf-8")
    corridas = r.leer_corridas(tmp_path)
    assert corridas[0]["fecha"] == "2026-09-02 10:00"
    ultimo = r.ultimo_resultado_por_test(corridas)
    assert ultimo["IDS-01"]["resultado"] == "paso"
    assert ultimo["IDS-02"]["fecha"] == "2026-09-01 10:00"


# --- Catálogo y proyecto reales -----------------------------------------------

def test_plantillas_son_validas_para_el_motor():
    """Las plantillas tienen valores válidos a propósito: si el formato del
    motor cambia, este test avisa que la plantilla quedó vieja."""
    r.validar_test(r.leer_archivo(r.CATALOGO / "_plantilla.md"))
    r.validar_hallazgo(r.leer_archivo(PROYECTO / "hallazgos" / "_plantilla.md"))
    c = r.leer_archivo(PROYECTO / "corridas" / "_plantilla.md")
    assert len(r.resultados_de_corrida(c["cuerpo"])) == 4


def test_el_registro_real_de_mitrabajo_se_lee_entero():
    estado = r.estado_proyecto("mitrabajo")
    assert estado["avance"]["iteracion"] >= 1
    assert len(estado["avance"]["etapas"]) == 10
    assert set(estado["resumen"]["por_eje"]) == set(r.EJES)


def test_todo_test_del_catalogo_cae_en_un_eje_del_readme():
    readme = (r.CATALOGO / "README.md").read_text(encoding="utf-8")
    for sigla, nombre in r.EJES.items():
        assert f"| {sigla} | {nombre} |" in readme, f"el README del catálogo no lista el eje {sigla}"

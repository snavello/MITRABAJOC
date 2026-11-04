"""El CUIL impreso con el dígito verificador mal (decisión de SDN, 2026-11-04):
el recibo se acepta como propio y el afiliado recibe un aviso para que su
empleador lo corrija. Caso real de la tirada de 40 del lote bancario: Nación
imprimió 27-34070910-0 en vez de 27-34070910-7.

Correr con: python -m pytest test_cuil_impreso.py -q
"""
import validador as V

SESION = "27340709107"


def test_detecta_solo_el_verificador_mal_del_propio_cuil():
    assert V.cuil_impreso_con_error("27-34070910-0", SESION)
    assert not V.cuil_impreso_con_error("27-34070910-7", SESION)      # el correcto
    assert not V.cuil_impreso_con_error("20-11111111-2", SESION)      # otra persona
    assert not V.cuil_impreso_con_error("27-34070911-0", SESION)      # otro número
    assert not V.cuil_impreso_con_error("", SESION)
    assert V.cuil_impreso_invalido([None, "OCULTO", "27-34070910-0"], SESION) == "27-34070910-0"
    assert V.cuil_impreso_invalido(["27340709107"], SESION) is None


def test_no_es_otra_persona_pero_otro_cuil_valido_si():
    assert not V.cuiles_distintos("27-34070910-0", SESION)
    assert V.cuiles_distintos("20-11111111-2", SESION)
    assert not V.cuil_no_coincide({"empleado": {"cuil": "27340709100"}}, SESION)


def _recibo(**extra):
    return {"periodo": "2026-05", "empleado": {"cuil": SESION}, "empleador": {"cuit": "30500010912"},
            "lineas": [{"codigo": "001", "descripcion": "Sueldo", "importe": 1000.0,
                        "tipo": "remuneracion", "seccion": "haberes"}],
            "totales_impresos": {"remuneraciones": 1000.0, "neto": 1000.0}, **extra}


def test_el_afiliado_recibe_el_aviso_y_el_recibo_se_valida_igual():
    res = V.validar([], [], _recibo(cuil_impreso_invalido="27-34070910-0"), cuil_sesion=SESION)
    aviso = [a for a in res["alertas"] if a["tipo"] == "cuil_impreso_invalido"]
    assert len(aviso) == 1
    assert "27-34070910-0" in aviso[0]["detalle"] and "27-34070910-7" in aviso[0]["detalle"]
    assert res["estado"] != "CUIL_NO_COINCIDE"
    # Sin la marca, o con un valor que no es el error del propio CUIL, no hay aviso.
    for r in (_recibo(), _recibo(cuil_impreso_invalido="20-11111111-2")):
        assert not [a for a in V.validar([], [], r, cuil_sesion=SESION)["alertas"]
                    if a["tipo"] == "cuil_impreso_invalido"]

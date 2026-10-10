"""identificadores_demo.py: los CUIL/CUIT de la demo, antes y después del
módulo 11 (PLAN_CUIT_MOD11.md, etapa 3).

No importa cargar_demo.py: ese script carga la demo al importarse. Lo lee
como texto."""
import re
from pathlib import Path

import cuit
from identificadores_demo import REEMPLAZOS_MOD11

RAIZ = Path(__file__).resolve().parent
_ONCE = re.compile(r"(?<![\d-])\d{2}-?\d{8}-?\d(?![\d-])")


def test_los_viejos_son_invalidos_y_los_nuevos_validos_del_mismo_tipo():
    for viejo, nuevo in REEMPLAZOS_MOD11.items():
        assert len(viejo) == 11 and viejo.isdigit(), viejo
        assert not cuit.es_valido(viejo), f"{viejo} ya era válido: no hacía falta cambiarlo"
        assert cuit.es_valido(nuevo), f"{nuevo} no cumple el verificador"
        assert cuit.tipo(viejo) == cuit.tipo(nuevo), f"{viejo} -> {nuevo} cambia de tipo"


def test_sin_colisiones_ni_cadenas():
    nuevos = list(REEMPLAZOS_MOD11.values())
    assert len(set(nuevos)) == len(nuevos), "dos números viejos van al mismo nuevo"
    assert not set(nuevos) & set(REEMPLAZOS_MOD11), "un nuevo es a la vez un viejo"


def test_los_nuevos_son_la_correccion_o_el_siguiente_libre():
    for viejo, nuevo in REEMPLAZOS_MOD11.items():
        corregido = cuit.corregir(viejo)
        if nuevo != corregido:
            # Solo se aparta de la corrección cuando ésta choca con otro de la demo.
            otros = {cuit.corregir(v) for v in REEMPLAZOS_MOD11 if v != viejo}
            assert corregido in otros, f"{viejo}: {nuevo} no es ni la corrección ni una salida a una colisión"
            assert nuevo == cuit.siguiente_libre(viejo, set(REEMPLAZOS_MOD11.values()) - {nuevo}), viejo


def test_los_scripts_de_demo_cargan_solo_numeros_nuevos():
    """Todo CUIL/CUIT escrito en cargar_demo.py y cargar_bancaria.py es válido y
    es un valor del mapa: un número suelto que no esté acá no lo convertiría
    regularizar_cuit.py en las bases ya cargadas."""
    nuevos = set(REEMPLAZOS_MOD11.values())
    for nombre in ("cargar_demo.py", "cargar_bancaria.py"):
        texto = (RAIZ / nombre).read_text(encoding="utf-8")
        encontrados = {cuit.normalizar(m) for m in _ONCE.findall(texto)}
        assert encontrados, nombre
        sueltos = sorted(n for n in encontrados if n not in nuevos)
        assert not sueltos, f"{nombre} usa números fuera de identificadores_demo.py: {sueltos}"

"""El dígito verificador en las puertas de alta (PLAN_CUIT_MOD11.md, etapa 4).

La regla (D2): se exige el verificador donde un número NACE en el sistema
(altas, registro, carga masiva) y donde se REFERENCIA uno que ya existe (los
cuatro logins, el reset de clave, los criterios de notificación) se busca tal
cual -- si los logins lo validaran, los miles de CUIL sintéticos de los lotes
(que no lo cumplen y quedan así) no podrían entrar.

Qué verifica este archivo:

1. Cada puerta rechaza un inválido CON su aviso y SIN escribir nada en la base,
   y deja pasar uno válido.
2. Persona contra empresa donde corresponde (el CUIL es de persona, el CUIT del
   gremio de persona jurídica, el del empleador de cualquiera de las dos).
3. El alta masiva deja entrar a los válidos e informa los inválidos.
4. Una EDICIÓN que reenvía el mismo número viejo (inválido) no se bloquea: el
   verificador se exige solo si el número cambió.
5. Los logins y las búsquedas siguen andando con números inválidos ya cargados.
6. Fail-closed: toda ruta POST que recibe un campo con nombre de CUIL/CUIT está
   clasificada acá como "puerta" o "referencia", y las puertas llaman al
   verificador. Una ruta nueva sin clasificar rompe este archivo.
7. `static/cuit.js` (la cortesía del navegador) usa los mismos pesos y prefijos
   que `cuit.py`, y toda plantilla con `data-cuit` lo carga con sello. Si hay
   node en el sistema, además se corre el JS contra Python.

Correr con: python -m pytest test_cuit_puertas.py -q
"""
import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ["PLATAFORMA_PASSWORD"] = "test-plataforma"

import auth
import cuit
import db
import errores
import main
from db import (Concepto, CuentaEmpleador, CuentaTrabajador, Empleador, Sindicato,
                Trabajador, UsuarioSindicato)
from fastapi.testclient import TestClient
from modulos import MODULOS
from sqlmodel import Session, select

RAIZ = Path(__file__).resolve().parent

db.crear_tablas()

# ---- números de prueba ------------------------------------------------------
# Válidos (los dos primeros vienen de test_cuit.py / identificadores_demo.py).
CUIL_OK = "20202790411"           # persona, verificador correcto
CUIL_OK_2 = "20111111112"         # Juan Molina de la demo, ya convertido
CUIL_OK_3 = "27222222228"         # María Sánchez de la demo, ya convertida
CUIT_EMPRESA_OK = "30444640975"   # persona jurídica
CUIT_EMPRESA_OK_2 = "30999888778" # Metalúrgica del Sur, ya convertida
# Inválidos: los de siempre de la demo y del plan (ninguno cumplía el módulo 11).
CUIL_MAL = "27999999999"
CUIL_MAL_2 = "20111111119"
CUIT_MAL = "30999888776"          # el CUIT viejo de la demo
assert cuit.es_valido(CUIL_OK, cuit.PERSONA) and cuit.es_valido(CUIL_OK_2, cuit.PERSONA)
assert cuit.es_valido(CUIL_OK_3, cuit.PERSONA)
assert cuit.es_valido(CUIT_EMPRESA_OK, cuit.EMPRESA) and cuit.es_valido(CUIT_EMPRESA_OK_2, cuit.EMPRESA)
assert not cuit.es_valido(CUIL_MAL) and not cuit.es_valido(CUIL_MAL_2) and not cuit.es_valido(CUIT_MAL)

# Sintéticos que YA estaban cargados (inválidos) y tienen que seguir entrando.
SINT_CUIL = "20650000013"
SINT_CUIT = "30661900005"
SINT_ADMIN = "20111111110"        # el admin viejo de la UOM: no cumple el módulo 11
assert not cuit.es_valido(SINT_CUIL) and not cuit.es_valido(SINT_CUIT)
assert not cuit.es_valido(SINT_ADMIN)

ADMIN_CUIL = "20111111120"        # el Super Admin de la demo ya convertido
assert cuit.es_valido(ADMIN_CUIL, cuit.PERSONA)

with db.get_session() as s:
    sind = Sindicato(nombre="Sindicato Puertas CUIT", slug="sindicato-puertas-cuit",
                     color_base="#0f1b2d", modulos_habilitados=list(MODULOS.keys()))
    s.add(sind); s.commit(); s.refresh(sind)
    SID = sind.id
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=ADMIN_CUIL, cuil=ADMIN_CUIL,
                           nombre="Admin Puertas", clave_hash=auth.hashear_clave("admin-puertas"),
                           debe_cambiar_clave=False, es_super_admin=True))
    # Un administrador CARGADO ANTES de la regla: su CUIL no cumple el módulo 11.
    s.add(UsuarioSindicato(sindicato_id=SID, usuario=SINT_ADMIN, cuil=SINT_ADMIN,
                           nombre="Admin Viejo", clave_hash=auth.hashear_clave("admin-viejo"),
                           debe_cambiar_clave=False, es_super_admin=True))
    # Un afiliado sintético, ya registrado, con CUIL inválido.
    s.add(Trabajador(sindicato_id=SID, cuil=SINT_CUIL, activo=True, registrado=True,
                     cuit_empleador=SINT_CUIT))
    db.guardar_datos_personales(s, SINT_CUIL, nombre="Sintético Registrado")
    db.asegurar_cuenta(s, SINT_CUIL).clave_hash = auth.hashear_clave("clave-sint")
    # Una empresa sintética con cuenta, CUIT inválido.
    s.add(Empleador(sindicato_id=SID, cuit=SINT_CUIT, razon_social="Sintética SA",
                    registrado=True, activo=True))
    s.add(CuentaEmpleador(cuit=SINT_CUIT, clave_hash=auth.hashear_clave("clave-emp")))
    s.commit()


def _admin(usuario=ADMIN_CUIL, clave="admin-puertas"):
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": usuario, "clave": clave}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/inicio", r.headers
    return c


def _plataforma():
    c = TestClient(main.app)
    c.post("/plataforma/login", data={"cuit": "20000000000", "clave": "test-plataforma"})
    return c


def _contar(modelo, *condiciones):
    with Session(db.engine) as s:
        q = select(modelo)
        for cond in condiciones:
            q = q.where(cond)
        return len(s.exec(q).all())


def _trabajador(cuil):
    with Session(db.engine) as s:
        return s.exec(select(Trabajador).where(
            Trabajador.sindicato_id == SID, Trabajador.cuil == cuil)).first()


DOM = {"provincia": "Santa Fe", "localidad": "Rosario"}


# =============================================================================
# 1. POST /admin/trabajador
# =============================================================================

def test_admin_trabajador_rechaza_cuil_invalido_y_no_escribe():
    c = _admin()
    antes_t, antes_c = _contar(Trabajador), _contar(CuentaTrabajador)
    r = c.post("/admin/trabajador", data={"cuil": CUIL_MAL, "nombre": "Mal Digito", **DOM},
               follow_redirects=False)
    assert r.status_code == 303 and "err=cuil" in r.headers["location"], r.headers
    assert (_contar(Trabajador), _contar(CuentaTrabajador)) == (antes_t, antes_c)
    # y la pantalla dice por qué, con el código
    page = c.get(r.headers["location"].split("#")[0])
    assert "No se guardó: el CUIL no es válido" in page.text and "E-IDENT-01" in page.text
    print("OK  test_admin_trabajador_rechaza_cuil_invalido_y_no_escribe")


def test_admin_trabajador_rechaza_un_cuit_de_empresa_como_cuil():
    c = _admin()
    antes = _contar(Trabajador)
    r = c.post("/admin/trabajador", data={"cuil": CUIT_EMPRESA_OK, "nombre": "Empresa", **DOM},
               follow_redirects=False)
    assert "err=cuil" in r.headers["location"]
    assert _contar(Trabajador) == antes
    print("OK  test_admin_trabajador_rechaza_un_cuit_de_empresa_como_cuil")


def test_admin_trabajador_acepta_cuil_valido_con_o_sin_guiones():
    c = _admin()
    r = c.post("/admin/trabajador", data={"cuil": "20-20279041-1", "nombre": "Bien Digito", **DOM},
               follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers
    assert _trabajador(CUIL_OK) is not None
    print("OK  test_admin_trabajador_acepta_cuil_valido_con_o_sin_guiones")


def test_admin_trabajador_cuit_del_empleador_se_valida_si_viene():
    c = _admin()
    antes = _contar(Trabajador)
    r = c.post("/admin/trabajador", data={"cuil": CUIL_OK_3, "nombre": "Con Empleador Mal",
                                          "cuit_empleador": CUIT_MAL, **DOM}, follow_redirects=False)
    assert "err=cuitempleador" in r.headers["location"], r.headers
    assert _contar(Trabajador) == antes and _trabajador(CUIL_OK_3) is None
    page = c.get("/admin?err=cuitempleador")
    assert "No se guardó: el CUIT del empleador no es válido" in page.text and "E-IDENT-02" in page.text
    # válido: de empresa y de persona (un monotributista con empleados) entran
    for cuit_emp, cuil in ((CUIT_EMPRESA_OK_2, CUIL_OK_3), ):
        r = c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Con Empleador Bien",
                                              "cuit_empleador": cuit_emp, **DOM}, follow_redirects=False)
        assert "err=" not in r.headers["location"], r.headers
        assert _trabajador(cuil).cuit_empleador == cuit_emp
    print("OK  test_admin_trabajador_cuit_del_empleador_se_valida_si_viene")


def test_admin_trabajador_cuit_del_empleador_vacio_sigue_siendo_opcional():
    c = _admin()
    cuil = cuit.corregir("20333333330")
    r = c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Sin Empleador", **DOM},
               follow_redirects=False)
    assert "err=" not in r.headers["location"]
    assert _trabajador(cuil).cuit_empleador is None
    print("OK  test_admin_trabajador_cuit_del_empleador_vacio_sigue_siendo_opcional")


def test_admin_trabajador_edicion_con_el_mismo_numero_viejo_no_se_bloquea():
    c = _admin()
    t = _trabajador(SINT_CUIL)
    r = c.post("/admin/trabajador", data={
        "id": str(t.id), "cuil": SINT_CUIL, "nombre": "Sintético Editado",
        "cuit_empleador": SINT_CUIT, "telefono": "341-5551234", **DOM}, follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers
    with Session(db.engine) as s:
        cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == SINT_CUIL)).first()
        assert cuenta.nombre == "Sintético Editado" and cuenta.telefono == "341-5551234"
    assert _trabajador(SINT_CUIL).cuit_empleador == SINT_CUIT
    print("OK  test_admin_trabajador_edicion_con_el_mismo_numero_viejo_no_se_bloquea")


def test_admin_trabajador_edicion_que_cambia_el_numero_a_uno_invalido_se_bloquea():
    c = _admin()
    t = _trabajador(SINT_CUIL)
    r = c.post("/admin/trabajador", data={
        "id": str(t.id), "cuil": CUIL_MAL, "nombre": "No debería", **DOM}, follow_redirects=False)
    assert "err=cuilfijo" in r.headers["location"], r.headers
    assert _trabajador(SINT_CUIL) is not None and _trabajador(CUIL_MAL) is None
    # y cambiar solo el CUIT del empleador a uno inválido también
    r = c.post("/admin/trabajador", data={
        "id": str(t.id), "cuil": SINT_CUIL, "nombre": "Sintético Editado",
        "cuit_empleador": CUIT_MAL, **DOM}, follow_redirects=False)
    assert "err=cuitempleador" in r.headers["location"], r.headers
    assert _trabajador(SINT_CUIL).cuit_empleador == SINT_CUIT
    print("OK  test_admin_trabajador_edicion_que_cambia_el_numero_a_uno_invalido_se_bloquea")


def test_admin_trabajador_edicion_no_cambia_el_cuil_ni_a_uno_valido():
    """El CUIL no se cambia desde una edición (E-IDENT-03), ni siquiera para
    "corregirlo" a uno válido: cambiaba solo esta fila y dejaba atrás la
    cuenta (clave, foto), los recibos y los trámites de la persona. Se
    corrige con regularizar_cuit.py, en todas las tablas a la vez."""
    c = _admin()
    cuil_viejo = "20650000020"
    assert not cuit.es_valido(cuil_viejo)
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil=cuil_viejo, activo=True))
        db.guardar_datos_personales(s, cuil_viejo, nombre="Para Corregir")
        s.commit()
    t = _trabajador(cuil_viejo)
    nuevo = cuit.corregir(cuil_viejo)
    r = c.post("/admin/trabajador", data={"id": str(t.id), "cuil": nuevo, "nombre": "Otro Nombre", **DOM},
               follow_redirects=False)
    assert "err=cuilfijo" in r.headers["location"], r.headers
    assert _trabajador(nuevo) is None and _trabajador(cuil_viejo) is not None
    with Session(db.engine) as s:
        assert s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == nuevo)).first() is None
        cuenta = s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == cuil_viejo)).first()
        assert cuenta.nombre == "Para Corregir", "no se tiene que haber guardado nada"
    pagina = c.get("/admin?err=cuilfijo")
    assert "E-IDENT-03" in pagina.text
    print("OK  test_admin_trabajador_edicion_no_cambia_el_cuil_ni_a_uno_valido")


# =============================================================================
# 2. POST /admin/trabajador/masivo
# =============================================================================

def test_masivo_entran_los_validos_y_se_informan_los_invalidos():
    c = _admin()
    cuil_a, cuil_b = cuit.corregir("27410000005"), cuit.corregir("20410000103")
    lista = "\n".join([
        f"{cuil_a}, Ana Valida, Mitre, 100, , Rosario, Santa Fe",
        f"{CUIL_MAL}, Mal Uno, Mitre, 100, , Rosario, Santa Fe",
        f"{cuil_b}, Beto Valido, Mitre, 100, , Rosario, Santa Fe",
        f"{CUIL_MAL_2}, Mal Dos, Mitre, 100, , Rosario, Santa Fe",
        f"{CUIT_EMPRESA_OK}, Empresa Como Persona, Mitre, 100, , Rosario, Santa Fe",
        f"{cuil_a}, Repetida, , , , Rosario, Santa Fe",     # duplicada: va a "omitidas"
    ])
    antes = _contar(Trabajador, Trabajador.sindicato_id == SID)
    r = c.post("/admin/trabajador/masivo", data={"lista": lista}, follow_redirects=False)
    destino = r.headers["location"]
    assert "altas=2" in destino, destino
    assert "cuilinvalidos=3" in destino, destino
    assert "omitidas=1" in destino, destino          # la duplicada, que ya se contaba antes
    for n in (CUIL_MAL, CUIL_MAL_2, CUIT_EMPRESA_OK):
        assert n in destino                          # CUÁLES, no solo cuántas
    assert _contar(Trabajador, Trabajador.sindicato_id == SID) == antes + 2
    for n in (CUIL_MAL, CUIL_MAL_2):
        assert _trabajador(n) is None
    assert _trabajador(cuil_a) is not None and _trabajador(cuil_b) is not None
    # y la pantalla lo dice (nunca en silencio)
    page = c.get(destino.split("#")[0])
    assert "3 líneas porque el CUIL no es válido" in page.text
    assert CUIL_MAL in page.text and "E-IDENT-01" in page.text
    print("OK  test_masivo_entran_los_validos_y_se_informan_los_invalidos")


def test_masivo_un_solo_invalido_dice_linea_en_singular():
    c = _admin()
    r = c.post("/admin/trabajador/masivo", data={
        "lista": f"{CUIL_MAL}, Solo Uno, , , , Rosario, Santa Fe"}, follow_redirects=False)
    assert "altas=0" in r.headers["location"] and "cuilinvalidos=1" in r.headers["location"]
    page = c.get(r.headers["location"].split("#")[0])
    assert "1 línea porque el CUIL no es válido" in page.text
    print("OK  test_masivo_un_solo_invalido_dice_linea_en_singular")


# =============================================================================
# 3. POST /admin/usuario
# =============================================================================

def test_admin_usuario_rechaza_cuil_invalido_y_no_escribe():
    c = _admin()
    antes = _contar(UsuarioSindicato)
    r = c.post("/admin/usuario", data={"usuario": CUIL_MAL, "nombre": "Mal", "clave_inicial": "x",
                                       "rol": "super"}, follow_redirects=False)
    assert "err=cuilusuario" in r.headers["location"], r.headers
    assert _contar(UsuarioSindicato) == antes
    page = c.get("/admin?err=cuilusuario&sub=usuarios")
    assert "El CUIL no es válido -- revisá" in page.text and "E-IDENT-01" in page.text
    # Una sola vez: el cartel del alta de trabajadores usa otra clave (err=cuil)
    # y no se tiene que prender en la otra pestaña (QA, 2026-10-10).
    assert page.text.count("Código E-IDENT-01") == 1
    print("OK  test_admin_usuario_rechaza_cuil_invalido_y_no_escribe")


def test_admin_usuario_rechaza_un_cuit_de_empresa_y_acepta_uno_valido():
    c = _admin()
    antes = _contar(UsuarioSindicato)
    r = c.post("/admin/usuario", data={"usuario": CUIT_EMPRESA_OK, "nombre": "Empresa",
                                       "clave_inicial": "x", "rol": "super"}, follow_redirects=False)
    assert "err=cuilusuario" in r.headers["location"] and _contar(UsuarioSindicato) == antes
    r = c.post("/admin/usuario", data={"usuario": CUIL_OK_2, "nombre": "Bien", "clave_inicial": "x",
                                       "rol": "super"}, follow_redirects=False)
    assert "ok=usuario" in r.headers["location"], r.headers
    assert _contar(UsuarioSindicato, UsuarioSindicato.usuario == CUIL_OK_2) == 1
    print("OK  test_admin_usuario_rechaza_un_cuit_de_empresa_y_acepta_uno_valido")


# =============================================================================
# 4. POST /admin/empleador
# =============================================================================

def test_admin_empleador_rechaza_cuit_invalido_y_no_escribe():
    c = _admin()
    antes = _contar(Empleador)
    for malo in (CUIT_MAL, "30111222334", "123"):
        r = c.post("/admin/empleador", data={"cuit": malo, "razon_social": "No entra"},
                   follow_redirects=False)
        assert "error=cuit" in r.headers["location"], (malo, r.headers)
    assert _contar(Empleador) == antes
    page = c.get("/admin?error=cuit")
    assert "El CUIT no es válido" in page.text and "E-IDENT-02" in page.text
    print("OK  test_admin_empleador_rechaza_cuit_invalido_y_no_escribe")


def test_admin_empleador_acepta_empresa_y_persona():
    c = _admin()
    # persona jurídica y persona física: un monotributista con empleados
    for n in (CUIT_EMPRESA_OK, CUIL_OK_2):
        r = c.post("/admin/empleador", data={"cuit": n, "razon_social": f"Emp {n}"},
                   follow_redirects=False)
        assert "error=" not in r.headers["location"], (n, r.headers)
        assert _contar(Empleador, Empleador.sindicato_id == SID, Empleador.cuit == n) == 1
    print("OK  test_admin_empleador_acepta_empresa_y_persona")


def test_admin_empleador_edicion_con_el_mismo_numero_viejo_no_se_bloquea():
    c = _admin()
    with Session(db.engine) as s:
        e = s.exec(select(Empleador).where(Empleador.sindicato_id == SID,
                                           Empleador.cuit == SINT_CUIT)).first()
        eid = e.id
    r = c.post("/admin/empleador", data={"id": str(eid), "cuit": SINT_CUIT,
                                         "razon_social": "Sintética Editada", "telefono": "11-5555"},
               follow_redirects=False)
    assert "error=" not in r.headers["location"], r.headers
    with Session(db.engine) as s:
        e = s.get(Empleador, eid)
        assert e.razon_social == "Sintética Editada" and e.cuit == SINT_CUIT
    # cambiarlo -- a un inválido o a uno válido -- se frena (E-IDENT-03) y no
    # toca la fila: el CUIT une al empleador con su cuenta, sus empleados y sus
    # recibos, y se corrige con regularizar_cuit.py en todas las tablas.
    for otro in (CUIT_MAL, cuit.corregir(SINT_CUIT)):
        r = c.post("/admin/empleador", data={"id": str(eid), "cuit": otro, "razon_social": "No"},
                   follow_redirects=False)
        assert "error=cuitfijo" in r.headers["location"], (otro, r.headers)
        with Session(db.engine) as s:
            e = s.get(Empleador, eid)
            assert e.cuit == SINT_CUIT and e.razon_social == "Sintética Editada"
    assert "E-IDENT-03" in c.get("/admin?error=cuitfijo").text
    print("OK  test_admin_empleador_edicion_con_el_mismo_numero_viejo_no_se_bloquea")


# =============================================================================
# 5. POST /admin/concepto
# =============================================================================

def _concepto(c, **extra):
    datos = {"codigo": "P001", "nombre": "Concepto Prueba", "tipo": "descuento",
             "remunerativo": "no", "alias": "", "categoria_sindical": "", "codigo_generico": ""}
    datos.update(extra)
    return c.post("/admin/concepto", data=datos, follow_redirects=False)


def test_admin_concepto_cuit_invalido_se_rechaza_y_no_escribe():
    c = _admin()
    antes = _contar(Concepto)
    r = _concepto(c, codigo="MAL1", cuit_empleador=CUIT_MAL)
    assert "error=cuitconcepto" in r.headers["location"], r.headers
    assert _contar(Concepto) == antes
    page = c.get("/admin?error=cuitconcepto")
    assert "No se guardó el concepto: el CUIT del empleador no es válido" in page.text and "E-IDENT-02" in page.text
    print("OK  test_admin_concepto_cuit_invalido_se_rechaza_y_no_escribe")


def test_admin_concepto_cuit_valido_vacio_y_con_guiones():
    c = _admin()
    r = _concepto(c, codigo="OK1", cuit_empleador="30-44464097-5")
    assert "error=" not in r.headers["location"], r.headers
    with Session(db.engine) as s:
        assert s.exec(select(Concepto).where(Concepto.codigo == "OK1")).first().cuit_empleador == CUIT_EMPRESA_OK
    # un empleador persona física también
    r = _concepto(c, codigo="OK2", cuit_empleador=CUIL_OK_2)
    assert "error=" not in r.headers["location"]
    # vacío = concepto genérico: sigue siendo opcional
    r = _concepto(c, codigo="OK3", cuit_empleador="")
    assert "error=" not in r.headers["location"]
    with Session(db.engine) as s:
        assert s.exec(select(Concepto).where(Concepto.codigo == "OK3")).first().cuit_empleador is None
    print("OK  test_admin_concepto_cuit_valido_vacio_y_con_guiones")


def test_admin_concepto_edicion_con_el_mismo_cuit_viejo_no_se_bloquea():
    c = _admin()
    with db.get_session() as s:
        viejo = Concepto(sindicato_id=SID, codigo="VIEJO1", nombre="Cargado antes", tipo="descuento",
                         remunerativo=False, alias=["Cargado antes"], cuit_empleador=SINT_CUIT)
        s.add(viejo); s.commit(); s.refresh(viejo)
        cid = viejo.id
    r = _concepto(c, id=str(cid), codigo="VIEJO1", nombre="Cargado antes (editado)",
                  cuit_empleador=SINT_CUIT)
    assert "error=" not in r.headers["location"], r.headers
    with Session(db.engine) as s:
        fila = s.get(Concepto, cid)
        assert fila.nombre == "Cargado antes (editado)" and fila.cuit_empleador == SINT_CUIT
    r = _concepto(c, id=str(cid), codigo="VIEJO1", nombre="No", cuit_empleador=CUIT_MAL)
    assert "error=cuitconcepto" in r.headers["location"]
    with Session(db.engine) as s:
        assert s.get(Concepto, cid).cuit_empleador == SINT_CUIT
    print("OK  test_admin_concepto_edicion_con_el_mismo_cuit_viejo_no_se_bloquea")


# =============================================================================
# 6. POST /plataforma/sindicato, /sindicato/editar, /usuario, /completar
# =============================================================================

def _payload_sind(**extra):
    base = {"nombre": "Gremio CUIT", "color_primario": "#152238", "color_secundario": "#1a7a6b",
            "color_acento": "#b23a2e", "color_base": "#0f1b2d"}
    base.update(extra)
    return base


def _sind_por_nombre(nombre):
    with Session(db.engine) as s:
        return s.exec(select(Sindicato).where(Sindicato.nombre == nombre)).first()


def test_plataforma_sindicato_alta_rechaza_cuit_invalido_y_no_crea():
    c = _plataforma()
    antes = _contar(Sindicato)
    for malo in (CUIT_MAL, CUIL_OK):       # el segundo es un CUIL válido, pero de PERSONA
        r = c.post("/plataforma/sindicato", data=_payload_sind(nombre="Gremio Mal", cuit=malo),
                   follow_redirects=False)
        assert "error=cuit" in r.headers["location"], (malo, r.headers)
    assert _contar(Sindicato) == antes and _sind_por_nombre("Gremio Mal") is None
    page = c.get("/plataforma?error=cuit")
    assert "CUIT del sindicato no es válido" in page.text and "E-IDENT-02" in page.text
    print("OK  test_plataforma_sindicato_alta_rechaza_cuit_invalido_y_no_crea")


def test_plataforma_sindicato_alta_acepta_empresa_con_o_sin_guiones_o_vacio():
    c = _plataforma()
    for nombre, n in (("Gremio Con Guiones", "30-44464097-5"), ("Gremio Pelado", CUIT_EMPRESA_OK_2),
                      ("Gremio Sin CUIT", "")):
        r = c.post("/plataforma/sindicato", data=_payload_sind(nombre=nombre, cuit=n),
                   follow_redirects=False)
        assert "error=" not in r.headers["location"], (nombre, r.headers)
        assert _sind_por_nombre(nombre) is not None
    print("OK  test_plataforma_sindicato_alta_acepta_empresa_con_o_sin_guiones_o_vacio")


def test_plataforma_sindicato_edicion_con_el_cuit_viejo_no_se_bloquea():
    c = _plataforma()
    with db.get_session() as s:
        s.add(Sindicato(nombre="Gremio Viejo", slug="gremio-viejo", color_base="#0f1b2d",
                        cuit="30-11111111-1"))     # el de la demo antes de la regla
        s.commit()
    sid = _sind_por_nombre("Gremio Viejo").id
    assert not cuit.es_valido("30-11111111-1")
    r = c.post("/plataforma/sindicato/editar", data=_payload_sind(
        id=str(sid), nombre="Gremio Viejo", cuit="30-11111111-1", telefonos="11-4444"),
        follow_redirects=False)
    assert "error=" not in r.headers["location"], r.headers
    assert _sind_por_nombre("Gremio Viejo").telefonos == "11-4444"
    # cambiarlo a otro inválido se frena y no toca nada
    r = c.post("/plataforma/sindicato/editar", data=_payload_sind(
        id=str(sid), nombre="Gremio Viejo Renombrado", cuit=CUIT_MAL), follow_redirects=False)
    assert "error=cuit" in r.headers["location"]
    fila = _sind_por_nombre("Gremio Viejo")
    assert fila is not None and fila.cuit == "30-11111111-1"
    assert _sind_por_nombre("Gremio Viejo Renombrado") is None
    # y a uno válido sí
    r = c.post("/plataforma/sindicato/editar", data=_payload_sind(
        id=str(sid), nombre="Gremio Viejo", cuit="30111111118"), follow_redirects=False)
    assert "error=" not in r.headers["location"]
    assert _sind_por_nombre("Gremio Viejo").cuit == "30111111118"
    print("OK  test_plataforma_sindicato_edicion_con_el_cuit_viejo_no_se_bloquea")


def test_plataforma_usuario_primer_admin_rechaza_cuil_invalido_y_no_escribe():
    c = _plataforma()
    antes = _contar(UsuarioSindicato)
    for malo in (CUIL_MAL, CUIT_EMPRESA_OK):
        r = c.post("/plataforma/usuario", data={"sindicato_id": str(SID), "usuario": malo,
                                                "nombre": "Mal", "clave_inicial": "x"},
                   follow_redirects=False)
        assert "error=cuil" in r.headers["location"], (malo, r.headers)
    assert _contar(UsuarioSindicato) == antes
    page = c.get("/plataforma?error=cuil")
    assert "CUIL no es válido" in page.text and "E-IDENT-01" in page.text
    r = c.post("/plataforma/usuario", data={"sindicato_id": str(SID), "usuario": CUIL_OK_3,
                                            "nombre": "Bien", "clave_inicial": "x"},
               follow_redirects=False)
    assert "error=" not in r.headers["location"]
    with Session(db.engine) as s:
        u = s.exec(select(UsuarioSindicato).where(UsuarioSindicato.usuario == CUIL_OK_3)).first()
        assert u is not None and u.es_super_admin and u.cuil == CUIL_OK_3
    print("OK  test_plataforma_usuario_primer_admin_rechaza_cuil_invalido_y_no_escribe")


def test_plataforma_completar_exige_el_verificador_del_cuil():
    db.sembrar_superadmins_iniciales()
    base = {"clave_nueva": "claveLarga2026", "clave_repetir": "claveLarga2026",
            "dni": "20279041", "email": "sna@example.com", "direccion": "Mitre 100",
            "telefono": "341555"}
    c = TestClient(main.app)
    r = c.post("/plataforma/login", data={"usuario": "snavello", "clave": "snaSandro"},
               follow_redirects=False)
    assert r.headers["location"] == "/plataforma/completar", r.headers
    r = c.post("/plataforma/completar", data={**base, "cuil": CUIL_MAL})
    assert r.status_code == 400
    assert "El CUIL no es válido" in r.text and "E-IDENT-01" in r.text
    assert db.usuario_plataforma_por_usuario("snavello").debe_completar_datos      # no se completó
    assert db.usuario_plataforma_por_usuario("snavello").cuil in (None, "")
    # lo que ya decía "11 dígitos" para un número de otro largo sigue igual
    r = c.post("/plataforma/completar", data={**base, "cuil": "123"})
    assert r.status_code == 400 and "11 dígitos" in r.text
    # y uno válido completa la cuenta
    r = c.post("/plataforma/completar", data={**base, "cuil": CUIL_OK}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/plataforma/inicio", r.text[:300]
    fila = db.usuario_plataforma_por_usuario("snavello")
    assert fila.cuil == CUIL_OK and not fila.debe_completar_datos
    print("OK  test_plataforma_completar_exige_el_verificador_del_cuil")


# =============================================================================
# 7. Registro del afiliado y de la empresa
# =============================================================================

def test_registro_del_afiliado_exige_el_verificador_antes_de_buscar_el_padron():
    c = TestClient(main.app)
    datos = {"clave": "clave123", "nombre": "Reg", **DOM}
    # Un CUIL inválido que ESTÁ en el padrón (un sintético sin clave): tampoco
    # se registra -- es la consecuencia buscada de la decisión 4 del plan.
    sin_clave = "20650000021"
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil=sin_clave, activo=True))
        db.guardar_datos_personales(s, sin_clave, nombre="Sin Clave")
        s.commit()
    antes = _contar(CuentaTrabajador, CuentaTrabajador.clave_hash != "")
    for malo in (CUIL_MAL, sin_clave, CUIT_EMPRESA_OK):
        r = c.post("/trabajador/registro", data={"cuil": malo, **datos}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/ingresar?error=cuil", (malo, r.headers)
    assert _contar(CuentaTrabajador, CuentaTrabajador.clave_hash != "") == antes
    with Session(db.engine) as s:
        assert not s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == sin_clave)).first().clave_hash
    # la pantalla de ingreso muestra el aviso, con el código, y deja abierta la pestaña de registro
    page = c.get("/ingresar?error=cuil")
    assert "El CUIL no es válido: revisá los 11 números" in page.text
    assert "avisale a tu sindicato" in page.text and "E-IDENT-01" in page.text
    assert "'cuil'" in page.text           # entra en la lista que abre la pestaña "Registrarme"
    print("OK  test_registro_del_afiliado_exige_el_verificador_antes_de_buscar_el_padron")


def test_registro_del_afiliado_con_cuil_valido_en_el_padron_entra():
    c = TestClient(main.app)
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil=CUIL_OK_2, activo=True))
        db.guardar_datos_personales(s, CUIL_OK_2, nombre="Juan Molina")
        s.commit()
    r = c.post("/trabajador/registro", data={"cuil": CUIL_OK_2, "clave": "clave123", "nombre": "Juan Molina",
                                             **DOM}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio", r.headers
    with Session(db.engine) as s:
        assert s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil == CUIL_OK_2)).first().clave_hash
    print("OK  test_registro_del_afiliado_con_cuil_valido_en_el_padron_entra")


def test_registro_de_la_empresa_de_la_demo_nuevo_cuit_si_y_viejo_no():
    c = TestClient(main.app)
    # como en la demo: el empleador está dado de alta en el sindicato
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=SID, cuit=CUIT_EMPRESA_OK_2, razon_social="Metalúrgica del Sur SRL"))
        s.add(Empleador(sindicato_id=SID, cuit=CUIT_MAL, razon_social="Metalúrgica (CUIT viejo)"))
        s.commit()
    antes = _contar(CuentaEmpleador)
    r = c.post("/empresa/registro", data={"cuit": CUIT_MAL, "clave": "clave123"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ingresar-empresa?error=cuit", r.headers
    assert _contar(CuentaEmpleador) == antes
    page = c.get("/ingresar-empresa?error=cuit")
    assert "El CUIT no es válido: revisá los 11 números" in page.text and "E-IDENT-02" in page.text
    r = c.post("/empresa/registro", data={"cuit": CUIT_EMPRESA_OK_2, "clave": "clave123"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/empresa/inicio", r.headers
    assert _contar(CuentaEmpleador) == antes + 1
    print("OK  test_registro_de_la_empresa_de_la_demo_nuevo_cuit_si_y_viejo_no")


def test_registro_de_la_empresa_acepta_cuit_de_persona_fisica():
    c = TestClient(main.app)
    valido = cuit.corregir("20410000103")      # un CUIT de persona física, con su verificador
    assert cuit.es_valido(valido, cuit.PERSONA)
    with db.get_session() as s:
        s.add(Empleador(sindicato_id=SID, cuit=valido, razon_social="Monotributista con empleados"))
        s.commit()
    r = c.post("/empresa/registro", data={"cuit": valido, "clave": "clave123"}, follow_redirects=False)
    assert r.headers["location"] == "/empresa/inicio", r.headers
    print("OK  test_registro_de_la_empresa_acepta_cuit_de_persona_fisica")


# =============================================================================
# 8. Lo que NO se valida: los logins y las referencias
# =============================================================================

def test_los_logins_siguen_andando_con_numeros_invalidos_ya_cargados():
    # trabajador con CUIL inválido y clave
    t = TestClient(main.app)
    r = t.post("/trabajador/login", data={"cuil": SINT_CUIL, "clave": "clave-sint"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/inicio", r.headers
    # administrador cuyo usuario (CUIL) no cumple el módulo 11
    a = TestClient(main.app)
    r = a.post("/admin/login", data={"usuario": SINT_ADMIN, "clave": "admin-viejo"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/inicio", r.headers
    # empresa con CUIT inválido
    e = TestClient(main.app)
    r = e.post("/empresa/login", data={"cuit": SINT_CUIT, "clave": "clave-emp"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/empresa/inicio", r.headers
    # el que ya estaba adentro sigue pudiendo usar el panel
    assert a.get("/admin").status_code == 200
    print("OK  test_los_logins_siguen_andando_con_numeros_invalidos_ya_cargados")


def test_reset_de_clave_busca_el_numero_tal_cual():
    c = _plataforma()
    r = c.post("/plataforma/reset-clave", data={"tipo": "trabajador", "identificador": SINT_CUIL,
                                                "clave_nueva": "otra-clave-9"}, follow_redirects=False)
    assert r.status_code == 303 and "reset=ok" in r.headers["location"], r.headers
    t = TestClient(main.app)
    r = t.post("/trabajador/login", data={"cuil": SINT_CUIL, "clave": "otra-clave-9"}, follow_redirects=False)
    assert r.headers["location"] == "/app/inicio"
    r = c.post("/plataforma/reset-clave", data={"tipo": "sindicato", "identificador": SINT_ADMIN,
                                                "clave_nueva": "otra-clave-8"}, follow_redirects=False)
    assert "reset=ok" in r.headers["location"], r.headers
    print("OK  test_reset_de_clave_busca_el_numero_tal_cual")


def test_criterio_de_notificacion_por_cuil_inexistente_o_sintetico_se_busca_tal_cual():
    c = _admin()
    r = c.post("/admin/notificacion/preview", data={"criterio": "cuil", "valores": [SINT_CUIL]})
    assert r.status_code == 200 and r.json()["cantidad"] == 1, r.text
    r = c.post("/admin/notificacion/preview", data={"criterio": "cuit_empleador", "valores": [SINT_CUIT]})
    assert r.status_code == 200 and r.json()["cantidad"] >= 1, r.text
    r = c.post("/admin/notificacion/preview", data={"criterio": "cuil", "valores": [CUIL_MAL]})
    assert r.status_code == 200 and r.json()["cantidad"] == 0     # no existe: 0, no un error
    print("OK  test_criterio_de_notificacion_por_cuil_inexistente_o_sintetico_se_busca_tal_cual")


# =============================================================================
# 9. Fail-closed: toda ruta con un campo de CUIL/CUIT está clasificada
# =============================================================================

NOMBRES_DE_IDENTIFICADOR = {"cuil", "cuit", "cuit_empleador", "usuario", "identificador"}

# Rutas por las que NACE un número: tienen que llamar al verificador.
PUERTAS = {
    "admin_trabajador_alta", "admin_trabajador_masivo", "admin_usuario_alta", "abm_concepto",
    "admin_empleador_alta", "plataforma_alta_sindicato", "plataforma_editar_sindicato",
    "plataforma_alta_usuario", "plataforma_completar_guardar", "trabajador_registro",
    "empresa_registro", "trabajador_registro_iniciar", "empresa_registro_iniciar",
}
# Rutas que REFERENCIAN un número que ya existe: se busca tal cual, SIN verificador.
REFERENCIAS = {
    "admin_login", "plataforma_login", "trabajador_login", "empresa_login", "entornos_login",
    "plataforma_reset_clave",
}
# Un campo llamado `usuario` que no es un CUIL: el alias de un usuario nominal
# de plataforma ("jperez").
NO_ES_NUMERO = {"plataforma_usuarios_crear"}

LLAMAN_AL_VERIFICADOR = {"_cuil_mal", "_cuit_mal", "_cuit_empresa_mal"}


def _rutas_post_de_main():
    arbol = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            es_post = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                          and d.func.attr in ("post", "put", "patch", "delete") for d in nodo.decorator_list)
            if es_post:
                yield nodo


def _nombres_llamados(nodo):
    return {n.func.id for n in ast.walk(nodo)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def test_toda_ruta_con_un_campo_de_cuil_o_cuit_esta_clasificada():
    sin_clasificar = []
    for f in _rutas_post_de_main():
        args = {a.arg for a in f.args.args + f.args.kwonlyargs}
        if args & NOMBRES_DE_IDENTIFICADOR and f.name not in (PUERTAS | REFERENCIAS | NO_ES_NUMERO):
            sin_clasificar.append(f.name)
    assert not sin_clasificar, (
        "estas rutas reciben un CUIL/CUIT y nadie dijo si es una puerta de alta (exige el "
        "verificador) o una referencia (lo busca tal cual); clasificalas en test_cuit_puertas.py "
        f"y, si nace un número, llamá a _cuil_mal/_cuit_mal: {sorted(sin_clasificar)}")
    print("OK  test_toda_ruta_con_un_campo_de_cuil_o_cuit_esta_clasificada")


def test_las_puertas_llaman_al_verificador_y_las_referencias_no():
    por_nombre = {f.name: f for f in _rutas_post_de_main()}
    faltan = sorted((PUERTAS | REFERENCIAS | NO_ES_NUMERO) - set(por_nombre))
    assert not faltan, f"clasificadas acá pero no existen en main.py: {faltan}"
    sin_verificador = sorted(n for n in PUERTAS
                             if not (_nombres_llamados(por_nombre[n]) & LLAMAN_AL_VERIFICADOR))
    assert not sin_verificador, f"puertas que ya no llaman al verificador: {sin_verificador}"
    con_verificador = sorted(n for n in REFERENCIAS | NO_ES_NUMERO
                             if _nombres_llamados(por_nombre[n]) & LLAMAN_AL_VERIFICADOR)
    assert not con_verificador, (
        "estas rutas solo referencian números que ya existen y no pueden validar el "
        f"verificador (los sintéticos no podrían entrar): {con_verificador}")
    print("OK  test_las_puertas_llaman_al_verificador_y_las_referencias_no")


def test_los_helpers_del_verificador_no_se_pisan_con_un_campo_llamado_cuit():
    """Varias rutas tienen un parámetro `cuit` que tapa el módulo `cuit`: por
    eso llaman a helpers de módulo y no a `cuit.es_valido` directamente."""
    por_nombre = {f.name: f for f in _rutas_post_de_main()}
    for nombre in PUERTAS:
        f = por_nombre[nombre]
        usa_el_modulo = [n for n in ast.walk(f) if isinstance(n, ast.Attribute)
                         and isinstance(n.value, ast.Name) and n.value.id == "cuit"
                         and n.attr in ("es_valido", "digito_verificador", "corregir")]
        assert not usa_el_modulo, f"{nombre} llama a cuit.{usa_el_modulo[0].attr} directo"
    print("OK  test_los_helpers_del_verificador_no_se_pisan_con_un_campo_llamado_cuit")


def test_los_mensajes_de_los_avisos_son_los_del_catalogo_de_errores():
    assert errores.MENSAJES["E-IDENT-01"][1].startswith("El CUIL no es válido: revisá los 11 números")
    assert errores.MENSAJES["E-IDENT-02"][1].startswith("El CUIT no es válido: revisá los 11 números")
    # no es un error de lectura: no habla de la foto
    assert "foto" not in errores.MENSAJES["E-IDENT-01"][1].lower().replace("figura", "")
    print("OK  test_los_mensajes_de_los_avisos_son_los_del_catalogo_de_errores")


# =============================================================================
# 10. static/cuit.js: la cortesía del navegador
# =============================================================================

JS = (RAIZ / "static" / "cuit.js").read_text(encoding="utf-8")


def _lista_js(nombre):
    m = re.search(r"var\s+" + nombre + r"\s*=\s*\[([^\]]*)\]", JS)
    assert m, f"cuit.js no define {nombre}"
    return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]


def test_cuit_js_usa_los_mismos_pesos_y_prefijos_que_cuit_py():
    assert [int(x) for x in _lista_js("PESOS")] == list(cuit.PESOS)
    assert set(_lista_js("PREFIJOS_PERSONA")) == set(cuit.PREFIJOS_PERSONA)
    assert set(_lista_js("PREFIJOS_EMPRESA")) == set(cuit.PREFIJOS_EMPRESA)
    assert len(_lista_js("PREFIJOS_PERSONA")) == len(cuit.PREFIJOS_PERSONA)   # sin repetidos
    print("OK  test_cuit_js_usa_los_mismos_pesos_y_prefijos_que_cuit_py")


def test_cuit_js_el_mensaje_es_el_pedido_y_se_engancha_por_data_cuit():
    assert "El CUIL/CUIT no es válido: revisá los 11 números" in JS
    assert "data-cuit" in JS and "setCustomValidity" in JS and "window" in JS
    assert "CuitMT" in JS
    print("OK  test_cuit_js_el_mensaje_es_el_pedido_y_se_engancha_por_data_cuit")


def _plantillas():
    return sorted((RAIZ / "templates").glob("*.html"))


def test_toda_plantilla_con_data_cuit_carga_cuit_js_con_sello():
    con_marca = []
    for p in _plantillas():
        texto = p.read_text(encoding="utf-8")
        if re.search(r"<input\b[^>]*\bdata-cuit=", texto):
            con_marca.append(p.name)
            assert re.search(r"""<script src="/static/cuit\.js\?v=\{\{ sello_static\('cuit\.js'\) \}\}"></script>""",
                             texto), f"{p.name} marca inputs con data-cuit y no carga cuit.js con sello"
    # las pantallas de las puertas de alta
    assert set(con_marca) == {"admin.html", "plataforma.html", "plataforma_completar.html",
                              "trabajador_login.html", "empresa_login.html"}, con_marca
    print("OK  test_toda_plantilla_con_data_cuit_carga_cuit_js_con_sello")


def test_ninguna_plantilla_carga_cuit_js_sin_sello():
    for p in _plantillas():
        for linea in p.read_text(encoding="utf-8").splitlines():
            if "<script" in linea and "cuit.js" in linea:
                assert "?v={{ sello_static('cuit.js') }}" in linea, (p.name, linea)
    print("OK  test_ninguna_plantilla_carga_cuit_js_sin_sello")


def test_los_valores_de_data_cuit_son_los_tres_conocidos():
    """Solo se miran los <input>: en admin.html hay además un `data-cuit` que
    no tiene nada que ver (la fila de un trámite de empresa lleva su CUIT para
    el filtro de la tabla). cuit.js tampoco lo toca: solo engancha <input>."""
    for p in _plantillas():
        for tag in re.findall(r"<input\b[^>]*\bdata-cuit=[^>]*>", p.read_text(encoding="utf-8")):
            valor = re.search(r'\bdata-cuit="([^"]*)"', tag).group(1)
            assert valor in {"persona", "empresa", "cualquiera"}, (p.name, valor)
    assert 'el.tagName === "INPUT"' in JS and 'input[data-cuit]' in JS     # solo engancha inputs
    print("OK  test_los_valores_de_data_cuit_son_los_tres_conocidos")


def test_solo_las_puertas_llevan_data_cuit_los_logins_no():
    """Marcados: SOLO los inputs de las puertas de la tabla. Un login con
    data-cuit avisaría que el CUIL de un sintético 'no es válido' cuando el
    servidor lo deja entrar."""
    esperados = {
        "admin.html": {("cuit_empleador", "cualquiera"), ("cuil", "persona"), ("cuit", "cualquiera"),
                       ("usuario", "persona")},
        "plataforma.html": {("cuit", "empresa"), ("usuario", "persona")},
        "plataforma_completar.html": {("cuil", "persona")},
        "trabajador_login.html": {("cuil", "persona")},
        "empresa_login.html": {("cuit", "cualquiera")},
    }
    for archivo, esperado in esperados.items():
        texto = (RAIZ / "templates" / archivo).read_text(encoding="utf-8")
        hallados = set()
        for tag in re.findall(r"<input\b[^>]*\bdata-cuit=[^>]*>", texto):
            nombre = re.search(r'\bname="([^"]+)"', tag).group(1)
            tipo = re.search(r'\bdata-cuit="([^"]+)"', tag).group(1)
            hallados.add((nombre, tipo))
        assert hallados == esperado, (archivo, hallados)
    # en los dos logins con registro, el formulario de INGRESO no lleva data-cuit
    for archivo in ("trabajador_login.html", "empresa_login.html"):
        texto = (RAIZ / "templates" / archivo).read_text(encoding="utf-8")
        form = re.search(r'<form[^>]*id="form-login".*?</form>', texto, re.S).group(0)
        assert "data-cuit" not in form, archivo
    for archivo in ("admin_login.html", "plataforma_login.html", "entornos_pin.html"):
        assert "data-cuit" not in (RAIZ / "templates" / archivo).read_text(encoding="utf-8"), archivo
    print("OK  test_solo_las_puertas_llevan_data_cuit_los_logins_no")


def test_las_paginas_sirven_cuit_js_y_el_archivo_existe():
    c = TestClient(main.app)
    for ruta in ("/ingresar", "/ingresar-empresa"):
        html = c.get(ruta).text
        m = re.search(r'/static/cuit\.js\?v=([^"]+)"', html)
        assert m and m.group(1), (ruta, "sin sello")
    r = c.get("/static/cuit.js")
    assert r.status_code == 200 and "CuitMT" in r.text
    print("OK  test_las_paginas_sirven_cuit_js_y_el_archivo_existe")


def _numeros_de_barrido():
    """Muchos números, válidos e inválidos, de todos los tipos y largos."""
    bases = []
    for prefijo in ("20", "23", "24", "25", "26", "27", "30", "33", "34", "10", "21", "31", "00"):
        for dni in ("20279041", "44464097", "12121212", "99999999", "11111111", "30500010"):
            bases.append(prefijo + dni)
    salida = []
    for b in bases:
        for d in "0123456789":
            salida.append(b + d)
    salida += ["", "123", "2020279041", "202027904111", "20-20279041-1", " 20 20279041 1 ",
               "30-44464097-5", "abc", "20.20279041.1", "27999999999", "27999999994"]
    return salida


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado en este sistema")
def test_cuit_js_corrido_en_node_da_lo_mismo_que_python(tmp_path):
    numeros = _numeros_de_barrido()
    tipos = [None, "persona", "empresa"]
    esperado = [[cuit.es_valido(n, t) for t in tipos] for n in numeros]
    guion = tmp_path / "comparar.js"
    guion.write_text(
        "const c = require(process.argv[2]);\n"
        "const numeros = JSON.parse(process.argv[3]);\n"
        "const tipos = [undefined, 'persona', 'empresa'];\n"
        "console.log(JSON.stringify(numeros.map(n => tipos.map(t => c.esValido(n, t)))));\n",
        encoding="utf-8")
    r = subprocess.run(["node", str(guion), str(RAIZ / "static" / "cuit.js"), json.dumps(numeros)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    obtenido = json.loads(r.stdout)
    distintos = [(n, e, o) for n, e, o in zip(numeros, esperado, obtenido) if e != o]
    assert not distintos, f"JS y Python no coinciden en {len(distintos)} de {len(numeros)}: {distintos[:5]}"
    # el barrido tiene de los dos lados, si no no prueba nada
    assert any(e[0] for e in esperado) and not all(e[0] for e in esperado)
    print(f"OK  test_cuit_js_corrido_en_node_da_lo_mismo_que_python ({len(numeros)} números)")


def test_un_cuit_opcional_escrito_con_letras_no_pasa_como_vacio():
    """QA, 2026-10-10: "abc" en el CUIT (opcional) del empleador se tomaba como
    campo vacío: en el alta de trabajador se guardaba "abc" y en el concepto
    quedaba genérico sin aviso. Un texto sin dígitos es un número mal escrito."""
    c = _admin()
    cuil = cuit.siguiente_libre("20456456450")
    antes = _contar(Trabajador)
    r = c.post("/admin/trabajador", data={"cuil": cuil, "nombre": "Con Letras",
                                          "cuit_empleador": "abc", **DOM}, follow_redirects=False)
    assert "err=cuitempleador" in r.headers["location"], r.headers
    assert _contar(Trabajador) == antes
    antes = _contar(Concepto)
    r = c.post("/admin/concepto", data={"codigo": "LETRAS", "nombre": "Letras", "tipo": "ingreso",
                                        "remunerativo": "si", "cuit_empleador": "abc"},
               follow_redirects=False)
    assert "error=cuitconcepto" in r.headers["location"], r.headers
    assert _contar(Concepto) == antes
    print("OK  test_un_cuit_opcional_escrito_con_letras_no_pasa_como_vacio")


# =============================================================================
# Puertas que encontró el revisor general (2026-10-10): el aprendizaje, la
# importación de CUIT desde conceptos y la confirmación de un concepto
# pendiente también hacen NACER un CUIT confirmado.
# =============================================================================

def test_aprender_aplicar_no_da_de_alta_un_concepto_con_cuit_invalido():
    c = _admin()
    antes = _contar(Concepto, Concepto.sindicato_id == SID)
    r = c.post("/admin/aprender/aplicar", json={"aprobados": [
        {"codigo": "AP-MAL", "descripcion": "Leído mal", "tipo": "ingreso",
         "cuit_empleador": "30-12345678-9"},                          # inválido
        {"codigo": "AP-BIEN", "descripcion": "Leído bien", "tipo": "ingreso",
         "cuit_empleador": CUIT_EMPRESA_OK},
        {"codigo": "AP-GEN", "descripcion": "Genérico", "tipo": "ingreso"},
    ]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["altas"] == 2 and data["cuit_invalidos"] == ["AP-MAL"], data
    assert _contar(Concepto, Concepto.sindicato_id == SID) == antes + 2
    assert _contar(Concepto, Concepto.codigo == "AP-MAL") == 0
    print("OK  test_aprender_aplicar_no_da_de_alta_un_concepto_con_cuit_invalido")


def test_importar_cuits_de_conceptos_saltea_los_invalidos():
    with db.get_session() as s:
        s.add(Concepto(sindicato_id=SID, codigo="IMP-MAL", nombre="x", tipo="ingreso",
                       cuit_empleador="30123456789"))                  # inválido
        s.add(Concepto(sindicato_id=SID, codigo="IMP-BIEN", nombre="y", tipo="ingreso",
                       cuit_empleador=cuit.formatear("30712345671")))  # válido, con guiones
        s.commit()
    assert cuit.es_valido("30712345671") and not cuit.es_valido("30123456789")
    c = _admin()
    r = c.post("/admin/empleador/importar-cuits", follow_redirects=False)
    loc = r.headers["location"]
    assert "cuitinvalidos=" in loc and "30123456789" in loc, loc
    assert _contar(Empleador, Empleador.sindicato_id == SID, Empleador.cuit == "30123456789") == 0
    # El válido entra normalizado, y una segunda corrida no lo duplica.
    assert _contar(Empleador, Empleador.sindicato_id == SID, Empleador.cuit == "30712345671") == 1
    c.post("/admin/empleador/importar-cuits", follow_redirects=False)
    assert _contar(Empleador, Empleador.sindicato_id == SID, Empleador.cuit == "30712345671") == 1
    assert "E-IDENT-02" in c.get(loc).text
    print("OK  test_importar_cuits_de_conceptos_saltea_los_invalidos")


def test_confirmar_un_concepto_pendiente_con_cuit_invalido_se_frena():
    with db.get_session() as s:
        malo = Concepto(sindicato_id=SID, codigo="CONF-MAL", nombre="x", tipo="ingreso",
                        cuit_empleador="30123456789", pendiente_revision=True)
        bueno = Concepto(sindicato_id=SID, codigo="CONF-BIEN", nombre="y", tipo="ingreso",
                         cuit_empleador=CUIT_EMPRESA_OK, pendiente_revision=True)
        s.add(malo); s.add(bueno); s.commit(); s.refresh(malo); s.refresh(bueno)
        id_malo, id_bueno = malo.id, bueno.id
    c = _admin()
    r = c.post("/admin/concepto/confirmar", data={"id": id_malo}, follow_redirects=False)
    assert "error=cuitconfirmar" in r.headers["location"], r.headers
    r = c.post("/admin/concepto/confirmar", data={"id": id_bueno}, follow_redirects=False)
    assert "error=" not in r.headers["location"]
    with Session(db.engine) as s:
        assert s.get(Concepto, id_malo).pendiente_revision is True
        assert s.get(Concepto, id_bueno).pendiente_revision is False
    assert "E-IDENT-02" in c.get("/admin?error=cuitconfirmar").text
    print("OK  test_confirmar_un_concepto_pendiente_con_cuit_invalido_se_frena")


def test_los_criterios_de_notificacion_comparan_normalizado():
    """El admin tipea con o sin guiones y las filas viejas pueden tener el
    CUIT del empleador guardado de las dos formas."""
    cuil_a, cuil_b = cuit.siguiente_libre("20515151510"), cuit.siguiente_libre("20525252520")
    with db.get_session() as s:
        s.add(Trabajador(sindicato_id=SID, cuil=cuil_a, activo=True,
                         cuit_empleador=cuit.formatear("30716161619")))   # guardado con guiones (legacy)
        s.add(Trabajador(sindicato_id=SID, cuil=cuil_b, activo=True, cuit_empleador="30716161619"))
        s.commit()
    for tipeado in ("30716161619", "30-71616161-9"):
        assert set(db.resolver_destinatarios(SID, "cuit_empleador", [tipeado])) == {cuil_a, cuil_b}, tipeado
    assert db.resolver_destinatarios(SID, "cuil", [cuit.formatear(cuil_a)]) == [cuil_a]
    print("OK  test_los_criterios_de_notificacion_comparan_normalizado")


# Todo lugar de main.py y db.py que ESCRIBE un CUIL/CUIT en un modelo de
# identidad, y por qué está bien. Si aparece uno nuevo, este test falla: hay
# que decidir si es una puerta (y entonces validar) o una referencia/derivado.
ESCRITURAS_DE_IDENTIDAD = {
    "main.api_validar": "lectura: concepto PENDIENTE con el CUIT que leyó la IA (se valida al confirmar)",
    "main.admin_trabajador_alta": "puerta",
    "main.admin_trabajador_masivo": "puerta",
    "main.admin_usuario_alta": "puerta",
    "main.abm_concepto": "puerta",
    "main.admin_empleador_alta": "puerta",
    "main.aprender_aplicar": "puerta",
    "main.plataforma_alta_sindicato": "puerta",
    "main.plataforma_alta_usuario": "puerta",
    "main.plataforma_editar_sindicato": "puerta",
    "main.empresa_registro": "puerta",
    "db.crear_usuario_plataforma": "no es un CUIL: usuario nominal de plataforma",
    "db.sembrar_superadmins_iniciales": "no es un CUIL: usuario nominal de plataforma",
    "db.completar_usuario_plataforma": "derivado: lo llama /plataforma/completar, que valida",
    "db.importar_cuits_de_conceptos": "puerta (saltea los inválidos)",
    "db.asegurar_cuenta": "derivado: la persona de un empadronamiento o de un registro ya validados",
    "db.guardar_suscripcion_push": "derivado: el CUIL de la sesión firmada",
}
_MODELOS_DE_IDENTIDAD = {"Trabajador", "CuentaTrabajador", "UsuarioSindicato", "UsuarioPlataforma",
                         "Empleador", "CuentaEmpleador", "Sindicato", "Concepto"}
_CAMPOS_DE_IDENTIDAD = {"cuil", "cuit", "cuit_empleador", "usuario"}
_VERIFICADORES = {"_cuil_mal", "_cuit_mal", "_cuit_empresa_mal", "es_valido"}


def _escrituras_de_identidad():
    encontradas = {}
    for archivo in ("main.py", "db.py"):
        arbol = ast.parse((RAIZ / archivo).read_text(encoding="utf-8"))
        for fn in ast.walk(arbol):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            escribe = False
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in _MODELOS_DE_IDENTIDAD
                        and {k.arg for k in n.keywords} & _CAMPOS_DE_IDENTIDAD):
                    escribe = True
                if isinstance(n, ast.Assign):
                    for destino in n.targets:
                        for e in (destino.elts if isinstance(destino, ast.Tuple) else [destino]):
                            if isinstance(e, ast.Attribute) and e.attr in _CAMPOS_DE_IDENTIDAD:
                                escribe = True
            if escribe:
                llamadas = {(n.func.id if isinstance(n.func, ast.Name) else
                             n.func.attr if isinstance(n.func, ast.Attribute) else "")
                            for n in ast.walk(fn) if isinstance(n, ast.Call)}
                encontradas[f"{archivo[:-3]}.{fn.name}"] = llamadas
    return encontradas


def test_toda_escritura_de_un_cuil_o_cuit_esta_clasificada():
    encontradas = _escrituras_de_identidad()
    sin_decidir = sorted(set(encontradas) - set(ESCRITURAS_DE_IDENTIDAD))
    assert not sin_decidir, ("estas funciones escriben un CUIL/CUIT y nadie decidió si son una "
                             "puerta (validar) o un derivado: " + ", ".join(sin_decidir))
    sobran = sorted(set(ESCRITURAS_DE_IDENTIDAD) - set(encontradas))
    assert not sobran, f"ya no escriben un CUIL/CUIT, sacalas de la lista: {sobran}"
    sin_verificar = sorted(f for f, motivo in ESCRITURAS_DE_IDENTIDAD.items()
                           if motivo.startswith("puerta") and not encontradas[f] & _VERIFICADORES)
    assert not sin_verificar, f"son puertas y no llaman al verificador: {sin_verificar}"
    print("OK  test_toda_escritura_de_un_cuil_o_cuit_esta_clasificada")

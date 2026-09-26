"""Ninguna ruta de la app entrega nada a quien no inició sesión.

Recorre TODAS las rutas registradas en la app (no una lista escrita a mano)
y las pide sin sesión, dos veces: limpio, y con las cookies que un atacante
puede fabricar (las planas `cuil_trab`/`cuit_emp`/`sind_elegido`, un pase de
entornos y tokens de sesión falsos). Corre como Pruebas, que es el entorno
con más rutas vivas (`/entornos` y sus solapas).

Es fail-closed: una ruta NUEVA que responda algo que no sea un rechazo, una
redirección a un ingreso o la pantalla de login hace fallar el test, aunque
nadie se haya acordado de revisarla. Si es pública a propósito, se agrega a
PUBLICAS con el motivo.

Contexto (2026-09-26): `/` servía la pantalla de subir recibos sin sesión
desde el principio. Correr con:
.venv/Scripts/python.exe -m pytest test_rutas_sin_sesion.py -q
"""

import os
os.environ["ENTORNO"] = "pruebas"

import re
import types
import typing

import pytest
from fastapi import UploadFile
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import db
import main

db.crear_tablas()

# Públicas a propósito: (método, path) -> por qué.
PUBLICAS = {
    ("GET", "/"): "landing con las tres entradas",
    ("GET", "/sw.js"): "service worker de la PWA",
    ("GET", "/healthz"): "health check de Render, no toca la base",
    ("GET", "/readyz"): "SELECT 1, para mirar a mano",
    ("GET", "/api/version"): "versión de cada app, la lee /entornos de otro entorno",
    ("GET", "/api/push/clave-publica"): "clave VAPID pública",
    ("GET", "/v/{token}"): "verificación pública de la credencial por QR",
    ("GET", "/ingresar"): "login del trabajador",
    ("GET", "/ingresar-empresa"): "login de la empresa",
    ("GET", "/logo/{sindicato_id}"): "logo del gremio, va en los logins",
    ("GET", "/firma/{sindicato_id}"): "firma de la credencial, la muestra /v/",
    ("GET", "/logo-plataforma"): "logo de Colm3na",
    ("GET", "/logo-plataforma-oscuro"): "logo de Colm3na",
    ("GET", "/noticia-imagen/{noticia_id}/{n}"): "imagen de noticia (contenido público del gremio)",
    ("GET", "/beneficio-imagen/{beneficio_id}"): "imagen de beneficio (ídem)",
}

# Pantallas con sesión que, sin ella, responden 200 con el FORMULARIO de
# ingreso en vez de redirigir. Se verifica que sea el login y no el panel.
DEVUELVEN_LOGIN = {
    "/admin": "/admin/login",
    "/admin/inicio": "/admin/login",
    "/admin/dashboard": "/admin/login",
    "/admin/encuesta/{encuesta_id}/resultados": "/admin/login",
    "/plataforma": "/plataforma/login",
    "/plataforma/inicio": "/plataforma/login",
    "/entornos": "/entornos/",  # la puerta del PIN / login nominal
}

# Adjuntos: con un id inexistente dan 404 antes de mirar la sesión, así que
# el recorrido no los puede juzgar. Con un id real exigen ser el admin del
# mismo sindicato o un destinatario (revisado en el código, 2026-09-26).
ADJUNTOS = {
    "/notificacion-adjunto/{notificacion_id}",
    "/notificacion-empresa-adjunto/{notificacion_empleador_id}",
    "/tramite-respuesta-archivo/{respuesta_id}",
    "/tramite-nota-adjunto/{nota_id}",
    "/tramite-empresa-respuesta-archivo/{respuesta_id}",
    "/tramite-empresa-nota-adjunto/{nota_id}",
}

# Una redirección sin sesión solo puede llevar a un ingreso, a la puerta de
# entornos o a una portada (que a su vez manda al ingreso).
DESTINOS_VALIDOS = {"/admin", "/plataforma", "/plataforma/inicio", "/ingresar",
                    "/ingresar-empresa", "/app/inicio", "/empresa/inicio", "/entornos"}

COOKIES_FALSAS = {
    "cuil_trab": "20111111119", "cuit_emp": "30111222339",
    "sind_elegido": "1", "sind_elegido_emp": "1",
    "pase_entornos": "falso.falso",
    "sesion_trabajador": "x.y", "sesion_sindicato": "abc",
    "sesion_plataforma": "1", "sesion_empleador": "e30.firma",
}


def _valor(tipo):
    origen = typing.get_origin(tipo)
    if origen in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tipo) if a is not type(None)]
        return _valor(args[0]) if args else None
    if origen is list or tipo is list:
        return []
    if tipo is int:
        return 1
    if tipo is float:
        return 1.0
    if tipo is bool:
        return False
    if tipo is dict or origen is dict:
        return {}
    return "1"


def _pedir(cliente, ruta, metodo):
    """Pide la ruta con parámetros bien formados, para que el rechazo lo dé
    el control de sesión y no la validación de FastAPI (un 422 no prueba
    nada: el endpoint ni siquiera corrió)."""
    path = re.sub(r"\{[^}]+\}", "1", ruta.path)
    r = cliente.request(metodo, path)
    if r.status_code != 422:
        return r
    dep = ruta.dependant
    params = {(p.alias or p.name): _valor(p.type_) for p in dep.query_params}
    datos, archivos, cuerpo = {}, {}, None
    for p in dep.body_params:
        nombre = p.alias or p.name
        if p.type_ is UploadFile or UploadFile in typing.get_args(p.type_):
            archivos[nombre] = ("a.png", b"x", "image/png")
        elif type(p.field_info).__name__ in ("Form", "File"):
            datos[nombre] = _valor(p.type_)
        elif len(dep.body_params) == 1 and p.type_ is dict:
            cuerpo = {"recibo": {}}
        else:
            cuerpo = {**(cuerpo or {}), nombre: _valor(p.type_)}
    if datos or archivos:
        return cliente.request(metodo, path, params=params, data=datos, files=archivos or None)
    return cliente.request(metodo, path, params=params, json=cuerpo)


def _rutas():
    for ruta in main.app.routes:
        if isinstance(ruta, APIRoute):
            for metodo in sorted(ruta.methods - {"HEAD"}):
                yield ruta, metodo


def _problema(ruta, metodo, r):
    """None si la respuesta es un rechazo aceptable; si no, qué está mal."""
    if (metodo, ruta.path) in PUBLICAS:
        return None
    s = r.status_code
    if s in (401, 403):
        return None
    if s == 400 and (r.json().get("codigo") or "").startswith("E-SESION"):
        return None
    if s in (302, 303, 307):
        destino = r.headers.get("location", "").split("?")[0].split("#")[0]
        return None if destino in DESTINOS_VALIDOS else f"redirige a {destino!r}"
    if s == 404 and ruta.path in ADJUNTOS:
        return None
    if s == 200 and metodo == "GET" and ruta.path in DEVUELVEN_LOGIN:
        return None if DEVUELVEN_LOGIN[ruta.path] in r.text else "200 sin formulario de ingreso"
    if s == 200 and metodo in ("POST", "PUT", "DELETE") and ruta.path.endswith(("/login", "/registro", "/pin")):
        return None
    return f"{s}: {r.text[:120]!r}"


@pytest.mark.parametrize("cookies", [{}, COOKIES_FALSAS], ids=["limpio", "cookies-falsas"])
def test_ninguna_ruta_entrega_nada_sin_sesion(cookies):
    cliente = TestClient(main.app, raise_server_exceptions=False, follow_redirects=False)
    for k, v in cookies.items():
        cliente.cookies.set(k, v)
    problemas = []
    for ruta, metodo in _rutas():
        motivo = _problema(ruta, metodo, _pedir(cliente, ruta, metodo))
        if motivo:
            problemas.append(f"{metodo} {ruta.path} -> {motivo}")
    assert not problemas, "Rutas que responden sin sesión:\n" + "\n".join(problemas)


def test_el_recorrido_cubre_toda_la_app():
    # Si algún día se mudan rutas a un APIRouter o a otra app montada, el
    # recorrido tiene que seguir viéndolas; menos de 200 es que se perdió algo.
    assert sum(1 for _ in _rutas()) > 200


def test_las_publicas_siguen_existiendo():
    # Una entrada vieja en PUBLICAS que ya no existe es permiso de más
    # esperando a la próxima ruta que reuse ese path.
    vivas = {(m, r.path) for r, m in _rutas()}
    assert set(PUBLICAS) <= vivas, set(PUBLICAS) - vivas

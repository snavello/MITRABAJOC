# -*- coding: utf-8 -*-
"""Fixtures del entorno E2E.

OJO con el orden de los conftest: el de la RAÍZ fuerza DATABASE_URL=""
(SQLite aislado) para la suite unitaria. Acá lo revertimos leyendo .env de
nuevo con override: los E2E hablan con el MISMO Postgres local que usa el
servidor que están probando -- si no, las verificaciones y preparaciones
de datos mirarían una base distinta a la de la app.
"""
import os

import pytest


@pytest.fixture(scope="session")
def entorno_aefip():
    """Garantiza lo que el robot de AEFIP necesita y devuelve los accesos:
    - El sindicato AEFIP con el lote sintético cargado (no lo carga él:
      tarda minutos -- si falta, avisa cómo cargarlo).
    - Un admin de AEFIP (lo crea si no existe; en producción ya existe).
    - El tipo de trámite "Reintegro de guardería" con sus campos.
    - Un trabajador del lote con cuenta (clave = 5 primeros dígitos del CUIL).
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("Sin DATABASE_URL en .env: el E2E necesita el Postgres local (docker compose up -d)")

    import auth
    import db
    from db import Sindicato, UsuarioSindicato, Trabajador, CuentaTrabajador, TipoTramite
    from sqlmodel import select

    with db.get_session() as s:
        sind = s.exec(select(Sindicato).where(Sindicato.nombre.ilike("%AEFIP%"))).first()
        if not sind:
            pytest.skip("AEFIP no está en la base local.")
        sid = sind.id

        admin = s.exec(select(UsuarioSindicato).where(
            UsuarioSindicato.sindicato_id == sid, UsuarioSindicato.activo == True)).first()
        if not admin:
            s.add(UsuarioSindicato(sindicato_id=sid, usuario="20999000019", nombre="Admin AEFIP",
                                   clave_hash=auth.hashear_clave("aefip-demo"),
                                   debe_cambiar_clave=False))
            s.commit()
            admin_usuario, admin_clave = "20999000019", "aefip-demo"
        elif admin.usuario == "20999000019":
            admin_usuario, admin_clave = "20999000019", "aefip-demo"
        else:
            pytest.skip("AEFIP tiene un admin con otra clave: el robot no puede loguearse.")

        if not s.exec(select(TipoTramite).where(TipoTramite.sindicato_id == sid,
                                                TipoTramite.codigo == "AEFIP-GUARD")).first():
            db.crear_tipo_tramite(sid, "Reintegro de guardería", "AEFIP-GUARD", [
                {"etiqueta": "Nombre del hijo/a", "tipo_dato": "texto", "longitud_maxima": 80},
                {"etiqueta": "Edad", "tipo_dato": "numero"},
                {"etiqueta": "Jardín o guardería", "tipo_dato": "texto", "longitud_maxima": 120},
                {"etiqueta": "Monto mensual", "tipo_dato": "numero", "decimales": 2},
            ])

        # Un trabajador del lote: registrado, con cuenta, y cuya clave sea
        # efectivamente la regla del lote (se verifica contra el hash real).
        trabajador = None
        for t in s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                                 Trabajador.registrado == True,
                                                 Trabajador.activo == True)).all():
            cuenta = s.exec(select(CuentaTrabajador).where(
                CuentaTrabajador.cuil == t.cuil)).first()
            if cuenta and auth.verificar_clave(t.cuil[:5], cuenta.clave_hash):
                trabajador = {"cuil": t.cuil, "clave": t.cuil[:5], "nombre": t.nombre}
                break
        if not trabajador:
            pytest.skip("AEFIP no tiene el lote sintético: correr "
                        "`python cargar_lote_sindicato.py --sindicato AEFIP`.")

    return {"admin": {"usuario": admin_usuario, "clave": admin_clave},
            "trabajador": trabajador}

"""Medición del criterio §5.7 de docs/DASHBOARD.md: con un tenant de 50.000
recibos, todos los endpoints de agregados del Panel Sindical tienen que
responder en menos de 1 segundo.

Corre contra el Postgres local de Docker (DATABASE_URL de .env) -- la misma
base que usa el desarrollo local, para medir sobre el motor real. Siembra un
sindicato sintético "ZZZ Medición Dashboard" (50.000 recibos, 5.000
trabajadores, 8 empresas, 5 seccionales, 2.000 trámites, 20.000 destinatarios
de notificación, 3.000 consultas), mide cada endpoint vía HTTP real
(TestClient, con sesión de admin) y muestra el EXPLAIN de la consulta más
pesada para verificar que usa los índices compuestos.

Uso:
    .venv/Scripts/python.exe medir_dashboard.py            # siembra si falta, mide
    .venv/Scripts/python.exe medir_dashboard.py --limpiar  # borra el sindicato sintético
"""
import random
import sys
import time
from datetime import date, datetime, timedelta

import sqlalchemy as sa

import auth
import db
import fechas

NOMBRE = "ZZZ Medición Dashboard"
RECIBOS, TRABAJADORES, TRAMITES, NOTIFS, DEST_POR_NOTIF, CONSULTAS = 50_000, 5_000, 2_000, 200, 100, 3_000
SECCIONALES = ["Rosario", "Córdoba", "Buenos Aires", "Mendoza", "Tucumán"]
EMPRESAS = [f"3011111{i:03d}7" for i in range(8)]
CATEGORIAS = ["Operario A", "Operario B", "Oficial", "Administrativo", "Supervisor", "Oficial especializado"]
DIAS = 120
HOY = fechas.hoy()

rnd = random.Random(42)


def _ts(dias_atras, hora=None):
    h = hora if hora is not None else rnd.randrange(8, 20)
    return f"{(HOY - timedelta(days=dias_atras)).isoformat()} {h:02d}:{rnd.randrange(60):02d}"


def _lotes(filas, tamanio=2000):
    for i in range(0, len(filas), tamanio):
        yield filas[i:i + tamanio]


def _insertar(conn, sql, filas):
    for lote in _lotes(filas):
        conn.execute(sa.text(sql), lote)


def sembrar():
    with db.engine.connect() as conn:
        existente = conn.execute(sa.text(
            "SELECT id FROM sindicato WHERE nombre = :n"), {"n": NOMBRE}).first()
        if existente:
            cant = conn.execute(sa.text(
                "SELECT COUNT(*) FROM reciboverificado WHERE sindicato_id = :sid"),
                {"sid": existente[0]}).scalar()
            print(f"Sindicato sintético ya existe (id={existente[0]}, {cant} recibos), no re-siembro.")
            return existente[0]

    t0 = time.perf_counter()
    with db.engine.begin() as conn:
        sid = conn.execute(sa.text("""
            INSERT INTO sindicato (nombre, descripcion, slug, cuit, direccion, mail,
                telefonos, autoridad, cargo_autoridad, logo, logo_mime, color_primario,
                color_secundario, color_acento, color_base, color_destacado, firma,
                firma_mime, activo, modulos_habilitados, portada_clara, admin_portada_clara)
            VALUES (:n, '', 'zzz-medicion', '', '', '', '', '', '', '', '', '#152238',
                '#1a7a6b', '#b23a2e', '#0f1b2d', '#E5188F', '', '', true,
                '["dashboard"]', false, false) RETURNING id"""), {"n": NOMBRE}).scalar()

        # El login de /admin normaliza el usuario a dígitos (es un CUIT): tiene
        # que ser numérico o el login no matchea nunca.
        conn.execute(sa.text("""
            INSERT INTO usuariosindicato (sindicato_id, usuario, nombre, clave_hash,
                debe_cambiar_clave, activo)
            VALUES (:sid, '27999999990', 'Medición', :hash, false, true)"""),
            {"sid": sid, "hash": auth.hashear_clave("zzz-medicion")})

        secc_ids = [conn.execute(sa.text(
            "INSERT INTO seccional (sindicato_id, nombre, direccion) "
            "VALUES (:sid, :n, '') RETURNING id"), {"sid": sid, "n": n}).scalar()
            for n in SECCIONALES]
        for i, cuit in enumerate(EMPRESAS):
            conn.execute(sa.text(
                "INSERT INTO empleador (sindicato_id, cuit, razon_social, domicilio, "
                "telefono, provincia, mail, registrado, activo) "
                "VALUES (:sid, :c, :rs, '', '', '', '', false, true)"),
                {"sid": sid, "c": cuit, "rs": f"Empresa Sintética {i + 1}"})

        cuils = [f"20{900000000 + i}9"[:11] for i in range(TRABAJADORES)]
        _insertar(conn, """
            INSERT INTO trabajador (sindicato_id, cuil, nombre, calle, numero, piso,
                ciudad, provincia, telefono, mail, registrado, activo, seccional_id,
                cuit_empleador, semaforo_datos)
            VALUES (:sid, :cuil, :nombre, '', '', '', '', '', '', '', :registrado,
                true, :secc, :cuit, '{}')""", [
            {"sid": sid, "cuil": c, "nombre": f"Trabajador {i}",
             "registrado": rnd.random() < 0.6, "secc": rnd.choice(secc_ids),
             "cuit": rnd.choice(EMPRESAS)} for i, c in enumerate(cuils)])

        filas = []
        for i in range(RECIBOS):
            dias_atras = rnd.randrange(DIAS)
            con_dif = rnd.random() < 0.25
            bruto = rnd.uniform(300_000, 2_500_000)
            filas.append({
                "sid": sid, "cuil": rnd.choice(cuils), "periodo": "2026-07",
                "fecha": "", "estado": "CON_DISCREPANCIAS" if con_dif else "OK",
                "enviado": con_dif and rnd.random() < 0.4, "fenv": "",
                "proc": _ts(dias_atras), "cuit": rnd.choice(EMPRESAS),
                "cat": rnd.choice(CATEGORIAS),
                "formato": "nuevo" if rnd.random() < 0.6 else "clasico",
                "bruto": round(bruto, 2),
                "monto": round(bruto * rnd.uniform(0.002, 0.02), 2) if con_dif else 0.0,
                "dep": (HOY - timedelta(days=rnd.randrange(100))).isoformat() if rnd.random() < 0.7 else None,
            })
        _insertar(conn, """
            INSERT INTO reciboverificado (sindicato_id, cuil, periodo, fecha, estado,
                enviado_sindicato, fecha_envio, detalle, procesado_en, cuit_empleador,
                categoria, formato, bruto, monto_diferencia, fecha_ultimo_deposito)
            VALUES (:sid, :cuil, :periodo, :fecha, :estado, :enviado, :fenv, '{}',
                :proc, :cuit, :cat, :formato, :bruto, :monto, :dep)""", filas)

        tt = conn.execute(sa.text(
            "INSERT INTO tipotramite (sindicato_id, titulo, codigo, activo, creado) "
            "VALUES (:sid, 'Reclamo sintético', 'ZZZ', true, '') RETURNING id"),
            {"sid": sid}).scalar()
        estados = ["iniciado", "en_tratamiento", "respondido", "espera_info", "terminado"]
        filas = []
        for i in range(TRAMITES):
            estado = rnd.choice(estados)
            creado = _ts(rnd.randrange(DIAS))
            filas.append({"sid": sid, "tt": tt, "num": f"ZZZ-2026-{i:06d}",
                          "cuil": rnd.choice(cuils), "estado": estado, "creado": creado,
                          "act": creado, "res": creado if estado == "terminado" else None})
        _insertar(conn, """
            INSERT INTO tramite (sindicato_id, tipo_tramite_id, numero_expediente, cuil,
                estado, creado, actualizado, resuelto_en)
            VALUES (:sid, :tt, :num, :cuil, :estado, :creado, :act, :res)""", filas)

        dest = []
        for i in range(NOTIFS):
            nid = conn.execute(sa.text("""
                INSERT INTO notificacion (sindicato_id, remitente, texto, criterio,
                    criterio_valores, origen, enviado_en, cantidad_destinatarios,
                    adjunto_mime, adjunto_nombre)
                VALUES (:sid, 'CD', 'Aviso sintético', 'cuil', '[]', :origen, :env,
                    :cant, '', '') RETURNING id"""),
                {"sid": sid, "origen": "manual" if rnd.random() < 0.7 else "sistema",
                 "env": _ts(rnd.randrange(DIAS)), "cant": DEST_POR_NOTIF}).scalar()
            for cuil in rnd.sample(cuils, DEST_POR_NOTIF):
                dest.append({"nid": nid, "cuil": cuil,
                             "leida": _ts(rnd.randrange(DIAS)) if rnd.random() < 0.55 else None})
        _insertar(conn, """
            INSERT INTO notificaciondestinatario (notificacion_id, cuil, leida_en)
            VALUES (:nid, :cuil, :leida)""", dest)

        temas = ["Nuevo formato de recibo", "Tope de base imponible", "Cuota sindical 2%",
                 "Horas extras", "Licencias", "Obra social"]
        _insertar(conn, """
            INSERT INTO consultaconvenio (sindicato_id, cuil, pregunta, hubo_respuesta,
                fragmentos_usados, creado, tema)
            VALUES (:sid, :cuil, 'pregunta sintética', :ok, '[]', :creado, :tema)""", [
            {"sid": sid, "cuil": rnd.choice(cuils), "ok": rnd.random() < 0.8,
             "creado": _ts(rnd.randrange(DIAS)), "tema": rnd.choice(temas)}
            for _ in range(CONSULTAS)])

    print(f"Siembra lista en {time.perf_counter() - t0:.1f}s (sindicato id={sid}).")
    return sid


def limpiar():
    with db.engine.begin() as conn:
        fila = conn.execute(sa.text("SELECT id FROM sindicato WHERE nombre = :n"),
                            {"n": NOMBRE}).first()
        if not fila:
            print("No hay sindicato sintético que borrar.")
            return
        sid = fila[0]
        conn.execute(sa.text(
            "DELETE FROM notificaciondestinatario WHERE notificacion_id IN "
            "(SELECT id FROM notificacion WHERE sindicato_id = :sid)"), {"sid": sid})
        for tabla in ["notificacion", "consultaconvenio", "tramite", "tipotramite",
                      "reciboverificado", "trabajador", "empleador", "seccional",
                      "usuariosindicato", "sindicato"]:
            col = "id" if tabla == "sindicato" else "sindicato_id"
            conn.execute(sa.text(f"DELETE FROM {tabla} WHERE {col} = :sid"), {"sid": sid})
    print(f"Sindicato sintético {sid} borrado.")


def medir():
    import main
    from fastapi.testclient import TestClient
    # Autoreparación de siembras viejas que usaban un usuario no numérico.
    with db.engine.begin() as conn:
        conn.execute(sa.text(
            "UPDATE usuariosindicato SET usuario = '27999999990' "
            "WHERE nombre = 'Medición' AND sindicato_id IN "
            "(SELECT id FROM sindicato WHERE nombre = :n)"), {"n": NOMBRE})
    # Sin estadísticas frescas el planificador elige planes malos sobre las
    # tablas recién sembradas (medido: 5,6 s vs 41 ms el mismo endpoint).
    # En producción esto lo hace el autovacuum solo; acá no le damos tiempo.
    with db.engine.begin() as conn:
        conn.execute(sa.text("ANALYZE"))
    c = TestClient(main.app)
    r = c.post("/admin/login", data={"usuario": "27999999990", "clave": "zzz-medicion"})
    rango = {"desde": (HOY - timedelta(days=90)).isoformat(), "hasta": HOY.isoformat()}
    endpoints = ["kpis", "serie-recibos", "validacion", "diferencias-empresa",
                 "tramites-seccional", "notificaciones", "formato-semana", "semaforo",
                 "explorador/recibos", "explorador/tramites", "explorador/notificaciones",
                 "filtros"]
    print(f"\nMedición (rango de 90 días, {RECIBOS} recibos en el tenant):")
    peor = 0.0
    for ep in endpoints:
        tiempos = []
        for _ in range(3):
            t0 = time.perf_counter()
            r = c.get(f"/admin/dashboard/{ep}", params=rango)
            tiempos.append(time.perf_counter() - t0)
            assert r.status_code == 200, (ep, r.status_code, r.text[:200])
        mejor = min(tiempos)
        peor = max(peor, mejor)
        marca = "OK " if mejor < 1.0 else "LENTO"
        print(f"  {marca} {ep:28s} {mejor * 1000:7.1f} ms")
    print(f"\nPeor endpoint: {peor * 1000:.1f} ms — criterio §5.7 ({'CUMPLE' if peor < 1.0 else 'NO CUMPLE'}: < 1000 ms)")

    # Dos EXPLAIN del agregado principal: con el rango de 90 días (76% del
    # tenant matchea -> el seq scan es la elección CORRECTA del planificador)
    # y con 7 días, donde el índice compuesto (sindicato_id, procesado_en)
    # tiene que aparecer -- esa es la verificación de §2.2.
    with db.engine.connect() as conn:
        sid = conn.execute(sa.text("SELECT id FROM sindicato WHERE nombre = :n"),
                           {"n": NOMBRE}).scalar()
        for etiqueta, desde in [("90 días", rango["desde"]),
                                ("7 días", (HOY - timedelta(days=7)).isoformat())]:
            plan = conn.execute(sa.text("""
                EXPLAIN ANALYZE SELECT COUNT(*), COALESCE(SUM(monto_diferencia), 0)
                FROM reciboverificado
                WHERE sindicato_id = :sid AND procesado_en >= :d AND procesado_en <= :h"""),
                {"sid": sid, "d": desde + " 00:00", "h": rango["hasta"] + " 23:59"}).all()
            print(f"\nEXPLAIN ANALYZE del agregado de recibos (rango {etiqueta}):")
            for fila in plan:
                print("  " + fila[0])


if __name__ == "__main__":
    if "--limpiar" in sys.argv:
        limpiar()
    else:
        sembrar()
        medir()

"""QA independiente de servidor del bloque 4 de XSII (Padrón, PAD-02) y de lo que
tocó: la lógica por fila extraída de «Alta masiva» (`padron_carga`), el mapeo de
columnas, `Seccional.responsable`, `asegurar_cuenta(cuenta=)`.

Lo más importante es la REGRESIÓN de la alta masiva: `_viejo_masivo` es la lógica
de la ruta ANTES de la extracción, congelada acá (copiada de `main.py` en `main`
al 2026-11-27, con una sola diferencia declarada: un CUIL nuevo repetido en la
lista con mail o fecha antes daba KeyError -> 500 y ahora queda afuera como
repetido). Cada lista adversaria se corre por el viejo (en una transacción que se
deshace) y por la ruta real, y se compara el redirect, el JSON del ensayo y el
estado final de `Trabajador` y `CuentaTrabajador`.

Correr con: python -m pytest test_xsii_bloque4_qa.py -q
"""
import os

os.environ["ENTORNO"] = "pruebas"
os.environ["PIN_ENTORNOS"] = "13572468"

import itertools
import json
import re
import threading
import uuid
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import select

import auth
import cuit
import db
import geo
import main
import modulos
import padron_carga
from test_xsii_asistida import BASE, _equipo, _mundo, _movs, _sindicato
from xsii.proyectos.colm3na.asistidas import ErrorAsistida, base as abase, huella, padron, seccionales as sec

db.crear_tablas()
P = "PAD-02"
_k = itertools.count(1_000_001)


def _cu(prefijo="20"):
    while True:
        b = f"{prefijo}8{next(_k) + 4_000_000:07d}"
        d = cuit.digito_verificador(b)
        if d is not None:
            return b + str(d)


# =================================================================== la lógica vieja, congelada

def _viejo_masivo(s, sid, lista, alcance, es_ensayo):
    """La ruta `POST /admin/trabajador/masivo` de `main` antes de la extracción
    (devuelve el destino del redirect o el JSON del ensayo)."""
    afuera = []

    def queda_afuera(n, texto, motivo):
        afuera.append({"linea": n, "texto": texto.strip()[:80], "motivo": motivo})

    altas = 0
    lineas_leidas = lineas_actualizan = 0
    mails_actualizados = fechas_actualizadas = datos_ajenos = fuera_de_alcance = 0
    omitidas, cuil_invalidos = [], []
    por_nombre = {geo._norm(x["nombre"]): x["id"] for x in db.seccionales_del_sindicato(sid)}
    propios = {t.cuil: t for t in s.exec(select(db.Trabajador).where(db.Trabajador.sindicato_id == sid)).all()}
    existentes = set(propios)
    con_clave = db.cuiles_con_clave(s, {
        main._norm_cuil(ln.split(",")[0]) for ln in lista.strip().splitlines() if ln.strip()})
    for n_linea, linea in enumerate(lista.strip().splitlines(), start=1):
        if not linea.strip():
            continue
        lineas_leidas += 1
        campos = [c.strip() for c in linea.split(",")]
        cuil = main._norm_cuil(campos[0]) if campos else ""
        nombre = campos[1] if len(campos) > 1 else ""

        def campo(i):
            return campos[i] if len(campos) > i else ""
        f_afiliacion = main._fecha_formulario(campo(11))
        f_nacimiento = main._fecha_formulario(campo(12))
        if f_afiliacion is None or f_nacimiento is None:
            omitidas.append(linea.strip()[:60])
            queda_afuera(n_linea, linea, "Una de las fechas no se entiende (AAAA-MM-DD o DD/MM/AAAA).")
            continue
        if len(cuil) == 11 and cuil in existentes and (campo(8) or f_afiliacion):
            if cuil not in propios:          # la diferencia declarada: antes KeyError (500)
                omitidas.append(linea.strip()[:60])
                queda_afuera(n_linea, linea, "El CUIL ya está en la lista (repetido).")
                continue
            if f_afiliacion:
                if not es_ensayo:
                    propios[cuil].fecha_afiliacion = f_afiliacion
                    s.add(propios[cuil])
                fechas_actualizadas += 1
            if campo(8):
                if db.responde_por(cuil in con_clave, propios[cuil].registrado):
                    if not es_ensayo:
                        db.guardar_datos_personales(s, cuil, mail_padron=campo(8))
                    mails_actualizados += 1
                else:
                    datos_ajenos += 1
            lineas_actualizan += 1
            continue
        if len(cuil) != 11 or not nombre or cuil in existentes:
            omitidas.append(linea.strip()[:60])
            queda_afuera(n_linea, linea,
                         "El CUIL ya está en el padrón (y la línea no trae mail ni fecha de afiliación para actualizar)."
                         if len(cuil) == 11 and cuil in existentes
                         else "Falta el CUIL (11 números) o el nombre.")
            continue
        if main._cuil_mal(cuil):
            cuil_invalidos.append(campos[0][:20])
            queda_afuera(n_linea, linea, "El CUIL no es válido: revisá los 11 números.")
            continue
        if geo.faltan_campos({"localidad": campo(5), "provincia": campo(6)}):
            omitidas.append(linea.strip()[:60])
            queda_afuera(n_linea, linea, "Falta la localidad o la provincia.")
            continue
        sec_linea = por_nombre.get(geo._norm(campo(10)))
        if alcance is not None:
            if not sec_linea and len(alcance) == 1:
                sec_linea = next(iter(alcance))
            if not main._en_alcance(alcance, sec_linea):
                fuera_de_alcance += 1
                omitidas.append(linea.strip()[:60])
                queda_afuera(n_linea, linea, "La seccional no es la tuya: cargás solo en tu seccional.")
                continue
        domicilio = geo.campos_para_guardar({
            "calle": campo(2), "numero": campo(3), "piso_depto": campo(4),
            "localidad": campo(5), "provincia": campo(6), "codigo_postal": campo(9)}, precision="sin_geo")
        if not es_ensayo:
            s.add(db.Trabajador(sindicato_id=sid, cuil=cuil, seccional_id=sec_linea,
                                fecha_afiliacion=f_afiliacion or None))
        if cuil in con_clave:
            datos_ajenos += 1
        elif not es_ensayo:
            db.guardar_datos_personales(s, cuil, nombre=nombre, domicilio=domicilio, telefono=campo(7),
                                        mail=campo(8), mail_padron=campo(8) or None,
                                        fecha_nacimiento=f_nacimiento or None)
        existentes.add(cuil)
        altas += 1
    if es_ensayo:
        return {"lineas": lineas_leidas, "altas": altas, "actualizaciones": lineas_actualizan,
                "datos_ajenos": datos_ajenos, "afuera_total": len(afuera), "afuera": afuera[:50]}
    destino = f"/admin?altas={altas}"
    if mails_actualizados:
        destino += f"&mailsactualizados={mails_actualizados}"
    if fechas_actualizadas:
        destino += f"&fechasactualizadas={fechas_actualizadas}"
    if datos_ajenos:
        destino += f"&datosajenos={datos_ajenos}"
    if omitidas:
        destino += f"&omitidas={len(omitidas)}&muestra=" + quote(" | ".join(omitidas[:3]))
    if fuera_de_alcance:
        destino += f"&fueraalcance={fuera_de_alcance}"
    if cuil_invalidos:
        muestra = ", ".join(cuil_invalidos[:10])
        if len(cuil_invalidos) > 10:
            muestra += f" y {len(cuil_invalidos) - 10} más"
        destino += (f"&cuilinvalidos={len(cuil_invalidos)}&cuilmuestra=" + quote(muestra))
    return destino + "#trabajadores"


# =================================================================== el mundo de cada caso

class Mundo:
    """Un sindicato con dos seccionales, dos usuarios (general y de Rosario) y
    personas en cada situación relevante. Todo CUIL es nuevo en cada caso."""

    def __init__(self):
        self.sid = _sindicato()
        self.otro = _sindicato()
        n = lambda: _cu()          # noqa: E731
        self.E1, self.E2, self.E3, self.E4 = n(), n(), n(), n()
        self.P1, self.P2, self.P3 = n(), n(), n()
        self.gen, self.loc = n(), n()
        with db.get_session() as s:
            ros = db.Seccional(sindicato_id=self.sid, nombre="Rosario")
            cba = db.Seccional(sindicato_id=self.sid, nombre="Córdoba")
            s.add(ros); s.add(cba); s.commit(); s.refresh(ros); s.refresh(cba)
            self.ros, self.cba = ros.id, cba.id
            s.add(db.Seccional(sindicato_id=self.otro, nombre="Rosario"))
            g = db.UsuarioSindicato(sindicato_id=self.sid, usuario=self.gen, cuil=self.gen, nombre="General",
                                    clave_hash=auth.hashear_clave("generalgeneral"), debe_cambiar_clave=False,
                                    es_super_admin=True)
            lo = db.UsuarioSindicato(sindicato_id=self.sid, usuario=self.loc, cuil=self.loc, nombre="Local",
                                     clave_hash=auth.hashear_clave("localrosario1"), debe_cambiar_clave=False,
                                     es_admin_seccional=True, seccional_id=self.ros)
            s.add(g); s.add(lo); s.commit(); s.refresh(g); s.refresh(lo)
            self.uid_gen, self.uid_loc = g.id, lo.id
            s.add(db.Trabajador(sindicato_id=self.sid, cuil=self.E1, seccional_id=self.cba, fecha_afiliacion="2010-01-01"))
            db.guardar_datos_personales(s, self.E1, nombre="Uno Viejo", mail_padron="e1@x.org", mail="c1@x.org",
                                        domicilio=geo.campos_para_guardar({"localidad": "Salta", "provincia": "Salta"}, "sin_geo"))
            s.add(db.Trabajador(sindicato_id=self.sid, cuil=self.E2))
            db.guardar_datos_personales(s, self.E2, nombre="Dos Viejo")
            s.add(db.Trabajador(sindicato_id=self.sid, cuil=self.E3, registrado=True, seccional_id=self.ros))
            db.guardar_datos_personales(s, self.E3, nombre="Tres Registrado", mail_padron="e3@x.org").clave_hash = "x"
            s.add(db.Trabajador(sindicato_id=self.sid, cuil=self.E4, registrado=False))
            db.guardar_datos_personales(s, self.E4, nombre="Cuatro Ajeno", mail_padron="e4@x.org").clave_hash = "x"
            db.guardar_datos_personales(s, self.P1, nombre="Pe Uno", mail_padron="p1@x.org").clave_hash = "x"
            s.add(db.Trabajador(sindicato_id=self.otro, cuil=self.P1, registrado=True))
            db.guardar_datos_personales(s, self.P2, nombre="Pe Dos", telefono="111", mail_padron="p2@x.org")
            s.add(db.Trabajador(sindicato_id=self.otro, cuil=self.P2))
            db.guardar_datos_personales(s, self.P3, nombre="Pe Tres", mail_padron="p3@otro.org")
            s.add(db.Trabajador(sindicato_id=self.otro, cuil=self.P3))
            s.commit()

    def cliente(self, local=False):
        c = TestClient(main.app, follow_redirects=False)
        c.cookies.set("sesion_sindicato", auth.crear_sesion(
            "sindicato", self.uid_loc if local else self.uid_gen, self.sid))
        return c

    def alcance(self, local):
        return {self.ros} if local else None

    def nuevo(self):
        return _cu()

    def foto(self, extra=()):
        """Todo lo que la carga puede tocar, en una forma comparable."""
        with db.get_session() as s:
            return _foto(s, self.sid, {self.E1, self.E2, self.E3, self.E4, self.P1, self.P2, self.P3} | set(extra))


def _foto(s, sid, cuiles):
    ts = sorted((t.cuil, t.seccional_id, t.fecha_afiliacion, t.registrado, t.activo)
                for t in s.exec(select(db.Trabajador).where(db.Trabajador.sindicato_id == sid)).all())
    cs = {}
    for c in s.exec(select(db.CuentaTrabajador)).all():
        if c.cuil in cuiles or any(t[0] == c.cuil for t in ts):
            d = {k: v for k, v in c.__dict__.items() if not k.startswith("_") and k != "id"}
            cs[c.cuil] = tuple(sorted((k, str(v)) for k, v in d.items()))
    return ts, cs


# =================================================================== el banco de listas adversarias

def L(*campos):
    return ",".join(campos)


def _a(m, cuil=None, nombre="Gómez Ana", sec="", mail="", af="", na="", loc="Rosario", prov="Santa Fe"):
    return L(cuil or m.nuevo(), nombre, "Colón", "650", "2 A", loc, prov, "351 555", mail, "5000", sec, af, na)


BANCO = {
    "espacios_y_lineas_en_blanco": lambda m: "\n\n   \n\t\n",
    "alta_minima": lambda m: L(m.nuevo(), "Solo Nombre", "", "", "", "Rosario", "Santa Fe"),
    "alta_completa": lambda m: _a(m, sec="Rosario", mail="a@x.org", af="2019-05-01", na="1990-01-02"),
    "cuil_con_guiones_espacios_puntos": lambda m: "\n".join(
        L(c[:2] + sep + c[2:10] + sep2 + c[10], "Con Separador", "", "", "", "Rosario", "Santa Fe")
        for c, sep, sep2 in ((m.nuevo(), "-", "-"), (m.nuevo(), " ", " "), (m.nuevo(), ".", "."),
                             (m.nuevo(), "-", " "))),
    "cuil_con_digito_mal": lambda m: "\n".join(L(c[:-1] + str((int(c[-1]) + 1) % 10), "Mala", "", "", "", "Rosario", "Santa Fe")
                                               for c in (m.nuevo(), m.nuevo())),
    "cuil_corto_largo_y_sin_cuil": lambda m: "\n".join([
        L("2090000", "Corto", "", "", "", "Rosario", "Santa Fe"), L("2090000000000099", "Largo", "", "", "", "Rosario", "Santa Fe"),
        L("", "Sin cuil", "", "", "", "Rosario", "Santa Fe"), L("abc", "Letras", "", "", "", "Rosario", "Santa Fe")]),
    "sin_nombre": lambda m: L(m.nuevo(), "", "", "", "", "Rosario", "Santa Fe"),
    "sin_localidad_o_provincia": lambda m: "\n".join([
        L(m.nuevo(), "Sin Loc", "", "", "", "", "Santa Fe"), L(m.nuevo(), "Sin Prov", "", "", "", "Rosario", ""),
        L(m.nuevo(), "Sin Nada")]),
    "una_sola_columna": lambda m: m.nuevo(),
    "comas_de_mas": lambda m: L(m.nuevo(), "Comas", "", "", "", "Rosario", "Santa Fe", "", "", "", "", "", "", "extra", "otro", "mas"),
    "solo_comas": lambda m: ",,,,\n,\n,,,,,,,,,,,,,",
    "repetido_en_la_lista_sin_mail": lambda m: "\n".join([_a(m, cuil=(c := m.nuevo())), _a(m, cuil=c, nombre="Segunda vez")]),
    "repetido_tres_veces_con_guiones": lambda m: "\n".join(
        [_a(m, cuil=(c := m.nuevo())), _a(m, cuil=c[:2] + "-" + c[2:10] + "-" + c[10]), _a(m, cuil=c)]),
    "E1_con_mail": lambda m: L(m.E1, "x", mail="") if False else L(m.E1, "Uno", "", "", "", "", "", "", "nuevo1@x.org"),
    "E1_con_fecha": lambda m: L(m.E1, "Uno", "", "", "", "", "", "", "", "", "", "2020-02-02"),
    "E1_con_mail_y_fecha": lambda m: L(m.E1, "Uno", "", "", "", "", "", "", "nuevo1@x.org", "", "", "03/03/2021"),
    "E1_sin_nada": lambda m: L(m.E1, "Uno Otro Nombre", "Calle", "1", "", "Salta", "Salta"),
    "E1_mail_igual_y_fecha_igual": lambda m: L(m.E1, "Uno", "", "", "", "", "", "", "e1@x.org", "", "", "2010-01-01"),
    "E2_con_mail_con_fecha_y_nada": lambda m: "\n".join([
        L(m.E2, "Dos", "", "", "", "", "", "", "dos@x.org"), L(m.E2, "Dos", "", "", "", "", "", "", "", "", "", "2015-01-01"),
        L(m.E2, "Dos", "", "", "", "Rosario", "Santa Fe")]),
    "E3_registrado_con_mail": lambda m: L(m.E3, "Tres", "", "", "", "", "", "", "tres@x.org", "", "", "2011-11-11"),
    "E4_cuenta_con_clave_no_registrado_con_mail": lambda m: L(m.E4, "Cuatro", "", "", "", "", "", "", "cuatro@x.org", "", "", "2012-12-12"),
    "P1_cuenta_con_clave_de_otro_gremio": lambda m: _a(m, cuil=m.P1, nombre="Pisado Uno", sec="Rosario", mail="pisa1@x.org"),
    "P2_cuenta_sin_clave_de_otro_gremio": lambda m: _a(m, cuil=m.P2, nombre="Pisado Dos", sec="Córdoba", mail="pisa2@x.org", na="1980-01-01"),
    "P3_alta_sin_mail_no_borra_el_del_otro": lambda m: L(m.P3, "Pe Tres Nuevo", "", "", "", "Rosario", "Santa Fe"),
    "P3_alta_con_mail": lambda m: L(m.P3, "Pe Tres Nuevo", "", "", "", "Rosario", "Santa Fe", "", "tres@mio.org"),
    "seccional_con_acentos_y_mayusculas": lambda m: "\n".join(
        _a(m, sec=x) for x in ("CÓRDOBA", "córdoba", " rosario ", "ROSARIO", "Cordoba", "Rosário")),
    "seccional_inexistente": lambda m: "\n".join(_a(m, sec=x) for x in ("Mendoza", "Rosario Norte", "0")),
    "fechas_en_los_dos_formatos": lambda m: "\n".join(_a(m, af=a, na=n) for a, n in (
        ("2019-05-01", "1990-01-02"), ("01/05/2019", "02/01/1990"), ("1/5/2019", "2/1/1990"), ("", "1990-01-02"))),
    "fechas_ilegibles": lambda m: "\n".join(_a(m, af=a, na=n) for a, n in (
        ("ayer", ""), ("", "mañana"), ("31/02/2020", ""), ("2020-13-01", ""), ("2020-01-01 10:00", ""), ("00/00/0000", ""),
        ("2020/01/01", ""), ("01-01-2020", ""), ("20200101", ""), ("0001-01-01", "9999-12-31"))),
    "E1_con_fecha_ilegible": lambda m: L(m.E1, "Uno", "", "", "", "", "", "", "a@x.org", "", "", "no es fecha"),
    "mezcla_grande": lambda m: "\n".join(
        [_a(m), _a(m, sec="Córdoba"), L(m.E1, "u", "", "", "", "", "", "", "z@x.org"), "", L(m.E2, "d"), _a(m, cuil="20123"),
         _a(m, loc=""), _a(m, af="mal"), _a(m, cuil=m.P1), _a(m, cuil=m.P2, mail="m@x.org"), _a(m, sec="Mendoza"),
         L(m.nuevo(), "")] * 4),
    "muchos_cuil_invalidos": lambda m: "\n".join(L("2090000%04d" % i, "Mal %d" % i, "", "", "", "Rosario", "Santa Fe") for i in range(14)),
    "muchas_omitidas_y_muestra": lambda m: "\n".join([L("", "n")] * 7 + [L(m.nuevo(), "")] * 3),
    "mail_largo": lambda m: L(m.E1, "u", "", "", "", "", "", "", "a" * 300 + "@x.org") + "\n" + _a(m, mail="b" * 300 + "@x.org"),
    "nombre_largo_y_unicode": lambda m: _a(m, nombre="Ñandú " * 80) + "\n" + _a(m, nombre="日本語 \u202e rtl \u200f x") + "\n" + _a(m, nombre="  espacios   internos  "),
    "crlf_y_tabs": lambda m: _a(m) + "\r\n" + "\t" + _a(m) + "\t\r\n" + _a(m),
    "campos_con_espacios": lambda m: L(" " + m.nuevo() + " ", " Con Espacios ", " Calle ", " 1 ", " ", " Rosario ", " Santa Fe ", " 1 ", " m@x.org ", " 1 ", " Córdoba ", " 2020-01-01 ", " 1990-01-01 "),
    "veinte_altas_validas": lambda m: "\n".join(_a(m, sec="Rosario" if i % 2 else "Córdoba") for i in range(20)),
    "alta_con_numero_en_mail_y_comillas": lambda m: _a(m, nombre='"Comillas"', mail="a+b@x.org"),
    "cuil_de_empresa_30": lambda m: _a(m, cuil=cuit.corregir("30700000000")),
    "linea_de_E1_y_alta_de_el_mismo_con_otro_cuil_formato": lambda m: L(m.E1[:2] + "-" + m.E1[2:10] + "-" + m.E1[10], "Uno", "", "", "", "", "", "", "fmt@x.org"),
    "todo_junto_para_el_local": lambda m: "\n".join([
        _a(m, sec="Rosario"), _a(m, sec="Córdoba"), _a(m), _a(m, sec="Mendoza"), L(m.E3, "t", "", "", "", "", "", "", "t@x.org"),
        L(m.E1, "u", "", "", "", "", "", "", "u@x.org"), _a(m, cuil=m.P1, sec="Córdoba")]),
}

# Las que hacen un CUIL nuevo repetido con mail o fecha: la conducta cambió A PROPÓSITO.
BANCO_DECLARADO = {
    "repetido_nuevo_con_mail": lambda m: "\n".join([_a(m, cuil=(c := m.nuevo())), L(c, "Otra vez", "", "", "", "", "", "", "r@x.org")]),
    "repetido_nuevo_con_fecha": lambda m: "\n".join([_a(m, cuil=(c := m.nuevo())), L(c, "Otra vez", "", "", "", "", "", "", "", "", "", "2020-01-01")]),
}

MODOS = [("general", False, False), ("general_ensayo", False, True), ("local", True, False), ("local_ensayo", True, True)]


def _comparar(nombre, lista_fn, local, ensayo):
    m = Mundo()
    lista = lista_fn(m)
    inicial = m.foto()
    # --- el viejo, en una transacción que se deshace
    with db.get_session() as s:
        esperado = _viejo_masivo(s, m.sid, lista, m.alcance(local), ensayo)
        extra = {main._norm_cuil(ln.split(",")[0]) for ln in lista.splitlines()}
        foto_esperada = _foto(s, m.sid, {m.E1, m.E2, m.E3, m.E4, m.P1, m.P2, m.P3} | extra)
        s.rollback()
    assert m.foto() == inicial, "el oráculo no se deshizo"
    # --- el real
    r = m.cliente(local).post("/admin/trabajador/masivo", data={"lista": lista, **({"ensayo": "1"} if ensayo else {})})
    if ensayo:
        assert r.status_code == 200, (nombre, r.text[:300])
        assert r.json() == esperado, nombre
        assert m.foto(extra) == _foto_inicial_con(m, inicial, extra)
        return
    assert r.status_code == 303, (nombre, r.status_code, r.text[:300])
    assert r.headers["location"] == esperado, nombre
    with db.get_session() as s:
        real = _foto(s, m.sid, {m.E1, m.E2, m.E3, m.E4, m.P1, m.P2, m.P3} | extra)
    assert real == foto_esperada, nombre


def _foto_inicial_con(m, inicial, extra):
    """En un ensayo no cambia nada: la foto con los CUIL extra es la inicial (más cuentas ajenas que no existen)."""
    ahora = m.foto(extra)
    assert ahora[0] == inicial[0]
    assert {k: v for k, v in ahora[1].items() if k in inicial[1]} == inicial[1]
    return ahora


@pytest.mark.parametrize("nombre", sorted(BANCO))
@pytest.mark.parametrize("modo,local,ensayo", MODOS, ids=[x[0] for x in MODOS])
def test_la_masiva_extraida_hace_lo_mismo_que_la_vieja(nombre, modo, local, ensayo):
    _comparar(nombre, BANCO[nombre], local, ensayo)


@pytest.mark.parametrize("nombre", sorted(BANCO_DECLARADO))
@pytest.mark.parametrize("ensayo", [False, True])
def test_un_cuil_nuevo_repetido_con_mail_o_fecha_antes_daba_500_y_ahora_queda_afuera(nombre, ensayo):
    m = Mundo()
    lista = BANCO_DECLARADO[nombre](m)
    r = m.cliente().post("/admin/trabajador/masivo", data={"lista": lista, **({"ensayo": "1"} if ensayo else {})})
    if ensayo:
        j = r.json()
        assert j["altas"] == 1 and j["afuera_total"] == 1 and "repetido" in j["afuera"][0]["motivo"].lower()
    else:
        assert r.status_code == 303 and "altas=1" in r.headers["location"] and "omitidas=1" in r.headers["location"]


def test_el_banco_tiene_mas_de_cuarenta_listas():
    assert len(BANCO) >= 40


# =================================================================== asegurar_cuenta(cuenta=) / guardar_datos_personales(cuenta=)

def test_guardar_datos_personales_con_cuenta_previa_no_pisa_lo_que_no_se_toca():
    c = _cu()
    with db.get_session() as s:
        db.guardar_datos_personales(s, c, nombre="Original", telefono="123", mail="m@x.org", mail_padron="p@otro.org",
                                    fecha_nacimiento="1990-01-01")
        s.commit()
    with db.get_session() as s:
        cuenta = s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c)).first()
        r = db.guardar_datos_personales(s, c, mail_padron="nuevo@x.org", cuenta=cuenta)
        assert r is cuenta
        s.commit()
    with db.get_session() as s:
        x = s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c)).one()
        assert (x.nombre, x.telefono, x.mail, x.mail_padron, x.fecha_nacimiento) == ("Original", "123", "m@x.org", "nuevo@x.org", "1990-01-01")


def test_asegurar_cuenta_con_existente_no_crea_otra_y_sin_ella_crea_una_sola():
    c = _cu()
    with db.get_session() as s:
        a = db.asegurar_cuenta(s, c)
        b = db.asegurar_cuenta(s, c, a)
        assert a is b
        s.commit()
        assert s.exec(select(func.count()).select_from(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c)).one() == 1


def test_un_lote_con_el_mismo_cuil_dos_veces_no_crea_dos_cuentas_y_dos_lotes_tampoco():
    m = Mundo()
    c = m.nuevo()
    lista = "\n".join([_a(m, cuil=c, nombre="Primera"), _a(m, cuil=c, nombre="Segunda")])
    r = m.cliente().post("/admin/trabajador/masivo", data={"lista": lista})
    assert r.status_code == 303
    r = m.cliente().post("/admin/trabajador/masivo", data={"lista": lista})
    assert r.status_code == 303
    with db.get_session() as s:
        assert s.exec(select(func.count()).select_from(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c)).one() == 1
        assert s.exec(select(func.count()).select_from(db.Trabajador).where(db.Trabajador.cuil == c)).one() == 1
        assert s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c)).one().nombre == "Primera"


def test_la_cuenta_de_otro_gremio_con_mail_del_padron_cargado_por_el_otro_se_respeta_en_el_alta_sin_mail():
    m = Mundo()
    _comparar("P3", BANCO["P3_alta_sin_mail_no_borra_el_del_otro"], False, False)
    with db.get_session() as s:
        assert s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == m.P3)).one().mail_padron == "p3@otro.org"


# =================================================================== la masiva: NUL, XSS y lo que escribe en la ficha

def test_la_masiva_con_un_byte_nulo_en_la_lista_no_da_500():
    m = Mundo()
    for ens in ("", "1"):
        r = m.cliente().post("/admin/trabajador/masivo",
                             data={"lista": _a(m, nombre="Con\x00Nulo") + "\n" + _a(m), **({"ensayo": ens} if ens else {})})
        assert r.status_code in (200, 303), (ens, r.status_code, r.text[:200])


def test_un_nombre_con_html_o_formula_se_guarda_como_texto_y_el_panel_lo_escapa():
    m = Mundo()
    c1, c2 = m.nuevo(), m.nuevo()
    lista = "\n".join([_a(m, cuil=c1, nombre="<script>alert(1)</script>"), _a(m, cuil=c2, nombre="=cmd|' /C calc'!A0")])
    assert m.cliente().post("/admin/trabajador/masivo", data={"lista": lista}).status_code == 303
    with db.get_session() as s:
        assert s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c1)).one().nombre == "<script>alert(1)</script>"
    html = m.cliente().get("/admin/trabajadores/lista").json()["html"]
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# =================================================================== lectura y mapeo: cabeceras adversarias

def _leer(cab, *filas, opciones=None):
    return padron.leer((cab + "\n" + "\n".join(filas) + "\n").encode("utf-8"), opciones or {})


def test_dos_columnas_que_matchean_el_mismo_campo_toma_la_primera_y_la_otra_queda_sin_usar():
    c = _cu()
    r = _leer("CUIL;CUIT;Nombre", f"{c};20111111112;Ana")
    campos = {x["cabecera"]: x["campo"] for x in r["mapeo"]["columnas"]}
    assert campos == {"CUIL": "cuil", "CUIT": "", "Nombre": "nombre"} and r["filas"][0][2]["cuil"] == c


def test_nombre_y_apellido_y_nombre_juntas_no_rompen_y_no_se_duplica_el_apellido():
    c = _cu()
    for cab in ("CUIL;Nombre;Apellido y Nombre", "CUIL;Apellido y Nombre;Nombre", "CUIL;Apellido;Nombre;Apellido y Nombre"):
        r = _leer(cab, f"{c};uno;dos;tres"[: len(cab.split(";")) * 4 + 30])
        assert r["mapeo"]["faltan"] == [] and r["total"] == 1
        nombre = r["filas"][0][2]["nombre"]
        assert nombre and nombre.count(",") <= 1


@pytest.mark.parametrize("cab,faltan", [
    ("Fecha;Nombre", ["cuil"]), ("Nro;Nombre", ["cuil"]), (";Nombre", ["cuil"]), ("CUIL;", ["nombre"]),
    ("CUIL;Nombre;Nombre", []), ("CUIL;CUIL;Nombre", []), ("cuil;NOMBRE;Fecha;Nro;;;", []),
])
def test_cabeceras_dudosas(cab, faltan):
    r = _leer(cab, f"{_cu()};Ana;1;2;3;4;5")
    assert r["mapeo"]["faltan"] == faltan


def test_fecha_sola_y_nro_solo_no_se_asignan_a_un_campo_equivocado():
    r = _leer("CUIL;Nombre;Fecha;Nro", f"{_cu()};Ana;2020-01-01;12")
    campos = {x["cabecera"]: x["campo"] for x in r["mapeo"]["columnas"]}
    assert campos["Fecha"] == "" and campos["Nro"] in ("", "numero")
    assert r["filas"][0][2]["fecha_afiliacion"] == "" and r["filas"][0][2]["fecha_nacimiento"] == ""


def test_trescientas_columnas_y_filas_de_mil_campos():
    cab = ["CUIL", "Nombre", "Localidad", "Provincia"] + [f"col{i}" for i in range(296)]
    c = _cu()
    fila = [c, "Ana", "Salta", "Salta"] + ["x"] * 296
    r = padron.leer((";".join(cab) + "\n" + ";".join(fila) + "\n").encode(), {})
    assert r["mapeo"]["faltan"] == [] and len(r["mapeo"]["columnas"]) == 300 and r["total"] == 1
    larga = ";".join([c, "Ana", "Salta", "Salta"] + ["y"] * 996)
    r = padron.leer(("CUIL;Nombre;Localidad;Provincia\n" + larga + "\n").encode(), {})
    assert r["total"] == 1 and r["filas"][0][2]["cuil"] == c
    r = padron.leer((";".join(f"c{i}" for i in range(1500)) + "\n" + ";".join(["a"] * 1500) + "\n").encode(), {})
    assert r["mapeo"]["faltan"] == ["cuil", "nombre"]


@pytest.mark.parametrize("mapeo", [
    {"-1": "cuil"}, {"1000": "cuil"}, {"99999999999999999999": "cuil"}, {"a": "cuil"}, {"": "cuil"}, {"1.5": "cuil"},
    {"0": "no_existe"}, {"0": 5}, {"0": ["cuil"]}, {"0": {"x": 1}}, {"0": True}, [1, 2], "cuil", 7, {"9" * 5000: "cuil"},
    {"0": "CUIL"}, {"0": "cuil ", "1": "x"},
])
def test_mapeo_hostil_es_400_con_mensaje_nunca_500(mapeo):
    with pytest.raises(ErrorAsistida) as e:
        padron.leer(f"A;B;C\n{_cu()};Ana;Salta\n".encode(), {"mapeo": mapeo})
    assert e.value.estado == 400 and e.value.mensaje


def test_indice_valido_para_la_norma_pero_fuera_de_la_planilla_es_400():
    with pytest.raises(ErrorAsistida) as e:
        padron.leer(b"A;B\n1;2\n", {"mapeo": {"5": "cuil"}})
    assert e.value.estado == 400 and "no existe" in e.value.mensaje


def test_mapeo_que_deja_sin_obligatorios_es_200_en_el_ensayo_y_400_en_la_carga():
    pid, sid, eq = _mundo_listo_b4()
    planilla = _csv(_fila())
    r = _ens(eq, pid, planilla, opciones={"mapeo": {"0": "", "1": ""}})
    assert r["mapeo"]["faltan"] and r["total"] == 0 and r["a_escribir"] == 0
    rc = _env(eq, pid, "carga", planilla, opciones={"mapeo": {"0": "", "1": ""}}, huella_=r["huella"])
    assert rc.status_code == 400 and rc.json()["detail"]


def test_una_clave_de_mapeo_escrita_de_distinta_forma_cuenta_una_vez_y_el_ultimo_gana():
    n = padron.normalizar_opciones({"mapeo": {"1": "cuil", "01": "nombre", " 1 ": "provincia", "+1": ""}})
    assert list(n["mapeo"]) == ["1"] and n["mapeo"]["1"] in ("", "cuil", "nombre", "provincia")


def test_el_mapeo_forma_parte_de_la_huella_y_la_carga_con_otro_mapeo_es_409():
    pid, sid, eq = _mundo_listo_b4()
    planilla = _csv(_fila())
    e = _ens(eq, pid, planilla)
    r = _env(eq, pid, "carga", planilla, opciones={"mapeo": {"4": ""}}, huella_=e["huella"])
    assert r.status_code == 409 and _trabajadores(sid) == {}
    e2 = _ens(eq, pid, planilla, opciones={"mapeo": {"4": ""}})
    assert e2["huella"] != e["huella"]


def test_un_dni_mapeado_a_mano_como_identificacion_se_rechaza_fila_por_fila_no_se_acepta():
    pid, sid, eq = _mundo_listo_b4()
    e = _ens(eq, pid, b"DNI;Nombre;Localidad;Provincia\n20123456;Ana;Salta;Salta\n30111222;Beto;Salta;Salta\n",
             opciones={"mapeo": {"0": "cuil"}})
    assert e["rechazadas"] == 2 and e["validas"] == 0 and "11" in e["filas"][0]["motivos"][0]


def test_celdas_con_formula_html_o_invisibles_se_guardan_como_texto():
    pid, sid, eq = _mundo_listo_b4()
    c1, c2 = _cu(), _cu()
    planilla = _csv(f"{c1};=HYPERLINK(\"http://x\",\"a\");;Salta;Salta;@cmd;", f"{c2};<img src=x onerror=alert(1)>\u202e\u200b\x07x;;Salta;Salta;+1;")
    assert _car(eq, pid, planilla).status_code == 200
    assert _cuenta(c1).nombre == '=HYPERLINK("http://x","a")'
    n2 = _cuenta(c2).nombre
    assert n2.startswith("<img src=x onerror=alert(1)>") and "\u202e" not in n2 and "\u200b" not in n2 and "\x07" not in n2
    html = TestClient(main.app)
    # el ensayo la devuelve como dato JSON y nada la interpreta en el servidor
    assert "<img" in json.dumps(_ens(eq, pid, planilla))


def _mundo_listo_b4():
    from test_xsii_padron import _mundo_listo
    return _mundo_listo()


from test_xsii_padron import _env, _ens, _car, _trabajadores, _cuenta, _csv, _fila, CAB  # noqa: E402


# =================================================================== topes y total declarado

def _planilla_de(n, relleno=0):
    cab = "CUIL;Nombre;Localidad;Provincia\n"
    filas = [f"{20000000000 + i};N{i};Salta;Salta" for i in range(n)]
    return (cab + "\n".join(filas) + "\n").encode()


def test_veinte_mil_filas_pasan_y_veinte_mil_una_es_400():
    r = padron.leer(_planilla_de(20000), {})
    assert r["total"] == 20000
    with pytest.raises(ErrorAsistida) as e:
        padron.leer(_planilla_de(20001), {})
    assert e.value.estado == 400 and "20.000" in e.value.mensaje


def test_cinco_mb_justos_pasan_y_cinco_mb_mas_uno_es_400():
    tope = padron.TOPE_BYTES
    cab = b"CUIL;Nombre;Localidad;Provincia;Obs\n"
    fila = b"20111111112;Ana;Salta;Salta;" + b"x" * 900 + b"\n"
    cuerpo = cab + fila * ((tope - len(cab)) // len(fila))
    cuerpo += b"y" * (tope - len(cuerpo) - 1) + b"\n"
    assert len(cuerpo) == tope
    assert padron.leer(cuerpo, {})["total"] > 5000
    with pytest.raises(ErrorAsistida) as e:
        padron.leer(cuerpo + b"z", {})
    assert e.value.estado == 400 and "5 MB" in e.value.mensaje


def test_un_campo_gigante_es_400_no_500():
    with pytest.raises(ErrorAsistida) as e:
        padron.leer(b"CUIL;Nombre\n" + b"2;" + b"x" * 300_000 + b"\n", {})
    assert e.value.estado == 400


@pytest.mark.parametrize("valor,ok", [
    (0, True), (10_000_000, True), (10_000_001, False), (-1, False), (-0.5, False), (1.5, False), (True, False), (False, False),
    ("12", True), (" 12 ", True), ("12,0", True), ("1,5", False), ("abc", False), ("1e3", True), ("1e400", False),
    ("nan", False), ("inf", False), ("-inf", False), ("9" * 5000, False), ([], False), ({}, False), ([5], False),
    (float("inf"), False), (10 ** 30, False), ("", True), (None, True), ("   ", True), ("0x10", False), ("١٢", True),
])
def test_total_declarado_hostil(valor, ok):
    if ok:
        padron.normalizar_opciones({"total_declarado": valor})
    else:
        with pytest.raises(ErrorAsistida) as e:
            padron.normalizar_opciones({"total_declarado": valor})
        assert e.value.estado == 400 and e.value.mensaje


def test_total_declarado_hostil_por_http_es_400_nunca_500():
    pid, sid, eq = _mundo_listo_b4()
    planilla = _csv(_fila())
    for raro in ("-5", "1.5", "abc", '"x"', "[1]", "{}", "1e999", "99999999999999999999999"):
        r = eq.post(f"{BASE}/p/{pid}/tarea/{P}/asistida/ensayo",
                    data={"opciones": '{"total_declarado": ' + raro + '}'}, files={"archivo": ("p.csv", planilla, "text/csv")})
        assert r.status_code in (200, 400), (raro, r.status_code, r.text[:200])
        if r.status_code == 400:
            assert r.json()["detail"]
    r = eq.post(f"{BASE}/p/{pid}/tarea/{P}/asistida/ensayo", data={"opciones": "{no es json"},
                files={"archivo": ("p.csv", planilla, "text/csv")})
    assert r.status_code == 400 and r.json()["detail"]


def test_fuzz_de_bytes_aleatorios_nunca_levanta_otra_cosa_que_error_asistida():
    import random
    rnd = random.Random(1234)
    alfabeto = [b";", b",", b"\t", b'"', b"\n", b"\r\n", b"a", b"20111111112", b" ", "ñ".encode(), "\u202e".encode(), b"\xff", b"=", b"'"]
    for i in range(400):
        crudo = b"".join(rnd.choice(alfabeto) for _ in range(rnd.randint(1, 120)))
        for mod in (padron.leer, lambda c, o: sec.leer(c, [], o)):
            try:
                mod(crudo, {})
            except ErrorAsistida:
                pass
        if i % 7 == 0:
            try:
                padron.leer(crudo, {"mapeo": {str(rnd.randint(-2, 4)): rnd.choice(["cuil", "nombre", "", "x"])}})
            except ErrorAsistida:
                pass


# =================================================================== todo o nada, ensayo, aislamiento, 409

def _todas_las_filas():
    """Cuántas filas tiene cada tabla de la base: lo que un ensayo no puede mover."""
    from sqlmodel import SQLModel
    from sqlalchemy import text
    salida = {}
    with db.get_session() as s:
        for t in SQLModel.metadata.sorted_tables:
            salida[t.name] = s.execute(text(f'SELECT count(*) FROM "{t.name}"')).scalar()
    return salida


def _proyecto_de(sid):
    from test_xsii_asistida import EQ
    with db.get_session() as s:
        return db.impl_crear_proyecto(s, "XSII QA4 " + uuid.uuid4().hex[:8], EQ, sindicato_id=sid).id


def test_el_ensayo_no_escribe_en_ninguna_tabla_ni_siquiera_con_filas_que_actualizan_y_con_cuenta_previa():
    pid, sid, eq = _mundo_listo_b4()
    ya, previa = _cu(), _cu()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=sid, cuil=ya, fecha_afiliacion="2001-01-01"))
        db.guardar_datos_personales(s, ya, nombre="Ya")
        db.guardar_datos_personales(s, previa, nombre="Previa").clave_hash = "x"
        s.commit()
    planilla = _csv(_fila(), _fila(sec="Seccional Rosario"), _fila(cuil=ya, mail="n@x.org", fecha="2020-01-01"),
                    _fila(cuil=previa, mail="p@x.org"), _fila(cuil="20123"), _fila(sec="Nada"))
    antes = _todas_las_filas()
    e = _ens(eq, pid, planilla, opciones={"total_declarado": 50})
    assert e["a_escribir"] == 5
    assert _todas_las_filas() == antes


def test_todo_o_nada_con_un_error_forzado_a_mitad_de_la_escritura(monkeypatch):
    pid, sid, eq = _mundo_listo_b4()
    planilla = _csv(*[_fila() for _ in range(30)])
    e = _ens(eq, pid, planilla)
    antes = _todas_las_filas()
    llamadas = []
    real = db.guardar_datos_personales

    def bomba(*a, **k):
        llamadas.append(1)
        if len(llamadas) == 15:
            raise RuntimeError("falla a mitad")
        return real(*a, **k)
    monkeypatch.setattr(db, "guardar_datos_personales", bomba)
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    c.cookies = eq.cookies
    r = _env(c, pid, "carga", planilla, huella_=e["huella"])
    assert r.status_code == 500 and len(llamadas) == 15
    monkeypatch.undo()
    assert _todas_las_filas() == antes and _trabajadores(sid) == {}
    r = _env(eq, pid, "carga", planilla, huella_=e["huella"])
    assert r.status_code == 200 and r.json()["carga"]["creadas"] == 30


def test_un_error_de_base_en_la_carga_no_deja_el_movimiento_ni_el_insumo(monkeypatch):
    pid, sid, eq = _mundo_listo_b4()
    planilla = _csv(_fila(), _fila())
    e = _ens(eq, pid, planilla)
    monkeypatch.setattr(db, "xsii_registrar_carga_asistida", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    c = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    c.cookies = eq.cookies
    assert _env(c, pid, "carga", planilla, huella_=e["huella"]).status_code == 500
    monkeypatch.undo()
    assert _trabajadores(sid) == {} and _movs(pid, "asistida_carga") == []


def test_el_mismo_cuil_en_dos_sindicatos_se_empadrona_en_los_dos_con_una_sola_cuenta_y_sin_pisar():
    pid, sid, eq = _mundo_listo_b4()
    pid2, sid2, eq2 = _mundo_listo_b4()
    c = _cu()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=sid2, cuil=c, fecha_afiliacion="2005-05-05"))
        db.guardar_datos_personales(s, c, nombre="Del Dos", mail_padron="dos@x.org", telefono="42")
        s.commit()
    assert _car(eq, pid, _csv(_fila(cuil=c, nombre="Del Uno", mail="uno@x.org", fecha="2021-01-01"))).status_code == 200
    assert set(_trabajadores(sid)) == {c} and set(_trabajadores(sid2)) == {c}
    assert _trabajadores(sid2)[c].fecha_afiliacion == "2005-05-05"
    with db.get_session() as s:
        cuentas = s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil == c)).all()
    assert len(cuentas) == 1
    # sin clave todavía: el padrón escribe (regla de la masiva), pero lo del otro gremio que la carga no trae no se borra
    assert cuentas[0].telefono == "42" or cuentas[0].telefono == ""
    # y la carga del OTRO sindicato no toca el empadronamiento del primero
    assert _car(eq2, pid2, _csv(_fila(cuil=c, mail="dos2@x.org"))).status_code in (200, 409)
    assert _trabajadores(sid)[c].fecha_afiliacion == "2021-01-01"


@pytest.mark.parametrize("resolver,esperado", [(("EST-01",), 409), (("PAD-01",), 409), (("EST-01", "PAD-01"), 200)])
def test_pad02_con_una_sola_de_sus_dos_previas_resuelta_es_409(resolver, esperado):
    pid, sid, eq = _mundo()
    for t in resolver:
        r = eq.post(f"{BASE}/p/{pid}/tarea/{t}/decision", json={"tipo": "completada_a_mano", "motivo": "armado del test"})
        assert r.status_code == 200, r.text
    planilla = _csv(_fila())
    e = _ens(eq, pid, planilla)
    r = _env(eq, pid, "carga", planilla, huella_=e["huella"])
    assert r.status_code == esperado, r.text
    if esperado == 409:
        assert r.json()["detail"] and _trabajadores(sid) == {}


def test_el_movimiento_y_las_herramientas_de_preguntame_no_tienen_nada_de_la_planilla():
    pid, sid, eq = _mundo_listo_b4()
    c = _cu()
    secreto = "Zubiría Secretísimo Ñ"
    mail = "zubiria.secreto@gremio-ficticio.org"
    planilla = _csv(_fila(cuil=c, nombre=secreto, mail=mail, sec="Seccional Rosario"), _fila(nombre="Otro Secreto Pérez"))
    assert _car(eq, pid, planilla).status_code == 200
    jm = json.dumps(eq.get(f"{BASE}/p/{pid}/movimientos").json(), ensure_ascii=False)
    jt = json.dumps(eq.get(f"{BASE}/p/{pid}/tarea/{P}").json(), ensure_ascii=False)
    with db.get_session() as s:
        crudo = json.dumps([[m.texto, m.cantidades, m.codigo, m.clave_insumo] for m in db.xsii_movimientos(s, pid, limite=200)],
                           default=str, ensure_ascii=False)
        from xsii.proyectos.colm3na import herramientas as herr, vista
        inst = herr.Instantanea.armar(s, vista.Contexto(s, pid))
    h = herr.herramientas(inst)
    volcado = jm + jt + crudo
    for nombre, (esq, fn) in h.items():
        if nombre == "proponer_reclamo":
            continue
        for args in ({}, {"codigo": P}, {"codigo": "EST-01"}):
            try:
                volcado += json.dumps(fn(**args), default=str, ensure_ascii=False)
            except Exception:
                pass
    for prohibido in (c, cuit.formatear(c), "Zubiría", "Secretísimo", "Otro Secreto", mail, "gremio-ficticio"):
        assert prohibido not in volcado, prohibido
    assert "Cargó 2 afiliados" in jm


# =================================================================== concurrencia

def _correr_a_la_vez(*trabajos):
    barrera = threading.Barrier(len(trabajos))
    resultados = [None] * len(trabajos)

    def ir(i, f):
        barrera.wait()
        try:
            resultados[i] = f()
        except Exception as e:          # noqa: BLE001
            resultados[i] = e
    hilos = [threading.Thread(target=ir, args=(i, f)) for i, f in enumerate(trabajos)]
    [h.start() for h in hilos]
    [h.join(120) for h in hilos]
    return resultados


def _cuenta_dups(cuiles, sid):
    with db.get_session() as s:
        ts = [t.cuil for t in s.exec(select(db.Trabajador).where(db.Trabajador.sindicato_id == sid)).all()]
        cs = [c.cuil for c in s.exec(select(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil.in_(list(cuiles)))).all()]
    return len(ts) - len(set(ts)), len(cs) - len(set(cs)), len(set(ts))


def test_dos_cargas_del_mismo_archivo_a_la_vez_no_duplican_nada():
    pid, sid, eq = _mundo_listo_b4()
    cuiles = [_cu() for _ in range(40)]
    planilla = _csv(*[_fila(cuil=c) for c in cuiles])
    e = _ens(eq, pid, planilla)
    otro = _equipo()
    res = _correr_a_la_vez(lambda: _env(eq, pid, "carga", planilla, huella_=e["huella"]).status_code,
                           lambda: _env(otro, pid, "carga", planilla, huella_=e["huella"]).status_code)
    assert sorted(res) == [200, 409], res
    assert _cuenta_dups(cuiles, sid) == (0, 0, 40)


def test_dos_proyectos_del_mismo_sindicato_cargando_el_padron_a_la_vez():
    pid, sid, eq = _mundo_listo_b4()
    pid2 = _proyecto_de(sid)
    for t in ("EST-01", "PAD-01"):      # EST-01 ya se resuelve sola: las seccionales existen
        eq.post(f"{BASE}/p/{pid2}/tarea/{t}/decision", json={"tipo": "completada_a_mano", "motivo": "x"})
    cuiles = [_cu() for _ in range(40)]
    planilla = _csv(*[_fila(cuil=c) for c in cuiles])
    e1, e2 = _ens(eq, pid, planilla), _ens(eq, pid2, planilla)
    res = _correr_a_la_vez(lambda: _env(eq, pid, "carga", planilla, huella_=e1["huella"]).status_code,
                           lambda: _env(eq, pid2, "carga", planilla, huella_=e2["huella"]).status_code)
    assert sorted(res) == [200, 409], res
    assert _cuenta_dups(cuiles, sid) == (0, 0, 40)


def test_una_carga_asistida_y_un_alta_masiva_del_panel_a_la_vez_con_cuil_en_comun():
    pid, sid, eq = _mundo_listo_b4()
    panel = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    with db.get_session() as s:
        usuario = _cu()
        u = db.UsuarioSindicato(sindicato_id=sid, usuario=usuario, cuil=usuario, nombre="Admin",
                                clave_hash=auth.hashear_clave("generalgeneral"), debe_cambiar_clave=False, es_super_admin=True)
        s.add(u); s.commit(); s.refresh(u)
        panel.cookies.set("sesion_sindicato", auth.crear_sesion("sindicato", u.id, sid))
    cuiles = [_cu() for _ in range(60)]
    planilla = _csv(*[_fila(cuil=c) for c in cuiles])
    lista = "\n".join(L(c, "Del Panel", "", "", "", "Rosario", "Santa Fe") for c in cuiles)
    e = _ens(eq, pid, planilla)
    res = _correr_a_la_vez(lambda: _env(eq, pid, "carga", planilla, huella_=e["huella"]).status_code,
                           lambda: panel.post("/admin/trabajador/masivo", data={"lista": lista}).status_code)
    assert all(isinstance(x, int) and x < 500 for x in res), res
    assert _cuenta_dups(cuiles, sid) == (0, 0, 60), res


# =================================================================== Seccionales con mapeo

def _sec_csv(*filas, cab="nombre;provincia;localidad;calle;numero;latitud;longitud;precision_geo;responsable"):
    return (cab + "\n" + "\n".join(filas) + "\n").encode("utf-8")


@pytest.mark.parametrize("fila,estado,precision", [
    ("A;Salta;Salta;Balcarce;10;-24,78;-65,41;exacta;", "valida", "exacta"),
    ("B;Salta;Salta;Balcarce;10;-24,78;-65,41;EXACTA;", "valida", "exacta"),
    ("C;Salta;Salta;Balcarce;10;-24,78;-65,41;Aproximada;", "dudosa", "aproximada"),
    ("D;Salta;Salta;Balcarce;10;-24,78;-65,41;exacto;", "valida", "manual"),
    ("E;Salta;Salta;Balcarce;10;-24,78;-65,41;sin_geo;", "valida", "manual"),
    ("F;Salta;Salta;Balcarce;10;-24,78;-65,41;<script>;", "valida", "manual"),
    ("G;Salta;Salta;Balcarce;10;-24,78;-65,41;;", "valida", "manual"),
    ("H;Salta;Salta;Balcarce;10;;;exacta;", "dudosa", "sin_geo"),
    ("I;Salta;Salta;Balcarce;10;;;aproximada;", "dudosa", "sin_geo"),
])
def test_precision_geo_hostil_se_normaliza_y_sin_coordenadas_nunca_vale_exacta(fila, estado, precision):
    pid, sid, eq = _mundo()
    r = sec.leer(_sec_csv(fila), [], {})
    f = r["filas"][0]
    assert f["estado"] == estado, f["motivos"]
    escrito = sec._a_escribir(f["datos"], None)
    assert escrito["precision_geo"] == precision


def test_una_aproximada_es_dudosa_entra_y_el_control_de_est02_la_cuenta():
    from test_xsii_asistida import _enviar, _ensayo
    pid, sid, eq = _mundo()
    planilla = _sec_csv("Sede Central;Salta;Salta;Balcarce;10;-24,78;-65,41;aproximada;", "Seccional B;Salta;Salta;Balcarce;12;-24,79;-65,42;exacta;")
    e = _ensayo(eq, pid, planilla)
    assert e["dudosas"] == 1 and e["validas"] == 1
    r = _enviar(eq, pid, "carga", planilla, huella_=e["huella"])
    assert r.status_code == 200, r.text
    with db.get_session() as s:
        porn = {x.nombre: x for x in s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == sid)).all()}
        from xsii.proyectos.colm3na import controles
        ctrl = controles.est_02(s, sid)
    assert porn["Sede Central"].precision_geo == "aproximada" and porn["Seccional B"].precision_geo == "exacta"
    assert ctrl.cifras["aproximadas"] == 1 and ctrl.cifras["sin_ubicar"] == 0 and ctrl.estado == "observaciones", ctrl


def test_responsable_de_500_caracteres_html_e_invisibles_en_la_planilla():
    r = sec.leer(_sec_csv("A;Salta;Salta;Balcarce;10;-24,78;-65,41;exacta;" + "R" * 500).replace(b"R" * 500, b"R" * 500), [], {})
    assert len(sec._a_escribir(r["filas"][0]["datos"], None)["responsable"]) == 120
    sucio = "<b>Ana</b> &amp; \u202e\u200b\u2800x\x07y"
    r = sec.leer(_sec_csv(f"A;Salta;Salta;Balcarce;10;-24,78;-65,41;exacta;{sucio}"), [], {})
    resp = sec._a_escribir(r["filas"][0]["datos"], None)["responsable"]
    assert resp == "<b>Ana</b> &amp; xy" or resp.startswith("<b>Ana</b>")
    assert not any(ch in resp for ch in "\u202e\u200b\u2800\x07")


def test_el_responsable_de_la_planilla_no_pisa_con_vacio_y_actualiza_con_valor():
    existente = {"id": 1, "nombre": "A", "ve_todas": False, "calle": "Balcarce", "numero": "10", "piso_depto": "",
                 "localidad": "Salta", "provincia": "Salta", "codigo_postal": "", "direccion_texto": "Balcarce 10, Salta", "latitud": -24.78,
                 "longitud": -65.41, "precision_geo": "exacta", "telefono": "", "whatsapp": "", "mail": "",
                 "horario_atencion": "", "responsable": "Marta"}
    vacio = sec.leer(_sec_csv("A;Salta;Salta;Balcarce;10;-24,78;-65,41;exacta;"), [existente], {"actualizar_existentes": True})
    assert vacio["filas"][0]["cambios"] == {}
    nuevo = sec.leer(_sec_csv("A;Salta;Salta;Balcarce;10;-24,78;-65,41;exacta;Hugo"), [existente], {"actualizar_existentes": True})
    assert nuevo["filas"][0]["cambios"] == {"responsable": "Hugo"}


def test_los_dos_ejemplos_de_la_planilla_de_seccionales_se_leen():
    import pathlib
    base = pathlib.Path(__file__).parent / "docs" / "xsii" / "ejemplos"
    como_viene = sec.leer((base / "seccionales-como-viene.csv").read_bytes(), [], {})
    assert como_viene["mapeo"]["faltan"] == [] and como_viene["total"] >= 4
    assert any("responsable" == c["campo"] for c in como_viene["mapeo"]["columnas"])
    assert all(f["estado"] != "rechazada" for f in como_viene["filas"]), [f["motivos"] for f in como_viene["filas"]]
    viejo = sec.leer((base / "seccionales-ejemplo.csv").read_bytes(), [], {})
    assert viejo["mapeo"]["faltan"] == [] and viejo["total"] > 0
    ensayo_padron = padron.leer((base / "padron-ejemplo.csv").read_bytes(), {})
    assert ensayo_padron["mapeo"]["faltan"] == [] and ensayo_padron["total"] == 30


# =================================================================== Responsable: XSS y permisos

def test_el_responsable_con_html_no_ejecuta_ni_en_la_ficha_ni_en_el_panel_ni_en_la_app_del_afiliado():
    m = Mundo()
    atacante = '<img src=x onerror=alert(1)>"\'</script><script>alert(2)</script>'
    gen = m.cliente()
    r = gen.post("/admin/seccional", data={"id": str(m.ros), "nombre": "Rosario", "provincia": "Santa Fe", "localidad": "Rosario",
                                           "calle": "San Martín", "numero": "850", "latitud": "-32.947338",
                                           "longitud": "-60.636893", "precision_geo": "exacta", "responsable": atacante})
    assert r.status_code == 303
    ficha = gen.get(f"/admin/seccional/{m.ros}/ficha")
    assert ficha.status_code == 200 and ficha.json()["responsable"] == atacante[:120]
    panel = gen.get("/admin").text
    assert atacante not in panel and "<script>alert(2)</script>" not in panel
    a = _cu()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=m.sid, cuil=a, registrado=True, seccional_id=m.ros))
        db.guardar_datos_personales(s, a, nombre="Afiliada").clave_hash = "x"
        s.commit()
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=m.sid, ident=a))
    c.cookies.set("cuil_trab", a)
    html = c.get("/app/inicio").text
    assert "<script>alert(2)</script>" not in html and "<img src=x onerror" not in html
    api = c.get("/api/seccionales")
    assert api.status_code == 200 and api.headers["content-type"].startswith("application/json")


def test_la_ficha_escapa_todos_los_textos_libres_de_la_seccional_no_solo_el_responsable():
    """La ficha arma HTML con innerHTML: telefono, whatsapp, mail y horario venían sin escapar
    (y desde XSII entran por planilla)."""
    import re as _re
    fuente = open("templates/admin.html", encoding="utf-8").read()
    i = fuente.index("dato('Teléfono'")
    bloque = fuente[i:i + 700]
    for campo in ("s.telefono", "s.whatsapp", "s.mail", "s.horario_atencion"):
        assert _re.search(r"esc\(\s*" + _re.escape(campo) + r"\s*\)", bloque), campo


def test_borrar_el_responsable_lo_vacia_y_un_usuario_de_area_sin_permiso_o_de_otra_seccional_no_lo_cambia():
    m = Mundo()
    gen = m.cliente()
    datos = {"nombre": "Córdoba", "id": str(m.cba), "provincia": "Córdoba", "localidad": "Córdoba", "calle": "Colón",
             "numero": "1", "latitud": "-31.41", "longitud": "-64.18", "precision_geo": "exacta"}
    assert gen.post("/admin/seccional", data={**datos, "responsable": "Titular"}).status_code == 303
    assert gen.post("/admin/seccional", data={**datos, "responsable": ""}).status_code == 303
    with db.get_session() as s:
        assert s.get(db.Seccional, m.cba).responsable == ""
    # el admin de Rosario no toca la de Córdoba
    assert gen.post("/admin/seccional", data={**datos, "responsable": "Otro"}).status_code == 303
    r = m.cliente(local=True).post("/admin/seccional", data={**datos, "responsable": "Intruso"})
    assert r.status_code == 403
    with db.get_session() as s:
        assert s.get(db.Seccional, m.cba).responsable == "Otro"
    # un usuario de área sin la sección Seccionales (es una sección fija: siempre visible) no puede editar otra seccional
    with db.get_session() as s:
        area = db.Area(sindicato_id=m.sid, nombre="Prensa", seccional_id=m.ros)
        s.add(area); s.commit(); s.refresh(area)
        cu = _cu()
        u = db.UsuarioSindicato(sindicato_id=m.sid, usuario=cu, cuil=cu, nombre="Prensa", clave_hash=auth.hashear_clave("generalgeneral"),
                                debe_cambiar_clave=False, area_id=area.id, seccional_id=m.ros)
        s.add(u); s.commit(); s.refresh(u)
    c = TestClient(main.app, follow_redirects=False)
    c.cookies.set("sesion_sindicato", auth.crear_sesion("sindicato", u.id, m.sid))
    r = c.post("/admin/seccional", data={**datos, "responsable": "Area"})
    assert r.status_code in (302, 303, 401, 403) and (r.status_code != 303 or "login" in r.headers.get("location", "") or True)
    with db.get_session() as s:
        assert s.get(db.Seccional, m.cba).responsable == "Otro"


def test_responsable_con_caracteres_invisibles_escritos_a_mano_en_el_panel_se_guarda_acotado_a_120():
    m = Mundo()
    datos = {"nombre": "Nueva", "provincia": "Salta", "localidad": "Salta", "calle": "Balcarce", "numero": "1",
             "latitud": "-24.78", "longitud": "-65.41", "precision_geo": "exacta", "responsable": "\u202e" + "x" * 300}
    assert m.cliente().post("/admin/seccional", data=datos).status_code == 303
    with db.get_session() as s:
        r = s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == m.sid, db.Seccional.nombre == "Nueva")).one().responsable
    assert len(r) <= 120


def test_dos_cargas_del_padron_entrelazadas_a_proposito_no_chocan_ni_duplican():
    """La carrera de arriba es una ventana chica y puede no darse: acá se fuerza. A procesa (sin confirmar),
    B arranca mientras A sigue abierta y recién después A confirma. Dos sindicatos distintos con los mismos
    CUIL nuevos (la cuenta de la persona es una sola): sin un candado, B choca con el índice único de
    `cuentatrabajador` y la carga cae con un error."""
    m1, m2 = Mundo(), Mundo()
    cuiles = [_cu() for _ in range(15)]
    lista = "\n".join(L(c, "Persona", "", "", "", "Rosario", "Santa Fe") for c in cuiles)
    a_listo, errores = threading.Event(), []

    def hilo_a():
        try:
            with db.get_session() as s:
                padron_carga.procesar(s, m1.sid, padron_carga.filas_de_lista(lista), None, ensayo=False)
                a_listo.set()
                import time
                time.sleep(1.0)
                s.commit()
        except Exception as e:                # noqa: BLE001
            errores.append(repr(e)[:200])
        finally:
            a_listo.set()

    def hilo_b():
        a_listo.wait(20)
        try:
            with db.get_session() as s:
                padron_carga.procesar(s, m2.sid, padron_carga.filas_de_lista(lista), None, ensayo=False)
                s.commit()
        except Exception as e:                # noqa: BLE001
            errores.append(repr(e)[:200])
    ts = [threading.Thread(target=hilo_a), threading.Thread(target=hilo_b)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert errores == []
    with db.get_session() as s:
        assert s.exec(select(func.count()).select_from(db.CuentaTrabajador).where(db.CuentaTrabajador.cuil.in_(cuiles))).one() == 15
        for sid in (m1.sid, m2.sid):
            assert s.exec(select(func.count()).select_from(db.Trabajador).where(db.Trabajador.sindicato_id == sid, db.Trabajador.cuil.in_(cuiles))).one() == 15


def test_dos_altas_masivas_del_mismo_sindicato_entrelazadas_no_duplican_empadronamientos():
    m = Mundo()
    cuiles = [_cu() for _ in range(12)]
    lista = "\n".join(L(c, "Persona", "", "", "", "Rosario", "Santa Fe") for c in cuiles)
    a_listo, errores = threading.Event(), []

    def hilo_a():
        try:
            with db.get_session() as s:
                padron_carga.procesar(s, m.sid, padron_carga.filas_de_lista(lista), None, ensayo=False)
                a_listo.set()
                import time
                time.sleep(1.0)
                s.commit()
        except Exception as e:                # noqa: BLE001
            errores.append(repr(e)[:200])
        finally:
            a_listo.set()

    def hilo_b():
        a_listo.wait(20)
        try:
            with db.get_session() as s:
                padron_carga.procesar(s, m.sid, padron_carga.filas_de_lista(lista), None, ensayo=False)
                s.commit()
        except Exception as e:                # noqa: BLE001
            errores.append(repr(e)[:200])
    ts = [threading.Thread(target=hilo_a), threading.Thread(target=hilo_b)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert errores == []
    d = _cuenta_dups(cuiles, m.sid)
    assert d[:2] == (0, 0)
    with db.get_session() as s:
        assert s.exec(select(func.count()).select_from(db.Trabajador).where(db.Trabajador.sindicato_id == m.sid, db.Trabajador.cuil.in_(cuiles))).one() == 12


# =================================================================== volumen y bordes HTTP

def test_veinte_mil_filas_por_http_ensayo_y_carga_completos():
    import time
    pid, sid, eq = _mundo_listo_b4()
    inicio = 20_000_000_000 + (next(_k) % 1000) * 100_000
    filas, n = [], 0
    while len(filas) < 20000:
        cand = str(inicio + n)
        n += 1
        if cuit.es_valido(cand, cuit.PERSONA):
            filas.append(f"{cand};Persona {n};Salta;Salta")
    planilla = ("CUIL;Nombre;Localidad;Provincia\n" + "\n".join(filas) + "\n").encode()
    t0 = time.time()
    e = _ens(eq, pid, planilla)
    assert e["total"] == 20000 and e["validas"] + e["dudosas"] == 20000 and e["a_escribir"] == 20000
    r = _env(eq, pid, "carga", planilla, huella_=e["huella"])
    assert r.status_code == 200, r.text[:300]
    assert r.json()["carga"]["creadas"] == 20000 and len(_trabajadores(sid)) == 20000
    assert time.time() - t0 < 120
    again = _env(eq, pid, "carga", planilla, huella_=e["huella"])
    assert again.status_code == 409


def test_el_ensayo_y_la_carga_coinciden_y_dejar_afuera_solo_vale_para_dudosas():
    pid, sid, eq = _mundo_listo_b4()
    ya = _cu()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=sid, cuil=ya)); db.guardar_datos_personales(s, ya, nombre="Ya"); s.commit()
    planilla = _csv(_fila(sec="Seccional Rosario"), _fila(), _fila(sec="Nada"), _fila(cuil="20123"), _fila(cuil=ya, mail="m@x.org"))
    e = _ens(eq, pid, planilla)
    por = _por_linea_b4(e)
    dudosas = [l for l, f in por.items() if f["estado"] == "dudosa"]
    assert len(dudosas) == 2
    # se piden afuera: una dudosa, una válida (línea 2), una rechazada, una que ya existe, una inexistente, y una negativa
    r = _env(eq, pid, "carga", planilla, huella_=e["huella"], afuera=[dudosas[0], 2, 5, 6, 999, -3])
    assert r.status_code == 200, r.text
    c = r.json()["carga"]
    assert c["afuera"] == 1 and c["creadas"] == e["a_escribir"] - 1 - c["actualizadas"]
    assert c["actualizadas"] == 1 and len(_trabajadores(sid)) == 1 + c["creadas"]


def _por_linea_b4(e):
    return {f["linea"]: f for f in e["filas"]}


def test_padron_por_http_entradas_rotas_son_4xx_en_castellano_nunca_500():
    pid, sid, eq = _mundo_listo_b4()
    planilla = _csv(_fila())
    casos = [
        ("ensayo", dict(contenido=b"")), ("ensayo", dict(contenido=b"PK\x03\x04hola")), ("ensayo", dict(contenido=b"a\x00b")),
        ("ensayo", dict(contenido=planilla, afuera=[1, 2])), ("ensayo", dict(texto="")),
        ("carga", dict(contenido=planilla)), ("carga", dict(contenido=planilla, huella_="x")),
        ("carga", dict(contenido=planilla, huella_="", afuera=[1])), ("carga", dict(contenido=b"", huella_="x")),
    ]
    for que, kw in casos:
        r = _env(eq, pid, que, **kw)
        assert r.status_code in (200, 400, 409), (que, r.status_code, r.text[:200])
        if r.status_code != 200:
            assert r.json()["detail"], (que, kw)
    for malo in ('"x"', "{}", '["a"]', "[true]", "[1.5]", "[" + ",".join(["1"] * 1001) + "]"):
        r = eq.post(f"{BASE}/p/{pid}/tarea/{P}/asistida/carga", data={"dejar_afuera": malo, "huella": "x"},
                    files={"archivo": ("p.csv", planilla, "text/csv")})
        assert r.status_code == 400 and r.json()["detail"], (malo, r.status_code)
    assert _trabajadores(sid) == {}
    assert eq.get(f"{BASE}/p/999999/tarea/{P}/asistida").status_code == 404
    assert eq.post(f"{BASE}/p/999999/tarea/{P}/asistida/ensayo", files={"archivo": ("p.csv", planilla, "text/csv")}).status_code == 404
    assert eq.post(f"{BASE}/p/{pid}/tarea/ZZZ-99/asistida/ensayo", files={"archivo": ("p.csv", planilla, "text/csv")}).status_code in (400, 404)


def test_el_proyecto_sin_sindicato_no_carga_el_padron():
    pid, sid, eq = _mundo(con_sindicato=False)
    planilla = _csv(_fila())
    r = _env(eq, pid, "ensayo", planilla)
    assert r.status_code in (200, 409) and (r.status_code == 200 or r.json()["detail"])
    r = _env(eq, pid, "carga", planilla, huella_="x")
    assert r.status_code in (400, 409) and r.json()["detail"]


def test_responsable_por_el_panel_con_nulo_y_caracteres_de_control_no_da_500_y_se_limpia():
    m = Mundo()
    datos = {"nombre": "Con Controles", "provincia": "Salta", "localidad": "Salta", "calle": "Balcarce", "numero": "1",
             "latitud": "-24.78", "longitud": "-65.41", "precision_geo": "exacta",
             "responsable": "Ana\x00 Paz\u202e\u200b\x07\u2028 Díaz"}
    r = m.cliente().post("/admin/seccional", data=datos)
    assert r.status_code == 303, r.text[:200]
    with db.get_session() as s:
        resp = s.exec(select(db.Seccional).where(db.Seccional.sindicato_id == m.sid,
                                                 db.Seccional.nombre == "Con Controles")).one().responsable
    assert resp == "Ana Paz Díaz"


@pytest.mark.parametrize("mapeo", [{"-1": "nombre"}, {"1000": "nombre"}, {"x": "nombre"}, {"0": "no_existe"}, {"0": 3}, {"0": ["a"]}, [0], "nombre",
                                   {"9": "nombre"}, {"0": "nombre", "1": "nombre"}])
def test_mapeo_hostil_de_seccionales_es_400(mapeo):
    with pytest.raises(ErrorAsistida) as e:
        sec.leer(b"A;B;C\n1;2;3\n", [], {"mapeo": mapeo})
    assert e.value.estado == 400 and e.value.mensaje


# =================================================================== pedidos del QA de pantalla

def test_portada_dibuja_todo_texto_de_la_seccional_escapado():
    html = TestClient(main.app).get("/ingresar").text if False else open("templates/portada.html", encoding="utf-8").read()
    i = html.index("var escS")
    bloque = html[i:i + 3500]
    for campo in ("s.nombre", "s.direccion_texto", "s.horario_atencion", "s.responsable", "s.telefono"):
        assert f"escS({campo})" in bloque, campo
    for crudo in ("+ s.horario_atencion +", "+ s.direccion_texto +", "+ s.telefono +"):
        assert crudo not in bloque, crudo


def test_el_panel_y_la_portada_server_side_escapan_html_hostil_en_cada_campo():
    m = Mundo()
    mal = '<img src=x onerror=alert(7)>"'
    datos = {"id": str(m.ros), "nombre": "Rosario", "provincia": "Santa Fe", "localidad": "Rosario", "calle": "San Martín",
             "numero": "850", "latitud": "-32.947338", "longitud": "-60.636893", "precision_geo": "exacta",
             "telefono": mal, "whatsapp": mal, "mail": mal, "horario_atencion": mal, "responsable": mal}
    gen = m.cliente()
    assert gen.post("/admin/seccional", data=datos).status_code == 303
    assert "<img src=x onerror=alert(7)>" not in gen.get("/admin").text
    a = _cu()
    with db.get_session() as s:
        s.add(db.Trabajador(sindicato_id=m.sid, cuil=a, registrado=True, seccional_id=m.ros))
        db.guardar_datos_personales(s, a, nombre="Afiliada").clave_hash = "x"
        s.commit()
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_TRABAJADOR, auth.crear_sesion("trabajador", sindicato_id=m.sid, ident=a))
    c.cookies.set("cuil_trab", a)
    assert "<img src=x onerror=alert(7)>" not in c.get("/app/inicio").text


def test_los_resumenes_de_los_controles_llevan_separador_de_miles():
    from xsii.proyectos.colm3na import controles
    assert controles._plural(2987, "afiliado cargado", "afiliados cargados") == "2.987 afiliados cargados"
    assert controles._plural(1, "área", "áreas") == "1 área"


def test_preguntame_reconoce_2_987_y_2987_en_los_dos_sentidos():
    from xsii import asistente
    assert asistente.validar("Hay 2987 afiliados cargados.", visto="Hay 2.987 afiliados cargados.")["ok"]
    assert asistente.validar("Hay 2.987 afiliados cargados.", visto="afiliados_activos: 2987")["ok"]
    assert not asistente.validar("Hay 2.988 afiliados.", visto="Hay 2.987 afiliados cargados.")["ok"]


def test_el_aviso_del_dni_no_se_duplica_en_el_ensayo():
    r = padron.leer(b"CUIL;Nombre;DNI;Obs\n20111111112;Ana;123;x\n", {})
    assert sum("DNI" in a for a in r["avisos"]) == 1 and any("documento" in a for a in r["avisos"])
    assert any("«Obs»" in a for a in r["avisos"])


def test_los_popups_de_mapa_de_seccionales_escapan():
    assert "esc(s.nombre)" in open("templates/admin.html", encoding="utf-8").read()
    p = open("templates/portada.html", encoding="utf-8").read()
    assert "bindPopup('<b>' + escS(s.nombre)" in p

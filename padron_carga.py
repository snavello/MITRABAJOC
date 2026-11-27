"""La carga de afiliados al padrón: UNA sola implementación de la lógica por
fila, compartida por «Alta masiva» de Trabajadores (`POST
/admin/trabajador/masivo`, líneas separadas por coma) y por la tarea asistida
PAD-02 de XSII (planilla CSV con las columnas mapeadas).

Se extrajo de la ruta sin cambiarle la conducta: mismos contadores, mismos
motivos de «queda afuera», mismas escrituras y mismo ensayo. Lo que la ruta del
panel documenta (fechas, CUIL con módulo 11, domicilio obligatorio, mail del
padrón de quien ya está, cuentas previas, alcance de seccional) rige igual acá.

Quien llama:
- arma las filas (`filas_de_lista` para la línea con comas; la asistida las arma
  de su planilla), cada una `(linea, texto, campos)` con los campos de
  `CAMPOS_FILA` como texto ya recortado;
- pasa la sesión ABIERTA (un request no toma dos conexiones del pool) y hace el
  commit o el rollback: esta función nunca los hace.

Lo que se suma para la asistida y no cambia lo de la masiva:
- `filas` en el resultado: el detalle por fila (resultado, tipo, motivo, dudas);
- `seccional_desconocida="dejar_afuera"`: una seccional escrita que no existe
  deja la fila afuera (por defecto se ignora en silencio, como siempre; en
  cualquier caso la fila queda marcada en el detalle);
- `repetidas="rechazar"`: el mismo CUIL por segunda vez en la planilla se
  rechaza (la primera es la que entra);
- `lineas_afuera`: líneas dudosas que la persona decidió no cargar.
"""

from __future__ import annotations

from sqlmodel import select

import cuit
import db
import geo
import listas

CAMPOS_FILA = ("cuil", "nombre", "calle", "numero", "piso_depto", "localidad", "provincia",
               "telefono", "mail", "codigo_postal", "seccional", "fecha_afiliacion", "fecha_nacimiento")
# El orden de las columnas de la línea con comas de «Alta masiva».
ORDEN_LISTA = CAMPOS_FILA
_LOTE = 5000                  # cuántos CUIL se consultan juntos (IN de la consulta)


def filas_de_lista(lista: str) -> list:
    """La lista pegada de «Alta masiva»: una línea por persona, campos
    separados por coma. Devuelve `[(n_linea, texto, campos)]` salteando las
    líneas en blanco (que igual cuentan para el número de línea)."""
    filas = []
    for n_linea, linea in enumerate(lista.strip().splitlines(), start=1):
        if not linea.strip():
            continue
        partes = [c.strip() for c in linea.split(",")]
        filas.append((n_linea, linea, {k: (partes[i] if len(partes) > i else "")
                                       for i, k in enumerate(ORDEN_LISTA)}))
    return filas


def _de_a_lotes(valores):
    valores = list(valores)
    for i in range(0, len(valores), _LOTE):
        yield valores[i:i + _LOTE]


def procesar(s, sid: int, filas, alcance=None, ensayo: bool = False, *,
             repetidas: str = "legado", seccional_desconocida: str = "ignorar",
             lineas_afuera=(), cuil_mal=None) -> dict:
    """Recorre las filas con las reglas de siempre y, salvo en el ensayo,
    escribe. Devuelve los contadores de la masiva y el detalle por fila:

    `{lineas, altas, actualizaciones, mails_actualizados, fechas_actualizadas,
    datos_ajenos, omitidas, cuil_invalidos, fuera_de_alcance, afuera, filas,
    elegidas_afuera}`. Cada elemento de `filas` es
    `{linea, cuil, nombre, resultado, tipo, motivo, dudas, ...}` con `resultado`
    `alta` | `actualiza` | `afuera` (tipo `existe`: ya estaba y la línea no
    trae nada para actualizar). Ver los `tipo` en el código.

    `cuil_mal(numero) -> bool` es el verificador del CUIL; sin él se usa el
    módulo 11 de persona de `cuit.py` (la ruta del panel pasa `main._cuil_mal`,
    que es la misma regla y la que vigila `test_cuit_puertas.py`)."""
    if cuil_mal is None:
        def cuil_mal(numero):
            return not cuit.es_valido(numero, cuit.PERSONA)
    from db import Seccional, Trabajador, CuentaTrabajador
    filas = list(filas)
    lineas_afuera = set(lineas_afuera)
    por_nombre = {geo._norm(sec.nombre): sec.id for sec in s.exec(
        select(Seccional).where(Seccional.sindicato_id == sid).order_by(Seccional.nombre)).all()}
    hay_seccionales = bool(por_nombre)

    cuiles = {cuit.normalizar(f[2].get("cuil")) for f in filas}
    cuiles.discard("")
    propios, cuentas, con_clave = {}, {}, set()
    for lote in _de_a_lotes(cuiles):
        for t in s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                                 Trabajador.cuil.in_(lote))).all():
            propios[t.cuil] = t
        for c in s.exec(select(CuentaTrabajador).where(CuentaTrabajador.cuil.in_(lote))).all():
            cuentas[c.cuil] = c
        # Quiénes ya se registraron: sobre esas cuentas este padrón solo
        # responde si ya tenía a la persona cargada cuando se registró
        # (`db.responde_por`). Si no, la línea crea el empadronamiento y NO
        # escribe nombre, domicilio, contacto ni mails.
        con_clave |= db.cuiles_con_clave(s, lote)
    existentes = set(propios)
    vistos = set()           # CUIL que ya entraron (alta, actualización o ya estaba) en esta pasada

    altas = lineas_actualizan = 0
    mails_actualizados = fechas_actualizadas = datos_ajenos = fuera_de_alcance = elegidas_afuera = 0
    omitidas, cuil_invalidos, afuera, detalle = [], [], [], []

    for n_linea, texto, c in filas:
        cuil_crudo = (c.get("cuil") or "").strip()
        cuil = cuit.normalizar(cuil_crudo)
        nombre = (c.get("nombre") or "").strip()
        campo = lambda k: (c.get(k) or "").strip()       # noqa: E731
        det = {"linea": n_linea, "cuil": cuil, "nombre": nombre, "resultado": "afuera", "tipo": "",
               "motivo": "", "dudas": [], "seccional": campo("seccional"), "cambia": False}
        detalle.append(det)

        def queda_afuera(tipo, motivo, omitir=True):
            det.update(tipo=tipo, motivo=motivo)
            if omitir:
                omitidas.append(texto.strip()[:60])
            afuera.append({"linea": n_linea, "texto": texto.strip()[:80], "motivo": motivo})

        f_afiliacion = listas.fecha_formulario(campo("fecha_afiliacion"))
        f_nacimiento = listas.fecha_formulario(campo("fecha_nacimiento"))
        if f_afiliacion is None or f_nacimiento is None:
            queda_afuera("fecha", "Una de las fechas no se entiende (AAAA-MM-DD o DD/MM/AAAA).")
            continue
        if repetidas == "rechazar" and cuil in vistos:
            queda_afuera("repetida", "Repetida en la planilla: se carga la primera.")
            continue
        if len(cuil) == 11 and cuil in existentes and (campo("mail") or f_afiliacion):
            # Ya está en el padrón de este sindicato (quizá ya registrado): no
            # es un alta, pero la línea trae el mail y esta es la ÚNICA vía que
            # tiene el gremio para cargar el mail del padrón de quien ya tiene
            # cuenta. Solo `mail_padron`: ni el contacto ni el resto de los
            # datos de la persona se tocan.
            t = propios.get(cuil)
            if t is None:
                # El mismo CUIL, ya dado de alta unas líneas antes de esta misma
                # lista: no hay empadronamiento previo que actualizar.
                queda_afuera("existe", "El CUIL ya está en la lista (repetido).")
                continue
            if f_afiliacion:
                if f_afiliacion != (t.fecha_afiliacion or ""):
                    det["cambia"] = True
                if not ensayo:
                    t.fecha_afiliacion = f_afiliacion
                    s.add(t)
                fechas_actualizadas += 1
            if campo("mail"):
                if db.responde_por(cuil in con_clave, t.registrado):
                    cuenta = cuentas.get(cuil)
                    if campo("mail")[:200] != ((cuenta.mail_padron if cuenta else "") or ""):
                        det["cambia"] = True
                    if not ensayo:
                        cuentas[cuil] = db.guardar_datos_personales(s, cuil, mail_padron=campo("mail"),
                                                                    cuenta=cuentas.get(cuil))
                    mails_actualizados += 1
                else:
                    datos_ajenos += 1
                    det["dudas"].append("La persona ya tiene cuenta por otro sindicato: no se le toca el mail del padrón.")
            lineas_actualizan += 1       # una vez por línea, aunque traiga mail y fecha
            det.update(resultado="actualiza")
            vistos.add(cuil)
            continue
        if len(cuil) != 11 or not nombre or cuil in existentes:
            if len(cuil) == 11 and cuil in existentes:
                queda_afuera("existe", "El CUIL ya está en el padrón (y la línea no trae mail ni fecha de afiliación para actualizar).")
                vistos.add(cuil)
            else:
                tipo = "sin_cuil" if not cuil else ("cuil_longitud" if len(cuil) != 11 else "sin_nombre")
                queda_afuera(tipo, "Falta el CUIL (11 números) o el nombre.")
            continue
        # Un CUIL cuyo verificador no cierra: la línea queda afuera y se cuenta
        # aparte, con el número a la vista. Si entrara, el padrón se llenaría
        # de personas que no pueden registrarse y nadie sabría por qué.
        if cuil_mal(cuil):
            cuil_invalidos.append(cuil_crudo[:20])
            queda_afuera("cuil_invalido", "El CUIL no es válido: revisá los 11 números.", omitir=False)
            continue
        if geo.faltan_campos({"localidad": campo("localidad"), "provincia": campo("provincia")}):
            queda_afuera("domicilio", "Falta la localidad o la provincia.")
            continue
        sec_texto = campo("seccional")
        sec_linea = por_nombre.get(geo._norm(sec_texto))
        desconocida = bool(sec_texto) and sec_linea is None
        det["seccional_desconocida"] = desconocida
        if desconocida and seccional_desconocida == "dejar_afuera":
            queda_afuera("seccional_desconocida", f"La seccional «{sec_texto[:60]}» no existe en este sindicato.")
            continue
        # Un admin acotado carga solo en su seccional: una línea con otra
        # seccional queda omitida (y se informa), una sin seccional va a la suya.
        if alcance is not None:
            if not sec_linea and len(alcance) == 1:
                sec_linea = next(iter(alcance))
            if not db.en_alcance(alcance, sec_linea):
                fuera_de_alcance += 1
                queda_afuera("alcance", "La seccional no es la tuya: cargás solo en tu seccional.")
                continue
        if desconocida:
            det["dudas"].append(f"La seccional «{sec_texto[:60]}» no existe en este sindicato: entra sin seccional.")
        elif sec_linea is None and hay_seccionales:
            det["dudas"].append("Sin seccional: entra sin asignar.")
        if cuil in con_clave:
            det["dudas"].append("La persona ya tiene cuenta por otro sindicato: entra al padrón y no se le tocan los datos.")
        if det["dudas"] and n_linea in lineas_afuera:
            elegidas_afuera += 1
            det.update(tipo="elegida", motivo="La dejaste afuera.")
            continue
        domicilio = geo.campos_para_guardar({
            "calle": campo("calle"), "numero": campo("numero"), "piso_depto": campo("piso_depto"),
            "localidad": campo("localidad"), "provincia": campo("provincia"),
            "codigo_postal": campo("codigo_postal")}, precision="sin_geo")
        if not ensayo:
            s.add(Trabajador(sindicato_id=sid, cuil=cuil, seccional_id=sec_linea,
                             fecha_afiliacion=f_afiliacion or None))
        if cuil in con_clave:
            datos_ajenos += 1     # empadronamiento nuevo sobre una cuenta ya hecha: solo eso
        elif not ensayo:
            if cuil not in cuentas:       # ya se buscaron todas por lote: no hay una consulta por persona
                cuentas[cuil] = CuentaTrabajador(cuil=cuil)
                s.add(cuentas[cuil])
            db.guardar_datos_personales(
                s, cuil, nombre=nombre, domicilio=domicilio, telefono=campo("telefono"),
                mail=campo("mail"), mail_padron=campo("mail") or None,
                fecha_nacimiento=f_nacimiento or None, cuenta=cuentas[cuil])
        existentes.add(cuil)
        vistos.add(cuil)
        altas += 1
        det.update(resultado="alta", seccional_id=sec_linea)
    return {"lineas": len(filas), "altas": altas, "actualizaciones": lineas_actualizan,
            "mails_actualizados": mails_actualizados, "fechas_actualizadas": fechas_actualizadas,
            "datos_ajenos": datos_ajenos, "omitidas": omitidas, "cuil_invalidos": cuil_invalidos,
            "fuera_de_alcance": fuera_de_alcance, "afuera": afuera, "filas": detalle,
            "elegidas_afuera": elegidas_afuera}

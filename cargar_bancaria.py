# -*- coding: utf-8 -*-
"""Alta de "La Bancaria" (Asociación Bancaria) + su lote de datos sintéticos.

Los conceptos y las reglas de cálculo salen del **CCT 18/75** (el texto
ordenado del convenio bancario, `docs/cct-1875-bancarios.md` resume lo
relevante). Dos particularidades del convenio que mandan sobre el resto:

1. **Casi todos los adicionales son un % del "sueldo inicial"** (Auxiliar
   inicial, art. 5), NO del básico propio del agente: un cajero con 20 años
   cobra su adicional sobre el inicial, no sobre su básico de coeficiente
   1,74 (arts. 11, 12, 14, 16, 22, 24, 25).
2. **La antigüedad NO es una línea aparte**: está embebida en el básico, que
   sube por escala de coeficientes y dispara promociones automáticas a los
   15/20/25/30/35 años (art. 5). Un rubro "Antigüedad" suelto no existe en
   este convenio.

El sueldo inicial y la participación en las ganancias (ROE) son los reales
acordados con las cámaras para **julio de 2026**; el ROE no surge del CCT
(art. 42 b solo prohíbe absorberlo) sino del acuerdo paritario.

Los aportes de ley (jubilación, INSSJP, obra social) y la cuota sindical
**tampoco están en el CCT** —el convenio no fija ningún porcentaje—: son de
la ley general y del estatuto gremial. Por eso la cuota sindical se carga
como concepto pero SIN fórmula de validación: el sistema no puede reclamar
un porcentaje que el convenio no fija.

Uso:
    python cargar_bancaria.py            # crea el sindicato y siembra el lote
    python cargar_bancaria.py --limpiar  # borra el lote (deja el sindicato)
"""
import random
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import select

import auth
import db
from db import Sindicato, UsuarioSindicato, Concepto, Formula
import cargar_lote_sindicato as lote

NOMBRE = "La Bancaria"
ADMIN = ("20333444550", "bancaria-demo")

# Julio 2026, acordado con las cámaras empresariales bancarias.
SUELDO_INICIAL = 2_463_757.68      # Auxiliar inicial, art. 5 (coeficiente 1,00)
ROE_JULIO_2026 = 71_219.54         # Participación en las ganancias

# Art. 5: coeficiente del básico según años de antigüedad (la antigüedad va
# ADENTRO del básico). Se toma el tramo cumplido más alto.
ESCALA_ANTIGUEDAD = [
    (0, 1.00), (1, 1.04), (2, 1.08), (3, 1.11), (4, 1.13), (5, 1.17), (6, 1.20),
    (7, 1.24), (8, 1.26), (9, 1.30), (10, 1.35), (11, 1.39), (12, 1.43), (13, 1.48),
    (14, 1.52), (15, 1.63), (20, 1.74), (25, 1.96), (30, 2.07), (35, 2.17),
]
# Art. 5: la categoría también la da la antigüedad (promociones automáticas).
CATEGORIA_POR_ANTIGUEDAD = [
    (35, "2º Jefe de División de 1º"), (30, "2º Jefe de División de 2º"),
    (25, "2º Jefe de División de 3º"), (20, "Jefe de Sección"),
    (15, "Ayudante de firma"), (0, "Auxiliar"),
]

# Conceptos: (código, nombre, tipo, remunerativo, categoria_sindical)
CONCEPTOS = [
    ("BAS", "Sueldo básico (art. 5 CCT 18/75)", "ingreso", True, ""),
    ("ROE", "Participación en las ganancias (ROE)", "ingreso", True, ""),
    ("CAJFUN", "Adicional cajero - función (art. 22)", "ingreso", True, ""),
    ("CAJFAL", "Adicional falla de caja (art. 22)", "ingreso", True, ""),
    ("TITULO", "Adicional por título habilitante (art. 10)", "ingreso", True, ""),
    ("TECNICO", "Adicional funciones técnicas con título (art. 11)", "ingreso", True, ""),
    ("COMPU", "Adicional computación (art. 14)", "ingreso", True, ""),
    ("NOCTUR", "Suplemento horario nocturno (art. 15 B)", "ingreso", True, ""),
    ("MAQCON", "Adicional máquinas de contabilidad (art. 24)", "ingreso", True, ""),
    ("PORTAV", "Adicional portavalores (art. 39)", "ingreso", True, ""),
    ("ZONA", "Adicional por zona desfavorable (art. 25)", "ingreso", True, ""),
    # Los tres aportes de ley usan los códigos UNIVERSALES de la plataforma
    # (validador.CONCEPTOS_UNIVERSALES): todo sindicato nuevo los recibe solo
    # al darse de alta desde /plataforma. Inventarles un código propio los
    # duplicaba —dos jubilaciones, dos obras sociales— y cada fórmula sumaba
    # su línea a todos los recibos (visto en producción, 2026-08-31).
    ("JUBILACION", "Aporte jubilatorio (SIPA)", "descuento", True, ""),
    ("PAMI", "Ley 19.032 (PAMI)", "descuento", True, ""),
    ("OBRASOCIAL", "Obra Social", "descuento", True, ""),
    ("CUOTA", "Cuota sindical Asociación Bancaria", "descuento", True, "afiliacion"),
]

# Solo los aportes de LEY llevan fórmula: son los únicos con un porcentaje
# exigible. La cuota sindical no la fija el CCT (ver encabezado). Coinciden
# con las que crea db.crear_conceptos_universales, así que si el sindicato ya
# existía no se agrega ninguna: se reutilizan las suyas.
FORMULAS = [
    ("JUBILACION", "Jubilación (SIPA) = 11% del remunerativo", "0.11 * base_remunerativa", 1.0, True),
    ("PAMI", "Ley 19.032 (PAMI) = 3% del remunerativo", "0.03 * base_remunerativa", 1.0, True),
    ("OBRASOCIAL", "Obra Social = 3% del remunerativo", "0.03 * base_remunerativa", 1.0, True),
]

# Art. 22: cajero. (función, falla de caja) como % del sueldo inicial.
CAJEROS = {"Recibidor": (0.15, 0.20), "Recibidor y pagador": (0.20, 0.30), "Pagador": (0.25, 0.40)}
# Art. 10: un solo adicional por título, el de mayor monto. Como el CCT los
# fija en pesos de 1975, se expresan como % del inicial manteniendo su
# proporción original (150/300/450 sobre 4.600).
TITULOS = {"secundario": 0.0326, "intermedio": 0.0652, "universitario": 0.0978}
# Art. 11, agrupamiento III (el más frecuente), letras por antigüedad en la función.
TECNICO_III = [0.352, 0.638 / 2, 0.562, 0.495, 0.419, 0.352]
# Art. 25: zona desfavorable por grupo.
ZONAS = {"A": 0.60, "B": 0.50, "C": 0.40, "D": 0.20}


def coeficiente_antiguedad(anios: int) -> float:
    coef = 1.00
    for desde, valor in ESCALA_ANTIGUEDAD:
        if anios >= desde:
            coef = valor
    return coef


def categoria_de(anios: int) -> str:
    for desde, nombre in CATEGORIA_POR_ANTIGUEDAD:
        if anios >= desde:
            return nombre
    return "Auxiliar"


def _linea(codigo: str, importe: float) -> dict:
    nombre = next(c[1] for c in CONCEPTOS if c[0] == codigo)
    return {"codigo": codigo, "descripcion": nombre, "importe": round(importe, 2),
            "tipo": "remuneracion", "categoria_universal": None}


def componer_recibo_bancario(rnd, trab, conceptos, fecha_proceso):
    """Las líneas de ingreso de un recibo bancario, según el CCT 18/75.

    Los rasgos del agente (antigüedad, si es cajero, título, zona) son
    ESTABLES: salen de una semilla derivada de su CUIL, no se sortean en cada
    recibo. Lo que sí varía mes a mes es lo circunstancial (horas nocturnas,
    si ese mes hizo de portavalores)."""
    propio = random.Random(trab["semilla"])
    anios = trab["antiguedad"]
    trab["categoria"] = categoria_de(anios)

    lineas = [_linea("BAS", SUELDO_INICIAL * coeficiente_antiguedad(anios))]
    lineas.append(_linea("ROE", ROE_JULIO_2026))

    # Función de caja (art. 22): dos líneas separadas, función y falla.
    if propio.random() < 0.22:
        funcion = propio.choice(list(CAJEROS))
        pct_funcion, pct_falla = CAJEROS[funcion]
        lineas.append(_linea("CAJFUN", SUELDO_INICIAL * pct_funcion))
        lineas.append(_linea("CAJFAL", SUELDO_INICIAL * pct_falla))

    # Título habilitante (art. 10): uno solo, el de mayor monto.
    if propio.random() < 0.45:
        titulo = propio.choice(list(TITULOS))
        lineas.append(_linea("TITULO", SUELDO_INICIAL * TITULOS[titulo]))
        # Adicional por funciones técnicas (art. 11), solo si además las ejerce.
        if titulo == "universitario" and propio.random() < 0.5:
            letra = min(5, max(0, 5 - anios // 3))
            lineas.append(_linea("TECNICO", SUELDO_INICIAL * TECNICO_III[letra]))

    if propio.random() < 0.12:                      # área de computación (art. 14)
        lineas.append(_linea("COMPU", SUELDO_INICIAL * propio.choice([0.667, 0.619, 0.571])))
        if rnd.random() < 0.4:                      # nocturno, a prorrata (art. 15 B)
            lineas.append(_linea("NOCTUR", SUELDO_INICIAL * 0.0435 * rnd.uniform(0.3, 1.0)))
    elif propio.random() < 0.15:                    # máquinas de contabilidad (art. 24)
        lineas.append(_linea("MAQCON", SUELDO_INICIAL * 0.057))

    if rnd.random() < 0.08:                         # portavalores, mes a mes (art. 39)
        lineas.append(_linea("PORTAV", SUELDO_INICIAL * 0.0652))

    if propio.random() < 0.18:                      # zona desfavorable (art. 25)
        lineas.append(_linea("ZONA", SUELDO_INICIAL * ZONAS[propio.choice(list(ZONAS))]))

    # Cuota sindical: el 70% de los recibos la tiene (afiliados cotizantes).
    # Sin fórmula que la valide, su ausencia no genera discrepancia.
    if propio.random() < 0.70:
        base = sum(l["importe"] for l in lineas)
        lineas.append({"codigo": "CUOTA", "descripcion": "Cuota sindical Asociación Bancaria",
                       "importe": -round(base * 0.02, 2), "tipo": "aporte_trabajador",
                       "categoria_universal": "cuota_sindical"})
    return lineas


def _completar_catalogo(sid: int) -> tuple:
    """Agrega los conceptos, fórmulas y el admin que FALTEN (por código), sin
    tocar lo que el sindicato ya tenga cargado.

    Existe porque el sindicato puede haberse creado antes a mano desde
    /plataforma: si el script se limitaba a saltear la creación, quedaba sin
    catálogo y los recibos no se podían armar ni validar."""
    with db.get_session() as s:
        codigos = {c.codigo for c in s.exec(select(Concepto).where(
            Concepto.sindicato_id == sid)).all()}
        nuevos_conceptos = 0
        for codigo, nombre, tipo, remunerativo, categoria in CONCEPTOS:
            if codigo in codigos:
                continue
            s.add(Concepto(sindicato_id=sid, codigo=codigo, nombre=nombre, tipo=tipo,
                           remunerativo=remunerativo, alias=[nombre],
                           categoria_sindical=categoria))
            nuevos_conceptos += 1
        targets = {f.target for f in s.exec(select(Formula).where(
            Formula.sindicato_id == sid)).all()}
        nuevas_formulas = 0
        for target, descripcion, expr, tolerancia, tope in FORMULAS:
            if target in targets:
                continue
            s.add(Formula(sindicato_id=sid, target=target, descripcion=descripcion,
                          expr=expr, tolerancia=tolerancia, sujeto_a_tope=tope))
            nuevas_formulas += 1
        if not s.exec(select(UsuarioSindicato).where(
                UsuarioSindicato.sindicato_id == sid,
                UsuarioSindicato.usuario == ADMIN[0])).first():
            s.add(UsuarioSindicato(sindicato_id=sid, usuario=ADMIN[0], nombre="Administrador",
                                   clave_hash=auth.hashear_clave(ADMIN[1]),
                                   debe_cambiar_clave=False))
        s.commit()
    return nuevos_conceptos, nuevas_formulas


# Códigos que este script usó ANTES para los aportes de ley, antes de
# alinearse con los universales de la plataforma. Se borran solos: eran
# duplicados (dos jubilaciones, dos obras sociales) y cada fórmula sumaba su
# línea a todos los recibos.
LEGACY = {"JUB": "JUBILACION", "OSOC": "OBRASOCIAL"}


def quitar_duplicados_legacy(sid: int) -> None:
    with db.get_session() as s:
        formulas = [f for f in s.exec(select(Formula).where(
            Formula.sindicato_id == sid)).all() if f.target in LEGACY]
        conceptos = [c for c in s.exec(select(Concepto).where(
            Concepto.sindicato_id == sid)).all() if c.codigo in LEGACY]
        if not formulas and not conceptos:
            return
        for f in formulas:
            s.delete(f)
        for c in conceptos:
            s.delete(c)
        s.commit()
    quitados = sorted({f.target for f in formulas} | {c.codigo for c in conceptos})
    print("  Duplicados de aportes de ley eliminados (ahora se usan los códigos "
          f"universales): {', '.join(quitados)}")


def revisar_catalogo_ajeno(sid: int) -> None:
    """Aborta si el sindicato tiene FÓRMULAS que no son de este convenio.

    Pasó en producción: "La Bancaria" se había creado a mano y arrastraba un
    concepto y una fórmula de AEFIP. Como la autocorrección agrega una línea
    por cada fórmula del sindicato, ese concepto ajeno terminó en los 5.000
    recibos y en los reportes. Una fórmula de más ensucia TODO el lote, así
    que se corta antes de sembrar; los conceptos de más solo se avisan (no
    generan líneas por sí solos)."""
    codigos_convenio = {c[0] for c in CONCEPTOS}
    with db.get_session() as s:
        conceptos = {c.codigo: c.nombre for c in s.exec(select(Concepto).where(
            Concepto.sindicato_id == sid)).all()}
        formulas = {f.target: f.descripcion for f in s.exec(select(Formula).where(
            Formula.sindicato_id == sid)).all()}
    ajenas = {t: d for t, d in formulas.items() if t not in codigos_convenio}
    if ajenas:
        print("\nFÓRMULAS QUE NO SON DE ESTE CONVENIO:")
        for target, descripcion in sorted(ajenas.items()):
            print(f"   {target} — {descripcion}")
        sys.exit(
            "\nCada fórmula agrega su línea a TODOS los recibos: con estas, el lote\n"
            "saldría con conceptos que no son de La Bancaria. Borralas desde\n"
            "/admin → Fórmulas (y su concepto, si tampoco corresponde) y volvé a correr.")
    ajenos = {c: n for c, n in conceptos.items() if c not in codigos_convenio}
    if ajenos:
        print("Aviso: hay conceptos fuera del CCT 18/75 (no afectan la simulación, "
              "pero se ven en /admin → Conceptos):")
        for codigo, nombre in sorted(ajenos.items()):
            print(f"   {codigo} — {nombre}")


def crear_sindicato() -> int:
    with db.get_session() as s:
        existente = s.exec(select(Sindicato).where(Sindicato.nombre == NOMBRE)).first()
        if existente:
            sid = existente.id
            print(f"'{NOMBRE}' ya existe (id={sid}): completo lo que falte.")
            quitar_duplicados_legacy(sid)
            conceptos, formulas = _completar_catalogo(sid)
            print(f"  Conceptos agregados: {conceptos} · fórmulas agregadas: {formulas}.")
            return sid
        sind = Sindicato(
            nombre=NOMBRE, slug="la-bancaria",
            descripcion="Asociación Bancaria — Sociedad de Empleados de Banco (CCT 18/75)",
            cuit="30-52573385-9", mail="info@labancaria.org",
            autoridad="Comisión Directiva Nacional", cargo_autoridad="Secretaría General",
            color_base="#132a4a", color_primario="#1d4e89",
            color_acento="#e8b84b", color_secundario="#2f8f83",
            color_destacado="#E5188F",
            modulos_habilitados=["recibos", "aportes", "credencial", "capacitacion",
                                 "noticias", "beneficios", "notificaciones", "tramites",
                                 "dashboard"],
        )
        s.add(sind); s.commit(); s.refresh(sind)
        sid = sind.id
    _completar_catalogo(sid)
    print(f"'{NOMBRE}' creado (id={sid}): {len(CONCEPTOS)} conceptos, {len(FORMULAS)} fórmulas.")
    return sid


if __name__ == "__main__":
    # El perfil se registra ANTES de armar el contexto del lote.
    lote.PERFILES["BANCARIA"] = componer_recibo_bancario

    sid = crear_sindicato()
    ctx = lote.contexto_lote(sid, NOMBRE)

    if "--limpiar" in sys.argv:
        lote.limpiar(sid, ctx)
        sys.exit(0)

    revisar_catalogo_ajeno(sid)

    # El corte mira los RECIBOS, no los trabajadores: si una corrida anterior
    # se cortó después de sembrar la base, hay que poder retomarla (sembrar_base
    # es idempotente).
    with db.get_session() as s:
        from db import ReciboVerificado
        if s.exec(select(ReciboVerificado).where(
                ReciboVerificado.sindicato_id == sid,
                ReciboVerificado.cuil.in_(ctx["cuils"][:5]))).first():
            sys.exit("El lote de La Bancaria ya está cargado (usá --limpiar para regenerarlo).")

    print("Sembrando base (seccionales, bancos, 100 trabajadores con cuenta)...")
    trabajadores, empresas, secc_ids = lote.sembrar_base(sid, ctx)
    print("Generando y VALIDANDO 5.000 recibos con los conceptos del CCT 18/75...")
    contadores = lote.sembrar_recibos(sid, ctx, trabajadores)
    print(f"  Recibos: {contadores.get('OK', 0)} OK, "
          f"{contadores.get('CON_DISCREPANCIAS', 0)} con discrepancias, "
          f"{contadores['enviados']} enviados, {contadores['reportados']} reportados.")
    print("Creando 5 tipos de trámite y 2.000 trámites con formulario y diálogo...")
    print(f"  Trámites creados: {lote.sembrar_tramites(sid, ctx, trabajadores)}.")
    print("Enviando 200 notificaciones...")
    print(f"  Notificaciones: {lote.sembrar_notificaciones(sid, ctx, secc_ids, trabajadores)}.")
    print("Cargando 30 noticias y 20 beneficios...")
    lote.sembrar_contenido(sid, ctx, secc_ids)

    print(f"\nLa Bancaria lista. Admin: {ADMIN[0]} / {ADMIN[1]}")
    print("Trabajadores de ejemplo (clave = 5 primeros dígitos del CUIL):")
    for t in trabajadores[:3]:
        print(f"  {t['nombre']}: CUIL {t['cuil']} / clave {t['cuil'][:5]}")

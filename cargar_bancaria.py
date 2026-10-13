# -*- coding: utf-8 -*-
"""Alta de "La Bancaria" (Asociación Bancaria) + su lote de datos sintéticos.

La ESTRUCTURA sale del **CCT 18/75** (categorías, coeficientes, qué
adicionales existen) y los MONTOS de la **grilla salarial de agosto 2026**,
firmada con las cámaras el 11/09/2026 (`docs/cct-1875-bancarios.md` la
transcribe entera, con las fuentes). Lo que manda sobre el resto:

1. **Básico y conformado no son lo mismo.** El básico es el de la categoría
   (tiene un piso de $ 1.642.764,63 hasta cierta antigüedad); el conformado
   ($ 2.505.061,24 el inicial, el "Salario Inicial" del comunicado mensual) es
   la remuneración mínima garantizada hasta los 15 años. La diferencia va en
   una línea propia, "Complemento salario conformado". Cómo la imprime un
   banco no lo dice la grilla: el nombre y la mecánica son un supuesto.
2. **Los adicionales son montos fijos** (cajero, falla de caja, título, zona
   patagónica), no un % del inicial como en el texto de 1975.
3. **El ROE sale de una tabla**: tramo de sueldo bruto × ROE del banco, en
   montos anuales que se cobran de a 1/12.
4. **La antigüedad NO es una línea aparte**: está embebida en el básico, que
   sube por la escala de coeficientes y dispara promociones automáticas a los
   15/20/25/30/35 años (art. 44).

Los aportes de ley (jubilación, INSSJP, obra social) y la cuota sindical
**no están en el CCT** —el convenio no fija ningún porcentaje—: son de la ley
general y del estatuto gremial. Por eso la cuota sindical se carga como
concepto pero SIN fórmula de validación.

Uso:
    python cargar_bancaria.py                    # crea el sindicato y siembra el lote
    python cargar_bancaria.py --limpiar          # borra el lote (deja el sindicato)
    python cargar_bancaria.py --rehacer-recibos  # borra y regenera SOLO los recibos
                                                 # del lote (y sus envíos y reportes)
    python cargar_bancaria.py --borrar-recibos-de CUIL [--si]
        # borra los recibos, envíos, reportes y alertas de UN CUIL en La Bancaria
        # (la cuenta queda). Sin --si solo muestra qué borraría.
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
from grilla_bancaria import (GRILLA, FUNCION_CAJERO, FALLA_DE_CAJA, TITULOS,
                             ZONA_PATAGONICA, categoria_de, fila_de_escala, roe_mensual)

NOMBRE = "La Bancaria"
ADMIN = ("20333444551", "bancaria-demo")

# Conceptos: (código, nombre, tipo, remunerativo, categoria_sindical)
CONCEPTOS = [
    ("BAS", "Sueldo básico (art. 5 CCT 18/75)", "ingreso", True, ""),
    ("CONFOR", "Complemento salario conformado", "ingreso", True, ""),
    ("ROE", "Participación en las ganancias (ROE)", "ingreso", True, ""),
    ("CAJFUN", "Adicional cajero - función (art. 22)", "ingreso", True, ""),
    ("CAJFAL", "Adicional falla de caja (art. 22)", "ingreso", True, ""),
    ("TITULO", "Adicional por título habilitante (art. 10)", "ingreso", True, ""),
    # Los cinco que siguen existen en el CCT pero la grilla vigente no les
    # publica monto: quedan en el catálogo y la simulación no los usa.
    ("TECNICO", "Adicional funciones técnicas con título (art. 11)", "ingreso", True, ""),
    ("COMPU", "Adicional computación (art. 14)", "ingreso", True, ""),
    ("NOCTUR", "Suplemento horario nocturno (art. 15 B)", "ingreso", True, ""),
    ("MAQCON", "Adicional máquinas de contabilidad (art. 24)", "ingreso", True, ""),
    ("PORTAV", "Adicional portavalores (art. 39)", "ingreso", True, ""),
    ("ZONA", "Adicional zona patagónica (art. 25)", "ingreso", True, ""),
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

# Cada banco tiene SU tramo de ROE (lo publica el BCRA), estable: sale del
# CUIT. Pesos: la mayoría en los tramos medios y alguno que no paga.
PESOS_TRAMO_ROE = [1, 3, 3, 2, 1, 1]


def antiguedad_de(cuil: str) -> int:
    """Años de antigüedad del agente, estables y derivados del CUIL: así el
    lote y su regeneración (--rehacer-recibos) le dan la misma categoría."""
    return random.Random(f"antig-{cuil}").randint(0, 38)


def tramo_roe_del_banco(cuit: str) -> int:
    return random.Random(f"roe-{cuit}").choices(range(6), weights=PESOS_TRAMO_ROE)[0]


def _linea(codigo: str, importe: float) -> dict:
    nombre = next(c[1] for c in CONCEPTOS if c[0] == codigo)
    return {"codigo": codigo, "descripcion": nombre, "importe": round(importe, 2),
            "tipo": "remuneracion", "categoria_universal": None}


def componer_recibo_bancario(rnd, trab, conceptos, fecha_proceso):
    """Las líneas de ingreso de un recibo bancario, con la grilla vigente.

    Los rasgos del agente (antigüedad, si es cajero, título, zona) son
    ESTABLES: salen de una semilla derivada de su CUIL, no se sortean en cada
    recibo. El ROE depende del banco (su tramo es fijo) y del bruto del mes."""
    propio = random.Random(trab["semilla"])
    anios = antiguedad_de(trab["cuil"])
    trab["categoria"] = categoria_de(anios)
    _, _, basico, conformado = fila_de_escala(anios)

    lineas = [_linea("BAS", basico)]
    if conformado and conformado > basico:
        lineas.append(_linea("CONFOR", conformado - basico))

    # Cajero (art. 22): dos líneas separadas, función y falla.
    if propio.random() < 0.22:
        lineas.append(_linea("CAJFUN", FUNCION_CAJERO))
        lineas.append(_linea("CAJFAL", FALLA_DE_CAJA))

    # Título habilitante (art. 10): uno solo, el de mayor monto.
    if propio.random() < 0.45:
        lineas.append(_linea("TITULO", TITULOS[propio.choice(list(TITULOS))]))

    # Zona patagónica: solo quien trabaja allá.
    if propio.random() < 0.10:
        lineas.append(_linea("ZONA", ZONA_PATAGONICA[propio.choice(list(ZONA_PATAGONICA))]))

    # ROE: el tramo de bruto se elige con el mes SIN el ROE.
    bruto = sum(l["importe"] for l in lineas)
    roe = roe_mensual(bruto, tramo_roe_del_banco(trab["empresa"]["cuit"]))
    if roe:
        lineas.insert(1, _linea("ROE", roe))

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
                                   debe_cambiar_clave=False, es_super_admin=True))
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
            cuit="30-52573385-4", mail="info@labancaria.org",
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


def _tablas_de_recibos():
    """Donde vive un recibo leído o sembrado, por CUIL. UsoIA NO: es el
    historial de gasto de la IA, y borrarlo haría mentir al panel de costos."""
    from db import ReciboVerificado, EnvioSindicato, Reporte, ReciboSospechoso
    return (ReciboVerificado, EnvioSindicato, Reporte, ReciboSospechoso)


def borrar_recibos(sid: int, cuils: set, aplicar: bool) -> dict:
    """Borra los recibos, envíos al sindicato, reportes y alertas de
    adulteración de esos CUIL en ESTE sindicato. Las cuentas, el padrón y los
    trámites no se tocan. Sin `aplicar` solo cuenta."""
    conteo = {}
    with db.get_session() as s:
        for modelo in _tablas_de_recibos():
            filas = s.exec(select(modelo).where(modelo.sindicato_id == sid,
                                                modelo.cuil.in_(cuils))).all()
            conteo[modelo.__tablename__] = len(filas)
            if aplicar:
                for fila in filas:
                    s.delete(fila)
        if aplicar:
            s.commit()
    return conteo


def trabajadores_del_lote(sid: int, ctx: dict) -> list:
    """Los trabajadores del lote YA sembrado, leídos de la base.

    `lote.sembrar_base` no sirve para esto: vuelve a sortear el nombre y lo
    escribe en la cuenta de la persona, así que regenerar los recibos le
    cambiaría el nombre a los cien afiliados."""
    from db import Trabajador, CuentaTrabajador, Empleador
    conductas = dict(lote.BANCOS)
    with db.get_session() as s:
        razones = {e.cuit: e.razon_social or e.cuit for e in s.exec(
            select(Empleador).where(Empleador.sindicato_id == sid)).all()}
        nombres = {c.cuil: c.nombre for c in s.exec(select(CuentaTrabajador).where(
            CuentaTrabajador.cuil.in_(ctx["cuils"]))).all()}
        filas = s.exec(select(Trabajador).where(Trabajador.sindicato_id == sid,
                                                Trabajador.cuil.in_(ctx["cuils"]))).all()
    orden = {c: i for i, c in enumerate(ctx["cuils"])}
    trabajadores = []
    for t in sorted(filas, key=lambda f: orden[f.cuil]):
        razon = razones.get(t.cuit_empleador, t.cuit_empleador or "Banco")
        trabajadores.append({
            "cuil": t.cuil, "nombre": nombres.get(t.cuil) or t.cuil,
            "empresa": {"cuit": t.cuit_empleador or "", "razon": razon,
                        "conducta": conductas.get(razon, (5, 20))},
            "semilla": int(t.cuil[-7:])})
    return trabajadores


def _resumen_recibos(contadores: dict) -> None:
    total = contadores.get("OK", 0) + contadores.get("CON_DISCREPANCIAS", 0)
    pct = 100 * contadores.get("OK", 0) / total if total else 0
    print(f"  Recibos: {contadores.get('OK', 0)} OK ({pct:.0f}%), "
          f"{contadores.get('CON_DISCREPANCIAS', 0)} con discrepancias, "
          f"{contadores['enviados']} enviados, {contadores['reportados']} reportados.")


if __name__ == "__main__":
    # El perfil se registra ANTES de armar el contexto del lote.
    lote.PERFILES["BANCARIA"] = componer_recibo_bancario

    sid = crear_sindicato()
    ctx = lote.contexto_lote(sid, NOMBRE)

    if "--limpiar" in sys.argv:
        lote.limpiar(sid, ctx)
        sys.exit(0)

    if "--borrar-recibos-de" in sys.argv:
        cuil = lote.argumento("--borrar-recibos-de").replace("-", "").strip()
        if not cuil.isdigit() or len(cuil) != 11:
            sys.exit("Indicá el CUIL, once dígitos: --borrar-recibos-de CUIL")
        aplicar = "--si" in sys.argv
        conteo = borrar_recibos(sid, {cuil}, aplicar)
        verbo = "Borrados" if aplicar else "Se borrarían (corré con --si para borrar)"
        print(f"{verbo}, CUIL {cuil} en {NOMBRE}: " +
              ", ".join(f"{t} {n}" for t, n in conteo.items()))
        sys.exit(0)

    if "--rehacer-recibos" in sys.argv:
        revisar_catalogo_ajeno(sid)
        trabajadores = trabajadores_del_lote(sid, ctx)
        if not trabajadores:
            sys.exit("No hay lote sembrado en La Bancaria: corré el script sin opciones.")
        conteo = borrar_recibos(sid, set(ctx["cuils"]), aplicar=True)
        print("Recibos del lote borrados: " +
              ", ".join(f"{t} {n}" for t, n in conteo.items()))
        print(f"Generando y VALIDANDO 5.000 recibos con la grilla de {GRILLA}...")
        _resumen_recibos(lote.sembrar_recibos(sid, ctx, trabajadores))
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
    print(f"Generando y VALIDANDO 5.000 recibos con la grilla de {GRILLA}...")
    _resumen_recibos(lote.sembrar_recibos(sid, ctx, trabajadores))
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

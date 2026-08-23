"""Test de aceptación del bloque 3, contra el convenio de AEFIP ya indexado.

Lo que se mide NO es solo si acierta: es si SABE CUÁNDO NO SABE. La medición
previa mostró que el umbral de similitud no puede distinguir una pregunta
legítima de una ajena del mismo tema (margen 0,011), así que esa distinción
la tiene que hacer el modelo leyendo el material. Estas son las preguntas
que lo prueban.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import db, rag

SID, CONV = 3, 1   # UOM / convenio AFIP-AEFIP. Ajustar si cambian los ids.

CASOS = [
    # (pregunta, debe_contestar, artículo que tendría que citar)
    ("¿Cuántos días de licencia por enfermedad común tengo por año?", True, "44"),
    ("Tengo una enfermedad de tratamiento largo, ¿cuánta licencia me dan?", True, "46"),
    ("¿Cuánto me corresponde de licencia por maternidad?", True, "48"),
    ("¿Percibo alguna suma de dinero al jubilarme?", True, "24"),
    ("¿Qué adicional técnico me corresponde?", True, "116"),
    ("¿Me justifican la inasistencia si dono sangre?", True, "63"),
    # --- LOS DOS QUE IMPORTAN: el convenio NO los contesta ---
    ("¿Cuánto cuesta el metro cuadrado en Puerto Madero?", False, None),
    ("¿Cómo se afecta mi SIPES si tengo inasistencias?", False, None),
]

print(f"{'':3} {'pregunta':56} {'esperado':10} {'obtuvo':10}")
print("-" * 92)
ok = 0
fallas = []
for pregunta, debe, articulo in CASOS:
    r = rag.responder(pregunta, SID, CONV, cuil="20111111119", registrar=True)
    contesto = r["hubo_respuesta"]
    bien = contesto == debe
    if bien and debe and articulo:
        bien = f"Artículo {articulo}" in r["respuesta"] or f"artículo {articulo}" in r["respuesta"]
    ok += bien
    if not bien:
        fallas.append((pregunta, r))
    print(f"{'OK ' if bien else 'NO '} {pregunta[:56]:56} "
          f"{'contesta' if debe else 'NO contesta':10} "
          f"{'contestó' if contesto else 'no contestó':10}")

print(f"\n{ok}/{len(CASOS)} correctos")

print("\n" + "=" * 92)
print("RESPUESTAS COMPLETAS")
print("=" * 92)
for pregunta, debe, _ in CASOS:
    r = rag.responder(pregunta, SID, CONV, registrar=False)
    print(f"\n### {pregunta}")
    print(f"  {r['respuesta']}")
    if r["fuentes"]:
        print(f"  fuentes: {', '.join(f['referencia'] for f in r['fuentes'][:4])}")

if fallas:
    print("\n" + "=" * 92)
    print("DETALLE DE LAS FALLAS")
    for p, r in fallas:
        print(f"\n### {p}\n  {r['respuesta'][:400]}")

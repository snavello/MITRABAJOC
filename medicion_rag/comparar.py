"""Compara tres modelos de embedding sobre el convenio real de AEFIP.

Mide dos cosas distintas, y la segunda importa tanto como la primera:

- POSITIVAS: ¿los artículos que contestan la pregunta entran entre los
  primeros K resultados? (recall@3 y recall@8)
- NEGATIVAS: para preguntas que el convenio NO contesta, ¿la similitud del
  mejor resultado queda por DEBAJO de la de las positivas? Si no hay
  separación, no existe umbral posible y la baranda "no lo encontré" no se
  puede implementar: el sistema va a inventar con confianza.
"""
import json, pathlib, sys
import numpy as np
from fastembed import TextEmbedding

AQUI = pathlib.Path(__file__).parent
FRAGS = json.loads((AQUI / "fragmentos.json").read_text(encoding="utf-8"))

MODELOS = [
    ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384),
    ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", 768),
    ("intfloat/multilingual-e5-large", 1024),
]

# (pregunta, artículos que la contestan). Lista vacía = el convenio NO la contesta.
PREGUNTAS = [
    ("¿Cuántos días de licencia por enfermedad común tengo por año?", [44]),
    ("Me tuve que ir a mitad de jornada por enfermedad, ¿cuenta como licencia?", [45]),
    ("Tengo una enfermedad de tratamiento largo, ¿cuánta licencia me dan?", [46]),
    ("Si mi enfermedad queda como incapacidad definitiva, ¿qué pasa?", [47]),
    ("¿Cuánto me corresponde de licencia por maternidad?", [48]),
    ("¿Cómo se otorga la licencia anual ordinaria?", [43]),
    ("¿Me justifican la inasistencia si dono sangre?", [63]),
    ("Si fallece un agente, ¿cobra algo la familia?", [18]),
    ("Si quedo con incapacidad absoluta por un accidente, ¿qué me corresponde?", [17]),
    ("¿Cómo se paga el adicional por antigüedad?", [105]),
    ("¿Qué derechos tengo como trabajador según el convenio?", [12]),
    ("¿Los derechos de los casados valen para convivientes?", [13]),
    ("¿Qué tipos de relación laboral hay en AFIP?", [3]),
    ("¿A quiénes se aplica este convenio?", [1]),
    ("¿Qué adicional técnico me corresponde?", [116, 115]),      # multi-artículo
    ("¿Percibo alguna suma de dinero al jubilarme?", [24]),
    ("¿Cuánto cuesta el metro cuadrado en Puerto Madero?", []),  # negativa fácil
    ("¿Cómo se afecta mi SIPES si tengo inasistencias?", []),    # negativa DIFÍCIL
]


def cos(a, b):
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return b @ a.T


def evaluar(nombre, dim):
    m = TextEmbedding(nombre)
    textos = [f"{f['titulo']}\n{f['texto']}" for f in FRAGS]
    # e5 se entrenó con prefijos query:/passage: -- usarlos cambia la calidad.
    # batch_size chico a propósito: con 246 fragmentos de una, el pooling de
    # mpnet pide ~740 MB en un solo array y revienta. En Render la indexación
    # va a tener que ir por lotes igual, así que se mide como se va a usar.
    LOTE = 8
    if "e5" in nombre:
        vf = np.array(list(m.passage_embed(textos, batch_size=LOTE)))
        vq = np.array(list(m.query_embed([p for p, _ in PREGUNTAS], batch_size=LOTE)))
    else:
        vf = np.array(list(m.embed(textos, batch_size=LOTE)))
        vq = np.array(list(m.embed([p for p, _ in PREGUNTAS], batch_size=LOTE)))
    sim = cos(vf, vq)                       # (preguntas, fragmentos)

    r3 = r8 = tot = 0
    peor_positiva = 1.0
    mejor_negativa = 0.0
    detalle = []
    for i, (preg, esperados) in enumerate(PREGUNTAS):
        orden = np.argsort(-sim[i])
        top = [(FRAGS[j]["articulo"], float(sim[i][j])) for j in orden[:8]]
        arts8 = [a for a, _ in top]
        arts3 = arts8[:3]
        if esperados:
            en3 = sum(1 for e in esperados if e in arts3)
            en8 = sum(1 for e in esperados if e in arts8)
            r3 += en3; r8 += en8; tot += len(esperados)
            peor_positiva = min(peor_positiva, top[0][1])
            detalle.append((preg[:46], esperados, arts3, en8 == len(esperados), top[0][1]))
        else:
            mejor_negativa = max(mejor_negativa, top[0][1])
            detalle.append((preg[:46], "NEGATIVA", arts3, None, top[0][1]))
    return {"modelo": nombre, "dim": dim, "recall3": r3 / tot, "recall8": r8 / tot,
            "peor_positiva": peor_positiva, "mejor_negativa": mejor_negativa,
            "detalle": detalle}


if __name__ == "__main__":
    res = []
    for nombre, dim in MODELOS:
        print(f"\n{'='*78}\n{nombre}  (dim {dim})", flush=True)
        r = evaluar(nombre, dim)
        res.append(r)
        print(f"  recall@3: {r['recall3']:.0%}   recall@8: {r['recall8']:.0%}")
        print(f"  similitud peor POSITIVA : {r['peor_positiva']:.3f}")
        print(f"  similitud mejor NEGATIVA: {r['mejor_negativa']:.3f}")
        margen = r['peor_positiva'] - r['mejor_negativa']
        print(f"  MARGEN (positiva - negativa): {margen:+.3f}"
              f"   {'hay umbral posible' if margen > 0 else 'NO se puede separar'}")
        for preg, esp, top3, ok, s in r["detalle"]:
            marca = "  " if ok is None else ("OK " if ok else "NO ")
            print(f"   {marca} {preg:48} esperado={str(esp):12} top3={top3} sim={s:.3f}")
    (AQUI / "resultado.json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "detalle"} for r in res],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n\n=== RESUMEN ===")
    print(f"{'modelo':56} {'dim':>5} {'r@3':>6} {'r@8':>6} {'margen':>8}")
    for r in res:
        print(f"{r['modelo'][-52:]:56} {r['dim']:>5} {r['recall3']:>5.0%} {r['recall8']:>5.0%} "
              f"{r['peor_positiva']-r['mejor_negativa']:>+8.3f}")

# Medición previa del piloto de RAG

Scripts con los que se eligió el modelo de embeddings **antes** de escribir
la migración, usando material real: el convenio de AEFIP y 18 preguntas.

No son código de la app. Están versionados porque:

- La elección del modelo fija `vector(1024)` en el esquema, y conviene poder
  reproducir por qué.
- `trocear.py` es el borrador del troceo que va al bloque 2, con los tres
  arreglos que el convenio real destapó.
- Si mañana se evalúa otro modelo, se corre lo mismo y se compara contra
  `resultado_medicion.txt`.

## Cómo se corre

```bash
pip install fastembed pypdf
python medicion_rag/trocear.py     # PDF -> fragmentos.json
python medicion_rag/comparar.py    # compara los modelos y reporta
```

`trocear.py` tiene la ruta del PDF hardcodeada — es un script de medición,
no de producción. Cambiala si vas a medir con otro convenio.

## Qué mide

Dos cosas, y la segunda importa tanto como la primera:

- **recall@3 / recall@8** — ¿los artículos que contestan la pregunta entran
  entre los primeros resultados?
- **Margen positiva − negativa** — para preguntas que el convenio NO
  contesta, ¿su mejor similitud queda por debajo de la peor pregunta
  legítima? Si no, no existe umbral posible y la baranda de "no lo encontré"
  no se puede implementar con un número.

## Resultado (2026-08-23)

| Modelo | dim | recall@3 | recall@8 | margen |
|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | 65% | 76% | -0,029 |
| paraphrase-multilingual-mpnet-base-v2 | 768 | 24% | 47% | -0,106 |
| **intfloat/multilingual-e5-large** | **1024** | **82%** | **94%** | **+0,011** |

Conclusiones y su porqué: ver `PLAN_RAG_CONVENIO.md`, sección "Lo que midió
el piloto antes de escribir código".

# Plantilla de cierre de bloque (Chat y Cowork)

Al terminar un bloque de trabajo en Chat o Cowork, pegar esto como último
mensaje. Claude devuelve las tres cosas listas para copiar al repo.

---

**Cierre de bloque.** Devolveme, en este orden y sin comentarios extra:

1. **Archivo para `docs/chat/`**: nombre `AAAA-MM-DD-tema-corto.md` (fecha
   de hoy) y contenido completo, empezando con este encabezado:

   ```
   # <Título>
   Fecha: AAAA-MM-DD · Herramienta: Chat|Cowork · Origen: <link a este chat o artefacto>
   Estado: borrador | acordado | superado por <archivo>
   Quién: <SDN|AKG|ARS|DOA>
   ```

   Después, lo producido: el documento, el plan, el prompt o las decisiones
   tomadas (fecha, alternativas descartadas, quién decidió).

2. **Una línea para `BITACORA.md`**, con el formato exacto de la tabla:

   ```
   | AAAA-MM-DD | Chat | <Módulo> | <Qué se hizo, una frase> | docs/chat/<archivo>; chat <id corto> | <Quién> |
   ```

3. **Si algo cambió el estado del proyecto** (una decisión que Code tiene
   que conocer): el texto exacto para pegar en `CLAUDE.md`, indicando la
   sección ("Decisiones tomadas", "Estado actual" o "Pendientes").

Si el documento debe publicarse en `/entornos`, agregá al final la entrada
para `recursos.SEMILLA` (clave, título, descripción, fecha, archivo).

---

## Cómo se lleva al repo

Desde la PC: crear el archivo en `docs/chat/`, pegar la línea al final de
`BITACORA.md`, correr `python generar_bitacora.py`, commitear:

```
git checkout -b docs/<tema>
git add docs/chat/<archivo> BITACORA.md recursos/bitacora.html
git commit -m "Cierre de bloque: <tema>"
git checkout main && git merge docs/<tema> && git push origin main
```

O pedírselo a Claude Code en la próxima sesión: *"Aplicá el cierre de bloque
que te pego: archivo en docs/chat/, línea en BITACORA.md, regenerá la
bitácora y commiteá."*

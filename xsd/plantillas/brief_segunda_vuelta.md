# Auditoría de diseño de {SISTEMA}: segunda vuelta

Esta es una **segunda vuelta**. Primero leé el encargo de la primera, que sigue valiendo entero salvo lo que cambia acá:
`{BRIEF_ORIGINAL}`.

Si ese archivo no existe en esta corrida, el encargo de la primera es
`xsd/plantillas/brief_revisor.md`, con los datos de la ficha.

## Qué cambió desde la primera vuelta

<Lo que se hizo entre vueltas, en cinco a diez líneas: qué se migró, qué
componentes compartidos cambiaron, qué pantallas NO te tocan.>

## Qué tenés que hacer

1. **Mirá las capturas nuevas** de tus pantallas, en todas las variantes y
   vistas. Están en `{CAPTURAS}/`, con el mismo nombre de siempre.
2. **Leé tu archivo de antecedentes**: `{CORRIDA}/previos/<TU GRUPO>.json`.
   Trae dos cosas:
   - `pantallas`: lo que revisás;
   - `hallazgos_anteriores`: lo que se dijo de esas pantallas antes, cada
     uno con su `estado`, que es la decisión de la persona:
     - **aceptar**: se pidió hacerlo;
     - **cambio**: se pidió otra cosa, que está en `nota`;
     - **dejar**: la persona decidió que quede así. **No lo vuelvas a
       proponer**;
     - **pendiente**: no se decidió.
3. **Verificá lo anterior.** Para cada hallazgo anterior en **aceptar**,
   **cambio** o **pendiente**, fijate en la captura nueva si sigue o si se
   resolvió, y anotalo en `verificacion`. Un hallazgo que sigue no se repite
   como hallazgo nuevo: queda en `verificacion` con su id viejo.
4. **Buscá lo nuevo**: lo que rompió el cambio, lo que quedó inconsistente
   entre variantes o con el resto de la app, y lo que no respeta las reglas
   de la casa. Va como hallazgo, con el mismo formato y el mismo estándar de
   la primera vuelta.

## Salida

Escribí `{CORRIDA}/hallazgos/<TU GRUPO>.json`, con el mismo formato de la
primera vuelta y estas diferencias:
- `"grupo"` es el de esta vuelta (`R1`, `R2`…), y los ids de los hallazgos
  nuevos llevan su prefijo (`R2-07`);
- la raíz suma este campo:

```json
"verificacion": [
  {"id": "G8-12", "resultado": "resuelto | sigue | parcial | ya no aplica", "comentario": "Una línea: qué se ve ahora."}
]
```

`ya no aplica` es, por ejemplo, para una pestaña que ya no existe. Si la
sugerencia de un hallazgo que **sigue** o es **parcial** cambió con el
cambio, va en el comentario.

Validá el JSON antes de terminar. Respondé en cuatro líneas:
- pantallas revisadas;
- anteriores resueltos, que siguen y parciales;
- nuevos por severidad;
- los dos más graves.

**No toques ningún archivo del repositorio.**

# Video "Asistente de trámites: de la idea al celular del afiliado" (1:46, narrado)

Fuentes para regenerar `recursos/colm3na-asistente-tramites.mp4`. Solo
scripts: los cuadros, la música y la voz no se versionan. Historia en
HISTORIAL.md, "El video Asistente de trámites" (las dos versiones: la de 30 s
al compás, descartada por SDN, y la narrada).

## Cómo está hecho (tres capas)
1. **Filmación** de cada pantalla real de Pruebas, cuadro por cuadro con
   reloj virtual (`lib.js`: `page.clock` de Playwright + seek de animaciones
   CSS + cámara por `transform` del body + cursor dibujado):
   - `portada.js` — la portada de Josefina en el celular (390×844 a 3x).
   - `asistente2.js` — el asistente con la IA real, retenida hasta el corte;
     al llegar al resultado vuelca `.diagrama` (HTML + hojas) para el vuelo.
   - `movil2.js` — Josefina pide el kit escolar y queda el expediente abierto.
   - `bandeja.js` — la bandeja de Trámites del panel con su expediente.
   - `textura.js` — renderiza el diagrama volcado a 3x (`frames/diagrama.png`).
   - `asistente.js`, `movil.js`, `intro.js` — la versión de 30 s al compás.
2. **Escenario 3D** (`escenario/stage.html` + `escenario/escenario.js`): cada
   cuadro final es una página con los cuadros filmados como planos CSS 3D
   (pantalla, teléfono con bisel y reflejo, piso para el circuito), con
   cámara por claves (`armar_timeline2.py` → `timeline2.json`), rótulos de dos
   líneas, placas y fundidos. Se fotografía cuadro a cuadro a 1080p.
3. **Audio** (`mezclar.py`): la voz (`guion.json`, es-AR-ElenaNeural de
   Edge TTS, `edge-tts --rate=+4%`, una pista por línea) en sus tiempos, la
   música agachada debajo de la voz (`sidechaincompress`) y `loudnorm`.
   Música: Vivaldi, "La primavera", Allegro, grabación de John Harrison con la
   Wichita State University Chamber Players (archive.org,
   `The_Four_Seasons_Vivaldi-10361`, pista 01, CC BY-SA 3.0).

## Regenerarlo
Desde una carpeta de trabajo con `playwright` (Node) y `edge-tts` (pip):
copiar estos scripts a `film/` y `stage/` dentro de ella (asumen
`__dirname/../frames`, `../adjuntos`, `../musica`, `../voz`).
1. Voz: por cada línea de `guion.json`, `edge-tts --voice es-AR-ElenaNeural
   --rate=+4% --text "..." --write-media voz/<id>.mp3` (detrás del proxy de
   la sesión hace falta su CA en `certifi` y `--proxy`).
2. Pruebas tiene que tener en La Bancaria el área «Acción Social» y el
   formulario «Kit escolar 2027» publicado.
3. `node film/portada.js`, `node film/asistente2.js` (una llamada a la IA),
   `node film/textura.js`, `node film/movil2.js` (envía un trámite real),
   `node film/bandeja.js`.
4. `python armar_timeline2.py` (ajustar las duraciones de las voces si
   cambiaron), `python mezclar.py`, `node stage/escenario.js` y
   `ffmpeg -framerate 30 -i out2/%05d.png -i mezcla.wav -c:v libx264
   -preset slow -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest
   -movflags +faststart asistente-tramites.mp4`.

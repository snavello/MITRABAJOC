# Video "Asistente de trámites: de la idea al celular del afiliado" (30 s)

Fuentes para regenerar `recursos/colm3na-asistente-tramites.mp4`. Solo
scripts: los cuadros y la música no se versionan. Historia en HISTORIAL.md,
"El video Asistente de trámites".

## Qué hace cada archivo
- `lib.js` — el filmador: reloj virtual (`page.clock`), seek de animaciones
  CSS, cámara (zoom/paneo con límites) y cursor dibujado.
- `asistente.js` — escena del asistente en Pruebas (login de plataforma,
  relato, IA real retenida hasta el corte, preguntas, datos, resultado con
  vuelo 3D y vista previa). `T0` y `BAR` por variable de entorno.
- `movil.js` — escena del celular (CUIL de prueba de La Bancaria, Kit escolar
  2027, envío real con sello ENVIADO). Viewport 390×844 a 3x.
- `intro.js` + `intro.html` — las dos placas (apertura y cierre).
- `grid.py` / `beats2.py` — grilla de compases medida sobre el audio.
- `timeline.json` — qué escena va en qué segundo, zooms del celular y rótulos.
- `componer.py` — arma los 909 cuadros finales (marco del teléfono, rótulos,
  fundido) en `out/`.

## Cómo regenerarlo
1. Música: bajar de archive.org el ítem `The_Four_Seasons_Vivaldi-10361`,
   pista 06 (Summer, Mvt 3, Presto; CC BY-SA 3.0) como `musica/presto.mp3` y
   cortar el segmento: `ffmpeg -ss 128.723 -t 31 -i presto.mp3 -af
   "afade=t=in:st=0:d=0.25,loudnorm=I=-11:TP=-1.1:LRA=9" -ar 48000 segmento.wav`.
2. Pruebas tiene que tener en La Bancaria el área «Acción Social» y el
   formulario «Kit escolar 2027» publicado (si no, `alta_tramite` de la
   sesión: `POST /admin/area` + `POST /admin/tramite-tipo` con los campos de
   `docs/chat/2026-10-16-ejemplo-kit-escolar.colm3na.json`).
3. Desde una carpeta de trabajo con `playwright` instalado:
   `node intro.js apertura` (DUR=2.272), `T0=28.653 DUR=1.65 node intro.js cierre`,
   `node asistente.js` (gasta una llamada a la IA), `node movil.js`
   (envía un trámite real).
4. `python componer.py` y después
   `ffmpeg -framerate 30 -i out/%05d.png -i musica/segmento.wav -c:v libx264
   -preset slow -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest
   -movflags +faststart asistente-tramites.mp4`.

Los scripts asumen las rutas de la sesión en que se escribieron
(`__dirname/../frames`, `../adjuntos`, `../intro`, `../musica`): copiarlos a
una carpeta `film/` dentro de la carpeta de trabajo. Los adjuntos simulados
(`dni-chico.jpg`, `constancia.jpg`) se generan con PIL, marcados
"DOCUMENTO SIMULADO".

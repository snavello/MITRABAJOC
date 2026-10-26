# Encargo: estilos con movimiento para el catálogo XSD

Primero leé ``<kit>/catalogo/encargos/estilo.md`` entero. Vale todo lo que dice: el molde, los tokens, las fotos reales, las fichas, los archivos que entregás y las reglas.

Ya hay 40 estilos estáticos en `preview/estilos/`. Miralos como referencia de nivel y no los toques. La persona aprobó los 40 y pidió **20 más que incluyan animaciones**. A vos te tocan cinco. **El movimiento es la firma de estos estilos**: alguien que los mira tiene que decir «este se mueve así» y reconocerlo por eso. No alcanza con un fundido genérico.

## Cómo funciona el movimiento en el preview

- La página le pone la clase **`en-vista`** a cada portada (`.m`) cuando entra en pantalla, y el botón «Repetir la animación» se la saca y se la vuelve a poner. Por eso:
  - **Las animaciones de entrada** (lo que aparece, se arma, se dibuja o sube) van bajo `.e-<id>.en-vista …`. Sin esa clase, cada pieza tiene que estar en su estado inicial, oculta o sin dibujar. Así cada vez que se repite, la entrada se ve desde el principio.
  - **Las animaciones de ambiente** (un latido, una marquesina, un brillo que recorre, una respiración lenta) pueden correr siempre. Tienen que ser lentas y de poco recorrido: en la página conviven 60 portadas.
- Duraciones: la entrada completa entre 1 y 2,5 s, en cascada. Un ambiente, de 3 a 30 s por ciclo. Curvas `cubic-bezier(.22,.61,.36,1)` o `cubic-bezier(.16,1,.3,1)` para entrar, nunca `linear` salvo en marquesinas.
- **Solo `transform`, `opacity`, `filter`, `clip-path`, `background-position` y `stroke-dashoffset`.** Nada que mueva el layout (ni `width`, ni `height`, ni `top`, ni `margin`). Cada animación lleva su `@keyframes` con nombre único: `e-<id>-<algo>`.
- **Reducir movimiento es obligatorio.** Agregá `@media (prefers-reduced-motion: reduce) { .e-<id> *, .e-<id> *::before, .e-<id> *::after { animation: none !important; transition: none !important; } }`, y fijate que el estado final se vea bien sin animación: nada puede quedar oculto.
- Si algo del original no se puede hacer solo con CSS (un video, un split-flap con letras que cambian), aproximalo con CSS (un clip de la foto con zoom lento y tinte, letras que caen) y decilo en tu reporte. **No agregues JavaScript**: el preview no ejecuta scripts por estilo.

## Cómo lo probás

```
python3 CAT/armar.py CAT/_<tu-nombre>.html
ESPERA=300 node CAT/captura.cjs $PWD/CAT/_<tu-nombre>.html $PWD/xsd-trabajo/catalogo/capturas/medio <id>
ESPERA=4000 node CAT/captura.cjs $PWD/CAT/_<tu-nombre>.html $PWD/xsd-trabajo/catalogo/capturas <id>
```

`ESPERA` son los milisegundos que pasan entre que se pone `en-vista` y la captura. Creá antes `xsd-trabajo/catalogo/capturas/medio/`. Mirá las dos capturas con Read:
- la del medio tiene que mostrar la entrada en curso;
- la final tiene que mostrar la portada completa y legible.

La final es la que queda en `xsd-trabajo/catalogo/capturas/<id>.png`. Al terminar, borrá tu `_<tu-nombre>.html`.

Terminá con dos líneas por estilo: qué movimiento tomaste del original y cómo se ve, y qué no pudiste hacer.
